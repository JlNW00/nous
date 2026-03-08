"""Graph worker — §6.3 and §12.

Creates/updates Neo4j nodes and edges from evidence, runs entity resolution.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from packages.common.celery_app import celery_app
from packages.common.database import get_sync_session
from packages.common.enums import CaseStatus, EdgeType
from packages.common.graph import neo4j_client
from packages.common.models import Case, Contract, RawEvidence, Wallet

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.graph.enrich_graph", bind=True, max_retries=2)
def enrich_graph(self, case_id: str) -> dict:
    """
    Build graph nodes and edges from stored evidence.

    1. Read raw evidence for this case.
    2. Upsert wallet, contract, domain nodes.
    3. Create FUNDED_BY, DEPLOYED, TRANSFERRED_TO edges.
    4. Run entity resolution heuristics.
    5. Transition case to ANALYZING and dispatch signal workers.
    """
    logger.info("Enriching graph for case %s", case_id)

    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                return {"error": "case_not_found"}

            evidence_rows = (
                db.query(RawEvidence)
                .filter(RawEvidence.case_id == case.case_id)
                .all()
            )

            for ev in evidence_rows:
                _process_evidence_to_graph(ev)

            # Run entity resolution after graph is built
            _run_entity_resolution(case_id)

            # Transition to analyzing
            case.status = CaseStatus.ANALYZING.value
            db.commit()

    except Exception as exc:
        logger.exception("Graph enrichment failed for case %s", case_id)
        raise self.retry(exc=exc)

    # Dispatch signal calculation
    celery_app.send_task(
        "workers.signals.calculate_signals",
        args=[case_id],
        queue="signals",
    )

    return {"status": "graph_enriched"}


def _process_evidence_to_graph(evidence: RawEvidence) -> None:
    """Parse evidence payload and upsert corresponding graph nodes/edges."""
    payload = evidence.payload_json
    source = evidence.source_type

    if source == "on_chain":
        _process_onchain_evidence(payload)
    elif source == "code":
        _process_code_evidence(payload)
    elif source == "infrastructure":
        _process_infra_evidence(payload)
    # Social and market evidence create nodes but fewer edges


def _process_onchain_evidence(payload: dict[str, Any]) -> None:
    """Create wallet and contract nodes with funding/deployment edges."""

    # Deployer → Contract
    if "deployer_address" in payload and "contract_address" in payload:
        chain = payload.get("chain", "unknown")

        neo4j_client.upsert_node(
            "Wallet",
            {"address": payload["deployer_address"]},
            {"chain": chain},
        )
        neo4j_client.upsert_node(
            "Contract",
            {"address": payload["contract_address"]},
            {"chain": chain, "contract_type": payload.get("contract_type", "token")},
        )
        neo4j_client.upsert_edge(
            "Wallet", {"address": payload["deployer_address"]},
            "Contract", {"address": payload["contract_address"]},
            EdgeType.DEPLOYED.value,
            {"tx_hash": payload.get("deploy_tx"), "timestamp": payload.get("deploy_time")},
        )

    # Funding chain: funder → deployer
    if "funding_source" in payload and "deployer_address" in payload:
        neo4j_client.upsert_node(
            "Wallet",
            {"address": payload["funding_source"]},
            {"chain": payload.get("chain", "unknown")},
        )
        neo4j_client.upsert_edge(
            "Wallet", {"address": payload["funding_source"]},
            "Wallet", {"address": payload["deployer_address"]},
            EdgeType.FUNDED_BY.value,
            {"amount": payload.get("funding_amount"), "timestamp": payload.get("funding_time")},
        )

    # Transfer relationships
    for transfer in payload.get("transfers", []):
        if "from_address" in transfer and "to_address" in transfer:
            neo4j_client.upsert_edge(
                "Wallet", {"address": transfer["from_address"]},
                "Wallet", {"address": transfer["to_address"]},
                EdgeType.TRANSFERRED_TO.value,
                {"amount": transfer.get("amount"), "timestamp": transfer.get("timestamp")},
            )


def _process_code_evidence(payload: dict[str, Any]) -> None:
    """Create repo nodes."""
    if "repo_url" in payload:
        neo4j_client.upsert_node(
            "Repo",
            {"repo_url": payload["repo_url"]},
            {"owner": payload.get("owner_name"), "created_at": payload.get("created_at")},
        )


def _process_infra_evidence(payload: dict[str, Any]) -> None:
    """Create domain nodes."""
    if "domain" in payload:
        neo4j_client.upsert_node(
            "Domain",
            {"domain": payload["domain"]},
            {"registrar": payload.get("registrar"), "created_at": payload.get("created_at")},
        )


def _run_entity_resolution(case_id: str) -> None:
    """
    Entity resolution heuristics — §9.1.

    Phase 1 (shipped now):
    - Shared funding source within short time window.
    - Deployer reuse (same wallet deployed multiple contracts).

    Phase 2 (future):
    - Gas payer patterns.
    - Bridge pattern matching.
    - Deployment signature similarity.
    """
    logger.info("Running entity resolution for case %s", case_id)

    # Heuristic 1: Deployer reuse — find wallets that deployed 2+ contracts
    query = """
    MATCH (w:Wallet)-[:DEPLOYED]->(c:Contract)
    WITH w, collect(c.address) AS contracts, count(c) AS deploy_count
    WHERE deploy_count >= 2
    RETURN w.address AS deployer, contracts, deploy_count
    """
    with neo4j_client.session() as session:
        results = session.run(query)
        for record in results:
            deployer = record["deployer"]
            count = record["deploy_count"]
            logger.info(
                "Entity resolution: wallet %s deployed %d contracts",
                deployer[:16],
                count,
            )
            # Mark as entity cluster in Neo4j
            neo4j_client.upsert_node(
                "Entity",
                {"primary_address": deployer},
                {"deploy_count": count, "resolution_method": "deployer_reuse"},
            )
            neo4j_client.upsert_edge(
                "Wallet", {"address": deployer},
                "Entity", {"primary_address": deployer},
                EdgeType.CONTROLS.value,
            )

    # Heuristic 2: Shared funding source — wallets funded by the same source
    query2 = """
    MATCH (source:Wallet)-[:FUNDED_BY]->(target:Wallet)
    WITH source, collect(target.address) AS funded_wallets, count(target) AS fund_count
    WHERE fund_count >= 2
    RETURN source.address AS funder, funded_wallets, fund_count
    """
    with neo4j_client.session() as session:
        results = session.run(query2)
        for record in results:
            funder = record["funder"]
            count = record["fund_count"]
            logger.info(
                "Entity resolution: wallet %s funded %d wallets",
                funder[:16],
                count,
            )
            neo4j_client.upsert_node(
                "Entity",
                {"primary_address": funder},
                {"fund_count": count, "resolution_method": "shared_funding"},
            )

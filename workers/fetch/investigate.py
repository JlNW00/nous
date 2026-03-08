"""Synchronous investigation runner.

Runs the full pipeline (fetch → graph → signal → score → report) in a single
request without needing Celery/Redis. Use this for development and testing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from packages.common.enums import CaseStatus, SignalName, Verdict
from packages.common.models import (
    Case,
    Contract,
    Project,
    RawEvidence,
    Report,
    ScoreHistory,
    Signal,
    Wallet,
)
from packages.common.scoring import SignalInput, compute_score

logger = logging.getLogger(__name__)


def run_investigation(db: Session, case: Case, project: Project) -> dict[str, Any]:
    """
    Execute the full investigation pipeline synchronously.

    Returns the completed report as a dict.
    """
    logger.info("Starting sync investigation for case %s", case.case_id)

    # Phase 1: Fetch data
    case.status = CaseStatus.COLLECTING.value
    db.flush()

    evidence_payloads = _fetch_all_data(db, case, project)

    # Phase 1b: Populate Neo4j graph from evidence
    _populate_graph(project, evidence_payloads)

    # Phase 2: Calculate signals from evidence
    case.status = CaseStatus.ANALYZING.value
    db.flush()

    signals = _calculate_signals(db, case, evidence_payloads)

    # Phase 3: Score
    case.status = CaseStatus.SCORED.value
    db.flush()

    signal_inputs = [
        SignalInput(
            signal_name=s.signal_name,
            value=s.signal_value,
            confidence=s.confidence,
        )
        for s in signals
    ]
    scoring_result = compute_score(signal_inputs)

    # Phase 3b: LLM Reasoning (optional — §14)
    reasoning_output = _run_llm_reasoning(case, project, signals, evidence_payloads)

    # Phase 4: Build report
    report_json = _build_report(project, scoring_result, signals, evidence_payloads)

    # Merge LLM reasoning into report if available
    if reasoning_output:
        report_json["llm_reasoning"] = {
            "summary": reasoning_output.get("summary"),
            "supporting_findings": reasoning_output.get("supporting_findings", []),
            "contradictions": reasoning_output.get("contradictions", []),
            "open_questions": reasoning_output.get("open_questions", []),
            "verdict_suggestion": reasoning_output.get("verdict_suggestion"),
            "confidence": reasoning_output.get("confidence"),
        }
        # Merge LLM contradictions + open questions into report top-level
        for c in reasoning_output.get("contradictions", []):
            if c not in report_json.get("top_findings", []):
                report_json.setdefault("contradictions", []).append(c)
        for q in reasoning_output.get("open_questions", []):
            if q not in report_json.get("open_questions", []):
                report_json["open_questions"].append(q)
        # Use LLM summary as executive summary if available
        if reasoning_output.get("summary"):
            report_json["executive_summary"] = reasoning_output["summary"]

    report = Report(
        case_id=case.case_id,
        version=1,
        verdict=scoring_result.verdict.value,
        credibility_score=scoring_result.total_score,
        confidence=scoring_result.overall_confidence,
        report_json=report_json,
    )
    db.add(report)
    db.flush()

    # Store score history
    for cs in scoring_result.category_scores:
        db.add(ScoreHistory(
            report_id=report.report_id,
            score_name=cs.name,
            score_value=cs.earned_points,
        ))

    case.status = CaseStatus.PUBLISHED.value
    db.flush()

    logger.info(
        "Investigation complete: score=%.1f verdict=%s",
        scoring_result.total_score,
        scoring_result.verdict.value,
    )

    return report_json


def _fetch_all_data(
    db: Session, case: Case, project: Project
) -> dict[str, Any]:
    """Fetch from all available providers and store evidence."""
    evidence: dict[str, Any] = {}

    # ── Helius: token + wallet data ─────────────────────────────────
    if project.chain == "solana" and project.primary_contract:
        try:
            from workers.fetch.adapters.helius import HeliusAdapter

            helius = HeliusAdapter()

            # Token metadata
            logger.info("Fetching token metadata from Helius...")
            token_meta = helius.get_token_metadata(project.primary_contract)
            evidence["token_metadata"] = token_meta
            _store_evidence(db, case.case_id, "on_chain", "helius", token_meta)

            # Update project with discovered metadata
            if token_meta.get("symbol") and not project.symbol:
                project.symbol = token_meta["symbol"]
            if token_meta.get("name") and project.canonical_name.startswith("unknown-"):
                project.canonical_name = token_meta["name"]
            db.flush()

            # Top holders
            logger.info("Fetching top holders from Helius...")
            holders = helius.get_top_holders(project.primary_contract)
            evidence["top_holders"] = holders
            _store_evidence(db, case.case_id, "on_chain", "helius", {
                "top_holders": holders,
                "mint": project.primary_contract,
            })

            # Deployer identification
            logger.info("Identifying deployer...")
            creation_tx = helius.get_token_creation_tx(project.primary_contract)
            evidence["_creation_tx"] = creation_tx
            deployer = None
            if creation_tx:
                if "feePayer" in creation_tx:
                    deployer = creation_tx["feePayer"]
                elif "transaction" in creation_tx:
                    msg = creation_tx["transaction"].get("message", {})
                    acct_keys = msg.get("accountKeys", [])
                    if acct_keys:
                        first = acct_keys[0]
                        deployer = first.get("pubkey") if isinstance(first, dict) else first
            evidence["deployer_address"] = deployer

            if deployer:
                # Store deployer wallet
                existing_wallet = db.query(Wallet).filter(
                    Wallet.chain == "solana",
                    Wallet.address == deployer,
                ).first()
                if not existing_wallet:
                    db.add(Wallet(chain="solana", address=deployer))
                    db.flush()

                # Store contract with deployer link
                existing_contract = db.query(Contract).filter(
                    Contract.chain == "solana",
                    Contract.address == project.primary_contract,
                ).first()
                if not existing_contract:
                    wallet = db.query(Wallet).filter(
                        Wallet.chain == "solana",
                        Wallet.address == deployer,
                    ).first()
                    db.add(Contract(
                        chain="solana",
                        address=project.primary_contract,
                        contract_type="token",
                        deployer_wallet_id=wallet.wallet_id if wallet else None,
                    ))
                    db.flush()

                _store_evidence(db, case.case_id, "on_chain", "helius", {
                    "deployer_address": deployer,
                    "contract_address": project.primary_contract,
                    "chain": "solana",
                })

                # Funding trace
                logger.info("Tracing funding source for deployer %s...", deployer[:16])
                try:
                    funding = helius.trace_funding_source(deployer, max_depth=3)
                    evidence["funding_chain"] = funding
                    if funding:
                        _store_evidence(db, case.case_id, "on_chain", "helius", {
                            "funding_chain": funding,
                            "deployer_address": deployer,
                        })
                except Exception as exc:
                    logger.warning("Funding trace failed: %s", exc)
                    evidence["funding_chain"] = []

            helius.close()

        except ValueError as exc:
            logger.warning("Helius adapter unavailable: %s", exc)
        except Exception as exc:
            logger.exception("Helius fetch failed: %s", exc)

    # ── DexScreener: market data ────────────────────────────────────
    if project.primary_contract:
        try:
            from workers.fetch.adapters.dexscreener import DexScreenerAdapter

            dex = DexScreenerAdapter()

            logger.info("Fetching market data from DexScreener...")
            market = dex.get_market_summary(project.primary_contract)
            evidence["market"] = market
            _store_evidence(db, case.case_id, "market", "dexscreener", market)

            dex.close()

        except Exception as exc:
            logger.exception("DexScreener fetch failed: %s", exc)

    # ── Bags: launchpad data ─────────────────────────────────────────
    if project.chain == "solana" and project.primary_contract:
        try:
            from workers.fetch.adapters.bags import BagsAdapter

            bags = BagsAdapter()

            logger.info("Fetching Bags token data...")
            bags_info = bags.get_token_info(project.primary_contract)
            evidence["bags"] = bags_info
            _store_evidence(db, case.case_id, "market", "bags", bags_info)

            # Also check Helius creation tx for Bags signer
            creation_tx = evidence.get("_creation_tx")
            if creation_tx:
                bags_info["bags_launched_helius"] = BagsAdapter.is_bags_launched(creation_tx)

            bags.close()

        except ValueError as exc:
            logger.warning("Bags adapter unavailable: %s", exc)
        except Exception as exc:
            logger.exception("Bags fetch failed: %s", exc)

    # ── GitHub: repository metadata and commit activity ─────────────
    github_url = _extract_github_url(evidence)
    if github_url:
        try:
            from workers.fetch.adapters.github import GitHubAdapter

            gh = GitHubAdapter()
            parsed = GitHubAdapter.parse_github_url(github_url)
            if parsed:
                owner, repo = parsed

                logger.info("Fetching GitHub repo info for %s/%s...", owner, repo)
                repo_info = gh.get_repo_info(owner, repo)
                evidence["github_repo"] = repo_info
                _store_evidence(db, case.case_id, "code", "github", repo_info)

                if repo_info.get("exists"):
                    logger.info("Fetching recent commits for %s/%s...", owner, repo)
                    commit_data = gh.get_recent_commit_activity(owner, repo)
                    evidence["github_commits"] = commit_data
                    _store_evidence(db, case.case_id, "code", "github", commit_data)

            gh.close()

        except Exception as exc:
            logger.exception("GitHub fetch failed: %s", exc)

    # ── Infrastructure: DNS/HTTP probing of project websites ────────
    infra_urls = _extract_website_urls(evidence)
    if infra_urls:
        try:
            from workers.fetch.adapters.infrastructure import InfrastructureAdapter

            infra = InfrastructureAdapter()
            logger.info("Probing infrastructure for %d URL(s)...", len(infra_urls))
            infra_result = infra.probe_domain_summary(infra_urls)
            evidence["infrastructure"] = infra_result
            _store_evidence(db, case.case_id, "infrastructure", "http_probe", infra_result)
            infra.close()

        except Exception as exc:
            logger.exception("Infrastructure probe failed: %s", exc)

    return evidence


def _store_evidence(
    db: Session,
    case_id: uuid.UUID,
    source_type: str,
    provider: str,
    payload: dict[str, Any],
) -> RawEvidence:
    """Store evidence with dedup by content hash."""
    raw_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()

    existing = db.query(RawEvidence).filter(
        RawEvidence.case_id == case_id,
        RawEvidence.hash == raw_hash,
    ).first()

    if existing:
        return existing

    ev = RawEvidence(
        case_id=case_id,
        source_type=source_type,
        provider=provider,
        payload_json=payload,
        hash=raw_hash,
    )
    db.add(ev)
    db.flush()
    return ev


def _extract_website_urls(evidence: dict[str, Any]) -> list[str]:
    """
    Collect project website URLs from evidence for infrastructure probing.

    Sources: Helius external_url, DexScreener websites list.
    Excludes GitHub URLs (handled by GitHub adapter).
    """
    urls: list[str] = []

    ext_url = (evidence.get("token_metadata") or {}).get("external_url") or ""
    if ext_url and "github.com" not in ext_url:
        urls.append(ext_url)

    market = evidence.get("market") or {}
    for site in market.get("websites", []):
        url = site.get("url") or ""
        if url and "github.com" not in url and url not in urls:
            urls.append(url)

    return urls


def _extract_github_url(evidence: dict[str, Any]) -> str | None:
    """
    Scan already-fetched evidence for a GitHub repository URL.

    Checks (in priority order):
      1. Helius token metadata: external_url
      2. DexScreener socials list: each item's "url"
      3. DexScreener websites list: each item's "url"

    Returns the first valid GitHub repo URL found, or None.
    """
    from workers.fetch.adapters.github import GitHubAdapter

    # Source 1: Helius external_url
    ext_url = (evidence.get("token_metadata") or {}).get("external_url") or ""
    if "github.com" in ext_url and GitHubAdapter.parse_github_url(ext_url):
        logger.debug("GitHub URL from Helius external_url: %s", ext_url)
        return ext_url

    market = evidence.get("market") or {}

    # Source 2: DexScreener socials
    for social in market.get("socials", []):
        url = social.get("url") or ""
        if "github.com" in url and GitHubAdapter.parse_github_url(url):
            logger.debug("GitHub URL from DexScreener socials: %s", url)
            return url

    # Source 3: DexScreener websites
    for site in market.get("websites", []):
        url = site.get("url") or ""
        if "github.com" in url and GitHubAdapter.parse_github_url(url):
            logger.debug("GitHub URL from DexScreener websites: %s", url)
            return url

    return None


def _populate_graph(project: Project, evidence: dict[str, Any]) -> None:
    """
    Populate Neo4j graph from collected evidence.

    Creates nodes and edges for the investigation's entities:
    - Token/Contract node
    - Deployer Wallet + DEPLOYED edge
    - Funding chain wallets + FUNDED_BY edges
    - GitHub Repo + LINKS_TO edge
    - Infrastructure Domain + LINKS_TO edge

    Entirely wrapped in try/except — graph failure never blocks the pipeline.
    """
    try:
        from packages.common.enums import EdgeType
        from packages.common.graph import neo4j_client

        chain = project.chain or "unknown"
        contract = project.primary_contract

        # Token contract node
        if contract:
            neo4j_client.upsert_node(
                "Contract",
                {"address": contract},
                {
                    "chain": chain,
                    "contract_type": "token",
                    "name": project.canonical_name,
                    "symbol": project.symbol or "",
                },
            )

        # Deployer wallet + DEPLOYED edge
        deployer = evidence.get("deployer_address")
        if deployer and contract:
            neo4j_client.upsert_node(
                "Wallet",
                {"address": deployer},
                {"chain": chain},
            )
            neo4j_client.upsert_edge(
                "Wallet", {"address": deployer},
                "Contract", {"address": contract},
                EdgeType.DEPLOYED.value,
            )

        # Funding chain → FUNDED_BY edges
        for hop in evidence.get("funding_chain", []):
            from_addr = hop.get("from")
            to_addr = hop.get("to")
            if from_addr and to_addr:
                neo4j_client.upsert_node(
                    "Wallet", {"address": from_addr}, {"chain": chain},
                )
                neo4j_client.upsert_node(
                    "Wallet", {"address": to_addr}, {"chain": chain},
                )
                neo4j_client.upsert_edge(
                    "Wallet", {"address": from_addr},
                    "Wallet", {"address": to_addr},
                    EdgeType.FUNDED_BY.value,
                    {
                        "amount_sol": hop.get("amount_sol"),
                        "tx_signature": hop.get("tx_signature"),
                    },
                )

        # GitHub repo node + LINKS_TO edge
        github_repo = evidence.get("github_repo") or {}
        if github_repo.get("exists") and contract:
            repo_url = f"https://github.com/{github_repo['owner']}/{github_repo['repo']}"
            neo4j_client.upsert_node(
                "Repo",
                {"repo_url": repo_url},
                {
                    "owner": github_repo.get("owner"),
                    "name": github_repo.get("repo"),
                    "created_at": github_repo.get("created_at"),
                    "stars": github_repo.get("stars", 0),
                    "is_fork": github_repo.get("is_fork", False),
                },
            )
            neo4j_client.upsert_edge(
                "Contract", {"address": contract},
                "Repo", {"repo_url": repo_url},
                EdgeType.LINKS_TO.value,
            )

        # Infrastructure domain node + LINKS_TO edge
        infra = evidence.get("infrastructure") or {}
        best_probe = infra.get("best_probe") or {}
        domain = best_probe.get("domain")
        if domain and contract:
            neo4j_client.upsert_node(
                "Domain",
                {"domain": domain},
                {
                    "dns_resolves": best_probe.get("dns_resolves"),
                    "has_tls": best_probe.get("has_valid_tls"),
                    "http_status": best_probe.get("http_status"),
                },
            )
            neo4j_client.upsert_edge(
                "Contract", {"address": contract},
                "Domain", {"domain": domain},
                EdgeType.LINKS_TO.value,
            )

        logger.info("Neo4j graph populated for %s", contract or project.canonical_name)

    except Exception as exc:
        logger.warning("Graph population failed (non-fatal): %s", exc)


def _calculate_signals(
    db: Session, case: Case, evidence: dict[str, Any]
) -> list[Signal]:
    """Calculate all deterministic signals from fetched evidence."""
    signals: list[Signal] = []

    # ── Top holder concentration ────────────────────────────────────
    holders = evidence.get("top_holders", [])
    if holders:
        top10_pct = sum(h.get("percentage", 0) for h in holders[:10])
        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.TOP_HOLDER_PCT.value,
            signal_value=min(top10_pct / 100.0, 1.0),
            score_component="token_structure_liquidity",
            confidence=0.85,
        )
        db.add(sig)
        signals.append(sig)

    # ── Liquidity assessment ────────────────────────────────────────
    market = evidence.get("market", {})
    if market and market.get("total_liquidity_usd"):
        liq = market["total_liquidity_usd"]
        # Normalize: <$1k = 0.1, $1k-$10k = 0.3, $10k-$100k = 0.6, $100k+ = 0.9
        if liq >= 100_000:
            lp_score = 0.9
        elif liq >= 10_000:
            lp_score = 0.6
        elif liq >= 1_000:
            lp_score = 0.3
        else:
            lp_score = 0.1

        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.LP_LOCKED.value,
            signal_value=lp_score,
            score_component="token_structure_liquidity",
            confidence=0.6,
        )
        db.add(sig)
        signals.append(sig)

    # ── Bags signals ─────────────────────────────────────────────────
    bags = evidence.get("bags", {})
    if bags:
        is_bags = bags.get("bags_launched", False) or bags.get("bags_launched_helius", False)
        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.BAGS_LAUNCHED.value,
            signal_value=0.8 if is_bags else 0.0,
            score_component="token_structure_liquidity",
            confidence=0.9 if bags.get("bags_launched") else 0.5,
        )
        db.add(sig)
        signals.append(sig)

        if is_bags:
            # Lifetime fees — normalize: 0 SOL=0.1, <1 SOL=0.3, 1-10=0.6, 10+=0.9
            fees_sol = bags.get("lifetime_fees_sol", 0) or 0
            if fees_sol >= 10:
                fees_score = 0.9
            elif fees_sol >= 1:
                fees_score = 0.6
            elif fees_sol > 0:
                fees_score = 0.3
            else:
                fees_score = 0.1
            sig = Signal(
                case_id=case.case_id,
                signal_name=SignalName.BAGS_LIFETIME_FEES.value,
                signal_value=fees_score,
                score_component="token_structure_liquidity",
                confidence=0.8,
            )
            db.add(sig)
            signals.append(sig)

            # Trading volume — normalize: <$1k=0.1, $1k-$10k=0.3, $10k-$100k=0.6, $100k+=0.9
            vol_usd = bags.get("trading_volume_usd", 0) or 0
            if vol_usd >= 100_000:
                vol_score = 0.9
            elif vol_usd >= 10_000:
                vol_score = 0.6
            elif vol_usd >= 1_000:
                vol_score = 0.3
            else:
                vol_score = 0.1
            sig = Signal(
                case_id=case.case_id,
                signal_name=SignalName.BAGS_TRADING_VOLUME.value,
                signal_value=vol_score,
                score_component="token_structure_liquidity",
                confidence=0.8,
            )
            db.add(sig)
            signals.append(sig)

    # ── Deployer reputation (basic) ─────────────────────────────────
    deployer = evidence.get("deployer_address")
    if deployer:
        # For now: deployer identified = some confidence, unknown history = neutral
        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.DEPLOYER_REPUTATION.value,
            signal_value=0.5,
            score_component="wallet_entity_reputation",
            confidence=0.3,
        )
        db.add(sig)
        signals.append(sig)

    # ── Capital origin score ────────────────────────────────────────
    funding = evidence.get("funding_chain", [])
    if funding:
        depth = len(funding)
        if depth <= 1:
            cap_score = 0.8
        elif depth <= 3:
            cap_score = 0.6
        else:
            cap_score = 0.3

        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.CAPITAL_ORIGIN_SCORE.value,
            signal_value=cap_score,
            score_component="capital_lineage_quality",
            confidence=0.5,
        )
        db.add(sig)
        signals.append(sig)
    elif deployer:
        # Couldn't trace = slightly suspicious
        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.CAPITAL_ORIGIN_SCORE.value,
            signal_value=0.3,
            score_component="capital_lineage_quality",
            confidence=0.3,
        )
        db.add(sig)
        signals.append(sig)

    # ── Narrative consistency (basic: do they have socials?) ────────
    market_socials = market.get("socials", [])
    market_websites = market.get("websites", [])
    has_presence = len(market_socials) > 0 or len(market_websites) > 0
    sig = Signal(
        case_id=case.case_id,
        signal_name=SignalName.NARRATIVE_CONSISTENCY.value,
        signal_value=0.6 if has_presence else 0.2,
        score_component="cross_signal_consistency",
        confidence=0.4,
    )
    db.add(sig)
    signals.append(sig)

    # ── Repository age ───────────────────────────────────────────────
    github_repo = evidence.get("github_repo") or {}
    if github_repo.get("exists"):
        age_days = github_repo.get("age_days", 0)
        if age_days >= 365:
            age_score = 0.9
        elif age_days >= 90:
            age_score = 0.6
        elif age_days >= 30:
            age_score = 0.3
        else:
            age_score = 0.1

        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.REPO_AGE_DAYS.value,
            signal_value=age_score,
            score_component="developer_code_authenticity",
            confidence=0.8,
        )
        db.add(sig)
        signals.append(sig)

    # ── Commit velocity ──────────────────────────────────────────────
    github_commits = evidence.get("github_commits") or {}
    if github_commits:
        commit_count = github_commits.get("commit_count_28d", 0)
        commits_per_week = commit_count / 4.0
        if commits_per_week > 15:
            vel_score = 0.9
        elif commits_per_week >= 5:
            vel_score = 0.85
        elif commits_per_week >= 1:
            vel_score = 0.6
        elif commits_per_week > 0:
            vel_score = 0.3
        else:
            vel_score = 0.05

        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.COMMIT_VELOCITY.value,
            signal_value=vel_score,
            score_component="developer_code_authenticity",
            confidence=0.7,
        )
        db.add(sig)
        signals.append(sig)

    # ── Backend presence (infrastructure probe) ───────────────────────
    infra = evidence.get("infrastructure") or {}
    best_probe = infra.get("best_probe") or {}
    if best_probe:
        status = best_probe.get("http_status") or 0
        is_2xx = 200 <= status < 300
        has_tls = best_probe.get("has_valid_tls", False)
        content_len = best_probe.get("content_length", 0)

        if is_2xx and has_tls and content_len > 500:
            infra_score = 0.9
        elif is_2xx and has_tls:
            infra_score = 0.7
        elif is_2xx:
            infra_score = 0.5
        elif best_probe.get("dns_resolves"):
            infra_score = 0.2
        else:
            infra_score = 0.1

        sig = Signal(
            case_id=case.case_id,
            signal_name=SignalName.BACKEND_PRESENCE.value,
            signal_value=infra_score,
            score_component="infrastructure_reality",
            confidence=0.75,
        )
        db.add(sig)
        signals.append(sig)

    db.flush()
    return signals


def _format_infra_for_report(infra: dict[str, Any] | None) -> dict[str, Any] | None:
    """Format infrastructure probe results for the report JSON."""
    if not infra or not infra.get("best_probe"):
        return None
    best = infra["best_probe"]
    return {
        "domain": best.get("domain"),
        "dns_resolves": best.get("dns_resolves"),
        "http_status": best.get("http_status"),
        "is_https": best.get("is_https"),
        "has_valid_tls": best.get("has_valid_tls"),
        "content_length": best.get("content_length"),
        "server_header": best.get("server_header"),
        "response_time_ms": best.get("response_time_ms"),
        "urls_checked": infra.get("urls_checked", []),
    }


def _run_llm_reasoning(
    case: Case,
    project: Project,
    signals: list[Signal],
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Call the LLM reasoning layer (§14) on structured evidence.
    Returns ReasoningOutput dict or None if unavailable/failed.
    """
    from packages.common.config import settings as _s

    if not _s.anthropic_api_key:
        logger.info("No ANTHROPIC_API_KEY — skipping LLM reasoning")
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=_s.anthropic_api_key)

        # Build structured inputs — never raw text dumps (§14)
        project_json = json.dumps({
            "name": project.canonical_name,
            "symbol": project.symbol,
            "chain": project.chain,
            "primary_contract": project.primary_contract,
        }, indent=2)

        signals_json = json.dumps([
            {
                "name": s.signal_name,
                "value": s.signal_value,
                "confidence": s.confidence,
                "component": s.score_component,
            }
            for s in signals
        ], indent=2)

        # Build evidence summary (not raw dumps)
        evidence_parts: list[str] = []
        for key, val in evidence.items():
            if key.startswith("_"):
                continue
            if isinstance(val, dict):
                evidence_parts.append(f"- {key}: keys={list(val.keys())[:8]}")
            elif isinstance(val, list):
                evidence_parts.append(f"- {key}: {len(val)} items")
            elif val is not None:
                evidence_parts.append(f"- {key}: {str(val)[:100]}")
        evidence_summary = "\n".join(evidence_parts) or "No evidence collected."

        system_prompt = (
            "You are a crypto project investigation assistant. You analyze structured "
            "evidence to assess project credibility.\n\n"
            "Rules:\n"
            "- Base your analysis ONLY on the evidence provided. Never invent or assume facts.\n"
            "- If data is missing, explicitly note it as missing — do not speculate.\n"
            "- You are not a market predictor. You assess whether a project's public narrative "
            "matches its on-chain, code, and infrastructure evidence.\n"
            "- Flag contradictions between public claims and evidence.\n"
            "- Be specific: cite signal names and values when supporting findings.\n\n"
            "Respond ONLY with a JSON object containing these fields:\n"
            '{\n  "summary": "One paragraph executive summary",\n'
            '  "supporting_findings": ["Finding 1", ...],\n'
            '  "contradictions": ["Contradiction 1", ...],\n'
            '  "open_questions": ["Question 1", ...],\n'
            '  "verdict_suggestion": "legitimate | suspicious | high_risk | larp",\n'
            '  "confidence": 0.0 to 1.0\n}'
        )

        user_msg = (
            f"Investigate this project:\n\n"
            f"## Project\n{project_json}\n\n"
            f"## Signals\n{signals_json}\n\n"
            f"## Evidence Summary\n{evidence_summary}\n\n"
            f"Analyze the evidence and produce your investigation findings as JSON."
        )

        logger.info("Calling LLM for reasoning on case %s...", case.case_id)
        response = client.messages.create(
            model=_s.llm_model,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )

        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

        parsed = json.loads(raw_text)
        logger.info("LLM reasoning complete for case %s", case.case_id)
        return parsed

    except Exception as exc:
        logger.warning("LLM reasoning failed (non-fatal): %s", exc)
        return None


def _format_bags_for_report(bags: dict[str, Any] | None) -> dict[str, Any] | None:
    """Format Bags data for the report JSON."""
    if not bags or bags.get("error") == "not_found":
        return None
    return {
        "bags_launched": bags.get("bags_launched", False),
        "lifetime_fees_sol": bags.get("lifetime_fees_sol"),
        "trading_volume_usd": bags.get("trading_volume_usd"),
        "creator": bags.get("creator"),
        "created_at": bags.get("created_at"),
        "holder_count": bags.get("holder_count"),
        "market_cap": bags.get("market_cap"),
    }


def _build_report(
    project: Project,
    scoring_result: Any,
    signals: list[Signal],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the final report JSON."""
    market = evidence.get("market", {})
    token_meta = evidence.get("token_metadata", {})

    report: dict[str, Any] = {
        "executive_summary": (
            f"Automated credibility assessment for {project.canonical_name} "
            f"({project.symbol or 'N/A'}) on {project.chain}. "
            f"Score: {scoring_result.total_score}/100. "
            f"Verdict: {scoring_result.verdict.value.upper()}."
        ),
        "project": {
            "name": project.canonical_name,
            "symbol": project.symbol,
            "chain": project.chain,
            "primary_contract": project.primary_contract,
            "description": token_meta.get("description"),
            "image": token_meta.get("image_url"),
        },
        "credibility_score": scoring_result.total_score,
        "verdict": scoring_result.verdict.value,
        "overall_confidence": scoring_result.overall_confidence,
        "score_breakdown": [
            {
                "category": cs.name,
                "earned": cs.earned_points,
                "max": cs.max_points,
                "confidence": cs.confidence,
            }
            for cs in scoring_result.category_scores
        ],
        "signals": [
            {
                "name": s.signal_name,
                "value": s.signal_value,
                "confidence": s.confidence,
                "component": s.score_component,
            }
            for s in signals
        ],
        "market_data": {
            "price_usd": market.get("price_usd"),
            "market_cap": market.get("market_cap"),
            "liquidity_usd": market.get("total_liquidity_usd"),
            "volume_24h": market.get("total_volume_24h"),
            "pairs_found": market.get("pairs_found"),
            "dex": market.get("dex"),
            "pair_created_at": market.get("pair_created_at"),
        },
        "deployer": {
            "address": evidence.get("deployer_address"),
            "funding_chain": evidence.get("funding_chain", []),
        },
        "top_holders": evidence.get("top_holders", [])[:10],
        "missing_data": scoring_result.missing_signals,
        "github": {
            "repo": evidence.get("github_repo"),
            "commits_28d": (evidence.get("github_commits") or {}).get("commit_count_28d"),
            "unique_authors_28d": (evidence.get("github_commits") or {}).get("unique_authors_28d"),
        } if evidence.get("github_repo") else None,
        "infrastructure": _format_infra_for_report(evidence.get("infrastructure")),
        "bags": _format_bags_for_report(evidence.get("bags")),
    }

    # Generate top findings
    findings: list[str] = []
    holders = evidence.get("top_holders", [])
    if holders:
        top10_pct = sum(h.get("percentage", 0) for h in holders[:10])
        findings.append(f"Top 10 holders control {top10_pct:.1f}% of supply")
    if market.get("total_liquidity_usd"):
        findings.append(f"Total liquidity: ${market['total_liquidity_usd']:,.0f}")
    if evidence.get("deployer_address"):
        findings.append(f"Deployer identified: {evidence['deployer_address'][:16]}...")
    if evidence.get("funding_chain"):
        depth = len(evidence["funding_chain"])
        findings.append(f"Funding traced {depth} hop(s) back from deployer")
    if not evidence.get("deployer_address"):
        findings.append("Could not identify deployer — limited historical data")

    bags_data = evidence.get("bags") or {}
    if bags_data.get("bags_launched"):
        findings.append("Token launched on Bags launchpad")
        if bags_data.get("lifetime_fees_sol"):
            findings.append(f"Bags lifetime fees: {bags_data['lifetime_fees_sol']:.4f} SOL")
        if bags_data.get("trading_volume_usd"):
            findings.append(f"Bags trading volume: ${bags_data['trading_volume_usd']:,.0f}")

    github_repo = evidence.get("github_repo") or {}
    github_commits = evidence.get("github_commits") or {}
    if github_repo.get("exists"):
        age = github_repo.get("age_days", 0)
        stars = github_repo.get("stars", 0)
        is_fork = github_repo.get("is_fork", False)
        findings.append(
            f"GitHub repo {github_repo['owner']}/{github_repo['repo']}: "
            f"{age}d old, {stars} stars"
            + (" [FORK]" if is_fork else "")
        )
        if github_commits:
            c = github_commits.get("commit_count_28d", 0)
            a = github_commits.get("unique_authors_28d", 0)
            findings.append(f"Recent activity: {c} commits / {a} unique authors (last 28d)")

    infra = evidence.get("infrastructure") or {}
    best = infra.get("best_probe") or {}
    if best:
        status = best.get("http_status") or 0
        domain = best.get("domain", "unknown")
        tls = "TLS" if best.get("has_valid_tls") else "no TLS"
        if 200 <= status < 300:
            findings.append(f"Website live: {domain} (HTTP {status}, {tls})")
        elif best.get("dns_resolves"):
            findings.append(f"Website DNS resolves but HTTP failed: {domain} (HTTP {status})")
        else:
            findings.append(f"Website unreachable: {domain}")

    report["top_findings"] = findings
    report["open_questions"] = []

    if scoring_result.missing_signals:
        report["open_questions"].append(
            f"Missing signals: {', '.join(scoring_result.missing_signals)}"
        )
    if not evidence.get("funding_chain"):
        report["open_questions"].append("Funding source could not be traced")

    # Embed partner CTA for Legitimate verdicts on Bags tokens
    from packages.common.config import settings as _settings
    if (
        scoring_result.verdict == Verdict.LEGITIMATE
        and bags_data.get("bags_launched")
        and _settings.bags_partner_key
    ):
        report["bags_partner_cta"] = (
            f"https://bags.fm/trade/{project.primary_contract}"
            f"?partner={_settings.bags_partner_key}"
        )

    return report

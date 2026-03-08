"""Discovery worker — §6.1 and §11.

Autonomous discovery loop:
- Polls Bags API every 5 minutes for new token launches
- Listens to Helius webhooks for new mint events
- Deduplicates by contract address
- Assigns investigation priority (volume velocity, Bags-launched flag)
- Creates Case records and runs the sync investigation pipeline
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from packages.common.celery_app import celery_app
from packages.common.config import settings
from packages.common.database import get_sync_session
from packages.common.enums import CaseStatus, CasePriority, TriggerSource
from packages.common.models import Case, Job, Project, ProjectAlias

logger = logging.getLogger(__name__)


# ── Autonomous Bags Polling (§11.1) ────────────────────────────────────────


@celery_app.task(name="workers.discovery.poll_bags_launches", bind=True, max_retries=3)
def poll_bags_launches(self) -> dict:
    """
    Poll Bags API for new token launches.
    Runs every 5 minutes via Celery Beat.
    Creates cases for tokens not yet investigated.
    """
    logger.info("Polling Bags API for new launches...")

    try:
        from workers.fetch.adapters.bags import BagsAdapter

        bags = BagsAdapter()
        launches = bags.get_recent_launches(limit=50)
        bags.close()
    except ValueError:
        logger.warning("BAGS_API_KEY not set — skipping Bags poll")
        return {"status": "skipped", "reason": "no_api_key"}
    except Exception as exc:
        logger.exception("Bags poll failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)

    if not launches:
        logger.info("No new launches from Bags")
        return {"status": "ok", "new_cases": 0}

    new_cases = 0

    with get_sync_session() as db:
        for token in launches:
            token_address = token.get("token_address")
            if not token_address:
                continue

            # Dedup: skip if we already have this contract
            existing = (
                db.query(Project)
                .filter(Project.primary_contract == token_address)
                .first()
            )
            if existing:
                continue

            # Priority scoring: volume velocity + Bags-launched bonus
            priority = _assign_priority(token)

            # Create project + case
            project = Project(
                canonical_name=token.get("name") or f"bags-{token_address[:8]}",
                symbol=token.get("symbol"),
                chain="solana",
                primary_contract=token_address,
            )
            db.add(project)
            db.flush()

            # Store aliases
            if token.get("symbol"):
                db.add(ProjectAlias(
                    project_id=project.project_id,
                    alias_type="symbol",
                    alias_value=token["symbol"],
                ))
            db.add(ProjectAlias(
                project_id=project.project_id,
                alias_type="contract",
                alias_value=token_address,
            ))

            case = Case(
                project_id=project.project_id,
                trigger_source=TriggerSource.CHAIN_EVENT.value,
                priority=priority,
                status=CaseStatus.CREATED.value,
            )
            db.add(case)
            db.flush()

            new_cases += 1

            # Dispatch investigation
            celery_app.send_task(
                "workers.discovery.run_autonomous_investigation",
                args=[str(case.case_id), str(project.project_id)],
                queue="discovery",
            )

            logger.info(
                "Discovered new Bags token: %s (%s) — priority=%s",
                token.get("name"), token_address[:16], priority,
            )

        db.commit()

    logger.info("Bags poll complete: %d new cases created", new_cases)
    return {"status": "ok", "new_cases": new_cases}


# ── Helius Webhook Handler (§11.1) ─────────────────────────────────────────


@celery_app.task(name="workers.discovery.handle_helius_webhook", bind=True, max_retries=2)
def handle_helius_webhook(self, webhook_data: dict) -> dict:
    """
    Process a Helius webhook event for a new token mint.
    Higher priority than Bags polling.
    """
    logger.info("Processing Helius webhook event")

    token_address = _extract_mint_from_webhook(webhook_data)
    if not token_address:
        logger.warning("Could not extract mint address from webhook")
        return {"status": "skipped", "reason": "no_mint_address"}

    with get_sync_session() as db:
        # Dedup
        existing = (
            db.query(Project)
            .filter(Project.primary_contract == token_address)
            .first()
        )
        if existing:
            return {"status": "skipped", "reason": "already_exists"}

        project = Project(
            canonical_name=f"unknown-{token_address[:8]}",
            chain="solana",
            primary_contract=token_address,
        )
        db.add(project)
        db.flush()

        db.add(ProjectAlias(
            project_id=project.project_id,
            alias_type="contract",
            alias_value=token_address,
        ))

        case = Case(
            project_id=project.project_id,
            trigger_source=TriggerSource.CHAIN_EVENT.value,
            priority=CasePriority.HIGH.value,
            status=CaseStatus.CREATED.value,
        )
        db.add(case)
        db.flush()

        db.commit()

    celery_app.send_task(
        "workers.discovery.run_autonomous_investigation",
        args=[str(case.case_id), str(project.project_id)],
        queue="discovery",
    )

    return {"status": "ok", "case_id": str(case.case_id)}


# ── Autonomous Investigation Runner ───────────────────────────────────────


@celery_app.task(
    name="workers.discovery.run_autonomous_investigation",
    bind=True,
    max_retries=2,
    soft_time_limit=300,
    time_limit=360,
)
def run_autonomous_investigation(self, case_id: str, project_id: str) -> dict:
    """
    Run the full sync investigation pipeline autonomously.
    This is what makes the system an agent — no human input needed.
    """
    logger.info("Running autonomous investigation: case=%s", case_id)

    try:
        from workers.fetch.investigate import run_investigation

        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            project = db.get(Project, uuid.UUID(project_id))

            if not case or not project:
                return {"error": "case_or_project_not_found"}

            report = run_investigation(db, case, project)
            db.commit()

        logger.info(
            "Autonomous investigation complete: case=%s score=%s verdict=%s",
            case_id,
            report.get("credibility_score"),
            report.get("verdict"),
        )

        # Dispatch LLM reasoning as follow-up (if API key is set)
        if settings.anthropic_api_key:
            celery_app.send_task(
                "workers.reasoning.generate_verdict",
                args=[case_id],
                queue="reasoning",
            )

        return {
            "status": "ok",
            "case_id": case_id,
            "score": report.get("credibility_score"),
            "verdict": report.get("verdict"),
        }

    except Exception as exc:
        logger.exception("Autonomous investigation failed: case=%s", case_id)
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if case:
                case.status = CaseStatus.FAILED.value
                db.commit()
        raise self.retry(exc=exc, countdown=30)


# ── Re-Investigation Triggers (§11.2) ──────────────────────────────────────


@celery_app.task(name="workers.discovery.reinvestigate_active_cases", bind=True)
def reinvestigate_active_cases(self) -> dict:
    """
    Scheduled: re-investigate all active cases every 24 hours.
    Also triggered by price spikes or volume anomalies.
    """
    logger.info("Starting re-investigation sweep")
    reinvestigated = 0

    with get_sync_session() as db:
        active_cases = (
            db.query(Case)
            .filter(Case.status == CaseStatus.PUBLISHED.value)
            .all()
        )

        for case in active_cases:
            celery_app.send_task(
                "workers.discovery.run_autonomous_investigation",
                args=[str(case.case_id), str(case.project_id)],
                queue="discovery",
            )
            reinvestigated += 1

    logger.info("Queued %d cases for re-investigation", reinvestigated)
    return {"status": "ok", "reinvestigated": reinvestigated}


# ── Legacy Celery dispatch (kept for /cases/analyze endpoint) ──────────────


@celery_app.task(name="workers.discovery.start_investigation", bind=True, max_retries=3)
def start_investigation(self, case_id: str) -> dict:
    """
    Entry point after a case is created via API.
    Runs the sync pipeline directly instead of dispatching individual fetch jobs.
    """
    logger.info("Starting investigation for case %s", case_id)

    with get_sync_session() as db:
        case = db.get(Case, uuid.UUID(case_id))
        if case is None:
            logger.error("Case %s not found", case_id)
            return {"error": "case_not_found"}

        project = db.get(Project, case.project_id)
        if project is None:
            logger.error("Project not found for case %s", case_id)
            return {"error": "project_not_found"}

    # Dispatch autonomous investigation
    celery_app.send_task(
        "workers.discovery.run_autonomous_investigation",
        args=[case_id, str(project.project_id)],
        queue="discovery",
    )

    return {"case_id": case_id, "status": "dispatched"}


# ── Helpers ────────────────────────────────────────────────────────────────


def _assign_priority(token: dict[str, Any]) -> str:
    """
    Assign investigation priority based on volume velocity and Bags flag.

    Priority scoring:
    - High volume (>$100k) or rapid trading: CRITICAL
    - Medium volume ($10k-$100k): HIGH
    - Low volume ($1k-$10k): MEDIUM
    - Minimal activity: LOW
    """
    vol = token.get("trading_volume_usd", 0) or 0
    mcap = token.get("market_cap", 0) or 0

    if vol >= 100_000 or mcap >= 1_000_000:
        return CasePriority.CRITICAL.value
    elif vol >= 10_000 or mcap >= 100_000:
        return CasePriority.HIGH.value
    elif vol >= 1_000:
        return CasePriority.MEDIUM.value
    else:
        return CasePriority.LOW.value


def _extract_mint_from_webhook(data: dict[str, Any]) -> str | None:
    """Extract the token mint address from a Helius webhook payload."""
    # Helius enhanced tx format
    if isinstance(data, list) and data:
        data = data[0]

    # Check token transfers
    for transfer in data.get("tokenTransfers", []):
        if transfer.get("tokenStandard") == "Fungible":
            return transfer.get("mint")

    # Check account data for new token mints
    for acc in data.get("accountData", []):
        if acc.get("tokenBalanceChanges"):
            for change in acc["tokenBalanceChanges"]:
                return change.get("mint")

    # Fallback: check events
    events = data.get("events", {})
    if "nft" in events or "token" in events:
        token_event = events.get("token", events.get("nft", {}))
        return token_event.get("mint")

    return None

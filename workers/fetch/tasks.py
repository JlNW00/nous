"""Fetch worker — §6.2 and §12.

Pulls raw evidence from provider adapters, stores it, and signals completion.
"""

from __future__ import annotations

import logging
import uuid

from packages.common.celery_app import celery_app
from packages.common.database import get_sync_session
from packages.common.enums import JobStatus
from packages.common.models import Case, Job, Project

logger = logging.getLogger(__name__)


def _mark_job(db, job_id: str, status: str, error: str | None = None) -> None:
    job = db.get(Job, uuid.UUID(job_id))
    if job:
        job.status = status
        job.attempts += 1
        if error:
            job.error_message = error
        db.flush()


def _on_fetch_complete(case_id: str) -> None:
    """Notify discovery worker to check if all fetches are done."""
    celery_app.send_task(
        "workers.discovery.check_collection_complete",
        args=[case_id],
        queue="discovery",
    )


@celery_app.task(name="workers.fetch.fetch_token_data", bind=True, max_retries=3)
def fetch_token_data(self, case_id: str, job_id: str) -> dict:
    """Fetch token metadata, holders, and supply data."""
    logger.info("Fetching token data for case %s", case_id)
    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                _mark_job(db, job_id, JobStatus.FAILED.value, "case_not_found")
                return {"error": "case_not_found"}

            project = db.get(Project, case.project_id)
            if not project or not project.primary_contract:
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                return {"status": "skipped", "reason": "no_contract"}

            # TODO: Instantiate chain-specific adapter (Helius for Solana, Alchemy for ETH, etc.)
            # adapter = get_token_adapter(project.chain)
            # evidence = adapter.fetch(db, address=project.primary_contract)
            # adapter.store_evidence(db, case.case_id, evidence)

            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            db.commit()

    except Exception as exc:
        logger.exception("Failed to fetch token data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            db.commit()
        raise self.retry(exc=exc)
    finally:
        _on_fetch_complete(case_id)

    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_wallet_data", bind=True, max_retries=3)
def fetch_wallet_data(self, case_id: str, job_id: str) -> dict:
    """Fetch deployer wallet history, funding sources, and transaction patterns."""
    logger.info("Fetching wallet data for case %s", case_id)
    try:
        with get_sync_session() as db:
            # TODO: Resolve deployer from contract, trace funding chain up to CASE_MAX_DEPTH
            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            db.commit()
    except Exception as exc:
        logger.exception("Failed to fetch wallet data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            db.commit()
        raise self.retry(exc=exc)
    finally:
        _on_fetch_complete(case_id)
    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_liquidity_data", bind=True, max_retries=3)
def fetch_liquidity_data(self, case_id: str, job_id: str) -> dict:
    """Fetch DEX pair data, liquidity positions, and lock status."""
    logger.info("Fetching liquidity data for case %s", case_id)
    try:
        with get_sync_session() as db:
            # TODO: DexScreener / Birdeye adapter
            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            db.commit()
    except Exception as exc:
        logger.exception("Failed to fetch liquidity data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            db.commit()
        raise self.retry(exc=exc)
    finally:
        _on_fetch_complete(case_id)
    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_code_data", bind=True, max_retries=3)
def fetch_code_data(self, case_id: str, job_id: str) -> dict:
    """Fetch GitHub repo metadata, commit history, and contributor data."""
    logger.info("Fetching code data for case %s", case_id)
    try:
        with get_sync_session() as db:
            # TODO: GitHub API adapter
            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            db.commit()
    except Exception as exc:
        logger.exception("Failed to fetch code data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            db.commit()
        raise self.retry(exc=exc)
    finally:
        _on_fetch_complete(case_id)
    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_social_data", bind=True, max_retries=3)
def fetch_social_data(self, case_id: str, job_id: str) -> dict:
    """Fetch X/Telegram/Discord account metadata and engagement data."""
    logger.info("Fetching social data for case %s", case_id)
    try:
        with get_sync_session() as db:
            # TODO: X API / scraper adapter
            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            db.commit()
    except Exception as exc:
        logger.exception("Failed to fetch social data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            db.commit()
        raise self.retry(exc=exc)
    finally:
        _on_fetch_complete(case_id)
    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_infrastructure_data", bind=True, max_retries=3)
def fetch_infrastructure_data(self, case_id: str, job_id: str) -> dict:
    """Fetch DNS, WHOIS, SSL, and HTTP probe data."""
    logger.info("Fetching infrastructure data for case %s", case_id)
    try:
        with get_sync_session() as db:
            # TODO: DNS/WHOIS/HTTP adapter
            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            db.commit()
    except Exception as exc:
        logger.exception("Failed to fetch infrastructure data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            db.commit()
        raise self.retry(exc=exc)
    finally:
        _on_fetch_complete(case_id)
    return {"status": "completed"}

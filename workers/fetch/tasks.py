"""Fetch worker — §6.2 and §12.

Pulls raw evidence from provider adapters, stores it, and signals completion.

Each task handles one data domain (token, wallet, liquidity, code, social,
infrastructure). Tasks run in parallel on the 'fetch' queue. When all fetch
jobs for a case complete, the last one to finish dispatches the graph worker.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from packages.common.celery_app import celery_app
from packages.common.database import get_sync_session
from packages.common.enums import CaseStatus, JobStatus
from packages.common.models import Case, Contract, Job, Project, RawEvidence, Wallet

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _mark_job(db, job_id: str, status: str, error: str | None = None) -> None:
    job = db.get(Job, uuid.UUID(job_id))
    if job:
        job.status = status
        job.attempts += 1
        if error:
            job.error_message = error
        db.flush()


def _store_evidence(
    db,
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


def _check_and_dispatch_next_stage(db, case_id: str) -> bool:
    """
    Check if ALL fetch jobs for this case are done.
    If so, transition case and dispatch graph enrichment.
    Returns True if graph worker was dispatched.
    """
    pending_jobs = (
        db.query(Job)
        .filter(
            Job.case_id == uuid.UUID(case_id),
            Job.job_type.like("fetch_%"),
            Job.status.notin_([JobStatus.COMPLETED.value, JobStatus.FAILED.value]),
        )
        .count()
    )

    if pending_jobs == 0:
        case = db.get(Case, uuid.UUID(case_id))
        if case and case.status == CaseStatus.COLLECTING.value:
            case.status = CaseStatus.ANALYZING.value
            db.flush()

            # Dispatch graph enrichment
            celery_app.send_task(
                "workers.graph.enrich_graph",
                args=[case_id],
                queue="graph",
            )
            logger.info(
                "All fetch jobs complete for case %s — dispatched graph enrichment",
                case_id,
            )
            return True

    return False


# ── Evidence extraction helpers ─────────────────────────────────────────────
# These mirror the logic from investigate.py but read from DB evidence rows
# rather than in-memory dicts, since async tasks can't share state.


def _extract_github_url_from_evidence(evidence_rows: list[RawEvidence]) -> str | None:
    """Scan stored evidence for a GitHub repository URL."""
    from workers.fetch.adapters.github import GitHubAdapter

    for ev in evidence_rows:
        payload = ev.payload_json

        # Helius external_url
        ext_url = payload.get("external_url") or ""
        if "github.com" in ext_url and GitHubAdapter.parse_github_url(ext_url):
            return ext_url

        # DexScreener socials
        for social in payload.get("socials", []):
            url = social.get("url") or ""
            if "github.com" in url and GitHubAdapter.parse_github_url(url):
                return url

        # DexScreener websites
        for site in payload.get("websites", []):
            url = site.get("url") or ""
            if "github.com" in url and GitHubAdapter.parse_github_url(url):
                return url

    return None


def _extract_website_urls_from_evidence(evidence_rows: list[RawEvidence]) -> list[str]:
    """Collect project website URLs from evidence for infrastructure probing."""
    urls: list[str] = []

    for ev in evidence_rows:
        payload = ev.payload_json

        # Helius external_url
        ext_url = payload.get("external_url") or ""
        if ext_url and "github.com" not in ext_url and ext_url not in urls:
            urls.append(ext_url)

        # DexScreener websites
        for site in payload.get("websites", []):
            url = site.get("url") or ""
            if url and "github.com" not in url and url not in urls:
                urls.append(url)

    return urls


# ── Fetch Tasks ─────────────────────────────────────────────────────────────


@celery_app.task(name="workers.fetch.fetch_token_data", bind=True, max_retries=3)
def fetch_token_data(self, case_id: str, job_id: str) -> dict:
    """Fetch token metadata, holders, and supply data via Helius."""
    logger.info("Fetching token data for case %s", case_id)
    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                _mark_job(db, job_id, JobStatus.FAILED.value, "case_not_found")
                db.commit()
                return {"error": "case_not_found"}

            project = db.get(Project, case.project_id)
            if not project or not project.primary_contract:
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "no_contract"}

            if project.chain != "solana":
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "unsupported_chain"}

            # ── Helius: token metadata + holders ────────────────────────
            from workers.fetch.adapters.helius import HeliusAdapter

            helius = HeliusAdapter()

            # Token metadata
            logger.info("Fetching token metadata from Helius...")
            token_meta = helius.get_token_metadata(project.primary_contract)
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
            _store_evidence(db, case.case_id, "on_chain", "helius", {
                "top_holders": holders,
                "mint": project.primary_contract,
            })

            # Deployer identification
            logger.info("Identifying deployer...")
            creation_tx = helius.get_token_creation_tx(project.primary_contract)
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

                # Check if Bags-launched (via creation tx signers)
                from workers.fetch.adapters.bags import BagsAdapter
                bags_launched_helius = BagsAdapter.is_bags_launched(creation_tx)
                if bags_launched_helius:
                    _store_evidence(db, case.case_id, "on_chain", "helius", {
                        "bags_launched_helius": True,
                        "mint": project.primary_contract,
                    })

            helius.close()

            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()

    except ValueError as exc:
        logger.warning("Helius adapter unavailable: %s", exc)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()
        return {"status": "skipped", "reason": str(exc)}

    except Exception as exc:
        logger.exception("Failed to fetch token data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()
        raise self.retry(exc=exc, countdown=10)

    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_wallet_data", bind=True, max_retries=3)
def fetch_wallet_data(self, case_id: str, job_id: str) -> dict:
    """Fetch deployer wallet history, funding sources, and transaction patterns."""
    logger.info("Fetching wallet data for case %s", case_id)
    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                _mark_job(db, job_id, JobStatus.FAILED.value, "case_not_found")
                db.commit()
                return {"error": "case_not_found"}

            project = db.get(Project, case.project_id)
            if not project or project.chain != "solana":
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "unsupported_chain"}

            # Find deployer from already-stored evidence
            deployer_evidence = (
                db.query(RawEvidence)
                .filter(
                    RawEvidence.case_id == case.case_id,
                    RawEvidence.provider == "helius",
                )
                .all()
            )

            deployer = None
            for ev in deployer_evidence:
                if ev.payload_json.get("deployer_address"):
                    deployer = ev.payload_json["deployer_address"]
                    break

            if not deployer:
                logger.info("No deployer found for case %s — skipping wallet fetch", case_id)
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "no_deployer"}

            # ── Trace funding chain ─────────────────────────────────────
            from workers.fetch.adapters.helius import HeliusAdapter

            helius = HeliusAdapter()

            logger.info("Tracing funding source for deployer %s...", deployer[:16])
            try:
                funding_chain = helius.trace_funding_source(deployer, max_depth=3)
                if funding_chain:
                    _store_evidence(db, case.case_id, "on_chain", "helius", {
                        "funding_chain": funding_chain,
                        "deployer_address": deployer,
                    })
            except Exception as trace_exc:
                logger.warning("Funding trace failed: %s", trace_exc)

            # Fetch deployer's recent transaction history
            logger.info("Fetching deployer transaction history...")
            try:
                deployer_txs = helius.get_wallet_transactions(deployer, limit=50)
                _store_evidence(db, case.case_id, "on_chain", "helius", {
                    "deployer_transactions": deployer_txs,
                    "deployer_address": deployer,
                    "tx_count": len(deployer_txs),
                })
            except Exception as tx_exc:
                logger.warning("Deployer tx history failed: %s", tx_exc)

            helius.close()

            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()

    except ValueError as exc:
        logger.warning("Helius adapter unavailable: %s", exc)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()
        return {"status": "skipped", "reason": str(exc)}

    except Exception as exc:
        logger.exception("Failed to fetch wallet data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()
        raise self.retry(exc=exc, countdown=10)

    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_liquidity_data", bind=True, max_retries=3)
def fetch_liquidity_data(self, case_id: str, job_id: str) -> dict:
    """Fetch DEX pair data, liquidity positions, and Bags launchpad data."""
    logger.info("Fetching liquidity data for case %s", case_id)
    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                _mark_job(db, job_id, JobStatus.FAILED.value, "case_not_found")
                db.commit()
                return {"error": "case_not_found"}

            project = db.get(Project, case.project_id)
            if not project or not project.primary_contract:
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "no_contract"}

            # ── DexScreener: market data ────────────────────────────────
            try:
                from workers.fetch.adapters.dexscreener import DexScreenerAdapter

                dex = DexScreenerAdapter()
                logger.info("Fetching market data from DexScreener...")
                market = dex.get_market_summary(project.primary_contract)
                _store_evidence(db, case.case_id, "market", "dexscreener", market)
                dex.close()
            except Exception as dex_exc:
                logger.exception("DexScreener fetch failed: %s", dex_exc)

            # ── Bags: launchpad data ────────────────────────────────────
            if project.chain == "solana":
                try:
                    from workers.fetch.adapters.bags import BagsAdapter

                    bags = BagsAdapter()
                    logger.info("Fetching Bags token data...")
                    bags_info = bags.get_token_info(project.primary_contract)
                    _store_evidence(db, case.case_id, "market", "bags", bags_info)
                    bags.close()
                except ValueError as bags_exc:
                    logger.warning("Bags adapter unavailable: %s", bags_exc)
                except Exception as bags_exc:
                    logger.exception("Bags fetch failed: %s", bags_exc)

            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()

    except Exception as exc:
        logger.exception("Failed to fetch liquidity data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()
        raise self.retry(exc=exc, countdown=10)

    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_code_data", bind=True, max_retries=3)
def fetch_code_data(self, case_id: str, job_id: str) -> dict:
    """Fetch GitHub repo metadata, commit history, and contributor data."""
    logger.info("Fetching code data for case %s", case_id)
    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                _mark_job(db, job_id, JobStatus.FAILED.value, "case_not_found")
                db.commit()
                return {"error": "case_not_found"}

            # Find GitHub URL from already-stored evidence
            evidence_rows = (
                db.query(RawEvidence)
                .filter(RawEvidence.case_id == case.case_id)
                .all()
            )

            github_url = _extract_github_url_from_evidence(evidence_rows)
            if not github_url:
                logger.info("No GitHub URL found for case %s — skipping code fetch", case_id)
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "no_github_url"}

            # ── GitHub API ──────────────────────────────────────────────
            from workers.fetch.adapters.github import GitHubAdapter

            gh = GitHubAdapter()
            parsed = GitHubAdapter.parse_github_url(github_url)
            if not parsed:
                gh.close()
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "invalid_github_url"}

            owner, repo = parsed

            logger.info("Fetching GitHub repo info for %s/%s...", owner, repo)
            repo_info = gh.get_repo_info(owner, repo)
            _store_evidence(db, case.case_id, "code", "github", repo_info)

            if repo_info.get("exists"):
                logger.info("Fetching recent commits for %s/%s...", owner, repo)
                commit_data = gh.get_recent_commit_activity(owner, repo)
                _store_evidence(db, case.case_id, "code", "github", commit_data)

            gh.close()

            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()

    except Exception as exc:
        logger.exception("Failed to fetch code data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()
        raise self.retry(exc=exc, countdown=10)

    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_social_data", bind=True, max_retries=3)
def fetch_social_data(self, case_id: str, job_id: str) -> dict:
    """Fetch X/Telegram/Discord account metadata and engagement data."""
    logger.info("Fetching social data for case %s", case_id)
    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                _mark_job(db, job_id, JobStatus.FAILED.value, "case_not_found")
                db.commit()
                return {"error": "case_not_found"}

            # Extract social URLs from market evidence
            evidence_rows = (
                db.query(RawEvidence)
                .filter(
                    RawEvidence.case_id == case.case_id,
                    RawEvidence.provider == "dexscreener",
                )
                .all()
            )

            socials: list[dict[str, Any]] = []
            for ev in evidence_rows:
                socials.extend(ev.payload_json.get("socials", []))

            if not socials:
                logger.info("No social links found for case %s", case_id)
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "no_social_links"}

            # Store social link metadata as evidence.
            # Full social scraping (X API, Telegram stats) is Phase 2.
            # For now we record presence/absence of social channels,
            # which feeds into the narrative_consistency signal.
            social_summary = {
                "social_links": socials,
                "platform_count": len({
                    s.get("type") for s in socials if s.get("type")
                }),
                "platforms": list({
                    s.get("type") for s in socials if s.get("type")
                }),
                "has_twitter": any(
                    s.get("type") in ("twitter", "x")
                    or "twitter.com" in s.get("url", "")
                    or "x.com" in s.get("url", "")
                    for s in socials
                ),
                "has_telegram": any(
                    s.get("type") == "telegram"
                    or "t.me" in s.get("url", "")
                    for s in socials
                ),
                "has_discord": any(
                    s.get("type") == "discord"
                    or "discord" in s.get("url", "")
                    for s in socials
                ),
            }
            _store_evidence(db, case.case_id, "social", "dexscreener", social_summary)

            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()

    except Exception as exc:
        logger.exception("Failed to fetch social data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()
        raise self.retry(exc=exc, countdown=10)

    return {"status": "completed"}


@celery_app.task(name="workers.fetch.fetch_infrastructure_data", bind=True, max_retries=3)
def fetch_infrastructure_data(self, case_id: str, job_id: str) -> dict:
    """Fetch DNS, WHOIS, SSL, and HTTP probe data for project websites."""
    logger.info("Fetching infrastructure data for case %s", case_id)
    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                _mark_job(db, job_id, JobStatus.FAILED.value, "case_not_found")
                db.commit()
                return {"error": "case_not_found"}

            # Extract website URLs from stored evidence
            evidence_rows = (
                db.query(RawEvidence)
                .filter(RawEvidence.case_id == case.case_id)
                .all()
            )

            urls = _extract_website_urls_from_evidence(evidence_rows)
            if not urls:
                logger.info("No website URLs for case %s — skipping infra probe", case_id)
                _mark_job(db, job_id, JobStatus.COMPLETED.value)
                _check_and_dispatch_next_stage(db, case_id)
                db.commit()
                return {"status": "skipped", "reason": "no_website_urls"}

            # ── Infrastructure probe ────────────────────────────────────
            from workers.fetch.adapters.infrastructure import InfrastructureAdapter

            infra = InfrastructureAdapter()
            logger.info("Probing infrastructure for %d URL(s)...", len(urls))
            infra_result = infra.probe_domain_summary(urls)
            _store_evidence(
                db, case.case_id, "infrastructure", "http_probe", infra_result
            )
            infra.close()

            _mark_job(db, job_id, JobStatus.COMPLETED.value)
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()

    except Exception as exc:
        logger.exception("Failed to fetch infra data for case %s", case_id)
        with get_sync_session() as db:
            _mark_job(db, job_id, JobStatus.FAILED.value, str(exc))
            _check_and_dispatch_next_stage(db, case_id)
            db.commit()
        raise self.retry(exc=exc, countdown=10)

    return {"status": "completed"}

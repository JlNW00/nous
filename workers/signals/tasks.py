"""Signal calculator worker — §6.4, §10, and §12.

Computes deterministic signals from evidence and graph context.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from packages.common.celery_app import celery_app
from packages.common.database import get_sync_session
from packages.common.enums import CaseStatus, SignalName
from packages.common.graph import neo4j_client
from packages.common.models import Case, RawEvidence, Signal

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.signals.calculate_signals", bind=True, max_retries=2)
def calculate_signals(self, case_id: str) -> dict:
    """
    Run all signal calculators for a case.

    Each calculator reads from raw_evidence and/or graph context,
    produces a Signal row with value, confidence, and evidence refs.
    """
    logger.info("Calculating signals for case %s", case_id)

    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                return {"error": "case_not_found"}

            evidence = (
                db.query(RawEvidence)
                .filter(RawEvidence.case_id == case.case_id)
                .all()
            )

            evidence_by_type: dict[str, list[RawEvidence]] = {}
            for ev in evidence:
                evidence_by_type.setdefault(ev.source_type, []).append(ev)

            # Run each calculator
            signals_created = 0

            for calculator in SIGNAL_CALCULATORS:
                try:
                    result = calculator(case_id, evidence_by_type)
                    if result is not None:
                        signal = Signal(
                            case_id=case.case_id,
                            signal_name=result["signal_name"],
                            signal_value=result["value"],
                            score_component=result.get("score_component"),
                            confidence=result.get("confidence", 0.5),
                            evidence_refs=result.get("evidence_refs", []),
                        )
                        db.add(signal)
                        signals_created += 1
                except Exception:
                    logger.exception(
                        "Signal calculator %s failed for case %s",
                        calculator.__name__,
                        case_id,
                    )

            case.status = CaseStatus.ANALYZING.value
            db.commit()

    except Exception as exc:
        logger.exception("Signal calculation failed for case %s", case_id)
        raise self.retry(exc=exc)

    # Dispatch reasoning
    celery_app.send_task(
        "workers.reasoning.generate_verdict",
        args=[case_id],
        queue="reasoning",
    )

    return {"status": "signals_calculated", "count": signals_created}


# ── Individual Signal Calculators ───────────────────────────────────────────
# Each returns a dict with signal_name, value, confidence, evidence_refs
# or None if insufficient data.


def calc_top_holder_pct(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: Concentration of supply in largest wallet(s). Higher is worse."""
    on_chain = evidence_by_type.get("on_chain", [])
    for ev in on_chain:
        holders = ev.payload_json.get("top_holders", [])
        if holders:
            # Sum top 10 holder percentages
            top_pct = sum(h.get("percentage", 0) for h in holders[:10]) / 100.0
            return {
                "signal_name": SignalName.TOP_HOLDER_PCT.value,
                "value": min(top_pct, 1.0),
                "score_component": "token_structure_liquidity",
                "confidence": 0.8,
                "evidence_refs": [ev.evidence_id],
            }
    return None


def calc_lp_locked(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: Whether liquidity is locked/renounced. Higher is better."""
    market = evidence_by_type.get("market", [])
    for ev in market:
        lp_info = ev.payload_json.get("liquidity", {})
        locked = lp_info.get("locked", False)
        return {
            "signal_name": SignalName.LP_LOCKED.value,
            "value": 1.0 if locked else 0.0,
            "score_component": "token_structure_liquidity",
            "confidence": 0.7 if "lock_address" in lp_info else 0.4,
            "evidence_refs": [ev.evidence_id],
        }
    return None


def calc_deployer_reputation(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: Historical quality of deployer entity's launches. Higher is better.

    Uses funding chain depth as a proxy for obfuscation:
    - Short chain (1 hop) = direct/traceable = better reputation
    - Long chain (3+ hops) = layered obfuscation = worse reputation

    Also queries Neo4j for related launches when available.
    """
    on_chain = evidence_by_type.get("on_chain", [])
    deployer = None
    funding_depth = 0

    for ev in on_chain:
        d = ev.payload_json.get("deployer_address")
        if d:
            deployer = d
        chain = ev.payload_json.get("funding_chain", [])
        if chain:
            funding_depth = max(funding_depth, len(chain))

    if not deployer:
        return None

    # Try graph lookup for related launches
    try:
        related = neo4j_client.find_related_launches(deployer)
        if related:
            # More known launches without rug labels = slightly better
            # TODO: Cross-reference with known rug/scam labels
            funding_depth = max(funding_depth, 1)
    except Exception:
        pass  # Graph unavailable — fall through to depth-based scoring

    # Score based on funding chain depth (proxy for obfuscation)
    if funding_depth == 0:
        rep_score, rep_conf = 0.4, 0.3   # no chain data = neutral lean negative
    elif funding_depth == 1:
        rep_score, rep_conf = 0.7, 0.55  # one direct hop = clean
    elif funding_depth == 2:
        rep_score, rep_conf = 0.55, 0.55 # two hops = slight concern
    elif funding_depth == 3:
        rep_score, rep_conf = 0.35, 0.6  # 3 hops = obfuscated
    else:
        rep_score, rep_conf = 0.2, 0.6   # 4+ hops = deeply layered

    return {
        "signal_name": SignalName.DEPLOYER_REPUTATION.value,
        "value": rep_score,
        "score_component": "wallet_entity_reputation",
        "confidence": rep_conf,
        "evidence_refs": [on_chain[0].evidence_id] if on_chain else [],
    }


def calc_capital_origin_score(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: Trust score of funding lineage. Higher is better."""
    on_chain = evidence_by_type.get("on_chain", [])
    for ev in on_chain:
        deployer = ev.payload_json.get("deployer_address")
        if not deployer:
            continue

        lineage = neo4j_client.find_capital_lineage(deployer)
        if not lineage:
            return {
                "signal_name": SignalName.CAPITAL_ORIGIN_SCORE.value,
                "value": 0.3,  # Can't trace = suspicious
                "score_component": "capital_lineage_quality",
                "confidence": 0.3,
                "evidence_refs": [ev.evidence_id],
            }

        # Shorter lineage to known exchange = better
        shortest_path = min(l.get("depth", 99) for l in lineage)
        # Normalize: depth 1-2 = good (0.8-1.0), 3-5 = medium, 5+ = suspicious
        if shortest_path <= 2:
            score = 0.9
        elif shortest_path <= 4:
            score = 0.6
        else:
            score = 0.3

        return {
            "signal_name": SignalName.CAPITAL_ORIGIN_SCORE.value,
            "value": score,
            "score_component": "capital_lineage_quality",
            "confidence": 0.6,
            "evidence_refs": [ev.evidence_id],
        }
    return None


def calc_repo_age_days(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: How old the main repo is relative to launch. Older is usually better."""
    code = evidence_by_type.get("code", [])
    for ev in code:
        created_at_str = ev.payload_json.get("repo_created_at")
        if not created_at_str:
            continue

        try:
            repo_created = datetime.fromisoformat(created_at_str)
            age_days = (datetime.now(timezone.utc) - repo_created.replace(tzinfo=timezone.utc)).days
            # Normalize: 0-7 days = 0.1, 7-30 = 0.3, 30-90 = 0.6, 90+ = 0.9
            if age_days >= 90:
                score = 0.9
            elif age_days >= 30:
                score = 0.6
            elif age_days >= 7:
                score = 0.3
            else:
                score = 0.1

            return {
                "signal_name": SignalName.REPO_AGE_DAYS.value,
                "value": score,
                "score_component": "developer_code_authenticity",
                "confidence": 0.8,
                "evidence_refs": [ev.evidence_id],
            }
        except (ValueError, TypeError):
            continue
    return None


def calc_commit_velocity(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: Recent development cadence. Higher is better."""
    code = evidence_by_type.get("code", [])
    for ev in code:
        commits_30d = ev.payload_json.get("commits_last_30_days")
        if commits_30d is None:
            continue

        # Normalize: 0 commits = 0.0, 1-5 = 0.3, 5-20 = 0.6, 20+ = 0.9
        if commits_30d >= 20:
            score = 0.9
        elif commits_30d >= 5:
            score = 0.6
        elif commits_30d >= 1:
            score = 0.3
        else:
            score = 0.0

        return {
            "signal_name": SignalName.COMMIT_VELOCITY.value,
            "value": score,
            "score_component": "developer_code_authenticity",
            "confidence": 0.7,
            "evidence_refs": [ev.evidence_id],
        }
    return None


def calc_account_age_days(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: Age of official social accounts. Older is usually better."""
    social = evidence_by_type.get("social", [])
    for ev in social:
        created_at_str = ev.payload_json.get("account_created_at")
        if not created_at_str:
            continue

        try:
            acct_created = datetime.fromisoformat(created_at_str)
            age_days = (datetime.now(timezone.utc) - acct_created.replace(tzinfo=timezone.utc)).days
            if age_days >= 180:
                score = 0.9
            elif age_days >= 30:
                score = 0.5
            elif age_days >= 7:
                score = 0.2
            else:
                score = 0.05

            return {
                "signal_name": SignalName.ACCOUNT_AGE_DAYS.value,
                "value": score,
                "score_component": "social_authenticity",
                "confidence": 0.7,
                "evidence_refs": [ev.evidence_id],
            }
        except (ValueError, TypeError):
            continue
    return None


def calc_backend_presence(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: Evidence of real backend/services vs static landing page. Higher is better."""
    infra = evidence_by_type.get("infrastructure", [])
    for ev in infra:
        has_api = ev.payload_json.get("has_api_endpoints", False)
        has_backend = ev.payload_json.get("has_backend", False)
        is_static_only = ev.payload_json.get("is_static_only", True)

        if has_api and has_backend:
            score = 0.9
        elif has_api or has_backend:
            score = 0.5
        elif is_static_only:
            score = 0.1
        else:
            score = 0.3

        return {
            "signal_name": SignalName.BACKEND_PRESENCE.value,
            "value": score,
            "score_component": "infrastructure_reality",
            "confidence": 0.6,
            "evidence_refs": [ev.evidence_id],
        }
    return None


def calc_narrative_consistency(
    case_id: str, evidence_by_type: dict[str, list[RawEvidence]]
) -> dict[str, Any] | None:
    """§10: Cross-signal consistency — multi-dimensional presence check."""
    has_socials = False
    has_websites = False
    has_github = False
    has_infra = False

    for ev in evidence_by_type.get("market", []):
        if ev.payload_json.get("socials"):
            has_socials = True
        if ev.payload_json.get("websites"):
            has_websites = True

    for ev in evidence_by_type.get("code", []):
        if ev.payload_json.get("exists") or ev.payload_json.get("repo"):
            has_github = True

    for ev in evidence_by_type.get("infrastructure", []):
        best = ev.payload_json.get("best_probe", {})
        if best.get("dns_resolves"):
            has_infra = True

    presence_count = sum([has_socials, has_websites, has_github, has_infra])

    if presence_count >= 4:
        score, conf = 0.8, 0.65
    elif presence_count >= 3:
        score, conf = 0.7, 0.6
    elif presence_count >= 2:
        score, conf = 0.55, 0.55
    elif presence_count == 1:
        score, conf = 0.35, 0.5
    else:
        score, conf = 0.15, 0.5

    return {
        "signal_name": SignalName.NARRATIVE_CONSISTENCY.value,
        "value": score,
        "score_component": "cross_signal_consistency",
        "confidence": conf,
        "evidence_refs": [],
    }


# Registry of all calculators
# NOTE: The primary signal path is investigate.py._calculate_signals() (sync pipeline).
# This registry is used by the Celery task path as a secondary/async fallback.
SIGNAL_CALCULATORS = [
    calc_top_holder_pct,
    calc_lp_locked,
    calc_deployer_reputation,
    calc_capital_origin_score,
    calc_repo_age_days,
    calc_commit_velocity,
    calc_account_age_days,
    calc_backend_presence,
    calc_narrative_consistency,
    # TODO: calc_related_rug_count, calc_engagement_authenticity (requires X/Twitter API)
]

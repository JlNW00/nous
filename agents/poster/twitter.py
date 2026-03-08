"""X/Twitter poster agent — §6.6 of the spec.

Autonomous posting of investigation verdicts.
Only posts when confidence >= threshold (default 0.75).

Uses X API v2 (OAuth 2.0 or Bearer Token).
"""

from __future__ import annotations

import logging
from typing import Any

from packages.common.celery_app import celery_app
from packages.common.config import settings
from packages.common.database import get_sync_session
from packages.common.enums import Verdict
from packages.common.models import Case, Project, Report

logger = logging.getLogger(__name__)

# Minimum confidence to auto-post — safety gate per §20
CONFIDENCE_THRESHOLD = 0.75

VERDICT_EMOJI = {
    Verdict.LEGITIMATE.value: "\u2705",
    Verdict.SUSPICIOUS.value: "\u26a0\ufe0f",
    Verdict.HIGH_RISK.value: "\ud83d\udea8",
    Verdict.LARP.value: "\ud83d\udc80",
}


@celery_app.task(name="agents.poster.post_verdict", bind=True, max_retries=2)
def post_verdict(self, case_id: str) -> dict:
    """
    Post a verdict summary to X/Twitter.
    Only posts if confidence meets threshold.
    """
    if not settings.x_bearer_token:
        logger.info("X_BEARER_TOKEN not set — skipping post")
        return {"status": "skipped", "reason": "no_token"}

    with get_sync_session() as db:
        case = db.query(Case).filter(Case.case_id == case_id).first()
        if not case:
            return {"status": "error", "reason": "case_not_found"}

        report = (
            db.query(Report)
            .filter(Report.case_id == case_id)
            .order_by(Report.version.desc())
            .first()
        )
        if not report:
            return {"status": "error", "reason": "no_report"}

        project = db.query(Project).filter(Project.project_id == case.project_id).first()
        if not project:
            return {"status": "error", "reason": "no_project"}

        # Safety gate: only post above confidence threshold
        confidence = report.confidence or 0
        if confidence < CONFIDENCE_THRESHOLD:
            logger.info(
                "Skipping post for %s: confidence %.2f < threshold %.2f",
                project.canonical_name, confidence, CONFIDENCE_THRESHOLD,
            )
            return {
                "status": "skipped",
                "reason": "below_confidence_threshold",
                "confidence": confidence,
            }

        tweet_text = _build_tweet(project, report)

    try:
        _post_tweet(tweet_text)
        logger.info("Posted verdict for %s to X/Twitter", project.canonical_name)
        return {"status": "posted", "text": tweet_text}
    except Exception as exc:
        logger.exception("Failed to post tweet: %s", exc)
        raise self.retry(exc=exc, countdown=60)


def _build_tweet(project: Project, report: Report) -> str:
    """Build a concise tweet from the investigation report."""
    report_data = report.report_json or {}
    verdict = report.verdict or "unknown"
    emoji = VERDICT_EMOJI.get(verdict, "")
    score = report.credibility_score or 0
    name = project.canonical_name
    symbol = f"${project.symbol}" if project.symbol else ""
    chain = project.chain or ""

    findings = report_data.get("top_findings", [])[:3]
    findings_text = "\n".join(f"\u2022 {f}" for f in findings)

    bags_data = report_data.get("bags") or {}
    bags_tag = " | Bags-launched" if bags_data.get("bags_launched") else ""

    partner_cta = report_data.get("bags_partner_cta", "")
    cta_line = f"\n\nTrade on Bags: {partner_cta}" if partner_cta else ""

    tweet = (
        f"{emoji} {name} {symbol} ({chain.upper()}){bags_tag}\n"
        f"Credibility: {score:.0f}/100 — {verdict.upper().replace('_', ' ')}\n\n"
        f"{findings_text}"
        f"{cta_line}\n\n"
        f"#CryptoInvestigator #Solana #DYOR"
    )

    # X/Twitter 280 char limit
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."

    return tweet


def _post_tweet(text: str) -> dict[str, Any]:
    """Post a tweet using X API v2."""
    import httpx

    response = httpx.post(
        "https://api.twitter.com/2/tweets",
        headers={
            "Authorization": f"Bearer {settings.x_bearer_token}",
            "Content-Type": "application/json",
        },
        json={"text": text},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

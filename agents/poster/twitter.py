"""X/Twitter poster agent — autonomous verdict posting + @mention response.

NOUS posts:
- Verdict threads when confidence >= threshold
- Score-gated: Legitimate threads (score > 70) vs LARP callouts (score < 30)
- Responds to @mentions with on-demand investigations

Auth: OAuth 1.0a required for posting (Bearer Token for reading mentions).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from base64 import b64encode
from typing import Any
from urllib.parse import quote

import httpx

from packages.common.celery_app import celery_app
from packages.common.config import settings
from packages.common.database import get_sync_session
from packages.common.enums import Verdict
from packages.common.models import Case, Project, Report

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.75
POST_URL = "https://api.twitter.com/2/tweets"
MENTIONS_URL = "https://api.twitter.com/2/users/{user_id}/mentions"
SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"

VERDICT_EMOJI = {
    Verdict.LEGITIMATE.value: "✅",
    Verdict.SUSPICIOUS.value: "⚠️",
    Verdict.HIGH_RISK.value: "🚨",
    Verdict.LARP.value: "💀",
}


# ── Celery Tasks ───────────────────────────────────────────────────────────


@celery_app.task(name="agents.poster.post_verdict", bind=True, max_retries=2)
def post_verdict(self, case_id: str) -> dict:
    """Post a verdict thread to X/Twitter. Score-gated + confidence-gated."""
    if not _can_post():
        logger.info("X credentials not configured — skipping post")
        return {"status": "skipped", "reason": "no_credentials"}

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

        confidence = report.confidence or 0
        score = report.credibility_score or 0

        # Skip if below confidence threshold
        if confidence < CONFIDENCE_THRESHOLD:
            logger.info(
                "Skipping post for %s: confidence %.2f < %.2f",
                project.canonical_name, confidence, CONFIDENCE_THRESHOLD,
            )
            return {"status": "skipped", "reason": "below_confidence_threshold", "confidence": confidence}

        # Skip mid-range scores (not interesting enough to post)
        if 30 <= score <= 70:
            logger.info(
                "Skipping post for %s: mid-range score %.0f (30-70 range)",
                project.canonical_name, score,
            )
            return {"status": "skipped", "reason": "mid_range_score", "score": score}

        thread = _build_thread(project, report)

    try:
        tweet_ids = _post_thread(thread)
        logger.info("Posted %d-tweet thread for %s", len(tweet_ids), project.canonical_name)
        return {"status": "posted", "tweets": len(tweet_ids), "thread": thread}
    except Exception as exc:
        logger.exception("Failed to post thread: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="agents.poster.check_mentions", bind=True, max_retries=1)
def check_mentions(self) -> dict:
    """
    Poll X/Twitter for @mentions of NOUS and respond with investigations.
    Runs every 5 minutes via Celery Beat.
    """
    if not settings.x_bearer_token or not settings.x_agent_username:
        return {"status": "skipped", "reason": "no_credentials"}

    try:
        mentions = _fetch_recent_mentions()
        dispatched = 0

        for mention in mentions:
            token_address = _extract_token_from_mention(mention.get("text", ""))
            if not token_address:
                continue

            mention_id = mention.get("id")
            author_id = mention.get("author_id")

            # Dispatch investigation + reply when done
            celery_app.send_task(
                "agents.poster.investigate_and_reply",
                args=[token_address, mention_id, author_id],
                queue="reporting",
            )
            dispatched += 1

        return {"status": "ok", "mentions_processed": len(mentions), "dispatched": dispatched}

    except Exception as exc:
        logger.exception("Failed to check mentions: %s", exc)
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(name="agents.poster.investigate_and_reply", bind=True, max_retries=2)
def investigate_and_reply(self, token_address: str, reply_to_id: str, author_id: str) -> dict:
    """
    Run investigation on a mentioned token and reply to the mention.
    """
    if not _can_post():
        return {"status": "skipped", "reason": "no_credentials"}

    try:
        # Run investigation inline
        from packages.common.database import get_sync_session
        from packages.common.enums import CaseStatus, CasePriority, TriggerSource
        from packages.common.models import Case, Project, ProjectAlias
        from workers.fetch.investigate import run_investigation

        with get_sync_session() as db:
            # Create or reuse project
            existing = (
                db.query(Project)
                .filter(Project.primary_contract == token_address)
                .first()
            )

            if existing:
                project = existing
                case = db.query(Case).filter(Case.project_id == project.project_id).order_by(Case.created_at.desc()).first()
                if not case:
                    case = Case(
                        project_id=project.project_id,
                        trigger_source=TriggerSource.USER_SUBMITTED.value,
                        priority=CasePriority.HIGH.value,
                        status=CaseStatus.CREATED.value,
                    )
                    db.add(case)
                    db.flush()
            else:
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
                    trigger_source=TriggerSource.USER_SUBMITTED.value,
                    priority=CasePriority.HIGH.value,
                    status=CaseStatus.CREATED.value,
                )
                db.add(case)
                db.flush()

            report = run_investigation(db, case, project)
            db.commit()

        score = report.get("credibility_score", 0)
        verdict = report.get("verdict", "unknown")
        emoji = VERDICT_EMOJI.get(verdict, "🔍")
        name = project.canonical_name
        summary = (report.get("llm_reasoning") or {}).get("summary", "")

        reply_text = (
            f"{emoji} Investigation complete: {name}\n"
            f"Score: {score:.0f}/100 — {verdict.upper().replace('_', ' ')}\n\n"
            f"{summary[:180] if summary else 'See full report for details.'}\n\n"
            f"Full report: [link]\n#NOUS"
        )

        if len(reply_text) > 280:
            reply_text = reply_text[:277] + "..."

        _post_tweet(reply_text, reply_to_id=reply_to_id)

        return {"status": "replied", "token": token_address, "score": score, "verdict": verdict}

    except Exception as exc:
        logger.exception("investigate_and_reply failed for %s: %s", token_address, exc)
        raise self.retry(exc=exc, countdown=30)


# ── Thread Builder ─────────────────────────────────────────────────────────


def _build_thread(project: Project, report: Report) -> list[str]:
    """
    Build a NOUS verdict thread. Tone varies by score.

    High score (>70): Legitimate signal thread
    Low score (<30): LARP/rug callout thread
    """
    report_data = report.report_json or {}
    verdict = report.verdict or "unknown"
    score = report.credibility_score or 0
    emoji = VERDICT_EMOJI.get(verdict, "🔍")
    name = project.canonical_name
    symbol = f"${project.symbol}" if project.symbol else ""
    llm = report_data.get("llm_reasoning") or {}
    thread_hook = llm.get("thread_hook", "")
    summary = llm.get("summary", "")
    findings = llm.get("supporting_findings") or report_data.get("top_findings") or []
    contradictions = llm.get("contradictions") or report_data.get("contradictions") or []
    open_qs = llm.get("open_questions") or report_data.get("open_questions") or []

    bags_data = report_data.get("bags") or {}
    bags_launched = bags_data.get("bags_launched", False)
    partner_cta = report_data.get("bags_partner_cta", "")

    thread = []

    # Tweet 1: Hook + verdict
    hook = thread_hook or f"NOUS investigated {name} {symbol}."
    tweet1 = (
        f"{emoji} {hook}\n\n"
        f"Score: {score:.0f}/100 — {verdict.upper().replace('_', ' ')}\n"
        f"Confidence: {(report.confidence or 0) * 100:.0f}%\n\n"
        f"Thread 🧵"
    )
    thread.append(_trim(tweet1))

    # Tweet 2: Summary
    if summary:
        thread.append(_trim(f"📋 FINDING\n\n{summary}"))

    # Tweet 3: Key signals
    if findings:
        lines = "\n".join(f"• {f}" for f in findings[:5])
        thread.append(_trim(f"📊 EVIDENCE\n\n{lines}"))

    # Tweet 4: Contradictions (only if any)
    if contradictions:
        lines = "\n".join(f"⚡ {c}" for c in contradictions[:3])
        thread.append(_trim(f"🔥 CONTRADICTIONS\n\n{lines}"))

    # Tweet 5: Score breakdown
    breakdown = report_data.get("score_breakdown") or []
    if breakdown:
        top_cats = sorted(breakdown, key=lambda x: x.get("earned", 0), reverse=True)[:3]
        lines = "\n".join(
            f"• {c['category'].replace('_', ' ').title()}: {c['earned']:.0f}/{c['max']}"
            for c in top_cats
        )
        thread.append(_trim(f"🏆 TOP SCORING CATEGORIES\n\n{lines}"))

    # Tweet 6: Open questions
    if open_qs:
        lines = "\n".join(f"❓ {q}" for q in open_qs[:2])
        thread.append(_trim(f"UNVERIFIED\n\n{lines}"))

    # Tweet 7: CTA
    cta_parts = [f"NOUS — autonomous on-chain intelligence agent."]
    if bags_launched and partner_cta:
        cta_parts.append(f"Trade on Bags: {partner_cta}")
    cta_parts.append("#NOUS #Solana #DYOR")
    thread.append(_trim("\n".join(cta_parts)))

    return thread


def _trim(text: str, limit: int = 280) -> str:
    """Trim tweet to character limit."""
    return text[:limit - 3] + "..." if len(text) > limit else text


# ── X API Helpers ──────────────────────────────────────────────────────────


def _can_post() -> bool:
    """Check if OAuth 1.0a credentials are configured for posting."""
    return bool(
        settings.x_api_key
        and settings.x_api_secret
        and settings.x_access_token
        and settings.x_access_token_secret
    )


def _post_thread(tweets: list[str]) -> list[str]:
    """Post a thread of tweets, chaining reply_to_id."""
    tweet_ids = []
    reply_to_id = None

    for tweet_text in tweets:
        result = _post_tweet(tweet_text, reply_to_id=reply_to_id)
        tweet_id = result.get("data", {}).get("id")
        if tweet_id:
            tweet_ids.append(tweet_id)
            reply_to_id = tweet_id

    return tweet_ids


def _post_tweet(text: str, reply_to_id: str | None = None) -> dict[str, Any]:
    """Post a single tweet using OAuth 1.0a."""
    body: dict[str, Any] = {"text": text}
    if reply_to_id:
        body["reply"] = {"in_reply_to_tweet_id": reply_to_id}

    auth_header = _oauth1_header("POST", POST_URL)

    with httpx.Client(timeout=30) as client:
        response = client.post(
            POST_URL,
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        return response.json()


def _fetch_recent_mentions() -> list[dict]:
    """Fetch recent @mentions using Bearer Token (read-only)."""
    if not settings.x_bearer_token:
        return []

    try:
        # First get agent user ID
        with httpx.Client(timeout=15) as client:
            me = client.get(
                "https://api.twitter.com/2/users/me",
                headers={"Authorization": f"Bearer {settings.x_bearer_token}"},
            )
            me.raise_for_status()
            user_id = me.json()["data"]["id"]

            # Fetch mentions
            resp = client.get(
                MENTIONS_URL.format(user_id=user_id),
                headers={"Authorization": f"Bearer {settings.x_bearer_token}"},
                params={
                    "max_results": 10,
                    "tweet.fields": "author_id,text,created_at",
                },
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
    except Exception as exc:
        logger.warning("Failed to fetch mentions: %s", exc)
        return []


def _extract_token_from_mention(text: str) -> str | None:
    """
    Extract a Solana token address from a tweet.
    Solana addresses are 32-44 base58 chars.
    """
    import re
    # Solana address pattern: 32-44 chars, base58 (no 0, O, I, l)
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    matches = re.findall(pattern, text)
    if matches:
        return matches[0]
    return None


def _oauth1_header(method: str, url: str) -> str:
    """Generate OAuth 1.0a Authorization header for X API."""
    oauth_params = {
        "oauth_consumer_key": settings.x_api_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": settings.x_access_token,
        "oauth_version": "1.0",
    }

    # Build signature base string
    sorted_params = "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}"
        for k, v in sorted(oauth_params.items())
    )
    signature_base = (
        f"{method.upper()}&{quote(url, safe='')}&{quote(sorted_params, safe='')}"
    )

    # Sign with HMAC-SHA1
    signing_key = (
        f"{quote(settings.x_api_secret, safe='')}"
        f"&{quote(settings.x_access_token_secret, safe='')}"
    )
    signature = b64encode(
        hmac.new(
            signing_key.encode(),
            signature_base.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()

    oauth_params["oauth_signature"] = signature

    # Build header
    header_parts = ", ".join(
        f'{quote(k, safe="")}="{quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"

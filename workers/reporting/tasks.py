"""Report generation worker — §6.6, §12, §16.

Combines scoring results and LLM reasoning into a versioned report.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select

from packages.common.celery_app import celery_app
from packages.common.database import get_sync_session
from packages.common.enums import CaseStatus
from packages.common.models import Case, Project, Report, ScoreHistory, Signal
from packages.common.scoring import SignalInput, compute_score

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.reporting.generate_report", bind=True, max_retries=1)
def generate_report(self, case_id: str, reasoning_output: dict[str, Any] | None) -> dict:
    """
    Generate a versioned credibility report.

    1. Load signals for the case.
    2. Run scoring framework.
    3. Merge with LLM reasoning (if available).
    4. Build report JSON per §16.
    5. Version and store.
    6. Transition case to PUBLISHED.
    """
    logger.info("Generating report for case %s", case_id)

    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                return {"error": "case_not_found"}

            project = db.get(Project, case.project_id)

            # Load signals
            signals = (
                db.query(Signal)
                .filter(Signal.case_id == case.case_id)
                .all()
            )

            # Run deterministic scoring
            signal_inputs = [
                SignalInput(
                    signal_name=s.signal_name,
                    value=s.signal_value,
                    confidence=s.confidence,
                )
                for s in signals
            ]
            scoring_result = compute_score(signal_inputs)

            # Determine version number
            max_version_row = (
                db.query(func.max(Report.version))
                .filter(Report.case_id == case.case_id)
                .scalar()
            )
            new_version = (max_version_row or 0) + 1

            # Build report JSON — §16
            report_json = _build_report_json(
                project=project,
                scoring_result=scoring_result,
                signals=signals,
                reasoning_output=reasoning_output,
            )

            # Use LLM verdict if available and confident, otherwise use deterministic
            if reasoning_output and reasoning_output.get("confidence", 0) >= 0.5:
                final_verdict = reasoning_output.get("verdict_suggestion", scoring_result.verdict.value)
                final_confidence = reasoning_output["confidence"]
            else:
                final_verdict = scoring_result.verdict.value
                final_confidence = scoring_result.overall_confidence

            # Create report
            report = Report(
                case_id=case.case_id,
                version=new_version,
                verdict=final_verdict,
                credibility_score=scoring_result.total_score,
                confidence=final_confidence,
                report_json=report_json,
            )
            db.add(report)
            db.flush()

            # Store score history for drift tracking
            for cat_score in scoring_result.category_scores:
                db.add(ScoreHistory(
                    report_id=report.report_id,
                    score_name=cat_score.name,
                    score_value=cat_score.earned_points,
                ))

            # Transition case
            case.status = CaseStatus.PUBLISHED.value
            db.commit()

            logger.info(
                "Report v%d for case %s: score=%.1f verdict=%s confidence=%.2f",
                new_version, case_id,
                scoring_result.total_score, final_verdict, final_confidence,
            )

    except Exception as exc:
        logger.exception("Report generation failed for case %s", case_id)
        raise self.retry(exc=exc)

    return {
        "status": "report_generated",
        "version": new_version,
        "score": scoring_result.total_score,
        "verdict": final_verdict,
    }


def _build_report_json(
    project: Project | None,
    scoring_result: Any,
    signals: list[Signal],
    reasoning_output: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the full report JSON structure per §16."""

    report: dict[str, Any] = {}

    # Executive summary
    if reasoning_output and reasoning_output.get("summary"):
        report["executive_summary"] = reasoning_output["summary"]
    else:
        report["executive_summary"] = (
            f"Automated credibility assessment for "
            f"{project.canonical_name if project else 'unknown project'}. "
            f"Score: {scoring_result.total_score}/100. "
            f"Verdict: {scoring_result.verdict.value}."
        )

    # Project identifiers
    report["project"] = {
        "name": project.canonical_name if project else "unknown",
        "symbol": project.symbol if project else None,
        "chain": project.chain if project else "unknown",
        "primary_contract": project.primary_contract if project else None,
    }

    # Score breakdown
    report["credibility_score"] = scoring_result.total_score
    report["verdict"] = scoring_result.verdict.value
    report["overall_confidence"] = scoring_result.overall_confidence

    report["score_breakdown"] = [
        {
            "category": cs.name,
            "earned": cs.earned_points,
            "max": cs.max_points,
            "confidence": cs.confidence,
            "contributing_signals": cs.contributing_signals,
        }
        for cs in scoring_result.category_scores
    ]

    # Top findings
    if reasoning_output and reasoning_output.get("supporting_findings"):
        report["top_findings"] = reasoning_output["supporting_findings"]
    else:
        # Generate from signals
        report["top_findings"] = [
            f"{s.signal_name}: {s.signal_value} (confidence: {s.confidence})"
            for s in sorted(signals, key=lambda x: x.confidence or 0, reverse=True)[:8]
        ]

    # Contradictions
    if reasoning_output and reasoning_output.get("contradictions"):
        report["contradictions"] = reasoning_output["contradictions"]
    else:
        report["contradictions"] = []

    # Open questions
    if reasoning_output and reasoning_output.get("open_questions"):
        report["open_questions"] = reasoning_output["open_questions"]
    else:
        report["open_questions"] = []
        if scoring_result.missing_signals:
            report["open_questions"].append(
                f"Missing signals: {', '.join(scoring_result.missing_signals)}"
            )

    # Signal details
    report["signals"] = [
        {
            "name": s.signal_name,
            "value": s.signal_value,
            "confidence": s.confidence,
            "component": s.score_component,
        }
        for s in signals
    ]

    return report

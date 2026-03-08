"""Reasoning worker — §6.5, §14, and §12.

Combines deterministic signals with LLM-based narrative reasoning.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from packages.common.celery_app import celery_app
from packages.common.config import settings
from packages.common.database import get_sync_session
from packages.common.enums import CaseStatus
from packages.common.models import Case, Project, RawEvidence, Signal
from packages.common.schemas import ReasoningOutput

logger = logging.getLogger(__name__)

# ── LLM Prompt Template — §14 ──────────────────────────────────────────────

INVESTIGATION_SYSTEM_PROMPT = """\
You are a crypto project investigation assistant. You analyze structured evidence \
to assess project credibility.

Rules:
- Base your analysis ONLY on the evidence provided. Never invent or assume facts.
- If data is missing, explicitly note it as missing — do not speculate.
- You are not a market predictor. You assess whether a project's public narrative \
  matches its on-chain, code, and infrastructure evidence.
- Flag contradictions between public claims and evidence.
- Be specific: cite signal names and values when supporting findings.

Respond ONLY with a JSON object containing these fields:
{
  "summary": "One paragraph executive summary of findings",
  "supporting_findings": ["Finding 1", "Finding 2", ...],
  "contradictions": ["Contradiction 1", ...],
  "open_questions": ["Question 1", ...],
  "verdict_suggestion": "legitimate | suspicious | high_risk | larp",
  "confidence": 0.0 to 1.0
}
"""

INVESTIGATION_USER_TEMPLATE = """\
Investigate this project based on the following structured evidence.

## Project
{project_json}

## Signals
{signals_json}

## Evidence Summary
{evidence_summary}

## Entity Graph Context
{graph_context}

Analyze the evidence and produce your investigation findings as JSON.
"""


@celery_app.task(name="workers.reasoning.generate_verdict", bind=True, max_retries=2)
def generate_verdict(self, case_id: str) -> dict:
    """
    Generate LLM-based reasoning from investigation payload.

    1. Assemble structured evidence payload.
    2. Call LLM with constrained prompt.
    3. Parse and validate JSON response.
    4. Dispatch report generation.
    """
    logger.info("Generating verdict for case %s", case_id)

    try:
        with get_sync_session() as db:
            case = db.get(Case, uuid.UUID(case_id))
            if not case:
                return {"error": "case_not_found"}

            project = db.get(Project, case.project_id)

            # Gather signals
            signals = (
                db.query(Signal)
                .filter(Signal.case_id == case.case_id)
                .all()
            )

            # Gather evidence summaries (not raw dumps — §14)
            evidence = (
                db.query(RawEvidence)
                .filter(RawEvidence.case_id == case.case_id)
                .all()
            )

            # Build the investigation payload
            project_json = json.dumps({
                "name": project.canonical_name if project else "unknown",
                "symbol": project.symbol if project else None,
                "chain": project.chain if project else "unknown",
                "primary_contract": project.primary_contract if project else None,
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

            evidence_summary = _build_evidence_summary(evidence)
            graph_context = _build_graph_context(project)

            # Call LLM
            reasoning_output = _call_llm(
                project_json=project_json,
                signals_json=signals_json,
                evidence_summary=evidence_summary,
                graph_context=graph_context,
            )

            # Store the reasoning output alongside the case
            # (Will be consumed by the report worker)
            case.status = CaseStatus.SCORED.value
            db.commit()

    except Exception as exc:
        logger.exception("Reasoning failed for case %s", case_id)
        # Fallback: dispatch report with deterministic-only scoring
        celery_app.send_task(
            "workers.reporting.generate_report",
            args=[case_id, None],  # None = no LLM reasoning
            queue="reporting",
        )
        return {"status": "fallback_to_deterministic", "error": str(exc)}

    # Dispatch report generation with reasoning
    celery_app.send_task(
        "workers.reporting.generate_report",
        args=[case_id, reasoning_output],
        queue="reporting",
    )

    return {"status": "verdict_generated"}


def _build_evidence_summary(evidence: list[RawEvidence]) -> str:
    """Build a structured summary of evidence without raw dumps."""
    summary_parts: list[str] = []
    for ev in evidence:
        payload = ev.payload_json
        summary_parts.append(
            f"- [{ev.source_type}/{ev.provider}] "
            f"Keys: {', '.join(list(payload.keys())[:10])}, "
            f"Fetched: {ev.fetched_at.isoformat()}"
        )
    return "\n".join(summary_parts) if summary_parts else "No evidence collected."


def _build_graph_context(project: Project | None) -> str:
    """Query Neo4j for relevant entity/capital lineage context."""
    if not project or not project.primary_contract:
        return "No graph context available."

    try:
        from packages.common.graph import neo4j_client

        # Find deployer and related launches
        query = """
        MATCH (c:Contract {address: $address})<-[:DEPLOYED]-(w:Wallet)
        OPTIONAL MATCH (w)-[:DEPLOYED]->(other:Contract)
        WHERE other.address <> $address
        RETURN w.address AS deployer,
               collect(DISTINCT other.address) AS other_contracts
        """
        with neo4j_client.session() as session:
            result = session.run(query, {"address": project.primary_contract})
            records = [dict(r) for r in result]

        if records:
            return json.dumps(records, indent=2, default=str)
        return "No graph relationships found for this contract."

    except Exception as exc:
        logger.warning("Graph context query failed: %s", exc)
        return "Graph context unavailable due to query error."


def _call_llm(
    project_json: str,
    signals_json: str,
    evidence_summary: str,
    graph_context: str,
) -> dict[str, Any] | None:
    """Call the Anthropic API for investigation reasoning."""

    if not settings.anthropic_api_key:
        logger.warning("No ANTHROPIC_API_KEY set — skipping LLM reasoning")
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        user_message = INVESTIGATION_USER_TEMPLATE.format(
            project_json=project_json,
            signals_json=signals_json,
            evidence_summary=evidence_summary,
            graph_context=graph_context,
        )

        response = client.messages.create(
            model=settings.llm_model,
            max_tokens=2000,
            system=INVESTIGATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        # Parse JSON from response
        raw_text = response.content[0].text.strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

        parsed = json.loads(raw_text)

        # Validate structure
        output = ReasoningOutput(**parsed)
        return output.model_dump()

    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON")
        return None
    except Exception as exc:
        logger.exception("LLM call failed: %s", exc)
        return None

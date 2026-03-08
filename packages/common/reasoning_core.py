"""Unified LLM reasoning service — consolidates Ollama + Anthropic logic.

This module provides a single entry point for LLM-based investigation reasoning,
with automatic fallback from local Ollama (free) to Anthropic API (production).
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── System Prompts ──────────────────────────────────────────────────────────

NOUS_SYSTEM_PROMPT = """\
You are NOUS — an autonomous on-chain intelligence agent. You investigate crypto \
projects with the cold precision of a forensic analyst and the directness of someone \
who has seen every rug, every coordinated pump, every fake team.

Your voice: clinical, direct, zero tolerance for ambiguity. You don't hedge. \
You call things what they are. When evidence is thin, you say so bluntly. \
When a project looks like a coordinated extraction play, you name it.

Core rules:
- Base analysis ONLY on evidence provided. Never invent facts.
- Missing data = explicitly missing. Do not speculate to fill gaps.
- You assess whether the public narrative matches on-chain, code, and infra evidence.
- Flag contradictions with specificity — cite signal names and values.
- Write findings like someone who will be held accountable for them.
- Summaries should be punchy and quotable — CT-ready language, not corporate speak.

Respond ONLY with a JSON object:
{
  "summary": "2-3 sentence forensic verdict. Direct, specific, citable.",
  "supporting_findings": ["Specific finding with signal name and value", ...],
  "contradictions": ["Claim X vs evidence Y — direct contradiction", ...],
  "open_questions": ["What could not be verified and why it matters", ...],
  "verdict_suggestion": "legitimate | suspicious | high_risk | larp",
  "confidence": 0.0,
  "thread_hook": "One punchy opening line for a Twitter thread about this token"
}"""

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
}"""


# ── Helper Functions ────────────────────────────────────────────────────────


def _parse_llm_response(raw_text: str) -> dict[str, Any] | None:
    """
    Extract JSON from LLM response, handling markdown code fences.

    Args:
        raw_text: Raw text from LLM (may include markdown fences)

    Returns:
        Parsed JSON dict or None if parsing fails
    """
    if not raw_text:
        return None

    try:
        # Strip markdown code fences if present
        if "```" in raw_text:
            # Find first and last backticks
            parts = raw_text.split("```")
            if len(parts) >= 2:
                raw_text = parts[1]
                # Remove "json" prefix if present
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()
                # Handle trailing backticks
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3].strip()

        # Parse JSON
        parsed = json.loads(raw_text)
        return parsed
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("Failed to parse LLM response as JSON: %s", exc)
        return None


def _call_ollama(
    project_json: str,
    signals_json: str,
    evidence_summary: str,
    system_prompt: str,
    timeout: int = 60,
) -> dict[str, Any] | None:
    """
    Call local Ollama instance for free LLM reasoning.

    Args:
        project_json: JSON-formatted project metadata
        signals_json: JSON-formatted signal array
        evidence_summary: Plain text evidence summary
        system_prompt: System prompt for the LLM
        timeout: Request timeout in seconds

    Returns:
        Parsed reasoning output dict or None if Ollama unavailable
    """
    try:
        import httpx

        user_msg = (
            f"Investigate this project:\n\n"
            f"## Project\n{project_json}\n\n"
            f"## Signals\n{signals_json}\n\n"
            f"## Evidence Summary\n{evidence_summary}\n\n"
            f"Produce your forensic investigation findings as JSON."
        )

        # Get available models and pick one
        with httpx.Client(timeout=timeout) as client:
            logger.info("Calling local Ollama for reasoning...")

            try:
                models_resp = client.get("http://localhost:11434/api/tags")
                available_models = [m.get("name") for m in models_resp.json().get("models", [])]
            except Exception:
                available_models = []

            if not available_models:
                logger.debug("No Ollama models available")
                return None

            # Try preferred models in order of speed/quality
            # Use substring matching since Ollama reports "mistral:latest", "llama3.1:8b", etc.
            preferred_keywords = ["mistral", "llama3.1:8b", "llama3:8b", "llama3.1:70b", "neural-chat"]
            model_to_use = None
            for keyword in preferred_keywords:
                for available in available_models:
                    if keyword in available:
                        model_to_use = available
                        break
                if model_to_use:
                    break

            if not model_to_use:
                model_to_use = available_models[0]

            logger.info("Using Ollama model: %s", model_to_use)

            response = client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model_to_use,
                    "prompt": f"{system_prompt}\n\n{user_msg}",
                    "stream": False,
                },
                timeout=timeout,
            )
            response.raise_for_status()

        result_data = response.json()
        raw_text = result_data.get("response", "").strip()

        if not raw_text:
            return None

        parsed = _parse_llm_response(raw_text)
        if parsed:
            logger.info("Ollama reasoning complete")
        return parsed

    except Exception as exc:
        logger.debug("Ollama reasoning unavailable: %s", exc)
        return None


def _call_anthropic(
    project_json: str,
    signals_json: str,
    evidence_summary: str,
    system_prompt: str,
    timeout: int = 30,
) -> dict[str, Any] | None:
    """
    Call Anthropic API for LLM reasoning.

    Args:
        project_json: JSON-formatted project metadata
        signals_json: JSON-formatted signal array
        evidence_summary: Plain text evidence summary
        system_prompt: System prompt for the LLM
        timeout: Request timeout in seconds

    Returns:
        Parsed reasoning output dict or None if API unavailable
    """
    try:
        import anthropic
        from packages.common.config import settings

        if not settings.anthropic_api_key:
            logger.debug("No ANTHROPIC_API_KEY configured")
            return None

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        user_msg = (
            f"Investigate this project:\n\n"
            f"## Project\n{project_json}\n\n"
            f"## Signals\n{signals_json}\n\n"
            f"## Evidence Summary\n{evidence_summary}\n\n"
            f"Produce your forensic investigation findings as JSON."
        )

        logger.info("Calling Anthropic API for reasoning...")
        response = client.messages.create(
            model=settings.llm_model,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
            timeout=timeout,
        )

        raw_text = response.content[0].text.strip()
        parsed = _parse_llm_response(raw_text)

        if parsed:
            logger.info("Anthropic reasoning complete")
        return parsed

    except Exception as exc:
        logger.debug("Anthropic reasoning unavailable: %s", exc)
        return None


# ── Main Entry Point ────────────────────────────────────────────────────────


def call_reasoning_service(
    project_json: str,
    signals_json: str,
    evidence_summary: str,
    graph_context: str = "",
    timeout: int = 60,
    system_prompt: str | None = None,
) -> dict[str, Any] | None:
    """
    Unified LLM reasoning service with automatic fallback chain.

    Tries Ollama first (local, free), falls back to Anthropic API (production).
    Returns structured ReasoningOutput dict or None if unavailable/failed.

    Args:
        project_json: JSON-formatted project metadata
        signals_json: JSON-formatted signal array
        evidence_summary: Plain text evidence summary (not raw dumps)
        graph_context: Optional Neo4j entity graph context (unused in prompts for now)
        timeout: Request timeout in seconds
        system_prompt: Optional custom system prompt (defaults to NOUS_SYSTEM_PROMPT)

    Returns:
        dict with keys: summary, supporting_findings, contradictions, open_questions,
                        verdict_suggestion, confidence, [thread_hook]
        OR None if all services unavailable or reasoning failed
    """
    if system_prompt is None:
        system_prompt = NOUS_SYSTEM_PROMPT

    # Try Ollama first (free, local, no API calls)
    result = _call_ollama(
        project_json=project_json,
        signals_json=signals_json,
        evidence_summary=evidence_summary,
        system_prompt=system_prompt,
        timeout=timeout,
    )
    if result is not None:
        return result

    # Fall back to Anthropic
    result = _call_anthropic(
        project_json=project_json,
        signals_json=signals_json,
        evidence_summary=evidence_summary,
        system_prompt=system_prompt,
        timeout=timeout,
    )
    if result is not None:
        return result

    # All services unavailable
    logger.info("No LLM service available (Ollama and Anthropic both unavailable)")
    return None

"""Scoring framework — §13 of the spec.

Each category has a bounded score. The final credibility score normalizes
to the assessable evidence only, separating risk from coverage.

Key design rule: Missing data is NOT equivalent to bad data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from packages.common.enums import SignalName, Verdict

logger = logging.getLogger(__name__)


# ── Score Category Definitions ──────────────────────────────────────────────


@dataclass(frozen=True)
class ScoreCategory:
    name: str
    max_points: int
    signals: list[str]  # SignalName values that feed into this category


CATEGORIES: list[ScoreCategory] = [
    ScoreCategory(
        name="wallet_entity_reputation",
        max_points=30,
        signals=[
            SignalName.DEPLOYER_REPUTATION.value,
            SignalName.CAPITAL_ORIGIN_SCORE.value,
            SignalName.RELATED_RUG_COUNT.value,
        ],
    ),
    ScoreCategory(
        name="token_structure_liquidity",
        max_points=20,
        signals=[
            SignalName.TOP_HOLDER_PCT.value,
            SignalName.LP_LOCKED.value,
            SignalName.BAGS_LAUNCHED.value,
            SignalName.BAGS_LIFETIME_FEES.value,
            SignalName.BAGS_TRADING_VOLUME.value,
        ],
    ),
    ScoreCategory(
        name="developer_code_authenticity",
        max_points=15,
        signals=[
            SignalName.REPO_AGE_DAYS.value,
            SignalName.COMMIT_VELOCITY.value,
        ],
    ),
    ScoreCategory(
        name="infrastructure_reality",
        max_points=10,
        signals=[
            SignalName.BACKEND_PRESENCE.value,
        ],
    ),
    ScoreCategory(
        name="social_authenticity",
        max_points=10,
        signals=[
            SignalName.ACCOUNT_AGE_DAYS.value,
            SignalName.ENGAGEMENT_AUTHENTICITY.value,
        ],
    ),
    ScoreCategory(
        name="capital_lineage_quality",
        max_points=10,
        signals=[
            SignalName.NARRATIVE_CONSISTENCY.value,
            SignalName.CAPITAL_ORIGIN_SCORE.value,
        ],
    ),
    ScoreCategory(
        name="cross_signal_consistency",
        max_points=5,
        signals=[
            SignalName.NARRATIVE_CONSISTENCY.value,
            SignalName.NARRATIVE_PUMP_SIGNAL.value,
        ],
    ),
]

TOTAL_MAX = sum(c.max_points for c in CATEGORIES)  # 100


# ── Verdict Bands ───────────────────────────────────────────────────────────


def verdict_from_score(risk_score: float, coverage: float) -> Verdict:
    """
    Determine verdict from risk_score (0-100 normalized to assessed data).

    When coverage is very low (<30%), we refuse to issue a strong verdict
    and cap at SUSPICIOUS — incomplete evidence should not condemn.
    """
    if coverage < 0.30:
        # Too little data to make a strong call either way
        if risk_score >= 70:
            return Verdict.LEGITIMATE
        else:
            return Verdict.SUSPICIOUS  # cap — don't condemn on thin evidence

    if risk_score >= 75:
        return Verdict.LEGITIMATE
    elif risk_score >= 55:
        return Verdict.SUSPICIOUS
    elif risk_score >= 30:
        return Verdict.HIGH_RISK
    else:
        return Verdict.LARP


# ── Score Calculation ───────────────────────────────────────────────────────


@dataclass
class SignalInput:
    signal_name: str
    value: float | None
    confidence: float = 0.5


@dataclass
class CategoryScore:
    name: str
    max_points: int
    earned_points: float
    contributing_signals: list[str]
    confidence: float
    has_data: bool  # True if at least one signal contributed


@dataclass
class ScoringResult:
    # Primary outputs
    risk_score: float           # 0-100, normalized to ASSESSED categories only
    coverage: float             # 0.0-1.0, fraction of max_points with data
    verdict: Verdict

    # Backward compat + detail
    total_score: float          # Raw sum of earned points (old field)
    overall_confidence: float
    category_scores: list[CategoryScore]
    missing_signals: list[str]
    assessed_max: float         # How many points were actually assessable


def _normalize_signal(signal_name: str, value: float | None) -> float:
    """
    Map a raw signal value to a 0.0-1.0 range.

    Convention from §10:
    - "higher is better" signals: normalized as-is (already 0-1 or clamped).
    - "higher is worse" signals: inverted (1 - normalized).
    """
    if value is None:
        return 0.0

    INVERTED = {
        SignalName.TOP_HOLDER_PCT.value,
        SignalName.RELATED_RUG_COUNT.value,
    }

    # Clamp to 0-1 if the signal calculator already outputs that range.
    clamped = max(0.0, min(1.0, value))

    if signal_name in INVERTED:
        return 1.0 - clamped

    return clamped


def compute_score(signals: list[SignalInput]) -> ScoringResult:
    """
    Compute credibility score from signal inputs.

    Key change: risk_score normalizes only to categories that have data.
    Missing categories reduce coverage, NOT risk_score.
    """
    signal_map: dict[str, SignalInput] = {s.signal_name: s for s in signals}
    category_scores: list[CategoryScore] = []
    missing_signals: list[str] = []

    for cat in CATEGORIES:
        contributing: list[str] = []
        weighted_sum = 0.0
        total_weight = 0.0

        for sig_name in cat.signals:
            sig = signal_map.get(sig_name)
            if sig is None or sig.value is None:
                missing_signals.append(sig_name)
                continue

            norm = _normalize_signal(sig_name, sig.value)
            weight = sig.confidence
            weighted_sum += norm * weight
            total_weight += weight
            contributing.append(sig_name)

        has_data = total_weight > 0

        if has_data:
            avg_normalized = weighted_sum / total_weight
            earned = avg_normalized * cat.max_points
            cat_confidence = total_weight / len(cat.signals)
        else:
            earned = 0.0
            cat_confidence = 0.0

        category_scores.append(
            CategoryScore(
                name=cat.name,
                max_points=cat.max_points,
                earned_points=round(earned, 2),
                contributing_signals=contributing,
                confidence=round(cat_confidence, 2),
                has_data=has_data,
            )
        )

    # ── Raw total (backward compat) ──────────────────────────────────
    total = sum(cs.earned_points for cs in category_scores)
    total = round(min(total, TOTAL_MAX), 2)

    # ── Risk score: normalized to assessed categories only ────────────
    assessed_max = sum(cs.max_points for cs in category_scores if cs.has_data)
    if assessed_max > 0:
        risk_score = round((total / assessed_max) * 100, 2)
    else:
        risk_score = 0.0

    # ── Coverage: what fraction of the 100-point scale had data ──────
    coverage = round(assessed_max / TOTAL_MAX, 2) if TOTAL_MAX > 0 else 0.0

    # ── Overall confidence: weighted avg of category confidences ─────
    conf_num = sum(cs.confidence * cs.max_points for cs in category_scores)
    overall_confidence = round(conf_num / TOTAL_MAX, 2) if TOTAL_MAX > 0 else 0.0

    # ── Verdict: based on risk_score + coverage ──────────────────────
    verdict = verdict_from_score(risk_score, coverage)

    return ScoringResult(
        risk_score=risk_score,
        coverage=coverage,
        verdict=verdict,
        total_score=total,
        overall_confidence=overall_confidence,
        category_scores=category_scores,
        missing_signals=list(set(missing_signals)),
        assessed_max=assessed_max,
    )

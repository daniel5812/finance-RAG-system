"""
intelligence/agents/validation.py — ValidationAgent

Responsibility:
  Sanity-check the IntelligenceReport AFTER all agents have run but BEFORE
  the report reaches the LLM. Detects and surfaces:
    1. Score values outside [0.0, 1.0]
    2. Recommendation actions that contradict the deterministic score thresholds
    3. Confidence levels inconsistent with data availability
    4. Recommendation confidence that exceeds data coverage

Design:
  - FULLY DETERMINISTIC — zero LLM calls
  - Non-blocking: on failure, the report is flagged and confidence is downgraded,
    but the pipeline continues (never crashes chat_service)
  - Thresholds are kept in sync with scoring_engine.py constants

Confidence downgrade rules:
  - 3+ flags → pipeline_confidence = "low"
  - Any flag when pipeline_confidence == "high" → downgrade to "medium"
  - 0 flags → no change
"""

from __future__ import annotations

from core.logger import get_logger
from intelligence.schemas import (
    IntelligenceReport,
    RecommendationAction,
    ValidationResult,
)

logger = get_logger(__name__)

# Must match scoring_engine.py thresholds exactly
_BUY_THRESHOLD    = 0.72
_HOLD_THRESHOLD   = 0.55
_REDUCE_THRESHOLD = 0.38


class ValidationAgent:
    """
    Post-pipeline validator. Runs synchronously after RecommendationAgent.
    """

    @staticmethod
    def run(report: IntelligenceReport) -> ValidationResult:
        """
        Validate the report. Returns ValidationResult; never raises.
        If confidence_override is set, the orchestrator applies it to pipeline_confidence.
        """
        try:
            result = _validate(report)
            if result.passed:
                logger.info('{"event": "validation_agent", "status": "passed"}')
            else:
                logger.warning(
                    f'{{"event": "validation_agent", "status": "flagged", '
                    f'"flag_count": {len(result.flags)}, '
                    f'"confidence_override": "{result.confidence_override}"}}'
                )
            return result
        except Exception as exc:
            logger.error(f'{{"event": "validation_agent", "status": "error", "error": "{exc}"}}')
            return ValidationResult(
                passed=False,
                flags=[f"validator_exception: {exc}"],
                confidence_override="low",
            )


def _validate(report: IntelligenceReport) -> ValidationResult:
    flags: list[str] = []

    # ── 1. Score range checks ─────────────────────────────────────────────────
    for score in report.asset_scores:
        for field_name, value in [
            ("market_fit_score",      score.market_fit_score),
            ("user_fit_score",        score.user_fit_score),
            ("diversification_score", score.diversification_score),
            ("risk_alignment_score",  score.risk_alignment_score),
            ("composite_score",       score.composite_score),
        ]:
            if not (0.0 <= value <= 1.0):
                flags.append(
                    f"SCORE_RANGE: {score.ticker}.{field_name}={value:.3f} "
                    f"is outside valid range [0.0, 1.0]"
                )

    # ── 2. Recommendation ↔ score consistency ─────────────────────────────────
    score_map = {s.ticker: s for s in report.asset_scores}
    for rec in report.recommendations:
        if rec.action == RecommendationAction.INSUFFICIENT_DATA:
            continue  # no score to validate against

        s = score_map.get(rec.ticker)
        if s is None:
            flags.append(
                f"MISSING_SCORE: {rec.ticker} has action={rec.action.value} "
                f"but no AssetScore exists for it"
            )
            continue

        cs = s.composite_score
        action = rec.action

        if action == RecommendationAction.BUY and cs < _BUY_THRESHOLD:
            flags.append(
                f"CONTRADICTION: {rec.ticker} action=BUY requires composite_score>={_BUY_THRESHOLD}, "
                f"got {cs:.3f}"
            )
        elif action == RecommendationAction.AVOID and cs >= _REDUCE_THRESHOLD:
            flags.append(
                f"CONTRADICTION: {rec.ticker} action=AVOID requires composite_score<{_REDUCE_THRESHOLD}, "
                f"got {cs:.3f}"
            )
        elif action == RecommendationAction.HOLD and not (_HOLD_THRESHOLD <= cs < _BUY_THRESHOLD):
            flags.append(
                f"CONTRADICTION: {rec.ticker} action=HOLD requires composite_score in "
                f"[{_HOLD_THRESHOLD}, {_BUY_THRESHOLD}), got {cs:.3f}"
            )
        elif action == RecommendationAction.REDUCE and not (_REDUCE_THRESHOLD <= cs < _HOLD_THRESHOLD):
            flags.append(
                f"CONTRADICTION: {rec.ticker} action=REDUCE requires composite_score in "
                f"[{_REDUCE_THRESHOLD}, {_HOLD_THRESHOLD}), got {cs:.3f}"
            )

    # ── 3. pipeline_confidence vs data availability ────────────────────────────
    if report.pipeline_confidence == "high":
        if not report.asset_scores:
            flags.append(
                "CONFIDENCE_MISMATCH: pipeline_confidence=high "
                "but no asset scores were computed"
            )
        if not report.market_context or report.market_context.fed_rate is None:
            flags.append(
                "CONFIDENCE_MISMATCH: pipeline_confidence=high "
                "but macro data (FEDFUNDS) is unavailable"
            )

    # ── 4. Recommendation confidence vs data coverage ─────────────────────────
    for rec in report.recommendations:
        if rec.confidence == "high":
            s = score_map.get(rec.ticker)
            if s and s.data_coverage != "full":
                flags.append(
                    f"CONFIDENCE_MISMATCH: {rec.ticker} recommendation.confidence=high "
                    f"but data_coverage={s.data_coverage} (only 'full' justifies high confidence)"
                )

    # ── 5. Normalized portfolio: check for impossible allocations ─────────────
    if report.normalized_portfolio:
        np = report.normalized_portfolio
        if np.allocation_pct:
            total_alloc = sum(np.allocation_pct.values())
            if not (99.0 <= total_alloc <= 101.0):  # allow rounding tolerance
                flags.append(
                    f"ALLOCATION_SUM: normalized_portfolio allocations sum to "
                    f"{total_alloc:.1f}% (expected ~100%)"
                )

    # ── Compute confidence override ────────────────────────────────────────────
    confidence_override: str | None = None
    if len(flags) >= 3:
        confidence_override = "low"
    elif flags and report.pipeline_confidence == "high":
        confidence_override = "medium"

    return ValidationResult(
        passed=len(flags) == 0,
        flags=flags,
        confidence_override=confidence_override,
    )

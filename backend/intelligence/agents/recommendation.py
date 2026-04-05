"""
intelligence/agents/recommendation.py — RecommendationAgent

Responsibility:
  Produce a buy / hold / reduce / avoid recommendation for each scored asset.

Architecture: TWO-STAGE HYBRID
  Stage 1 — DETERMINISTIC: maps composite_score → RecommendationAction + confidence.
             No LLM, no randomness. Same score → same action, always.
  Stage 2 — LLM (reasoning only): writes the EXPLANATION of the deterministic decision.
             The LLM does NOT choose the action — it explains an action already chosen.

This separation guarantees:
  - Recommendations are auditable and reproducible.
  - Confidence levels are computed, not hallucinated.
  - LLM adds value only where it's good: natural language reasoning.

Inputs:
  - scores: list[AssetScore]
  - asset_profiles: list[AssetProfile]
  - market_context: MarketContext
  - user_profile: UserInvestmentProfile

Outputs:
  - list[AssetRecommendation]

Score → Action mapping (deterministic):
  composite >= 0.72 → BUY   (high confidence if coverage=full, else medium)
  composite >= 0.55 → HOLD  (medium confidence)
  composite >= 0.38 → REDUCE (medium confidence)
  composite <  0.38 → AVOID  (low if coverage=minimal)
  data_coverage=minimal → INSUFFICIENT_DATA regardless of score
"""

from __future__ import annotations

import asyncio
import json

from core.llm_client import ChatAgentClient
from core.logger import get_logger
from intelligence.schemas import (
    AssetProfile, AssetRecommendation, AssetScore,
    MarketContext, RecommendationAction, UserInvestmentProfile,
)

logger = get_logger(__name__)

# ── Thresholds ────────────────────────────────────────────────
_BUY_THRESHOLD    = 0.72
_HOLD_THRESHOLD   = 0.55
_REDUCE_THRESHOLD = 0.38

# ── Reasoning prompt (minimalist — LLM explains, doesn't decide) ─────────────
_REASONING_PROMPT = """\
You are an investment analyst writing a concise recommendation explanation.

The DECISION has already been made by our scoring system. Your job is ONLY to
write 2-3 clear sentences explaining WHY this specific action is appropriate
given the data below. Do NOT second-guess or override the action.

Asset: {ticker}
Action: {action}
Composite Score: {score:.2f} / 1.00
Market Regime: {regime}
User Risk Tolerance: {risk}
User Experience: {experience}

Score Factors:
{factors}

Write:
1. reasoning: 2-3 sentences explaining the action given the score factors and context.
2. trade_offs: 1 sentence naming the main trade-off (what the user gives up with this action).
3. risks: 2-3 bullet point risks (as a JSON array of strings).

Respond ONLY with a valid JSON object:
{{
  "reasoning": "...",
  "trade_offs": "...",
  "risks": ["risk 1", "risk 2", "risk 3"]
}}
"""


class RecommendationAgent:
    """
    Deterministic action selection + LLM reasoning generation.
    """

    @staticmethod
    async def run(
        scores: list[AssetScore],
        asset_profiles: list[AssetProfile],
        market_context: MarketContext,
        user_profile: UserInvestmentProfile,
    ) -> list[AssetRecommendation]:
        """
        Produce one AssetRecommendation per AssetScore.
        Falls back to text-free recommendation if LLM call fails.
        """
        if not scores:
            return []

        profile_map = {ap.ticker: ap for ap in asset_profiles}

        # Stage 1: deterministic action for all assets (no LLM, instant)
        recs_stage1 = [_determine_action(s) for s in scores]

        # Stage 2: parallel LLM reasoning for assets with real actions
        tasks = []
        indices = []
        for i, (s, r) in enumerate(zip(scores, recs_stage1)):
            if r.action not in (RecommendationAction.INSUFFICIENT_DATA,):
                ap = profile_map.get(s.ticker)
                tasks.append(
                    _generate_reasoning(s, r, ap, market_context, user_profile)
                )
                indices.append(i)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for idx, result in zip(indices, results):
                if isinstance(result, Exception):
                    logger.warning(
                        f'{{"event": "recommendation_agent", '
                        f'"ticker": "{recs_stage1[idx].ticker}", '
                        f'"status": "reasoning_failed", "error": "{result}"}}'
                    )
                else:
                    recs_stage1[idx] = result

        for r in recs_stage1:
            logger.info(
                f'{{"event": "recommendation_agent", "ticker": "{r.ticker}", '
                f'"action": "{r.action}", "confidence": "{r.confidence}"}}'
            )

        return recs_stage1


# ─────────────────────────────────────────────────────────────
# Stage 1: deterministic action
# ─────────────────────────────────────────────────────────────

def _determine_action(score: AssetScore) -> AssetRecommendation:
    """Map composite score → action + confidence. Zero LLM calls."""

    if score.data_coverage == "minimal":
        return AssetRecommendation(
            ticker=score.ticker,
            action=RecommendationAction.INSUFFICIENT_DATA,
            confidence="none",
            reasoning="Insufficient price or market data to generate a recommendation.",
            composite_score=score.composite_score,
        )

    cs = score.composite_score

    if cs >= _BUY_THRESHOLD:
        action = RecommendationAction.BUY
        confidence = "high" if score.data_coverage == "full" else "medium"
    elif cs >= _HOLD_THRESHOLD:
        action = RecommendationAction.HOLD
        confidence = "medium"
    elif cs >= _REDUCE_THRESHOLD:
        action = RecommendationAction.REDUCE
        confidence = "medium"
    else:
        action = RecommendationAction.AVOID
        confidence = "low" if score.data_coverage != "full" else "medium"

    return AssetRecommendation(
        ticker=score.ticker,
        action=action,
        confidence=confidence,
        composite_score=score.composite_score,
    )


# ─────────────────────────────────────────────────────────────
# Stage 2: LLM reasoning (explains the already-determined action)
# ─────────────────────────────────────────────────────────────

async def _generate_reasoning(
    score: AssetScore,
    rec: AssetRecommendation,
    ap: AssetProfile | None,
    mc: MarketContext,
    up: UserInvestmentProfile,
) -> AssetRecommendation:
    """
    Call LLM to write reasoning text for the pre-determined action.
    Returns the same rec with reasoning fields populated.
    On failure: returns original rec unchanged (action is still valid).
    """
    factors_text = "\n".join(
        f"  {k}: {v}" for k, v in score.score_factors.items()
    )

    prompt = _REASONING_PROMPT.format(
        ticker=score.ticker,
        action=rec.action.value,
        score=score.composite_score,
        regime=mc.regime.value.replace("_", " "),
        risk=up.risk_tolerance,
        experience=up.experience_level,
        factors=factors_text,
    )

    raw = await ChatAgentClient.generate(
        messages=[
            {"role": "system", "content": "You are a concise investment analyst. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    # Parse — fail gracefully
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1].split("```")[0]
        if clean.startswith("json"):
            clean = clean[4:]
    data = json.loads(clean.strip())

    return AssetRecommendation(
        ticker=rec.ticker,
        action=rec.action,
        confidence=rec.confidence,
        composite_score=rec.composite_score,
        reasoning=str(data.get("reasoning", "")),
        trade_offs=str(data.get("trade_offs", "")),
        risks=[str(r) for r in data.get("risks", [])],
    )

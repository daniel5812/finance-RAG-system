"""
intelligence/agents/scoring_engine.py — ScoringEngineAgent

CRITICAL: This agent is FULLY DETERMINISTIC. Zero LLM calls.

Responsibility:
  Compute four independent scores (0.0–1.0) for each asset based on:
    1. market_fit_score    — how well the asset fits the current market regime
    2. user_fit_score      — how well the asset matches user profile
    3. diversification_score — how much the asset reduces portfolio concentration
    4. risk_alignment_score  — asset risk vs user risk tolerance

  Then compute a weighted composite_score and attach human-readable factor text.

Inputs:
  - asset_profiles: list[AssetProfile]
  - market_context: MarketContext
  - user_profile: UserInvestmentProfile
  - portfolio_tickers: list[str]     — tickers already held by user

Outputs:
  - list[AssetScore]

Design:
  - All thresholds are named constants — easy to tune without code changes.
  - Scoring is additive/subtractive from a 0.5 baseline using delta rules.
  - Each factor is capped [0.0, 1.0].
  - composite = weighted sum of the four scores.
  - score_factors dict always populated with human-readable explanations.
  - data_coverage tracks how many of the 4 sub-scores had real data.
"""

from __future__ import annotations

from core.logger import get_logger
from intelligence.schemas import (
    AssetProfile, AssetScore, AssetType,
    MarketContext, MarketRegime, UserInvestmentProfile,
)

logger = get_logger(__name__)

# ── Composite weights (must sum to 1.0) ──────────────────────────────────────
_W_MARKET       = 0.30
_W_USER         = 0.25
_W_DIVERSIFY    = 0.20
_W_RISK_ALIGN   = 0.25

# ── Risk tolerance → numeric ─────────────────────────────────────────────────
_RISK_NUM = {"low": 0.25, "medium": 0.50, "high": 0.75}

# ── Volatility → numeric ─────────────────────────────────────────────────────
_VOL_NUM  = {"low": 0.20, "medium": 0.50, "high": 0.80, "unknown": 0.50}

# ── Market-fit deltas per regime and asset type ──────────────────────────────
# Base is 0.5; values are absolute deltas applied to each AssetType
_REGIME_DELTAS: dict[MarketRegime, dict[AssetType, float]] = {
    MarketRegime.RISK_ON: {
        AssetType.STOCK:   +0.30,
        AssetType.ETF:     +0.15,
        AssetType.BOND:    -0.20,
        AssetType.UNKNOWN: +0.05,
    },
    MarketRegime.RISK_OFF: {
        AssetType.STOCK:   -0.25,
        AssetType.ETF:      0.00,   # depends on ETF type, neutral
        AssetType.BOND:    +0.30,
        AssetType.UNKNOWN: -0.05,
    },
    MarketRegime.STAGFLATION: {
        AssetType.STOCK:   -0.30,
        AssetType.ETF:     -0.10,
        AssetType.BOND:    -0.25,   # nominal bonds hurt by inflation
        AssetType.UNKNOWN: -0.10,
    },
    MarketRegime.RECESSION: {
        AssetType.STOCK:   -0.35,
        AssetType.ETF:     -0.10,
        AssetType.BOND:    +0.25,   # flight to safety
        AssetType.UNKNOWN: -0.15,
    },
    MarketRegime.RECOVERY: {
        AssetType.STOCK:   +0.20,
        AssetType.ETF:     +0.10,
        AssetType.BOND:    -0.10,
        AssetType.UNKNOWN: +0.05,
    },
    MarketRegime.NEUTRAL: {
        AssetType.STOCK:    0.00,
        AssetType.ETF:      0.00,
        AssetType.BOND:     0.00,
        AssetType.UNKNOWN:  0.00,
    },
}


class ScoringEngineAgent:
    """
    Deterministic scoring engine. All math, no model calls.
    """

    @staticmethod
    def run(
        asset_profiles: list[AssetProfile],
        market_context: MarketContext,
        user_profile: UserInvestmentProfile,
        portfolio_tickers: list[str],
    ) -> list[AssetScore]:
        """
        Score every asset profile. Returns one AssetScore per AssetProfile.
        """
        if not asset_profiles:
            return []

        port_set = {t.upper() for t in portfolio_tickers}
        scores: list[AssetScore] = []

        for ap in asset_profiles:
            score = _score_asset(ap, market_context, user_profile, port_set)
            scores.append(score)
            logger.info(
                f'{{"event": "scoring_engine_agent", "ticker": "{ap.ticker}", '
                f'"composite": {score.composite_score:.3f}, '
                f'"market_fit": {score.market_fit_score:.3f}, '
                f'"user_fit": {score.user_fit_score:.3f}, '
                f'"diversify": {score.diversification_score:.3f}, '
                f'"risk_align": {score.risk_alignment_score:.3f}}}'
            )

        return scores


# ─────────────────────────────────────────────────────────────
# Per-asset scoring
# ─────────────────────────────────────────────────────────────

def _score_asset(
    ap: AssetProfile,
    mc: MarketContext,
    up: UserInvestmentProfile,
    port_set: set[str],
) -> AssetScore:
    factors: dict[str, str] = {}
    data_dims = 0

    # ── 1. Market fit ────────────────────────────────────────
    mf_score = _market_fit(ap, mc, factors)
    if mc.fed_rate is not None or mc.inflation is not None:
        data_dims += 1

    # ── 2. User fit ──────────────────────────────────────────
    uf_score = _user_fit(ap, up, factors)
    data_dims += 1  # user profile always present

    # ── 3. Diversification ───────────────────────────────────
    div_score = _diversification(ap, port_set, factors)
    if port_set:
        data_dims += 1

    # ── 4. Risk alignment ────────────────────────────────────
    ra_score = _risk_alignment(ap, up, factors)
    if ap.price_volatility_signal != "unknown":
        data_dims += 1

    # ── Composite ────────────────────────────────────────────
    composite = (
        _W_MARKET     * mf_score +
        _W_USER       * uf_score +
        _W_DIVERSIFY  * div_score +
        _W_RISK_ALIGN * ra_score
    )
    composite = _clamp(composite)

    # ── Data coverage ─────────────────────────────────────────
    coverage = "full" if data_dims >= 4 else "partial" if data_dims >= 2 else "minimal"

    return AssetScore(
        ticker=ap.ticker,
        market_fit_score=round(mf_score, 3),
        user_fit_score=round(uf_score, 3),
        diversification_score=round(div_score, 3),
        risk_alignment_score=round(ra_score, 3),
        composite_score=round(composite, 3),
        score_factors=factors,
        data_coverage=coverage,
    )


# ─────────────────────────────────────────────────────────────
# Score sub-functions (all return float 0.0–1.0)
# ─────────────────────────────────────────────────────────────

def _market_fit(ap: AssetProfile, mc: MarketContext, factors: dict) -> float:
    base = 0.50
    deltas = _REGIME_DELTAS.get(mc.regime, {})
    delta  = deltas.get(ap.asset_type, 0.0)
    score  = _clamp(base + delta)

    regime_label = mc.regime.value.replace("_", " ")
    type_label   = ap.asset_type.value
    factors["market_fit"] = (
        f"Regime: {regime_label} | Asset: {type_label} | "
        f"Delta: {delta:+.2f} → score {score:.2f}"
    )
    return score


def _user_fit(ap: AssetProfile, up: UserInvestmentProfile, factors: dict) -> float:
    score = 0.50
    notes = []

    # Interest alignment bonus
    ticker_lower = ap.ticker.lower()
    if any(ticker_lower in interest or interest in ticker_lower
           for interest in up.interests):
        score = _clamp(score + 0.15)
        notes.append("ticker matches user interest (+0.15)")

    # Experience vs asset complexity
    if ap.asset_type == AssetType.ETF and up.experience_level == "beginner":
        score = _clamp(score + 0.10)
        notes.append("ETF suits beginner (+0.10)")
    elif ap.asset_type == AssetType.STOCK and up.experience_level == "beginner":
        score = _clamp(score - 0.10)
        notes.append("individual stock complexity for beginner (-0.10)")

    # Style preference: deep analysis users get a slight bonus for complex assets
    if up.preferred_style == "deep" and ap.asset_type in (AssetType.STOCK, AssetType.ETF):
        score = _clamp(score + 0.05)
        notes.append("deep-analysis user prefers detailed assets (+0.05)")

    factors["user_fit"] = f"Score {score:.2f}" + ((" | " + "; ".join(notes)) if notes else "")
    return score


def _diversification(ap: AssetProfile, port_set: set[str], factors: dict) -> float:
    if not port_set:
        factors["diversification"] = "No portfolio data — neutral (0.50)"
        return 0.50

    if ap.ticker.upper() in port_set:
        factors["diversification"] = f"{ap.ticker} already held — no additional diversification (0.25)"
        return 0.25

    # Simple concentration heuristic: if portfolio is small, any new asset diversifies
    portfolio_size = len(port_set)
    if portfolio_size <= 3:
        score = 0.85
        factors["diversification"] = f"Small portfolio ({portfolio_size} assets) → high diversification benefit (0.85)"
    elif portfolio_size <= 8:
        score = 0.70
        factors["diversification"] = f"Medium portfolio ({portfolio_size} assets) → moderate diversification (0.70)"
    else:
        score = 0.55
        factors["diversification"] = f"Large portfolio ({portfolio_size} assets) → marginal diversification (0.55)"

    return score


def _risk_alignment(ap: AssetProfile, up: UserInvestmentProfile, factors: dict) -> float:
    user_risk = _RISK_NUM.get(up.risk_tolerance, 0.50)
    asset_vol = _VOL_NUM.get(ap.price_volatility_signal, 0.50)

    # Score = 1 - |user_risk - asset_vol| normalized to [0,1]
    mismatch = abs(user_risk - asset_vol)
    score = _clamp(1.0 - mismatch)

    factors["risk_alignment"] = (
        f"User risk: {up.risk_tolerance} ({user_risk:.2f}) | "
        f"Asset vol: {ap.price_volatility_signal} ({asset_vol:.2f}) | "
        f"Mismatch: {mismatch:.2f} → score {score:.2f}"
    )
    return score


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))

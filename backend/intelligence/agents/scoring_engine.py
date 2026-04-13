"""
intelligence/agents/scoring_engine.py — ScoringEngineAgent

CRITICAL: This agent is FULLY DETERMINISTIC. Zero LLM calls.

Responsibility:
  Compute five independent scores (0.0–1.0) for each asset based on:
    1. market_fit_score    — how well the asset fits the current market regime
    2. user_fit_score      — how well the asset matches user profile
    3. diversification_score — how much the asset reduces portfolio concentration
    4. risk_alignment_score  — asset risk vs user risk tolerance (uses real annualized vol)
    5. momentum_score      — trend alignment with market regime

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
  - composite = weighted sum of the five scores.
  - risk_alignment uses actual annualized_vol (float) when available; falls
    back to categorical signal when not.
  - momentum_score rewards assets trending in the direction favored by the regime.
  - score_factors dict always populated with human-readable explanations.
  - data_coverage tracks how many of the 5 sub-scores had real data.
"""

from __future__ import annotations

from core.logger import get_logger
from intelligence.schemas import (
    AssetProfile, AssetScore, AssetType,
    MarketContext, MarketRegime, UserInvestmentProfile,
)

logger = get_logger(__name__)

# ── Composite weights (must sum to 1.0) ──────────────────────────────────────
_W_MARKET       = 0.28
_W_USER         = 0.22
_W_DIVERSIFY    = 0.18
_W_RISK_ALIGN   = 0.22
_W_MOMENTUM     = 0.10

# ── Risk tolerance → target annualized vol range ─────────────────────────────
# Maps risk tolerance to (min_vol, max_vol) the user is comfortable with
_RISK_VOL_RANGE = {
    "low":    (0.00, 0.15),   # < 15% annualized vol preferred
    "medium": (0.10, 0.30),   # 10–30% vol comfortable
    "high":   (0.20, 0.60),   # 20–60% vol acceptable
}

# ── Fallback: categorical vol → numeric midpoint ─────────────────────────────
_VOL_SIGNAL_MID = {"low": 0.10, "medium": 0.22, "high": 0.40, "unknown": 0.22}

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

# ── Sector adjustments per regime ────────────────────────────────────────────
# Applied on top of the asset-type delta
_SECTOR_REGIME_DELTA: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.RISK_ON: {
        "Technology": +0.10, "Consumer Discretionary": +0.08,
        "Financials": +0.05, "Energy": +0.03,
        "Consumer Staples": -0.05, "Utilities": -0.08,
        "Long-Term Bonds": -0.15, "US Bond Market": -0.12,
    },
    MarketRegime.RISK_OFF: {
        "Consumer Staples": +0.10, "Utilities": +0.12, "Healthcare": +0.08,
        "Long-Term Bonds": +0.15, "US Bond Market": +0.10,
        "Technology": -0.08, "Consumer Discretionary": -0.10,
        "Emerging Markets": -0.12,
    },
    MarketRegime.STAGFLATION: {
        "Energy": +0.15, "Materials": +0.10, "Commodities": +0.15,
        "Real Estate": +0.05,
        "Technology": -0.10, "Long-Term Bonds": -0.20,
    },
    MarketRegime.RECESSION: {
        "Consumer Staples": +0.12, "Healthcare": +0.10, "Utilities": +0.10,
        "Long-Term Bonds": +0.20,
        "Technology": -0.10, "Financials": -0.15, "Energy": -0.12,
        "Consumer Discretionary": -0.15,
    },
    MarketRegime.RECOVERY: {
        "Technology": +0.10, "Consumer Discretionary": +0.08,
        "Financials": +0.08, "Industrials": +0.05,
        "Long-Term Bonds": -0.08, "Utilities": -0.05,
    },
}

# ── Momentum alignment per regime ────────────────────────────────────────────
# Regimes where upward momentum is rewarded
_UPTREND_REGIMES = {MarketRegime.RISK_ON, MarketRegime.RECOVERY}
# Regimes where downtrend in risky assets is expected (avoid FOMO)
_DOWNTREND_REGIMES = {MarketRegime.RISK_OFF, MarketRegime.RECESSION, MarketRegime.STAGFLATION}


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
                f'"risk_align": {score.risk_alignment_score:.3f}, '
                f'"momentum": {score.momentum_score:.3f}}}'
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

    # ── 4. Risk alignment (uses real annualized vol) ─────────
    ra_score = _risk_alignment(ap, up, factors)
    if ap.annualized_vol is not None or ap.price_volatility_signal != "unknown":
        data_dims += 1

    # ── 5. Momentum ───────────────────────────────────────────
    mom_score = _momentum(ap, mc, factors)
    if ap.momentum is not None:
        data_dims += 1

    # ── Composite ────────────────────────────────────────────
    composite = (
        _W_MARKET     * mf_score +
        _W_USER       * uf_score +
        _W_DIVERSIFY  * div_score +
        _W_RISK_ALIGN * ra_score +
        _W_MOMENTUM   * mom_score
    )
    composite = _clamp(composite)

    # ── Data coverage ─────────────────────────────────────────
    coverage = "full" if data_dims >= 5 else "partial" if data_dims >= 2 else "minimal"

    return AssetScore(
        ticker=ap.ticker,
        market_fit_score=round(mf_score, 3),
        user_fit_score=round(uf_score, 3),
        diversification_score=round(div_score, 3),
        risk_alignment_score=round(ra_score, 3),
        momentum_score=round(mom_score, 3),
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

    # Apply sector-specific adjustment on top of asset-type delta
    sector_delta = 0.0
    if ap.sector:
        sector_adjustments = _SECTOR_REGIME_DELTA.get(mc.regime, {})
        sector_delta = sector_adjustments.get(ap.sector, 0.0)

    score  = _clamp(base + delta + sector_delta)

    regime_label = mc.regime.value.replace("_", " ")
    type_label   = ap.asset_type.value
    sector_note  = f" | Sector: {ap.sector} (Δ{sector_delta:+.2f})" if ap.sector else ""
    factors["market_fit"] = (
        f"Regime: {regime_label} | Asset: {type_label}{sector_note} | "
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

    # Sector interest alignment
    if ap.sector:
        sector_lower = ap.sector.lower()
        if any(sector_lower in interest.lower() or interest.lower() in sector_lower
               for interest in up.interests):
            score = _clamp(score + 0.08)
            notes.append(f"sector {ap.sector} matches interest (+0.08)")

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

    # Portfolio size heuristic with sector awareness
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
    """
    Compute risk alignment using actual annualized volatility when available.
    Falls back to categorical signal when annualized_vol is None.
    Score = 1.0 when asset vol is within user's comfort range, penalized when outside.
    """
    user_risk = up.risk_tolerance  # low / medium / high
    vol_range = _RISK_VOL_RANGE.get(user_risk, (0.10, 0.30))
    min_vol, max_vol = vol_range

    # Use actual annualized vol if available, otherwise estimate from signal
    if ap.annualized_vol is not None:
        asset_vol = ap.annualized_vol
        vol_label = f"{asset_vol * 100:.1f}% annualized"
    else:
        asset_vol = _VOL_SIGNAL_MID.get(ap.price_volatility_signal, 0.22)
        vol_label = f"{ap.price_volatility_signal} signal (~{asset_vol * 100:.0f}%)"

    # Score based on distance from preferred vol range
    if min_vol <= asset_vol <= max_vol:
        # Within range — perfect alignment
        score = 0.90
        note = "within preferred vol range"
    elif asset_vol < min_vol:
        # Below preferred range — too conservative for this user
        gap = min_vol - asset_vol
        score = _clamp(0.90 - gap * 2.0)  # penalize gradually
        note = f"too low vol for {user_risk}-risk user"
    else:
        # Above preferred range — too risky
        gap = asset_vol - max_vol
        score = _clamp(0.90 - gap * 1.5)  # penalize gradually
        note = f"excess vol for {user_risk}-risk user"

    factors["risk_alignment"] = (
        f"User: {user_risk} (range: {min_vol*100:.0f}%–{max_vol*100:.0f}%) | "
        f"Asset vol: {vol_label} | {note} → score {score:.2f}"
    )
    return score


def _momentum(ap: AssetProfile, mc: MarketContext, factors: dict) -> float:
    """
    Score momentum alignment. In uptrend regimes, positive momentum earns a bonus.
    In downtrend regimes, negative momentum is 'expected' (neutral/slight penalty on uptrend).
    """
    if ap.momentum is None:
        factors["momentum"] = "Momentum: no data — neutral (0.50)"
        return 0.50

    regime_favors_up = mc.regime in _UPTREND_REGIMES
    regime_favors_down = mc.regime in _DOWNTREND_REGIMES

    momentum_scores = {
        "strong_up":   (0.85, 0.55, 0.40),   # (up_regime, neutral, down_regime)
        "up":          (0.72, 0.60, 0.45),
        "flat":        (0.55, 0.55, 0.55),
        "down":        (0.35, 0.45, 0.65),
        "strong_down": (0.20, 0.38, 0.75),
    }

    scores_tuple = momentum_scores.get(ap.momentum, (0.50, 0.50, 0.50))
    if regime_favors_up:
        score = scores_tuple[0]
        regime_note = "uptrend regime rewards positive momentum"
    elif regime_favors_down:
        score = scores_tuple[2]
        regime_note = "downtrend regime context"
    else:
        score = scores_tuple[1]
        regime_note = "neutral regime"

    factors["momentum"] = (
        f"Momentum: {ap.momentum} | {regime_note} → score {score:.2f}"
    )
    return score


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))

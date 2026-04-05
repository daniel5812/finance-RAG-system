"""
intelligence/agents/market_analyzer.py — MarketAnalyzerAgent

Responsibility:
  Read latest macro indicators and FX rates from DB, classify the current
  market regime using DETERMINISTIC rules (no LLM), and produce a list of
  human-readable macro signals for LLM context injection.

Inputs:
  - asyncpg.Pool (reads macro_series and fx_rates — parameterized, read-only)

Outputs:
  - MarketContext with regime, key figures, and signal list

Design:
  - DETERMINISTIC regime classification (rule-based thresholds)
  - LLM is NOT called here — it receives the structured signals, not raw SQL rows
  - Graceful degradation: regime → NEUTRAL when data is missing
  - regime_confidence degrades with data freshness

Regime classification rules (applied in priority order):
  1. STAGFLATION  : FEDFUNDS >= 4.0 AND CPIAUCNS >= 4.0 AND GDP growth < 2%
  2. RECESSION    : GDP contraction (value < prev) OR UNRATE > 7.0
  3. RISK_OFF     : FEDFUNDS >= 4.0 (tight money regardless of growth)
  4. RECOVERY     : FEDFUNDS < 2.5 AND UNRATE > 5.5 (post-recession stimilus)
  5. RISK_ON      : FEDFUNDS < 2.5 AND CPIAUCNS < 3.0 (easy money, low inflation)
  6. NEUTRAL      : everything else / insufficient data
"""

from __future__ import annotations

import asyncpg

from core.logger import get_logger
from intelligence.schemas import MarketContext, MarketRegime

logger = get_logger(__name__)

# ─── Thresholds ─────────────────────────────────────────────────────────────
_FED_TIGHT       = 4.0   # FEDFUNDS >= this → tight monetary policy
_FED_EASY        = 2.5   # FEDFUNDS < this  → accommodative policy
_CPI_HOT         = 4.0   # CPIAUCNS >= this → high inflation
_CPI_TARGET      = 3.0   # CPIAUCNS < this  → near-target inflation
_UNRATE_HIGH     = 7.0   # unemployment → potential recession signal
_UNRATE_ELEVATED = 5.5   # unemployment → still elevated (recovery zone)
_GDP_WEAK        = 2.0   # GDP annual growth below this → weak expansion


class MarketAnalyzerAgent:
    """
    Fetches macro data from DB and classifies current market regime.
    All classification is deterministic — zero LLM calls.
    """

    @staticmethod
    async def run(pool: asyncpg.Pool) -> MarketContext:
        """
        Query DB for latest macro indicators → classify regime → return MarketContext.
        Never raises — returns NEUTRAL context on any failure.
        """
        try:
            macro = await _fetch_macro_latest(pool)
            fx    = await _fetch_fx_latest(pool, "USD", "ILS")
            ctx   = _classify_regime(macro, fx)
            logger.info(
                f'{{"event": "market_analyzer_agent", "status": "ok", '
                f'"regime": "{ctx.regime}", "confidence": "{ctx.regime_confidence}"}}'
            )
            return ctx
        except Exception as exc:
            logger.warning(f'{{"event": "market_analyzer_agent", "status": "error", "error": "{exc}"}}')
            return MarketContext(regime=MarketRegime.NEUTRAL, regime_confidence="none")


# ─────────────────────────────────────────────────────────────
# DB helpers — parameterized, read-only, no owner_id needed
# (macro data is global, not user-scoped)
# ─────────────────────────────────────────────────────────────

async def _fetch_macro_latest(pool: asyncpg.Pool) -> dict[str, float]:
    """Return {series_id: latest_value} for key FRED series."""
    series_ids = ("FEDFUNDS", "CPIAUCNS", "UNRATE", "GDP")
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (series_id)
            series_id, value, date
        FROM macro_series
        WHERE series_id = ANY($1::text[])
        ORDER BY series_id, date DESC
        """,
        list(series_ids),
    )
    return {r["series_id"]: float(r["value"]) for r in rows}


async def _fetch_fx_latest(pool: asyncpg.Pool, base: str, quote: str) -> float | None:
    """Return latest FX rate for base/quote pair, or None if not available."""
    row = await pool.fetchrow(
        """
        SELECT rate FROM fx_rates
        WHERE base_currency = $1 AND quote_currency = $2
        ORDER BY date DESC
        LIMIT 1
        """,
        base, quote,
    )
    return float(row["rate"]) if row else None


# ─────────────────────────────────────────────────────────────
# Deterministic regime classifier
# ─────────────────────────────────────────────────────────────

def _classify_regime(macro: dict[str, float], usd_ils: float | None) -> MarketContext:
    fed   = macro.get("FEDFUNDS")
    cpi   = macro.get("CPIAUCNS")
    unrate = macro.get("UNRATE")
    gdp   = macro.get("GDP")

    signals: list[str] = []
    data_count = sum(v is not None for v in [fed, cpi, unrate, gdp])

    # ── Build human-readable signals ────────────────────────────────────────
    if fed is not None:
        signals.append(
            f"Fed Funds Rate: {fed:.2f}% — "
            + ("tight monetary policy" if fed >= _FED_TIGHT else
               "accommodative policy" if fed < _FED_EASY else "neutral stance")
        )
    if cpi is not None:
        signals.append(
            f"CPI: {cpi:.1f} — "
            + ("high inflation pressure" if cpi >= _CPI_HOT else
               "near-target inflation" if cpi < _CPI_TARGET else "moderate inflation")
        )
    if unrate is not None:
        signals.append(
            f"Unemployment: {unrate:.1f}% — "
            + ("recessionary level" if unrate > _UNRATE_HIGH else
               "elevated, recovery mode" if unrate > _UNRATE_ELEVATED else "healthy labor market")
        )
    if gdp is not None:
        signals.append(f"GDP: {gdp:.1f}B (latest reported)")
    if usd_ils is not None:
        signals.append(f"USD/ILS: {usd_ils:.4f}")

    # ── Classify regime (priority order) ────────────────────────────────────
    regime = MarketRegime.NEUTRAL

    if fed is not None and cpi is not None:
        if fed >= _FED_TIGHT and cpi >= _CPI_HOT:
            regime = MarketRegime.STAGFLATION
        elif unrate is not None and unrate > _UNRATE_HIGH:
            regime = MarketRegime.RECESSION
        elif fed >= _FED_TIGHT:
            regime = MarketRegime.RISK_OFF
        elif fed < _FED_EASY and unrate is not None and unrate > _UNRATE_ELEVATED:
            regime = MarketRegime.RECOVERY
        elif fed < _FED_EASY and cpi < _CPI_TARGET:
            regime = MarketRegime.RISK_ON

    # ── Confidence based on data coverage ───────────────────────────────────
    confidence = "high" if data_count >= 3 else "medium" if data_count >= 2 else "low"

    return MarketContext(
        regime=regime,
        fed_rate=fed,
        inflation=cpi,
        unemployment=unrate,
        gdp_latest=gdp,
        usd_ils_rate=usd_ils,
        regime_confidence=confidence,
        macro_signals=signals,
    )

"""
intelligence/agents/asset_profiler.py — AssetProfilerAgent

Responsibility:
  Build a structured AssetProfile for each ticker mentioned in the query,
  using price history and ETF holdings already stored in the DB.

Inputs:
  - tickers: list[str]   — extracted by orchestrator from context/query
  - pool: asyncpg.Pool   — read-only queries to prices and etf_holdings

Outputs:
  - list[AssetProfile]

Design:
  - All DB queries are parameterized, no LLM calls.
  - Asset type is inferred from ETF holdings presence and known ETF list.
  - Volatility signal derived from 30-day price range (deterministic).
  - Source confidence degrades if price data is stale or missing.
  - ETF holdings fetched for known ETF symbols only (top 5 by weight).
  - Graceful degradation: if ticker has no data → minimal profile with low confidence.
"""

from __future__ import annotations

from datetime import date, timedelta
from math import sqrt

import asyncpg

from core.logger import get_logger
from intelligence.schemas import AssetProfile, AssetType

logger = get_logger(__name__)

# Known ETF universe (seed + common ones)
_KNOWN_ETFS = {
    "SPY", "QQQ", "IVV", "VTI", "VOO", "VEA", "VWO",
    "AGG", "BND", "GLD", "TLT", "IWM", "XLF", "XLE",
    "XLK", "XLV", "XLU", "XLB", "XLC", "XLI", "XLRE",
    "VNQ", "HYG", "LQD", "EMB", "IEFA", "EEM", "DIA",
}


class AssetProfilerAgent:
    """
    Fetches price history and ETF metadata from DB to build AssetProfile objects.
    """

    @staticmethod
    async def run(
        tickers: list[str],
        pool: asyncpg.Pool,
    ) -> list[AssetProfile]:
        """
        Build AssetProfile for each ticker.
        Returns empty list if tickers is empty or pool is None.
        """
        if not tickers or not pool:
            return []

        profiles: list[AssetProfile] = []
        for ticker in tickers[:5]:  # cap at 5 to bound latency
            try:
                profile = await _build_profile(ticker, pool)
                profiles.append(profile)
            except Exception as exc:
                logger.warning(
                    f'{{"event": "asset_profiler_agent", "ticker": "{ticker}", '
                    f'"status": "error", "error": "{exc}"}}'
                )
                profiles.append(AssetProfile(ticker=ticker, source_confidence="none"))

        logger.info(
            f'{{"event": "asset_profiler_agent", "status": "ok", '
            f'"tickers": {tickers[:5]}, "profiles_built": {len(profiles)}}}'
        )
        return profiles


# ─────────────────────────────────────────────────────────────
# Per-ticker builder
# ─────────────────────────────────────────────────────────────

async def _build_profile(ticker: str, pool: asyncpg.Pool) -> AssetProfile:
    prices = await _fetch_prices(ticker, pool, days=35)

    # ── Asset type ───────────────────────────────────────────
    if ticker in _KNOWN_ETFS:
        asset_type = AssetType.ETF
    elif ticker.endswith("T") or ticker in {"TLT", "SHY", "IEF", "BND", "AGG"}:
        asset_type = AssetType.BOND
    else:
        asset_type = AssetType.STOCK  # default assumption

    # ── Price stats ──────────────────────────────────────────
    recent_price: float | None = None
    p7d_chg: float | None = None
    p30d_chg: float | None = None
    vol_signal = "unknown"
    freshness = "unknown"

    if prices:
        # prices sorted DESC by date
        recent_price = prices[0]["close"]
        today = date.today()
        days_old = (today - prices[0]["date"]).days
        freshness = f"{days_old}d ago" if days_old > 0 else "today"

        # 7-day change
        if len(prices) >= 7:
            price_7d = prices[min(6, len(prices) - 1)]["close"]
            if price_7d and price_7d > 0:
                p7d_chg = round((recent_price - price_7d) / price_7d * 100, 2)

        # 30-day change
        if len(prices) >= 30:
            price_30d = prices[min(29, len(prices) - 1)]["close"]
            if price_30d and price_30d > 0:
                p30d_chg = round((recent_price - price_30d) / price_30d * 100, 2)

        # Volatility: daily range / close as proxy
        if len(prices) >= 5:
            ranges = []
            for p in prices[:20]:
                if p.get("high") and p.get("low") and p["close"]:
                    ranges.append((p["high"] - p["low"]) / p["close"])
            if ranges:
                avg_range = sum(ranges) / len(ranges)
                vol_signal = (
                    "high"   if avg_range > 0.025 else
                    "medium" if avg_range > 0.012 else
                    "low"
                )

    # ── Source confidence ────────────────────────────────────
    if not prices:
        source_confidence = "none"
    elif len(prices) >= 20:
        source_confidence = "high"
    elif len(prices) >= 7:
        source_confidence = "medium"
    else:
        source_confidence = "low"

    # ── ETF holdings ─────────────────────────────────────────
    etf_top: list[str] = []
    if asset_type == AssetType.ETF:
        etf_top = await _fetch_etf_top_holdings(ticker, pool, top_n=5)

    return AssetProfile(
        ticker=ticker,
        asset_type=asset_type,
        recent_price=recent_price,
        price_7d_change_pct=p7d_chg,
        price_30d_change_pct=p30d_chg,
        price_volatility_signal=vol_signal,
        etf_top_holdings=etf_top,
        data_freshness=freshness,
        source_confidence=source_confidence,
    )


# ─────────────────────────────────────────────────────────────
# DB helpers — parameterized, read-only
# ─────────────────────────────────────────────────────────────

async def _fetch_prices(ticker: str, pool: asyncpg.Pool, days: int = 35) -> list[dict]:
    """Fetch recent OHLCV rows for ticker, newest first."""
    cutoff = date.today() - timedelta(days=days)
    rows = await pool.fetch(
        """
        SELECT date, open, high, low, close, volume
        FROM prices
        WHERE symbol = $1 AND date >= $2
        ORDER BY date DESC
        LIMIT 35
        """,
        ticker, cutoff,
    )
    return [dict(r) for r in rows]


async def _fetch_etf_top_holdings(etf: str, pool: asyncpg.Pool, top_n: int = 5) -> list[str]:
    """Return top-N holding symbols for an ETF (by weight, latest date)."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (holding_symbol)
            holding_symbol, weight
        FROM etf_holdings
        WHERE etf_symbol = $1
          AND holding_symbol IS NOT NULL
        ORDER BY holding_symbol, date DESC, weight DESC
        LIMIT $2
        """,
        etf, top_n,
    )
    # Re-sort by weight desc after DISTINCT ON
    sorted_rows = sorted(rows, key=lambda r: float(r["weight"] or 0), reverse=True)
    return [r["holding_symbol"] for r in sorted_rows[:top_n]]

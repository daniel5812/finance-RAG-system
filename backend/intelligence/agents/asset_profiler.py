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
  - Volatility: annualized standard deviation of log returns × sqrt(252).
  - Beta vs SPY: computed from overlapping price history with SPY.
  - Momentum: derived from 7d and 30d price changes.
  - Sector: mapped from static dictionary; ETF-aware.
  - Source confidence degrades if price data is stale or missing.
  - ETF holdings fetched for known ETF symbols only (top 5 by weight).
  - Graceful degradation: if ticker has no data → minimal profile with low confidence.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
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

# Static sector mapping for common tickers and sector ETFs
_SECTOR_MAP: dict[str, str] = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "GOOG": "Technology", "META": "Technology", "NVDA": "Technology",
    "AMD": "Technology", "INTC": "Technology", "CRM": "Technology",
    "ORCL": "Technology", "CSCO": "Technology", "ADBE": "Technology",
    "QCOM": "Technology", "TXN": "Technology", "AVGO": "Technology",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "HD": "Consumer Discretionary",
    "MCD": "Consumer Discretionary", "SBUX": "Consumer Discretionary",
    # Financials
    "JPM": "Financials", "GS": "Financials", "BAC": "Financials",
    "WFC": "Financials", "V": "Financials", "MA": "Financials",
    "MS": "Financials", "C": "Financials", "BLK": "Financials",
    # Healthcare
    "JNJ": "Healthcare", "PFE": "Healthcare", "MRK": "Healthcare",
    "ABBV": "Healthcare", "LLY": "Healthcare", "UNH": "Healthcare",
    "BMY": "Healthcare", "AMGN": "Healthcare", "GILD": "Healthcare",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "SLB": "Energy", "EOG": "Energy",
    # Consumer Staples
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "WMT": "Consumer Staples", "COST": "Consumer Staples", "PM": "Consumer Staples",
    # Communication Services
    "NFLX": "Communication Services", "DIS": "Communication Services",
    "T": "Communication Services", "VZ": "Communication Services",
    # Industrials
    "BA": "Industrials", "CAT": "Industrials", "GE": "Industrials",
    "RTX": "Industrials", "HON": "Industrials", "UPS": "Industrials",
    # Materials
    "LIN": "Materials", "APD": "Materials", "NEM": "Materials",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
    # Real Estate
    "AMT": "Real Estate", "PLD": "Real Estate", "CCI": "Real Estate",
    # Commodities
    "GLD": "Commodities", "SLV": "Commodities", "USO": "Commodities",
    # Sector ETFs
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Healthcare", "XLU": "Utilities", "XLB": "Materials",
    "XLC": "Communication Services", "XLI": "Industrials", "XLRE": "Real Estate",
    # Broad market ETFs
    "SPY": "US Broad Market", "IVV": "US Broad Market", "VOO": "US Broad Market",
    "VTI": "US Total Market", "QQQ": "Technology Heavy",
    "IWM": "US Small Cap", "DIA": "US Large Cap",
    # International ETFs
    "VEA": "International Developed", "IEFA": "International Developed",
    "VWO": "Emerging Markets", "EEM": "Emerging Markets",
    # Real estate ETFs
    "VNQ": "Real Estate",
    # Fixed income ETFs
    "AGG": "US Bond Market", "BND": "US Bond Market",
    "TLT": "Long-Term Bonds", "SHY": "Short-Term Bonds", "IEF": "Intermediate Bonds",
    "HYG": "High Yield Bonds", "LQD": "Investment Grade Bonds",
    "EMB": "Emerging Market Bonds",
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

        # Pre-fetch SPY prices once for beta calculation (shared across all tickers)
        spy_prices: list[dict] = []
        if "SPY" not in tickers:
            try:
                spy_prices = await _fetch_prices("SPY", pool, days=35)
            except Exception:
                spy_prices = []

        profiles: list[AssetProfile] = []
        for ticker in tickers[:5]:  # cap at 5 to bound latency
            try:
                profile = await _build_profile(ticker, pool, spy_prices)
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

async def _build_profile(
    ticker: str,
    pool: asyncpg.Pool,
    spy_prices: list[dict],
) -> AssetProfile:
    prices = await _fetch_prices(ticker, pool, days=35)

    # ── Asset type ───────────────────────────────────────────
    if ticker in _KNOWN_ETFS:
        asset_type = AssetType.ETF
    elif ticker.endswith("T") or ticker in {"TLT", "SHY", "IEF", "BND", "AGG"}:
        asset_type = AssetType.BOND
    else:
        asset_type = AssetType.STOCK  # default assumption

    # ── Sector ───────────────────────────────────────────────
    sector = _SECTOR_MAP.get(ticker.upper())

    # ── Price stats ──────────────────────────────────────────
    recent_price: float | None = None
    p7d_chg: float | None = None
    p30d_chg: float | None = None
    vol_signal = "unknown"
    annualized_vol: float | None = None
    beta_vs_spy: float | None = None
    momentum: str | None = None
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

        # ── Volatility: annualized std of log returns ─────────
        # prices are DESC by date → sort ASC for sequential return computation
        sorted_prices = sorted(prices, key=lambda p: p["date"])
        closes = [p["close"] for p in sorted_prices if p.get("close") and p["close"] > 0]

        if len(closes) >= 5:
            log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
            if log_returns:
                daily_std = float(np.std(log_returns, ddof=1))
                annualized_vol = round(daily_std * math.sqrt(252), 4)  # e.g. 0.22 = 22% vol
                vol_signal = (
                    "high"   if annualized_vol > 0.30 else
                    "medium" if annualized_vol > 0.15 else
                    "low"
                )

        # ── Momentum: trend from 7d and 30d changes ──────────
        if p7d_chg is not None and p30d_chg is not None:
            if p7d_chg > 5 and p30d_chg > 10:
                momentum = "strong_up"
            elif p7d_chg > 2 or p30d_chg > 5:
                momentum = "up"
            elif p7d_chg < -5 and p30d_chg < -10:
                momentum = "strong_down"
            elif p7d_chg < -2 or p30d_chg < -5:
                momentum = "down"
            else:
                momentum = "flat"
        elif p30d_chg is not None:
            if p30d_chg > 10:
                momentum = "strong_up"
            elif p30d_chg > 5:
                momentum = "up"
            elif p30d_chg < -10:
                momentum = "strong_down"
            elif p30d_chg < -5:
                momentum = "down"
            else:
                momentum = "flat"

        # ── Beta vs SPY ───────────────────────────────────────
        ref_prices = spy_prices if ticker != "SPY" else []
        if ref_prices and len(closes) >= 10:
            beta_vs_spy = _compute_beta(prices, ref_prices)

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
        sector=sector,
        recent_price=recent_price,
        price_7d_change_pct=p7d_chg,
        price_30d_change_pct=p30d_chg,
        price_volatility_signal=vol_signal,
        annualized_vol=annualized_vol,
        beta_vs_spy=beta_vs_spy,
        momentum=momentum,
        etf_top_holdings=etf_top,
        data_freshness=freshness,
        source_confidence=source_confidence,
    )


# ─────────────────────────────────────────────────────────────
# Beta calculation
# ─────────────────────────────────────────────────────────────

def _compute_beta(ticker_prices: list[dict], spy_prices: list[dict]) -> float | None:
    """
    Compute beta of ticker vs SPY using overlapping daily log returns.
    Both price lists are sorted DESC by date.
    Returns None if insufficient overlapping data.
    """
    try:
        ticker_map = {
            p["date"]: p["close"]
            for p in ticker_prices
            if p.get("close") and p["close"] > 0
        }
        spy_map = {
            p["date"]: p["close"]
            for p in spy_prices
            if p.get("close") and p["close"] > 0
        }

        common_dates = sorted(ticker_map.keys() & spy_map.keys())
        if len(common_dates) < 10:
            return None

        ticker_closes = [ticker_map[d] for d in common_dates]
        spy_closes = [spy_map[d] for d in common_dates]

        ticker_returns = np.diff(np.log(ticker_closes))
        spy_returns = np.diff(np.log(spy_closes))

        spy_var = float(np.var(spy_returns, ddof=1))
        if spy_var == 0:
            return None

        cov = float(np.cov(ticker_returns, spy_returns)[0, 1])
        beta = cov / spy_var
        return round(beta, 2)
    except Exception:
        return None


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

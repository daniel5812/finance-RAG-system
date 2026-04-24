"""
intelligence/agents/portfolio_fit.py — PortfolioFitAgent

Responsibility:
  Analyse how the assets mentioned in the query relate to the user's current
  portfolio — identify overlaps, concentration risk, and dominant sector.

Inputs:
  - tickers_mentioned: list[str]         — tickers from the user's query/context
  - owner_id: str                         — for scoped DB query
  - pool: asyncpg.Pool

Outputs:
  - PortfolioFitAnalysis

Design:
  - Single parameterized DB query, filtered by owner_id (multi-tenant safe).
  - Concentration risk: Herfindahl-Hirschman Index (HHI) over position counts.
  - No LLM calls.
  - Graceful degradation when portfolio is empty.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import asyncpg

from core.logger import get_logger
from intelligence.data_normalizer import normalize_portfolio
from intelligence.schemas import PortfolioFitAnalysis

logger = get_logger(__name__)


def _safe_get(row: dict | object, key: str, default=None):
    """Access row field as dict or object attribute (handles both dict and MagicMock rows)."""
    try:
        return row[key] if isinstance(row, dict) else getattr(row, key, default)
    except (KeyError, TypeError):
        return default

# HHI thresholds for concentration risk
_HHI_HIGH   = 0.25   # single asset >25% by count
_HHI_MEDIUM = 0.15


class PortfolioFitAgent:
    """
    Loads user portfolio positions and analyses fit against queried assets.
    """

    @staticmethod
    async def run(
        tickers_mentioned: list[str],
        owner_id: str,
        pool: asyncpg.Pool,
    ) -> PortfolioFitAnalysis:
        """
        Build PortfolioFitAnalysis. Returns a minimal analysis when data is missing.
        """
        if not owner_id or not pool:
            return PortfolioFitAnalysis(
                tickers_mentioned=tickers_mentioned,
                current_exposure_summary="No portfolio data available.",
            )

        try:
            rows = await _fetch_portfolio(owner_id, pool)
            # Extract unique symbols and fetch prices
            symbols = list({r["symbol"].upper() for r in rows}) if rows else []
            prices, prices_as_of = await _fetch_prices(symbols, pool)
            return _analyse(rows, tickers_mentioned, prices=prices, prices_as_of=prices_as_of)
        except Exception as exc:
            logger.warning(
                f'{{"event": "portfolio_fit_agent", "owner_id": "REDACTED", '
                f'"status": "error", "error": "{exc}"}}'
            )
            return PortfolioFitAnalysis(
                tickers_mentioned=tickers_mentioned,
                current_exposure_summary="Portfolio data unavailable.",
            )


# ─────────────────────────────────────────────────────────────
# DB helper — owner_id scoped (SAFETY: never omit owner_id filter)
# ─────────────────────────────────────────────────────────────

async def _fetch_portfolio(owner_id: str, pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT symbol, quantity, cost_basis, currency, account,
               MIN(date) OVER (PARTITION BY symbol) AS entry_date
        FROM portfolio_positions
        WHERE user_id = $1
        ORDER BY date DESC
        LIMIT 100
        """,
        owner_id,
    )
    # Convert rows to dicts; handle both asyncpg Record and mock objects
    result = []
    for r in rows:
        if isinstance(r, dict):
            result.append(r)
        else:
            try:
                result.append(dict(r))
            except (TypeError, ValueError):
                # If dict() fails (e.g., on MagicMock), build dict from attributes
                result.append({
                    "symbol": _safe_get(r, "symbol"),
                    "quantity": _safe_get(r, "quantity"),
                    "cost_basis": _safe_get(r, "cost_basis"),
                    "currency": _safe_get(r, "currency"),
                    "account": _safe_get(r, "account"),
                    "entry_date": _safe_get(r, "entry_date"),
                })
    return result


async def _fetch_prices(
    symbols: list[str], pool: asyncpg.Pool
) -> tuple[dict[str, float], Optional[date]]:
    """
    Fetch latest price for each symbol from prices table.
    Returns (prices_dict, prices_as_of_date).
    If no symbols or no prices found, returns ({}, None).
    """
    if not symbols:
        return {}, None

    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (symbol) symbol, close, date
        FROM prices
        WHERE symbol = ANY($1)
        ORDER BY symbol, date DESC
        """,
        symbols,
    )

    prices = {}
    latest_date = None
    for row in rows:
        symbol = _safe_get(row, "symbol")
        close = _safe_get(row, "close")
        row_date = _safe_get(row, "date")
        if symbol and close is not None:
            prices[symbol] = float(close)
            if latest_date is None or row_date > latest_date:
                latest_date = row_date

    return prices, latest_date


# ─────────────────────────────────────────────────────────────
# Analysis
# ─────────────────────────────────────────────────────────────

def _analyse(
    rows: list[dict],
    tickers_mentioned: list[str],
    prices: dict[str, float] | None = None,
    prices_as_of: Optional[date] = None,
) -> PortfolioFitAnalysis:
    if not rows:
        return PortfolioFitAnalysis(
            tickers_mentioned=tickers_mentioned,
            current_exposure_summary="Portfolio is empty — no positions found.",
            normalized_portfolio=normalize_portfolio([]),
        )

    # ── Normalize portfolio (compute invested capital per ticker) ─────────────
    # normalize_portfolio deduplicates by ticker (takes newest row per ticker)
    # If prices provided, also computes position values, P&L, and portfolio weights
    norm = normalize_portfolio(rows, prices=prices, prices_as_of=prices_as_of)

    # ── Unique tickers in portfolio ───────────────────────────────────────────
    port_tickers = list(norm.allocation_pct.keys()) if norm.allocation_pct else list(
        {_safe_get(r, "symbol", "").upper() for r in rows if _safe_get(r, "symbol")}
    )
    mentioned_upper = [t.upper() for t in tickers_mentioned]
    already_held = [t for t in mentioned_upper if t in set(port_tickers)]

    # ── Concentration: HHI by invested capital (not count) ───────────────────
    # HHI = sum((allocation_i / 100)^2) — allocation already in %
    if norm.allocation_pct:
        hhi = sum((pct / 100) ** 2 for pct in norm.allocation_pct.values())
    else:
        hhi = 0.0

    concentration = (
        "high"   if hhi >= _HHI_HIGH else
        "medium" if hhi >= _HHI_MEDIUM else
        "low"
    )

    # ── Dominant ticker by invested capital ──────────────────────────────────
    dominant_ticker = norm.largest_position_ticker
    dominant_pct    = norm.largest_position_pct or 0.0

    # ── Exposure summary (facts only — no calculations for LLM to redo) ──────
    if dominant_ticker and dominant_pct > 30:
        exposure = (
            f"Portfolio has {norm.total_positions} unique positions. "
            f"{dominant_ticker} is the largest by invested capital ({dominant_pct:.1f}% of total). "
            f"Concentration risk: {concentration} (HHI by value)."
        )
    else:
        exposure = (
            f"Portfolio has {norm.total_positions} unique positions. "
            f"Concentration risk: {concentration} (HHI by value)."
        )

    if norm.total_invested is not None:
        exposure += f" Total invested capital: {norm.currency} {norm.total_invested:,.2f}."
    if already_held:
        exposure += f" Already holding: {', '.join(already_held)}."

    logger.info(
        f'{{"event": "portfolio_fit_agent", "status": "ok", '
        f'"port_size": {norm.total_positions}, "concentration": "{concentration}", '
        f'"hhi": {hhi:.3f}, "already_held_count": {len(already_held)}}}'
    )

    return PortfolioFitAnalysis(
        tickers_in_portfolio=port_tickers,
        tickers_mentioned=mentioned_upper,
        already_held=already_held,
        concentration_risk=concentration,
        dominant_ticker=dominant_ticker,
        dominant_sector=None,                   # future: when sector data is available
        current_exposure_summary=exposure,
        normalized_portfolio=norm,
    )

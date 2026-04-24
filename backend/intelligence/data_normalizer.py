"""
intelligence/data_normalizer.py — Data Normalization Layer

Responsibility:
  Convert raw portfolio_positions SQL rows into a canonical NormalizedPortfolio
  structure with pre-computed, semantically labelled financial metrics.

CRITICAL DESIGN RULE:
  ALL arithmetic is performed here — in deterministic Python.
  The LLM MUST NOT derive, compute, or infer financial figures on its own.
  The context_builder renders this structure directly into the LLM prompt
  so that the LLM only needs to read and cite — not calculate.

Schema contract (per schema.sql):
  portfolio_positions columns used:
    symbol      TEXT           — ticker symbol
    quantity    NUMERIC(14,4)  — number of units held
    cost_basis  NUMERIC(14,4)  — avg price paid PER UNIT (not total)
    currency    VARCHAR(10)    — position currency

  Total position value = quantity × cost_basis
  This represents INVESTED CAPITAL, not current market value.
  Returns / P&L are NOT computable here (no live prices).

Output: NormalizedPortfolio — directly injected into IntelligenceReport.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from intelligence.schemas import NormalizedPortfolio, PositionDetail


def _safe_get(row: dict | object, key: str, default=None):
    """Access row field as dict or object attribute (handles both dict and MagicMock rows)."""
    try:
        return row[key] if isinstance(row, dict) else getattr(row, key, default)
    except (KeyError, TypeError):
        return default


def normalize_portfolio(
    rows: list[dict],
    prices: dict[str, float] | None = None,
    prices_as_of: date | None = None,
) -> NormalizedPortfolio:
    """
    Compute canonical financial metrics from raw portfolio_positions rows.

    Parameters:
      rows: portfolio positions (symbol, quantity, cost_basis, currency)
      prices: optional dict[symbol → latest_close] for market-value computation
      prices_as_of: optional date label for price staleness (e.g., most recent price date)

    Field semantics:
      total_invested  = SUM(quantity × cost_basis) across all positions
      allocation_pct  = each ticker's invested capital as % of total_invested
      largest_*       = the ticker with the highest allocated capital

      When prices provided:
      positions       = dict[ticker → PositionDetail] with entry_date, PnL, weight
      total_market_value = SUM(quantity × price) for positions with known prices
      prices_as_of    = label for data freshness

    Returns a minimal NormalizedPortfolio if rows is empty.
    Never raises.
    """
    if not rows:
        return NormalizedPortfolio(
            total_positions=0,
            data_note="No portfolio positions found. Cannot compute allocation.",
        )

    try:
        return _compute(rows, prices=prices or {}, prices_as_of=prices_as_of)
    except Exception:
        return NormalizedPortfolio(
            total_positions=len(rows),
            data_note="Normalization error — allocation percentages unavailable.",
        )


def _compute(
    rows: list[dict],
    prices: dict[str, float] | None = None,
    prices_as_of: date | None = None,
) -> NormalizedPortfolio:
    # ── Aggregate by ticker ───────────────────────────────────────────────────
    # Each row: one position entry; same ticker may appear in multiple rows (e.g. date snapshots).
    # We use the most recent value per ticker (rows should already be sorted DESC by date).
    # De-duplicate by ticker: if multiple rows exist, use the first occurrence (newest).
    seen: set[str] = set()
    by_ticker: dict[str, dict] = {}

    currency = "USD"
    for row in rows:
        ticker = _safe_get(row, "symbol", "").upper()
        if not ticker:
            continue  # skip rows without symbol
        if ticker in seen:
            continue  # skip older rows for same ticker
        seen.add(ticker)

        qty = float(_safe_get(row, "quantity") or 0.0)
        cb  = float(_safe_get(row, "cost_basis") or 0.0)   # avg price per unit
        entry_dt = _safe_get(row, "entry_date")  # optional: MIN(date) from DB query
        total_position_value = qty * cb    # total invested in this position

        by_ticker[ticker] = {
            "quantity":       qty,
            "cost_basis":     cb,           # per-unit
            "total_invested": total_position_value,
            "entry_date":     entry_dt,     # from DB MIN(date) or None
        }
        cur = _safe_get(row, "currency")
        if cur:
            currency = str(cur)

    # ── Total invested capital ────────────────────────────────────────────────
    total_invested = sum(v["total_invested"] for v in by_ticker.values())

    # ── Allocation percentages (by invested capital, not count) ──────────────
    allocation_pct: dict[str, float] = {}
    if total_invested > 0:
        for ticker, v in by_ticker.items():
            allocation_pct[ticker] = round(v["total_invested"] / total_invested * 100, 2)
    else:
        # If total_invested is 0, all positions have 0% allocation
        for ticker in by_ticker.keys():
            allocation_pct[ticker] = 0.0

    # Sort descending by allocation
    allocation_pct = dict(
        sorted(allocation_pct.items(), key=lambda x: x[1], reverse=True)
    )

    largest_ticker = next(iter(allocation_pct), None)
    largest_pct    = allocation_pct[largest_ticker] if largest_ticker else None

    # ── Market-value enrichment (if prices provided) ──────────────────────────
    prices = prices or {}
    positions_detail: dict[str, PositionDetail] = {}
    total_market_value: float | None = None
    price_count = 0

    if prices:
        # Compute market value for positions with known prices
        market_values = {}
        for ticker, info in by_ticker.items():
            if ticker in prices:
                price = prices[ticker]
                if price is not None and price > 0:
                    market_val = info["quantity"] * price
                    market_values[ticker] = market_val
                    price_count += 1

        if market_values:
            total_market_value = sum(market_values.values())

        # Populate PositionDetail for each position
        for ticker, info in by_ticker.items():
            detail = PositionDetail()

            # entry_date from row (if available)
            if info.get("entry_date"):
                detail.entry_date = info["entry_date"]

            # current_price from prices dict
            if ticker in prices:
                detail.current_price = prices[ticker]

            # position_value and PnL only if price available
            if ticker in prices and prices[ticker] is not None and prices[ticker] > 0:
                qty = info["quantity"]
                price = prices[ticker]
                cb = info["cost_basis"]

                position_value = qty * price
                detail.position_value = round(position_value, 2)

                # PnL only if cost_basis is valid (non-zero)
                if cb and cb > 0:
                    invested_amt = qty * cb
                    pnl = position_value - invested_amt
                    detail.position_pnl = round(pnl, 2)

                    pnl_pct = (pnl / invested_amt) * 100
                    detail.position_pnl_pct = round(pnl_pct, 2)

                # portfolio_weight only if total_market_value available
                if total_market_value and total_market_value > 0:
                    weight = (position_value / total_market_value) * 100
                    detail.portfolio_weight = round(weight, 2)

            positions_detail[ticker] = detail

    # ── Build data_note based on price coverage ──────────────────────────────
    if prices:
        if price_count == len(by_ticker):
            price_note = (
                "Full price coverage — allocation %, P&L, and portfolio weights are available. "
            )
        elif price_count > 0:
            price_note = (
                f"Partial price coverage ({price_count}/{len(by_ticker)} positions priced) — "
                "P&L and weights computed only for positions with known prices. "
            )
        else:
            price_note = (
                "No price data available — reverting to invested-capital allocation only. "
            )
    else:
        price_note = ""

    data_note = (
        f"{price_note}"
        f"Allocation % is based on cost_basis × quantity (invested capital). "
        f"When prices are available, position values, P&L, and weights reflect market prices. "
        f"Missing price data is treated as unknown (null), never as zero."
    )

    return NormalizedPortfolio(
        total_positions=len(by_ticker),
        total_invested=round(total_invested, 2) if total_invested > 0 else None,
        allocation_pct=allocation_pct,
        largest_position_ticker=largest_ticker,
        largest_position_pct=largest_pct,
        currency=currency,
        positions=positions_detail,
        total_market_value=round(total_market_value, 2) if total_market_value else None,
        prices_as_of=prices_as_of,
        data_note=data_note,
    )

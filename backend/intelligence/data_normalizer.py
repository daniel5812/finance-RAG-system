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

from intelligence.schemas import NormalizedPortfolio


def normalize_portfolio(rows: list[dict]) -> NormalizedPortfolio:
    """
    Compute canonical financial metrics from raw portfolio_positions rows.

    Field semantics:
      total_invested  = SUM(quantity × cost_basis) across all positions
      allocation_pct  = each ticker's invested capital as % of total_invested
      largest_*       = the ticker with the highest allocated capital

    Returns a minimal NormalizedPortfolio if rows is empty.
    Never raises.
    """
    if not rows:
        return NormalizedPortfolio(
            total_positions=0,
            data_note="No portfolio positions found. Cannot compute allocation.",
        )

    try:
        return _compute(rows)
    except Exception:
        return NormalizedPortfolio(
            total_positions=len(rows),
            data_note="Normalization error — allocation percentages unavailable.",
        )


def _compute(rows: list[dict]) -> NormalizedPortfolio:
    # ── Aggregate by ticker ───────────────────────────────────────────────────
    # Each row: one position entry; same ticker may appear in multiple rows (e.g. date snapshots).
    # We use the most recent value per ticker (rows should already be sorted DESC by date
    # from the PortfolioFitAgent query). We take the last observed quantity/cost_basis per ticker.
    # De-duplicate by ticker: if multiple rows exist, use the first occurrence (newest).
    seen: set[str] = set()
    by_ticker: dict[str, dict[str, float]] = {}

    currency = "USD"
    for row in rows:
        ticker = row["symbol"].upper()
        if ticker in seen:
            continue  # skip older rows for same ticker
        seen.add(ticker)

        qty = float(row.get("quantity") or 0.0)
        cb  = float(row.get("cost_basis") or 0.0)   # avg price per unit
        total_position_value = qty * cb              # total invested in this position

        by_ticker[ticker] = {
            "quantity":      qty,
            "cost_basis":    cb,       # per-unit
            "total_invested": total_position_value,
        }
        if row.get("currency"):
            currency = str(row["currency"])

    # ── Total invested capital ────────────────────────────────────────────────
    total_invested = sum(v["total_invested"] for v in by_ticker.values())

    # ── Allocation percentages (by invested capital, not count) ──────────────
    allocation_pct: dict[str, float] = {}
    if total_invested > 0:
        for ticker, v in by_ticker.items():
            allocation_pct[ticker] = round(v["total_invested"] / total_invested * 100, 2)

    # Sort descending by allocation
    allocation_pct = dict(
        sorted(allocation_pct.items(), key=lambda x: x[1], reverse=True)
    )

    largest_ticker = next(iter(allocation_pct), None)
    largest_pct    = allocation_pct[largest_ticker] if largest_ticker else None

    return NormalizedPortfolio(
        total_positions=len(by_ticker),
        total_invested=round(total_invested, 2) if total_invested > 0 else None,
        allocation_pct=allocation_pct,
        largest_position_ticker=largest_ticker,
        largest_position_pct=largest_pct,
        currency=currency,
        data_note=(
            "Allocation % is computed from quantity × cost_basis_per_unit (= invested capital). "
            "This is entry cost, NOT current market value. "
            "Returns, P&L, and unrealised gains are NOT available from this data."
        ),
    )

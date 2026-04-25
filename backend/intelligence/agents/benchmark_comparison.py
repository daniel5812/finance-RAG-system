"""
intelligence/agents/benchmark_comparison.py — BenchmarkComparisonAgent

Responsibility:
  Compare the user's portfolio against SPY and QQQ using deterministic arithmetic.
  Produces a BenchmarkComparison result injected into the IntelligenceReport.

Inputs:
  - normalized_portfolio: NormalizedPortfolio — pre-computed allocation + position details
  - portfolio_hhi: float | None — from PortfolioGapAnalysis.concentration_score (not recomputed here)
  - spy_holdings: list[dict] — rows from etf_holdings for SPY ({holding_symbol, weight})
  - qqq_holdings: list[dict] — rows from etf_holdings for QQQ ({holding_symbol, weight})

Output:
  - BenchmarkComparison

Design rules:
  - Fully deterministic — zero LLM calls, zero DB calls
  - Pure synchronous function
  - etf_holdings.sector is NEVER read — always use _SECTOR_MAP for sector lookup
  - SPY sector weights always come from _SPY_SECTOR_WEIGHTS (static, authoritative)
  - QQQ sector weights computed from holdings + _SECTOR_MAP (partial coverage expected)
  - HHI suppressed when holdings coverage < _MIN_COVERAGE_FOR_HHI (80%)
  - Relative allocation falls back to allocation_pct when market prices unavailable
  - Always returns a valid BenchmarkComparison — never raises
"""

from __future__ import annotations

from core.logger import get_logger
from intelligence.schemas import BenchmarkComparison, BenchmarkSnapshot, NormalizedPortfolio
from intelligence.static_data import _SECTOR_MAP, _SPY_SECTOR_WEIGHTS

logger = get_logger(__name__)

_MIN_COVERAGE_FOR_HHI = 80.0       # suppress benchmark HHI below this % coverage
_CONCENTRATION_THRESHOLD = 0.05    # HHI delta above/below this → not "comparable"
_RELATIVE_WEIGHT_THRESHOLD = 2.0   # pp difference to appear in over/underweight lists
_MAX_RELATIVE_ENTRIES = 5          # cap overweight/underweight list length
_QQQ_MIN_SECTOR_COVERAGE = 50.0   # warn when QQQ sector mapping covers less than this %


class BenchmarkComparisonAgent:
    """
    Deterministic benchmark comparison — no DB, no async, no LLM.
    Called from the orchestrator after portfolio data and benchmark holdings are available.
    """

    @staticmethod
    def run(
        normalized_portfolio: NormalizedPortfolio | None,
        portfolio_hhi: float | None,
        spy_holdings: list[dict],
        qqq_holdings: list[dict],
    ) -> BenchmarkComparison:
        """
        Build BenchmarkComparison from pre-fetched data.
        Returns a valid (possibly empty) BenchmarkComparison on any error.
        """
        if not normalized_portfolio:
            return BenchmarkComparison(
                data_note="Benchmark comparison unavailable — no portfolio data.",
            )

        try:
            return _compare(normalized_portfolio, portfolio_hhi, spy_holdings, qqq_holdings)
        except Exception as exc:
            logger.warning(
                f'{{"event": "benchmark_comparison_agent", "status": "error", "error": "{exc}"}}'
            )
            return BenchmarkComparison(
                portfolio_hhi=portfolio_hhi,
                data_note="Benchmark comparison unavailable due to internal error.",
            )


# ─────────────────────────────────────────────────────────────
# Core comparison logic
# ─────────────────────────────────────────────────────────────

def _compare(
    norm: NormalizedPortfolio,
    portfolio_hhi: float | None,
    spy_holdings: list[dict],
    qqq_holdings: list[dict],
) -> BenchmarkComparison:

    # ── Determine portfolio weight source ─────────────────────────────────────
    portfolio_weights, weight_basis = _resolve_portfolio_weights(norm)

    # ── Build benchmark snapshots ─────────────────────────────────────────────
    spy_snapshot = _build_spy_snapshot(spy_holdings)
    qqq_snapshot = _build_qqq_snapshot(qqq_holdings)

    # ── Concentration comparisons (only when both HHIs are present) ───────────
    concentration_vs_spy = _label_concentration(portfolio_hhi, spy_snapshot.hhi)
    concentration_vs_qqq = _label_concentration(portfolio_hhi, qqq_snapshot.hhi)

    # ── Relative allocation vs SPY ────────────────────────────────────────────
    overweight, underweight = _relative_allocation(portfolio_weights, spy_holdings)

    # ── Portfolio overlap ─────────────────────────────────────────────────────
    overlap_spy = _compute_overlap(portfolio_weights, spy_holdings)
    overlap_qqq = _compute_overlap(portfolio_weights, qqq_holdings)

    # ── Top-level data_note ───────────────────────────────────────────────────
    data_note = _build_data_note(spy_snapshot, qqq_snapshot, weight_basis)

    logger.info(
        f'{{"event": "benchmark_comparison_agent", "status": "ok", '
        f'"portfolio_hhi": {portfolio_hhi}, '
        f'"concentration_vs_spy": "{concentration_vs_spy}", '
        f'"concentration_vs_qqq": "{concentration_vs_qqq}", '
        f'"weight_basis": "{weight_basis}", '
        f'"overlap_spy": {overlap_spy}, "overlap_qqq": {overlap_qqq}}}'
    )

    return BenchmarkComparison(
        portfolio_hhi=portfolio_hhi,
        weight_basis=weight_basis,
        benchmarks=[spy_snapshot, qqq_snapshot],
        concentration_vs_spy=concentration_vs_spy,
        concentration_vs_qqq=concentration_vs_qqq,
        overweight_vs_spy=overweight,
        underweight_vs_spy=underweight,
        portfolio_overlap_spy_pct=overlap_spy,
        portfolio_overlap_qqq_pct=overlap_qqq,
        data_note=data_note,
    )


# ─────────────────────────────────────────────────────────────
# Portfolio weight resolution
# ─────────────────────────────────────────────────────────────

def _resolve_portfolio_weights(norm: NormalizedPortfolio) -> tuple[dict[str, float], str]:
    """
    Determine which portfolio weight source to use.
    Returns (weights dict, basis label).

    Priority:
      1. market_value: all positions have PositionDetail.portfolio_weight
      2. mixed: some positions have portfolio_weight, rest use allocation_pct
      3. cost_basis: no portfolio_weight available → use allocation_pct
    """
    if not norm.positions:
        return norm.allocation_pct, "cost_basis"

    market_weights: dict[str, float] = {
        t: d.portfolio_weight
        for t, d in norm.positions.items()
        if d.portfolio_weight is not None
    }

    total_tickers = norm.total_positions

    if len(market_weights) == total_tickers and total_tickers > 0:
        return market_weights, "market_value"

    if market_weights:
        # Partial coverage: use market value for priced positions, cost_basis for rest
        merged = dict(norm.allocation_pct)
        merged.update(market_weights)
        return merged, "mixed"

    return norm.allocation_pct, "cost_basis"


# ─────────────────────────────────────────────────────────────
# Benchmark snapshot builders
# ─────────────────────────────────────────────────────────────

def _build_spy_snapshot(spy_holdings: list[dict]) -> BenchmarkSnapshot:
    """
    Build SPY snapshot.
    - HHI computed from holdings (gated on coverage).
    - top_sectors always from _SPY_SECTOR_WEIGHTS (static, authoritative).
    """
    if not spy_holdings:
        return BenchmarkSnapshot(
            symbol="SPY",
            hhi=None,
            holding_count=0,
            coverage_pct=0.0,
            top_sectors=dict(_SPY_SECTOR_WEIGHTS),
            data_note="SPY holdings not yet ingested — HHI unavailable.",
        )

    coverage_pct = sum(h["weight"] for h in spy_holdings)
    holding_count = len(spy_holdings)

    if coverage_pct >= _MIN_COVERAGE_FOR_HHI:
        hhi = round(sum((h["weight"] / 100) ** 2 for h in spy_holdings), 5)
        data_note = None
    else:
        hhi = None
        data_note = (
            f"SPY HHI suppressed — holdings coverage {coverage_pct:.0f}% "
            f"(need ≥{_MIN_COVERAGE_FOR_HHI:.0f}%)."
        )

    return BenchmarkSnapshot(
        symbol="SPY",
        hhi=hhi,
        holding_count=holding_count,
        coverage_pct=round(coverage_pct, 1),
        top_sectors=dict(_SPY_SECTOR_WEIGHTS),
        data_note=data_note,
    )


def _build_qqq_snapshot(qqq_holdings: list[dict]) -> BenchmarkSnapshot:
    """
    Build QQQ snapshot.
    - HHI computed from holdings (gated on coverage).
    - top_sectors computed from holdings + _SECTOR_MAP (partial coverage expected).
    - etf_holdings.sector column is NEVER used — sector derived from _SECTOR_MAP only.
    """
    if not qqq_holdings:
        return BenchmarkSnapshot(
            symbol="QQQ",
            hhi=None,
            holding_count=0,
            coverage_pct=0.0,
            top_sectors={},
            data_note="QQQ holdings not yet ingested — HHI and sector data unavailable.",
        )

    coverage_pct = sum(h["weight"] for h in qqq_holdings)
    holding_count = len(qqq_holdings)

    if coverage_pct >= _MIN_COVERAGE_FOR_HHI:
        hhi = round(sum((h["weight"] / 100) ** 2 for h in qqq_holdings), 5)
        hhi_note = None
    else:
        hhi = None
        hhi_note = (
            f"QQQ HHI suppressed — holdings coverage {coverage_pct:.0f}% "
            f"(need ≥{_MIN_COVERAGE_FOR_HHI:.0f}%)."
        )

    # Compute QQQ sector weights via _SECTOR_MAP (never use etf_holdings.sector)
    qqq_sector_pct: dict[str, float] = {}
    mapped_weight = 0.0
    for h in qqq_holdings:
        sector = _SECTOR_MAP.get(h["holding_symbol"].upper())
        if sector:
            qqq_sector_pct[sector] = qqq_sector_pct.get(sector, 0.0) + h["weight"]
            mapped_weight += h["weight"]

    # Sort by weight descending
    qqq_sector_pct = dict(
        sorted(qqq_sector_pct.items(), key=lambda x: x[1], reverse=True)
    )

    notes: list[str] = []
    if hhi_note:
        notes.append(hhi_note)
    if mapped_weight < _QQQ_MIN_SECTOR_COVERAGE:
        notes.append(
            f"QQQ sector map partial — {mapped_weight:.0f}% of holdings "
            f"mapped via sector dict."
        )

    return BenchmarkSnapshot(
        symbol="QQQ",
        hhi=hhi,
        holding_count=holding_count,
        coverage_pct=round(coverage_pct, 1),
        top_sectors=qqq_sector_pct,
        data_note=" ".join(notes) if notes else None,
    )


# ─────────────────────────────────────────────────────────────
# Concentration label
# ─────────────────────────────────────────────────────────────

def _label_concentration(
    portfolio_hhi: float | None,
    benchmark_hhi: float | None,
) -> str | None:
    """Return concentration label only when both HHIs are present."""
    if portfolio_hhi is None or benchmark_hhi is None:
        return None
    delta = portfolio_hhi - benchmark_hhi
    if delta > _CONCENTRATION_THRESHOLD:
        return "more_concentrated"
    if delta < -_CONCENTRATION_THRESHOLD:
        return "less_concentrated"
    return "comparable"


# ─────────────────────────────────────────────────────────────
# Relative allocation vs SPY
# ─────────────────────────────────────────────────────────────

def _relative_allocation(
    portfolio_weights: dict[str, float],
    spy_holdings: list[dict],
) -> tuple[list[str], list[str]]:
    """
    Compare per-ticker portfolio weight to SPY weight.
    Returns (overweight_list, underweight_list), capped at _MAX_RELATIVE_ENTRIES each.
    """
    if not portfolio_weights or not spy_holdings:
        return [], []

    spy_weight_map: dict[str, float] = {
        h["holding_symbol"].upper(): h["weight"]
        for h in spy_holdings
    }

    deltas: list[tuple[str, float, float, float]] = []  # (ticker, port_w, spy_w, delta)
    for ticker, port_w in portfolio_weights.items():
        spy_w = spy_weight_map.get(ticker.upper(), 0.0)
        delta = port_w - spy_w
        if abs(delta) >= _RELATIVE_WEIGHT_THRESHOLD:
            deltas.append((ticker, port_w, spy_w, delta))

    # Sort by absolute delta descending
    deltas.sort(key=lambda x: abs(x[3]), reverse=True)

    overweight: list[str] = []
    underweight: list[str] = []

    for ticker, port_w, spy_w, delta in deltas:
        sign = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
        entry = f"{ticker}: port={port_w:.1f}%  spy={spy_w:.1f}%  ({sign}pp)"
        if delta > 0:
            overweight.append(entry)
        else:
            underweight.append(entry)

    return overweight[:_MAX_RELATIVE_ENTRIES], underweight[:_MAX_RELATIVE_ENTRIES]


# ─────────────────────────────────────────────────────────────
# Portfolio overlap
# ─────────────────────────────────────────────────────────────

def _compute_overlap(
    portfolio_weights: dict[str, float],
    benchmark_holdings: list[dict],
) -> float | None:
    """
    Compute the % of portfolio (by weight) whose tickers also appear in the benchmark.
    Returns None when inputs are insufficient.
    """
    if not portfolio_weights or not benchmark_holdings:
        return None

    benchmark_symbols = {h["holding_symbol"].upper() for h in benchmark_holdings}
    overlap_weight = sum(
        w for t, w in portfolio_weights.items()
        if t.upper() in benchmark_symbols
    )
    total_weight = sum(portfolio_weights.values())
    if total_weight <= 0:
        return None
    return round((overlap_weight / total_weight) * 100, 1)


# ─────────────────────────────────────────────────────────────
# Data note builder
# ─────────────────────────────────────────────────────────────

def _build_data_note(
    spy_snapshot: BenchmarkSnapshot,
    qqq_snapshot: BenchmarkSnapshot,
    weight_basis: str,
) -> str | None:
    notes: list[str] = []
    if weight_basis == "cost_basis":
        notes.append(
            "Portfolio weights are cost-basis based (market prices unavailable); "
            "comparison may differ from market-value weighted benchmarks."
        )
    elif weight_basis == "mixed":
        notes.append(
            "Portfolio weights are mixed: market-value for priced positions, "
            "cost-basis for unpriced positions."
        )
    if spy_snapshot.data_note:
        notes.append(spy_snapshot.data_note)
    if qqq_snapshot.data_note:
        notes.append(qqq_snapshot.data_note)
    return " ".join(notes) if notes else None

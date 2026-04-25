"""
intelligence/agents/portfolio_gap_analysis.py — PortfolioGapAnalysisAgent

Responsibility:
  When no specific tickers are mentioned in the query, analyze the user's portfolio
  at a structural level:
    - Map each holding to a sector using the static sector dictionary
    - Compare sector distribution against SPY benchmark weights
    - Identify missing asset classes (bonds, international, real estate, etc.)
    - Compute HHI-based concentration score
    - Generate actionable diversification directions

Inputs:
  - normalized_portfolio: NormalizedPortfolio — pre-computed allocation percentages
  - portfolio_tickers: list[str] — ticker symbols in the portfolio

Outputs:
  - PortfolioGapAnalysis

Design:
  - Fully deterministic — zero LLM calls
  - Uses same sector map as AssetProfilerAgent (source of truth)
  - SPY sector weights are static reference benchmarks (updated periodically)
  - Graceful degradation when sector data unavailable
  - Non-blocking: errors return a partial analysis
"""

from __future__ import annotations

from core.logger import get_logger
from intelligence.schemas import NormalizedPortfolio, PortfolioGapAnalysis, SectorWeight
from intelligence.static_data import _ASSET_CLASSES, _SECTOR_MAP, _SPY_SECTOR_WEIGHTS

logger = get_logger(__name__)

# Thresholds for over/underweight classification
_OVERWEIGHT_THRESHOLD  =  10.0   # > 10pp above benchmark → overweight
_UNDERWEIGHT_THRESHOLD = -10.0   # > 10pp below benchmark → underweight


class PortfolioGapAnalysisAgent:
    """
    Analyzes portfolio structure relative to SPY benchmark.
    Identifies sector imbalances and missing asset classes.
    Fully deterministic — no LLM, no DB queries.
    """

    @staticmethod
    def run(
        normalized_portfolio: NormalizedPortfolio | None,
        portfolio_tickers: list[str],
    ) -> PortfolioGapAnalysis:
        """
        Build PortfolioGapAnalysis from pre-computed portfolio normalization.
        Returns a partial analysis with warnings if data is insufficient.
        """
        if not normalized_portfolio or not portfolio_tickers:
            return PortfolioGapAnalysis(
                diversification_gaps=["No portfolio data available for gap analysis."],
                suggested_directions=["Upload your portfolio to receive a personalized analysis."],
                data_coverage="none",
            )

        try:
            return _analyse(normalized_portfolio, portfolio_tickers)
        except Exception as exc:
            logger.warning(f'{{"event": "portfolio_gap_agent", "status": "error", "error": "{exc}"}}')
            return PortfolioGapAnalysis(
                diversification_gaps=["Gap analysis unavailable due to data error."],
                data_coverage="none",
            )


# ─────────────────────────────────────────────────────────────
# Core analysis
# ─────────────────────────────────────────────────────────────

def _analyse(
    norm: NormalizedPortfolio,
    portfolio_tickers: list[str],
) -> PortfolioGapAnalysis:

    allocation = norm.allocation_pct  # ticker → % of portfolio

    # ── Map tickers to sectors ────────────────────────────────────────────────
    sector_pct: dict[str, float] = {}
    unmapped_pct = 0.0
    for ticker, pct in allocation.items():
        sector = _SECTOR_MAP.get(ticker.upper())
        if sector:
            sector_pct[sector] = sector_pct.get(sector, 0.0) + pct
        else:
            unmapped_pct += pct

    mapped_coverage = (100.0 - unmapped_pct) / 100.0 if allocation else 0.0

    # ── Compare to SPY benchmark ──────────────────────────────────────────────
    sector_weights: list[SectorWeight] = []
    overweight: list[str] = []
    underweight: list[str] = []

    # All SPY sectors (include ones the portfolio may have none of)
    all_sectors = set(_SPY_SECTOR_WEIGHTS.keys()) | set(sector_pct.keys())
    for sector in sorted(all_sectors):
        port_pct = sector_pct.get(sector, 0.0)
        bench_pct = _SPY_SECTOR_WEIGHTS.get(sector, 0.0)
        gap = port_pct - bench_pct
        sw = SectorWeight(
            sector=sector,
            portfolio_pct=round(port_pct, 2),
            benchmark_pct=bench_pct,
            gap_pct=round(gap, 2),
        )
        sector_weights.append(sw)
        if gap > _OVERWEIGHT_THRESHOLD:
            overweight.append(f"{sector} (+{gap:.0f}pp vs SPY)")
        elif gap < _UNDERWEIGHT_THRESHOLD:
            underweight.append(f"{sector} ({gap:.0f}pp vs SPY)")

    # ── Identify missing asset classes ───────────────────────────────────────
    portfolio_sectors = set(sector_pct.keys())
    missing_classes: list[str] = []
    class_coverage: dict[str, float] = {}

    for asset_class, qualifying_sectors in _ASSET_CLASSES.items():
        covered_pct = sum(
            sector_pct.get(s, 0.0) for s in qualifying_sectors
        )
        class_coverage[asset_class] = covered_pct
        if covered_pct < 2.0:  # < 2% of portfolio → effectively missing
            missing_classes.append(asset_class)

    # ── HHI concentration score ───────────────────────────────────────────────
    if allocation:
        hhi = sum((pct / 100) ** 2 for pct in allocation.values())
    else:
        hhi = 0.0

    # ── Generate gap descriptions ─────────────────────────────────────────────
    gaps: list[str] = []
    if overweight:
        gaps.append(f"Significantly overweight vs SPY: {', '.join(overweight[:3])}")
    if underweight:
        gaps.append(f"Significantly underweight vs SPY: {', '.join(underweight[:3])}")
    if missing_classes:
        gaps.append(f"Missing asset classes: {', '.join(missing_classes)}")
    if hhi > 0.35:
        gaps.append(f"High concentration risk (HHI={hhi:.2f}) — consider spreading positions")
    if unmapped_pct > 20:
        gaps.append(f"{unmapped_pct:.0f}% of portfolio could not be sector-mapped")
    if not gaps:
        gaps.append("Portfolio appears reasonably diversified relative to SPY benchmark")

    # ── Generate actionable directions ────────────────────────────────────────
    directions: list[str] = []
    if "Fixed Income" in missing_classes:
        directions.append("Consider adding bond exposure (e.g. AGG, BND) to reduce equity correlation")
    if "International Equities" in missing_classes:
        directions.append("Add international diversification (e.g. VEA, VWO) to reduce US-only concentration")
    if "Real Estate" in missing_classes:
        directions.append("Real estate (REIT ETF like VNQ) can provide income and inflation hedge")
    if "Commodities" in missing_classes:
        directions.append("Commodities (GLD) can act as inflation hedge and portfolio stabilizer")

    sector_weights_sorted = sorted(sector_weights, key=lambda s: s.portfolio_pct, reverse=True)
    for sw in sector_weights_sorted[:1]:
        if sw.portfolio_pct > 40:
            directions.append(
                f"Heavy {sw.sector} concentration ({sw.portfolio_pct:.0f}%) — "
                f"consider rotating into underweight sectors"
            )

    if not directions:
        directions.append("Portfolio structure is broadly balanced — review periodically against market conditions")

    # ── Coverage quality ─────────────────────────────────────────────────────
    if mapped_coverage >= 0.80:
        data_coverage = "full"
    elif mapped_coverage >= 0.50:
        data_coverage = "partial"
    else:
        data_coverage = "minimal"

    logger.info(
        f'{{"event": "portfolio_gap_agent", "status": "ok", '
        f'"hhi": {hhi:.3f}, "missing_classes": {missing_classes}, '
        f'"overweight": {len(overweight)}, "underweight": {len(underweight)}}}'
    )

    return PortfolioGapAnalysis(
        sector_weights=sector_weights_sorted,
        missing_asset_classes=missing_classes,
        overweight_sectors=overweight,
        underweight_sectors=underweight,
        concentration_score=round(hhi, 3),
        diversification_gaps=gaps,
        suggested_directions=directions,
        data_coverage=data_coverage,
    )

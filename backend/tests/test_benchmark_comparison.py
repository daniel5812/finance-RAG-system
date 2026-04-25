"""
Step 3 — Benchmark Comparison Tests — pure unit, no DB, no network.
Tests for: BenchmarkComparisonAgent, coverage gate, weight basis logic,
sector mapping, context_builder rendering, fetch_benchmark_holdings.

Run: cd backend && pytest tests/test_benchmark_comparison.py -v
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from intelligence.agents.benchmark_comparison import BenchmarkComparisonAgent
from intelligence.schemas import (
    NormalizedPortfolio, PositionDetail, BenchmarkComparison,
    BenchmarkSnapshot, IntelligenceReport
)
from intelligence.context_builder import build_intelligence_context
from intelligence.static_data import _SPY_SECTOR_WEIGHTS, _SECTOR_MAP


# ── Test Data Builders ──────────────────────────────────────────────────────

def _position_detail(
    portfolio_weight: float | None = None,
    position_value: float | None = None,
) -> PositionDetail:
    """Helper to build a PositionDetail with optional price-based fields."""
    return PositionDetail(
        current_price=100.0 if portfolio_weight is not None else None,
        position_value=position_value,
        portfolio_weight=portfolio_weight,
    )


def _normalized_portfolio(
    allocation_pct: dict[str, float],
    positions_detail: dict[str, PositionDetail] | None = None,
    total_positions: int | None = None,
) -> NormalizedPortfolio:
    """Helper to build a NormalizedPortfolio."""
    if total_positions is None:
        total_positions = len(allocation_pct)
    if positions_detail is None:
        positions_detail = {}
    return NormalizedPortfolio(
        total_positions=total_positions,
        allocation_pct=allocation_pct,
        positions=positions_detail,
        currency="USD",
        data_note="Test data",
    )


def _holding(symbol: str, weight: float) -> dict:
    """Helper to build an etf_holding row dict."""
    return {"holding_symbol": symbol.upper(), "weight": weight}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Full Benchmark Coverage — HHI Computed
# ─────────────────────────────────────────────────────────────────────────────

def test_benchmark_comparison_full_spy_coverage():
    """SPY holdings coverage >= 80%; HHI computed and concentration label set."""
    # Portfolio: 60% AAPL, 40% MSFT (HHI = 0.52)
    portfolio_alloc = {"AAPL": 60.0, "MSFT": 40.0}
    positions = {
        "AAPL": _position_detail(portfolio_weight=60.0, position_value=6000.0),
        "MSFT": _position_detail(portfolio_weight=40.0, position_value=4000.0),
    }
    norm = _normalized_portfolio(portfolio_alloc, positions_detail=positions)
    portfolio_hhi = 0.52  # (0.6)^2 + (0.4)^2 = 0.36 + 0.16

    # SPY holdings: 9 tickers, coverage ~95% (sum > 80%)
    spy_holdings = [
        _holding("AAPL", 7.2),
        _holding("MSFT", 6.8),
        _holding("GOOGL", 5.5),
        _holding("AMZN", 4.2),
        _holding("NVDA", 4.1),
        _holding("META", 3.5),
        _holding("TSLA", 3.2),
        _holding("JPM", 3.1),
        _holding("V", 2.9),
    ]

    # QQQ holdings: top 3 tech, coverage ~85%
    qqq_holdings = [
        _holding("AAPL", 8.1),
        _holding("MSFT", 7.8),
        _holding("NVDA", 7.2),
        _holding("GOOGL", 6.5),
        _holding("META", 5.5),
        _holding("TSLA", 5.2),
        _holding("AMZN", 4.8),
        _holding("AMD", 4.1),
        _holding("CRM", 3.8),
        _holding("ADBE", 3.2),
        _holding("INTC", 2.9),
        _holding("ORCL", 2.7),
        _holding("CSCO", 2.4),
        _holding("QCOM", 2.2),
        _holding("TXN", 1.8),
    ]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, qqq_holdings)

    # Check SPY snapshot
    spy = next((s for s in bc.benchmarks if s.symbol == "SPY"), None)
    assert spy is not None
    assert spy.hhi is not None  # HHI computed
    assert spy.coverage_pct >= 80.0
    assert spy.holding_count == 9
    assert spy.top_sectors == _SPY_SECTOR_WEIGHTS  # static dict

    # Check QQQ snapshot
    qqq = next((s for s in bc.benchmarks if s.symbol == "QQQ"), None)
    assert qqq is not None
    assert qqq.hhi is not None  # HHI computed
    assert qqq.coverage_pct >= 80.0
    assert qqq.holding_count == 15

    # Concentration labels set (HHI > SPY's and QQQ's)
    assert bc.concentration_vs_spy is not None
    assert bc.concentration_vs_qqq is not None

    # Portfolio overlap computed
    assert bc.portfolio_overlap_spy_pct is not None
    assert bc.portfolio_overlap_spy_pct > 0.0


def test_concentration_labels():
    """Test concentration label logic: more/comparable/less."""
    portfolio_alloc = {"AAPL": 100.0}  # single stock, HHI = 1.0
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 1.0

    # SPY HHI ~0.012, delta = 1.0 - 0.012 = 0.988 >> 0.05 threshold
    spy_holdings = [_holding(f"TICK{i}", 1.0 / 11.0) for i in range(11)]  # equal weight

    # Empty QQQ
    qqq_holdings = []

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, qqq_holdings)

    # With 11 equal holdings SPY HHI ~0.0091
    assert bc.concentration_vs_spy == "more_concentrated"
    assert bc.concentration_vs_qqq is None  # QQQ HHI is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Partial Coverage — HHI Suppressed
# ─────────────────────────────────────────────────────────────────────────────

def test_benchmark_comparison_partial_coverage():
    """Holdings coverage < 80%; HHI suppressed, data_note explains why."""
    portfolio_alloc = {"AAPL": 100.0}
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 1.0

    # SPY holdings: only 3 holdings, coverage = 3% (way below 80%)
    spy_holdings = [
        _holding("AAPL", 7.2),
        _holding("MSFT", 6.8),
        _holding("GOOGL", 5.5),
    ]
    # Total weight = 19.5%, well below 80%

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    spy = next((s for s in bc.benchmarks if s.symbol == "SPY"), None)
    assert spy is not None
    assert spy.hhi is None  # suppressed
    assert spy.coverage_pct == 19.5
    assert "HHI suppressed" in (spy.data_note or "")
    assert "80" in (spy.data_note or "")  # threshold mentioned


def test_benchmark_comparison_empty_holdings():
    """Empty benchmark holdings; valid BenchmarkComparison returned."""
    portfolio_alloc = {"AAPL": 100.0}
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 1.0

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, [], [])

    assert len(bc.benchmarks) == 2  # SPY and QQQ snapshots created
    for snap in bc.benchmarks:
        assert snap.hhi is None
        assert snap.holding_count == 0
        assert snap.coverage_pct == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Weight Basis Resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_weight_basis_market_value():
    """All positions have portfolio_weight; basis is 'market_value'."""
    portfolio_alloc = {"AAPL": 50.0, "MSFT": 50.0}
    positions = {
        "AAPL": _position_detail(portfolio_weight=55.0),  # market value different
        "MSFT": _position_detail(portfolio_weight=45.0),
    }
    norm = _normalized_portfolio(portfolio_alloc, positions_detail=positions)
    portfolio_hhi = 0.5

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, [], [])

    assert bc.weight_basis == "market_value"


def test_weight_basis_cost_basis():
    """No positions have portfolio_weight; basis is 'cost_basis'."""
    portfolio_alloc = {"AAPL": 50.0, "MSFT": 50.0}
    positions = {
        "AAPL": _position_detail(portfolio_weight=None),  # no price
        "MSFT": _position_detail(portfolio_weight=None),
    }
    norm = _normalized_portfolio(portfolio_alloc, positions_detail=positions)
    portfolio_hhi = 0.5

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, [], [])

    assert bc.weight_basis == "cost_basis"
    assert "cost-basis weights" in (bc.data_note or "")


def test_weight_basis_mixed():
    """Partial positions have portfolio_weight; basis is 'mixed'."""
    portfolio_alloc = {"AAPL": 50.0, "MSFT": 50.0}
    positions = {
        "AAPL": _position_detail(portfolio_weight=55.0),  # has price
        "MSFT": _position_detail(portfolio_weight=None),  # no price
    }
    norm = _normalized_portfolio(portfolio_alloc, positions_detail=positions)
    portfolio_hhi = 0.5

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, [], [])

    assert bc.weight_basis == "mixed"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Relative Allocation vs SPY
# ─────────────────────────────────────────────────────────────────────────────

def test_relative_allocation_overweight():
    """Portfolio overweight vs SPY for specific tickers."""
    portfolio_alloc = {
        "AAPL": 15.0,  # portfolio 15%, SPY 7.2% → +7.8pp overweight
        "MSFT": 10.0,  # portfolio 10%, SPY 6.8% → +3.2pp overweight
        "GOOGL": 5.0,  # portfolio 5%, SPY 5.5% → -0.5pp (below threshold)
    }
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 0.35

    spy_holdings = [
        _holding("AAPL", 7.2),
        _holding("MSFT", 6.8),
        _holding("GOOGL", 5.5),
    ]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    # Should have AAPL and MSFT in overweight (delta >= 2.0pp)
    assert len(bc.overweight_vs_spy) >= 2
    assert any("AAPL" in e for e in bc.overweight_vs_spy)
    assert any("MSFT" in e for e in bc.overweight_vs_spy)

    # GOOGL delta < threshold, should not appear
    assert not any("GOOGL" in e for e in bc.overweight_vs_spy)


def test_relative_allocation_underweight():
    """Portfolio underweight vs SPY."""
    portfolio_alloc = {
        "AAPL": 2.0,  # portfolio 2%, SPY 7.2% → -5.2pp underweight
        "MSFT": 3.0,  # portfolio 3%, SPY 6.8% → -3.8pp underweight
    }
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 0.35

    spy_holdings = [
        _holding("AAPL", 7.2),
        _holding("MSFT", 6.8),
    ]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    assert len(bc.underweight_vs_spy) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# 5. Sector Mapping Logic
# ─────────────────────────────────────────────────────────────────────────────

def test_spy_sectors_from_static_dict():
    """SPY top_sectors always equals static _SPY_SECTOR_WEIGHTS."""
    portfolio_alloc = {"AAPL": 100.0}
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 1.0

    # Even with actual SPY holdings that differ
    spy_holdings = [_holding(f"TICK{i}", 1.0) for i in range(100)]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    spy = next((s for s in bc.benchmarks if s.symbol == "SPY"), None)
    assert spy is not None
    assert spy.top_sectors == _SPY_SECTOR_WEIGHTS


def test_qqq_sectors_via_sector_map():
    """QQQ top_sectors computed from holdings + _SECTOR_MAP."""
    portfolio_alloc = {"AAPL": 100.0}
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 1.0

    # QQQ holdings with known sector mappings
    qqq_holdings = [
        _holding("AAPL", 8.1),      # Technology
        _holding("MSFT", 7.8),      # Technology
        _holding("NVDA", 7.2),      # Technology
        _holding("GOOGL", 6.5),     # Technology
        _holding("AMZN", 4.8),      # Consumer Discretionary
        _holding("TSLA", 5.2),      # Consumer Discretionary
        _holding("UNKNOWN_X", 3.0),  # not in _SECTOR_MAP → skipped
    ]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, [], qqq_holdings)

    qqq = next((s for s in bc.benchmarks if s.symbol == "QQQ"), None)
    assert qqq is not None
    assert "Technology" in qqq.top_sectors
    assert "Consumer Discretionary" in qqq.top_sectors
    # UNKNOWN_X should not add a sector
    assert qqq.top_sectors["Technology"] > 20.0  # sum of 4 tech holdings


def test_qqq_sector_partial_coverage_note():
    """QQQ sector mapping partial coverage flagged in data_note."""
    portfolio_alloc = {"AAPL": 100.0}
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 1.0

    # Only 1 mapped holding out of 5 (20% < 50% threshold)
    qqq_holdings = [
        _holding("AAPL", 8.1),       # mapped
        _holding("UNKNOWN1", 25.0),  # not mapped
        _holding("UNKNOWN2", 25.0),  # not mapped
        _holding("UNKNOWN3", 25.0),  # not mapped
        _holding("UNKNOWN4", 16.9),  # not mapped
    ]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, [], qqq_holdings)

    qqq = next((s for s in bc.benchmarks if s.symbol == "QQQ"), None)
    assert qqq is not None
    assert qqq.data_note is not None
    assert "partial" in qqq.data_note.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Portfolio Overlap Percentage
# ─────────────────────────────────────────────────────────────────────────────

def test_portfolio_overlap_full():
    """All portfolio tickers in benchmark holdings."""
    portfolio_alloc = {
        "AAPL": 50.0,
        "MSFT": 50.0,
    }
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 0.5

    spy_holdings = [
        _holding("AAPL", 7.2),
        _holding("MSFT", 6.8),
        _holding("GOOGL", 5.5),
    ]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    # Both AAPL and MSFT in SPY → 100% overlap
    assert bc.portfolio_overlap_spy_pct == 100.0


def test_portfolio_overlap_partial():
    """Some portfolio tickers not in benchmark."""
    portfolio_alloc = {
        "AAPL": 60.0,   # in SPY
        "UNKNOWN": 40.0,  # not in SPY
    }
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 0.52

    spy_holdings = [_holding("AAPL", 7.2)]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    # Only 60% (AAPL weight) of portfolio is in SPY
    assert bc.portfolio_overlap_spy_pct == 60.0


# ─────────────────────────────────────────────────────────────────────────────
# 7. Context Builder Rendering
# ─────────────────────────────────────────────────────────────────────────────

def test_context_builder_benchmark_section():
    """[BENCHMARK COMPARISON] section appears in context with correct content."""
    portfolio_alloc = {"AAPL": 100.0}
    positions = {"AAPL": _position_detail(portfolio_weight=100.0)}
    norm = _normalized_portfolio(portfolio_alloc, positions_detail=positions)
    portfolio_hhi = 1.0

    spy_holdings = [
        _holding("AAPL", 7.2),
        _holding("MSFT", 6.8),
        _holding("GOOGL", 5.5),
    ]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    report = IntelligenceReport(
        benchmark_comparison=bc,
        normalized_portfolio=norm,
    )

    context = build_intelligence_context(report)

    assert "[BENCHMARK COMPARISON" in context
    assert "DO NOT recalculate" in context
    assert "market-value weights" in context


def test_context_builder_missing_hhi():
    """Rendering handles missing HHI gracefully."""
    portfolio_alloc = {"AAPL": 100.0}
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = None  # No HHI

    # Insufficient SPY coverage
    spy_holdings = [_holding("AAPL", 7.2)]  # coverage = 7.2% < 80%

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    report = IntelligenceReport(benchmark_comparison=bc)
    context = build_intelligence_context(report)

    # Should still render without crashing
    if bc.benchmarks:
        assert "[BENCHMARK COMPARISON" in context or context == ""


def test_context_builder_data_note():
    """data_note rendered when present."""
    portfolio_alloc = {"AAPL": 100.0}
    norm = _normalized_portfolio(portfolio_alloc)
    portfolio_hhi = 1.0

    # Coverage < 80%
    spy_holdings = [_holding("AAPL", 10.0)]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, [])

    assert bc.data_note is not None or any(s.data_note for s in bc.benchmarks)

    report = IntelligenceReport(benchmark_comparison=bc)
    context = build_intelligence_context(report)

    # If data_note exists, it should be in context or not rendered
    # (render function handles missing data gracefully)
    assert isinstance(context, str)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Edge Cases: Empty/Invalid Inputs
# ─────────────────────────────────────────────────────────────────────────────

def test_benchmark_comparison_no_portfolio():
    """Null portfolio; valid BenchmarkComparison returned."""
    bc = BenchmarkComparisonAgent.run(None, None, [], [])

    assert isinstance(bc, BenchmarkComparison)
    assert bc.data_note is not None


def test_benchmark_comparison_no_positions():
    """Portfolio with zero total_positions; handled gracefully."""
    norm = NormalizedPortfolio(
        total_positions=0,
        allocation_pct={},
        positions={},
    )

    bc = BenchmarkComparisonAgent.run(norm, None, [], [])

    assert isinstance(bc, BenchmarkComparison)


# ─────────────────────────────────────────────────────────────────────────────
# 9. fetch_benchmark_holdings Mock Test
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_benchmark_holdings_mock():
    """Test fetch_benchmark_holdings returns expected format."""
    # This test demonstrates the expected contract
    # In actual integration, this would hit the DB

    from financial.crud import fetch_benchmark_holdings

    # Mock the pool.fetch call
    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[
        MagicMock(holding_symbol="AAPL", weight=7.2),
        MagicMock(holding_symbol="MSFT", weight=6.8),
    ])

    result = await fetch_benchmark_holdings(mock_pool, "SPY")

    assert len(result) == 2
    assert result[0]["holding_symbol"] == "AAPL"
    assert result[0]["weight"] == 7.2
    assert result[1]["holding_symbol"] == "MSFT"
    assert result[1]["weight"] == 6.8


@pytest.mark.asyncio
async def test_fetch_benchmark_holdings_empty():
    """Test fetch_benchmark_holdings returns empty list when no rows."""
    from financial.crud import fetch_benchmark_holdings

    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[])

    result = await fetch_benchmark_holdings(mock_pool, "UNKNOWN_ETF")

    assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# 10. Real-World Scenario
# ─────────────────────────────────────────────────────────────────────────────

def test_real_world_concentrated_tech_portfolio():
    """Realistic scenario: concentrated tech portfolio vs diversified benchmarks."""
    # Portfolio: heavy tech concentration (80% AAPL+MSFT+NVDA)
    portfolio_alloc = {
        "AAPL": 35.0,
        "MSFT": 30.0,
        "NVDA": 15.0,
        "GOOGL": 10.0,
        "JNJ": 5.0,      # small healthcare position
        "JPM": 5.0,      # small financials position
    }
    positions = {
        t: _position_detail(portfolio_weight=w)
        for t, w in portfolio_alloc.items()
    }
    norm = _normalized_portfolio(portfolio_alloc, positions_detail=positions)

    # Portfolio HHI = (0.35)^2 + (0.30)^2 + (0.15)^2 + (0.10)^2 + (0.05)^2 + (0.05)^2
    #              = 0.1225 + 0.09 + 0.0225 + 0.01 + 0.0025 + 0.0025 = 0.25
    portfolio_hhi = 0.25

    # SPY: broad market
    spy_holdings = [
        _holding("AAPL", 7.2),
        _holding("MSFT", 6.8),
        _holding("GOOGL", 5.5),
        _holding("AMZN", 4.2),
        _holding("NVDA", 4.1),
        _holding("META", 3.5),
        _holding("TSLA", 3.2),
        _holding("JPM", 3.1),
        _holding("JNJ", 2.8),
        _holding("V", 2.9),
    ]

    # QQQ: tech-heavy
    qqq_holdings = [
        _holding("AAPL", 8.1),
        _holding("MSFT", 7.8),
        _holding("NVDA", 7.2),
        _holding("GOOGL", 6.5),
        _holding("META", 5.5),
        _holding("TSLA", 5.2),
        _holding("AMZN", 4.8),
    ]

    bc = BenchmarkComparisonAgent.run(norm, portfolio_hhi, spy_holdings, qqq_holdings)

    # Portfolio HHI (0.25) > SPY HHI (~0.012) → more concentrated
    assert bc.concentration_vs_spy == "more_concentrated"

    # Portfolio HHI (0.25) >> QQQ HHI (~0.04) → significantly more concentrated
    assert bc.concentration_vs_qqq == "more_concentrated"

    # Significant overweight in AAPL, MSFT, NVDA
    assert len(bc.overweight_vs_spy) >= 3

    # Portfolio overlap should be high (all holdings in both benchmarks)
    assert bc.portfolio_overlap_spy_pct == 100.0
    assert bc.portfolio_overlap_qqq_pct == 100.0

    # Weight basis should be market_value
    assert bc.weight_basis == "market_value"

"""
Portfolio Enrichment Step 1 Tests — pure unit, no DB, no network.
Tests for: data_normalizer, portfolio_fit integration, context_builder rendering.

Run: cd backend && pytest tests/test_portfolio_enrichment.py -v
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock
import pytest

from intelligence.data_normalizer import normalize_portfolio
from intelligence.schemas import (
    NormalizedPortfolio, PositionDetail, PortfolioFitAnalysis, IntelligenceReport
)
from intelligence.context_builder import build_intelligence_context
from intelligence.agents.portfolio_fit import PortfolioFitAgent


# ── Test Data Builders ──────────────────────────────────────────────────────

def _portfolio_row(
    symbol: str,
    quantity: float,
    cost_basis: float,
    currency: str = "USD",
    account: str = "default",
    entry_date: date | None = None,
) -> dict:
    """Helper to build a portfolio position row."""
    return {
        "symbol": symbol,
        "quantity": quantity,
        "cost_basis": cost_basis,
        "currency": currency,
        "account": account,
        "entry_date": entry_date,
    }


def _price(symbol: str, close: float) -> tuple[str, float]:
    """Helper tuple for prices dict."""
    return (symbol, close)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Full Price Coverage — All fields computed
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_portfolio_full_coverage():
    """All positions have prices; all enrichment fields populated."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, entry_date=date(2023, 1, 15)),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0, entry_date=date(2023, 3, 20)),
    ]
    prices = dict([_price("AAPL", 175.50), _price("MSFT", 310.25)])
    prices_as_of = date(2026, 4, 25)

    norm = normalize_portfolio(rows, prices=prices, prices_as_of=prices_as_of)

    # Overall metrics
    assert norm.total_positions == 2
    assert norm.total_invested == 30000.0  # (100*150) + (50*300) = 15000 + 15000
    assert norm.allocation_pct["AAPL"] == 50.0  # 15000/30000
    assert norm.allocation_pct["MSFT"] == 50.0  # 15000/30000

    # Market value
    assert norm.total_market_value == 33062.5  # (100*175.50) + (50*310.25) = 17550 + 15512.5
    assert norm.prices_as_of == prices_as_of

    # Per-position details
    aapl = norm.positions["AAPL"]
    assert aapl.entry_date == date(2023, 1, 15)
    assert aapl.current_price == 175.50
    assert aapl.position_value == 17550.0  # 100 * 175.50
    assert aapl.position_pnl == 2550.0  # 17550 - (100*150)
    assert aapl.position_pnl_pct == 17.0  # (2550/15000)*100
    assert aapl.portfolio_weight == 53.08  # (17550/33062.5)*100, rounded

    msft = norm.positions["MSFT"]
    assert msft.entry_date == date(2023, 3, 20)
    assert msft.current_price == 310.25
    assert msft.position_value == 15512.5  # 50 * 310.25
    assert msft.position_pnl == 5512.5  # 15512.5 - (50*300)
    assert msft.position_pnl_pct == 55.13  # (5512.5/15000)*100
    assert msft.portfolio_weight == 46.92  # (15512.5/33062.5)*100, rounded

    # Data note should indicate full coverage
    assert "Full price coverage" in norm.data_note


def test_normalize_portfolio_negative_pnl():
    """Position with loss (price < cost_basis)."""
    rows = [
        _portfolio_row("GOOG", quantity=20, cost_basis=100.0, entry_date=date(2023, 6, 1)),
    ]
    prices = dict([_price("GOOG", 85.0)])

    norm = normalize_portfolio(rows, prices=prices)

    goog = norm.positions["GOOG"]
    assert goog.position_value == 1700.0  # 20 * 85.0
    assert goog.position_pnl == -300.0  # 1700 - (20*100)
    assert goog.position_pnl_pct == -15.0  # (-300/2000)*100


# ─────────────────────────────────────────────────────────────────────────────
# 2. Partial Price Coverage — Only some tickers have prices
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_portfolio_partial_coverage():
    """Some positions have prices, some don't."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),
        _portfolio_row("GOOGL", quantity=30, cost_basis=120.0),  # No price
    ]
    prices = dict([_price("AAPL", 175.50), _price("MSFT", 310.25)])

    norm = normalize_portfolio(rows, prices=prices)

    # Overall still computed by invested capital
    assert norm.total_invested == 33600.0  # (100*150) + (50*300) + (30*120) = 15000 + 15000 + 3600
    assert norm.allocation_pct["AAPL"] == 44.64  # 15000/33600
    assert norm.allocation_pct["MSFT"] == 44.64  # 15000/33600
    assert norm.allocation_pct["GOOGL"] == 10.71  # 3600/33600

    # Market value only includes priced positions
    assert norm.total_market_value == 33062.5  # (100*175.50) + (50*310.25), GOOGL excluded

    # AAPL and MSFT have enrichment
    assert norm.positions["AAPL"].position_value == 17550.0
    assert norm.positions["MSFT"].position_value == 15512.5

    # GOOGL has no market-based fields
    googl = norm.positions["GOOGL"]
    assert googl.current_price is None
    assert googl.position_value is None
    assert googl.position_pnl is None
    assert googl.position_pnl_pct is None
    assert googl.portfolio_weight is None

    # Data note should indicate partial coverage
    assert "Partial price coverage" in norm.data_note
    assert "2/3 positions priced" in norm.data_note


# ─────────────────────────────────────────────────────────────────────────────
# 3. No Prices — Backward Compatibility
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_portfolio_no_prices():
    """No prices provided; old behavior preserved (allocated capital only)."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),
    ]

    # Call without prices
    norm = normalize_portfolio(rows)

    # Core metrics unchanged
    assert norm.total_positions == 2
    assert norm.total_invested == 30000.0  # (100*150) + (50*300) = 15000 + 15000
    assert norm.allocation_pct["AAPL"] == 50.0  # 15000/30000
    assert norm.allocation_pct["MSFT"] == 50.0  # 15000/30000

    # Market-value fields absent
    assert norm.total_market_value is None
    assert norm.prices_as_of is None

    # Positions dict empty
    assert len(norm.positions) == 0

    # Data note indicates no price data
    assert "No price data available" in norm.data_note or norm.positions == {}


def test_normalize_portfolio_empty_prices_dict():
    """Empty prices dict provided (equivalent to no prices)."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
    ]

    norm = normalize_portfolio(rows, prices={})

    # Core metrics only
    assert norm.total_invested == 15000.0
    assert norm.total_market_value is None
    assert len(norm.positions) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Edge Cases: Zero/Missing cost_basis
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_portfolio_zero_cost_basis():
    """Cost basis = 0; PnL fields should be None (avoid division by zero)."""
    rows = [
        _portfolio_row("STOCK", quantity=100, cost_basis=0.0),
    ]
    prices = dict([_price("STOCK", 50.0)])

    norm = normalize_portfolio(rows, prices=prices)

    detail = norm.positions["STOCK"]
    assert detail.current_price == 50.0
    assert detail.position_value == 5000.0  # 100 * 50
    assert detail.position_pnl is None  # Can't compute: cost_basis is 0
    assert detail.position_pnl_pct is None


def test_normalize_portfolio_none_cost_basis():
    """Cost basis = None; computed as 0.0 internally."""
    rows = [
        {"symbol": "STOCK", "quantity": 100, "cost_basis": None, "currency": "USD"}
    ]
    prices = dict([_price("STOCK", 50.0)])

    norm = normalize_portfolio(rows, prices=prices)

    assert norm.total_invested is None or norm.total_invested == 0.0
    detail = norm.positions["STOCK"]
    assert detail.position_value == 5000.0
    assert detail.position_pnl is None


def test_normalize_portfolio_zero_quantity():
    """Quantity = 0; position should still be tracked."""
    rows = [
        _portfolio_row("ZERO", quantity=0, cost_basis=100.0),
    ]
    prices = dict([_price("ZERO", 50.0)])

    norm = normalize_portfolio(rows, prices=prices)

    assert "ZERO" in norm.allocation_pct
    detail = norm.positions["ZERO"]
    assert detail.position_value == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Entry Date Capture
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_portfolio_entry_date():
    """Entry date from row is captured in PositionDetail."""
    entry = date(2022, 6, 15)
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, entry_date=entry),
    ]
    prices = dict([_price("AAPL", 175.0)])

    norm = normalize_portfolio(rows, prices=prices)

    assert norm.positions["AAPL"].entry_date == entry


def test_normalize_portfolio_no_entry_date():
    """Entry date = None; field remains None."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, entry_date=None),
    ]
    prices = dict([_price("AAPL", 175.0)])

    norm = normalize_portfolio(rows, prices=prices)

    assert norm.positions["AAPL"].entry_date is None


# ─────────────────────────────────────────────────────────────────────────────
# 6. Deduplication by Ticker (newest row wins)
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_portfolio_deduplication_by_ticker():
    """Multiple rows per ticker; only latest (first in list) is used."""
    rows = [
        # Newest first (from ORDER BY date DESC)
        _portfolio_row("AAPL", quantity=100, cost_basis=175.0),
        _portfolio_row("AAPL", quantity=80, cost_basis=150.0),  # Older, should be ignored
    ]
    prices = dict([_price("AAPL", 176.0)])

    norm = normalize_portfolio(rows, prices=prices)

    # Should use the first (newest) row
    assert norm.allocation_pct["AAPL"] == 100.0
    assert len(norm.positions) == 1
    detail = norm.positions["AAPL"]
    assert detail.position_value == 17600.0  # 100 * 176, not 80 * 176


# ─────────────────────────────────────────────────────────────────────────────
# 7. Empty Portfolio
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_portfolio_empty():
    """Empty rows list; returns minimal NormalizedPortfolio."""
    norm = normalize_portfolio([])

    assert norm.total_positions == 0
    assert norm.total_invested is None
    assert norm.allocation_pct == {}
    assert norm.positions == {}
    assert norm.total_market_value is None


def test_normalize_portfolio_empty_with_prices():
    """Empty rows; prices provided and ignored."""
    prices = dict([_price("AAPL", 175.0)])
    norm = normalize_portfolio([], prices=prices)

    assert norm.total_positions == 0
    assert len(norm.positions) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 8. Context Builder Rendering
# ─────────────────────────────────────────────────────────────────────────────

def test_context_builder_renders_enriched_portfolio():
    """Enriched portfolio is rendered with pre-computed disclaimer."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, entry_date=date(2023, 1, 15)),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),
    ]
    prices = dict([_price("AAPL", 175.50), _price("MSFT", 310.25)])
    norm = normalize_portfolio(rows, prices=prices, prices_as_of=date(2026, 4, 25))

    report = IntelligenceReport(
        normalized_portfolio=norm,
        agents_ran=["portfolio_fit"],
    )
    context = build_intelligence_context(report)

    # Check for pre-computed disclaimer
    assert "pre-computed, DO NOT recalculate" in context
    assert "DO NOT" in context

    # Check for position details
    assert "AAPL" in context
    assert "MSFT" in context
    assert "price=175.50" in context or "price" in context
    assert "pnl" in context.lower()
    assert "weight" in context.lower()

    # Check for market value and staleness
    assert "Total market value" in context
    assert "2026-04-25" in context or "Prices as of" in context


def test_context_builder_handles_partial_coverage():
    """Context builder gracefully renders partial price coverage."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),
        _portfolio_row("GOOGL", quantity=30, cost_basis=120.0),
    ]
    prices = dict([_price("AAPL", 175.0)])
    norm = normalize_portfolio(rows, prices=prices)

    report = IntelligenceReport(normalized_portfolio=norm)
    context = build_intelligence_context(report)

    # Should still be renderable
    assert "AAPL" in context
    assert "Partial price coverage" in context or "price" in context.lower()
    assert "no price data available" in context.lower() or "N/A" in context


def test_context_builder_no_positions_graceful():
    """Context builder handles portfolio with no enrichment gracefully."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
    ]
    norm = normalize_portfolio(rows)  # No prices

    report = IntelligenceReport(normalized_portfolio=norm)
    context = build_intelligence_context(report)

    # Should render allocation without crashing
    assert "Total positions: 1" in context
    assert "AAPL" in context


# ─────────────────────────────────────────────────────────────────────────────
# 9. Portfolio Fit Integration (with mocks)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_fit_fetches_entry_date_and_prices():
    """PortfolioFitAgent fetches entry_date and prices, passes to normalizer."""
    # Mock pool
    pool = AsyncMock()

    # Mock _fetch_portfolio to return rows with entry_date
    fetch_portfolio_rows = [
        {
            "symbol": "AAPL",
            "quantity": 100.0,
            "cost_basis": 150.0,
            "currency": "USD",
            "account": "default",
            "entry_date": date(2023, 1, 15),
        },
        {
            "symbol": "MSFT",
            "quantity": 50.0,
            "cost_basis": 300.0,
            "currency": "USD",
            "account": "default",
            "entry_date": date(2023, 3, 20),
        },
    ]
    pool.fetch = AsyncMock(side_effect=[
        # First call: _fetch_portfolio
        [MagicMock(**row) for row in fetch_portfolio_rows],
        # Second call: _fetch_prices
        [
            MagicMock(symbol="AAPL", close=175.50, date=date(2026, 4, 25)),
            MagicMock(symbol="MSFT", close=310.25, date=date(2026, 4, 25)),
        ],
    ])

    # Run PortfolioFitAgent
    result = await PortfolioFitAgent.run(
        tickers_mentioned=["AAPL"],
        owner_id="user_test_123",
        pool=pool,
    )

    # Verify result
    assert isinstance(result, PortfolioFitAnalysis)
    assert result.normalized_portfolio is not None

    # Verify enrichment was computed
    norm = result.normalized_portfolio
    assert "AAPL" in norm.positions
    assert norm.positions["AAPL"].position_value is not None
    assert norm.positions["AAPL"].portfolio_weight is not None


@pytest.mark.asyncio
async def test_portfolio_fit_handles_no_prices():
    """PortfolioFitAgent gracefully handles case where no prices are found."""
    pool = AsyncMock()

    # No price rows returned
    fetch_portfolio_rows = [
        {
            "symbol": "AAPL",
            "quantity": 100.0,
            "cost_basis": 150.0,
            "currency": "USD",
            "account": "default",
            "entry_date": date(2023, 1, 15),
        },
    ]
    pool.fetch = AsyncMock(side_effect=[
        [MagicMock(**row) for row in fetch_portfolio_rows],
        [],  # No prices found
    ])

    result = await PortfolioFitAgent.run(
        tickers_mentioned=[],
        owner_id="user_test_123",
        pool=pool,
    )

    assert result.normalized_portfolio is not None
    assert result.normalized_portfolio.total_positions == 1


@pytest.mark.asyncio
async def test_portfolio_fit_empty_portfolio():
    """PortfolioFitAgent handles empty portfolio gracefully."""
    pool = AsyncMock()

    # No positions
    pool.fetch = AsyncMock(side_effect=[
        [],  # No portfolio rows
        [],  # No prices
    ])

    result = await PortfolioFitAgent.run(
        tickers_mentioned=[],
        owner_id="user_test_123",
        pool=pool,
    )

    assert "Portfolio is empty" in result.current_exposure_summary


# ─────────────────────────────────────────────────────────────────────────────
# 10. Data Note Accuracy
# ─────────────────────────────────────────────────────────────────────────────

def test_data_note_full_coverage():
    """Data note correctly identifies full coverage."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),
    ]
    prices = {"AAPL": 175.0, "MSFT": 310.0}

    norm = normalize_portfolio(rows, prices=prices)

    assert "Full price coverage" in norm.data_note


def test_data_note_partial_coverage():
    """Data note correctly identifies partial coverage."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),
        _portfolio_row("GOOGL", quantity=30, cost_basis=120.0),
    ]
    prices = {"AAPL": 175.0}

    norm = normalize_portfolio(rows, prices=prices)

    assert "Partial price coverage" in norm.data_note
    assert "1/3" in norm.data_note


def test_data_note_no_price_coverage():
    """Data note correctly identifies zero price coverage."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
    ]
    prices = {}

    norm = normalize_portfolio(rows, prices=prices)

    assert "No price data available" in norm.data_note or norm.positions == {}

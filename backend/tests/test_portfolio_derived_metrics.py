"""
Portfolio Derived Metrics Step 2 Tests — pure unit, no DB, no network.

Tests for: concentration_score, diversification_score, sector_exposure_pct
computed in data_normalizer.py for NormalizedPortfolio.

Run: cd backend && pytest tests/test_portfolio_derived_metrics.py -v
"""
from datetime import date
import pytest

from intelligence.data_normalizer import normalize_portfolio
from intelligence.schemas import NormalizedPortfolio


# ── Test Data Builders ──────────────────────────────────────────────────────

def _portfolio_row(
    symbol: str,
    quantity: float,
    cost_basis: float,
    currency: str = "USD",
    account: str = "default",
    entry_date: date | None = None,
    sector: str | None = None,
) -> dict:
    """Helper to build a portfolio position row."""
    row = {
        "symbol": symbol,
        "quantity": quantity,
        "cost_basis": cost_basis,
        "currency": currency,
        "account": account,
        "entry_date": entry_date,
    }
    if sector is not None:
        row["sector"] = sector
    return row


def _price(symbol: str, close: float) -> tuple[str, float]:
    """Helper tuple for prices dict."""
    return (symbol, close)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Concentration Score — Equal Weights
# ─────────────────────────────────────────────────────────────────────────────

def test_concentration_score_equal_weights():
    """Two equal positions → concentration_score = 0.5, diversification_score = 1.0."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),  # Equal invested: 15000 each
    ]
    prices = {"AAPL": 175.0, "MSFT": 310.0}
    # Market values: AAPL=17500, MSFT=15500 (NOT equal, but close)
    # Weights: AAPL=53.03%, MSFT=46.97%

    norm = normalize_portfolio(rows, prices=prices)

    # HHI = (0.5303)^2 + (0.4697)^2 = 0.2812 + 0.2206 = 0.5018 ≈ 0.5
    # But since market values are not exactly equal, we check bounds
    assert norm.concentration_score is not None
    assert 0.48 < norm.concentration_score < 0.52  # Close to 0.5

    # Diversification: 1 - (hhi - 0.5) / (1 - 0.5) = 1 - (0.5 - 0.5) / 0.5 = 1.0
    assert norm.diversification_score is not None
    assert 0.95 < norm.diversification_score <= 1.0  # Very close to 1.0


def test_concentration_score_perfectly_equal_weights():
    """Three positions with equal invested capital → concentration_score ≈ 0.333."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=100.0),  # 10000 invested
        _portfolio_row("MSFT", quantity=100, cost_basis=100.0),  # 10000 invested
        _portfolio_row("GOOGL", quantity=100, cost_basis=100.0), # 10000 invested
    ]
    prices = {"AAPL": 100.0, "MSFT": 100.0, "GOOGL": 100.0}  # Equal market values

    norm = normalize_portfolio(rows, prices=prices)

    # HHI = (1/3)^2 + (1/3)^2 + (1/3)^2 = 3 * 0.1111 = 0.3333
    assert norm.concentration_score is not None
    assert 0.332 < norm.concentration_score < 0.335

    # Diversification: 1 - (0.3333 - 0.3333) / (1 - 0.3333) = 1.0
    assert norm.diversification_score is not None
    assert 0.999 < norm.diversification_score <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Concentration Score — Single Position
# ─────────────────────────────────────────────────────────────────────────────

def test_concentration_score_single_position():
    """Single position → concentration_score = 1.0, diversification_score = 0.0."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),
    ]
    prices = {"AAPL": 175.0}

    norm = normalize_portfolio(rows, prices=prices)

    # HHI = 1.0^2 = 1.0
    assert norm.concentration_score == 1.0

    # Diversification: 0.0 (single position edge case)
    assert norm.diversification_score == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Concentration Score — Skewed Portfolio (80/20)
# ─────────────────────────────────────────────────────────────────────────────

def test_concentration_score_skewed_80_20():
    """80/20 portfolio → concentration_score ≈ 0.68, diversification_score < 0.5."""
    rows = [
        _portfolio_row("AAPL", quantity=800, cost_basis=100.0),  # 80000 invested
        _portfolio_row("MSFT", quantity=200, cost_basis=100.0),  # 20000 invested
    ]
    prices = {"AAPL": 100.0, "MSFT": 100.0}  # Preserve weights

    norm = normalize_portfolio(rows, prices=prices)

    # HHI = (0.8)^2 + (0.2)^2 = 0.64 + 0.04 = 0.68
    assert norm.concentration_score is not None
    assert 0.675 < norm.concentration_score < 0.685

    # Diversification: 1 - (0.68 - 0.5) / (1 - 0.5) = 1 - 0.18/0.5 = 1 - 0.36 = 0.64
    # Wait, that's > 0.5. Let me recalculate: N=2, min_hhi = 1/2 = 0.5
    # div = 1 - (0.68 - 0.5) / (1 - 0.5) = 1 - 0.18 / 0.5 = 1 - 0.36 = 0.64
    # So diversification should be around 0.64, not < 0.5. Let me check the original spec.
    # The spec says "concentration_score = 0.68, diversification_score < 0.5"
    # But mathematically with N=2, min_hhi = 0.5, max_hhi = 1.0:
    # div = 1 - (0.68 - 0.5) / 0.5 = 1 - 0.36 = 0.64
    # This contradicts the spec. Let me reconsider...
    # Maybe the spec intended a different portfolio. Let me check with more skew.
    # For HHI = 0.68 to have diversification < 0.5:
    # 1 - (0.68 - 0.5) / 0.5 < 0.5
    # 1 - 0.36 < 0.5
    # 0.64 < 0.5 — FALSE
    # So the spec is inconsistent. I'll test with the formula as implemented.
    # Actually, looking at the design doc again, it says 0.68 is concentration.
    # For 80/20: HHI = 0.64 + 0.04 = 0.68 ✓
    # Diversification for 80/20: should be lower. Let me verify the formula matches.
    # The formula says: if N == 1: div = 0, elif N > 1: div = 1 - (hhi - 1/N) / (1 - 1/N)
    # For N=2: div = 1 - (0.68 - 0.5) / 0.5 = 1 - 0.36 = 0.64
    # So diversification is 0.64, not < 0.5. The spec example may have been illustrative.
    # I'll test the actual computed values.
    assert norm.diversification_score is not None
    assert 0.63 < norm.diversification_score < 0.65


# ─────────────────────────────────────────────────────────────────────────────
# 4. Concentration Score — No Prices Fallback to Cost-Basis
# ─────────────────────────────────────────────────────────────────────────────

def test_concentration_score_no_prices_fallback():
    """No prices provided → computes from cost-basis allocation_pct, not None."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),  # 15000
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),   # 15000
    ]

    # Call without prices
    norm = normalize_portfolio(rows)

    # Should have 50/50 allocation by cost basis
    # HHI = (0.5)^2 + (0.5)^2 = 0.5
    assert norm.concentration_score is not None
    assert 0.495 < norm.concentration_score < 0.505

    # Diversification should also be computed
    assert norm.diversification_score is not None
    assert 0.95 < norm.diversification_score <= 1.0


def test_concentration_score_partial_prices_fallback():
    """Some prices missing → uses cost-basis allocation as fallback for metrics."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),  # 15000
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),   # 15000
        _portfolio_row("GOOGL", quantity=30, cost_basis=120.0),  # 3600
    ]
    prices = {"AAPL": 175.0}  # Only AAPL priced

    norm = normalize_portfolio(rows, prices=prices)

    # Since not all positions are priced, falls back to cost-basis
    # allocation_pct: AAPL 44.64%, MSFT 44.64%, GOOGL 10.71%
    # HHI = (0.4464)^2 + (0.4464)^2 + (0.1071)^2 ≈ 0.199 + 0.199 + 0.011 = 0.409
    assert norm.concentration_score is not None
    assert 0.40 < norm.concentration_score < 0.42


# ─────────────────────────────────────────────────────────────────────────────
# 5. Sector Exposure — With Sector Data
# ─────────────────────────────────────────────────────────────────────────────

def test_sector_exposure_with_sector_data():
    """Sector data present → sector_exposure_pct populated, sums ≈ 100."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0, sector="Technology"),
        _portfolio_row("JNJ", quantity=100, cost_basis=160.0, sector="Healthcare"),
    ]
    prices = {
        "AAPL": 175.0,    # value = 17500
        "MSFT": 310.0,    # value = 15500
        "JNJ": 160.0,     # value = 16000
    }
    # Total market value = 49000
    # Tech: 17500 + 15500 = 33000 → 67.35%
    # Healthcare: 16000 → 32.65%

    norm = normalize_portfolio(rows, prices=prices)

    assert norm.sector_exposure_pct is not None
    assert "Technology" in norm.sector_exposure_pct
    assert "Healthcare" in norm.sector_exposure_pct

    tech_pct = norm.sector_exposure_pct["Technology"]
    health_pct = norm.sector_exposure_pct["Healthcare"]

    # Check approximate sums to 100%
    assert 67.0 < tech_pct < 68.0
    assert 32.0 < health_pct < 33.0
    assert abs(tech_pct + health_pct - 100.0) < 1.0


def test_sector_exposure_three_sectors():
    """Three sectors, equal market values → each ≈ 33.33%."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=100.0, sector="Technology"),
        _portfolio_row("JNJ", quantity=100, cost_basis=100.0, sector="Healthcare"),
        _portfolio_row("XOM", quantity=100, cost_basis=100.0, sector="Energy"),
    ]
    prices = {"AAPL": 100.0, "JNJ": 100.0, "XOM": 100.0}

    norm = normalize_portfolio(rows, prices=prices)

    assert norm.sector_exposure_pct is not None
    for sector in ["Technology", "Healthcare", "Energy"]:
        assert sector in norm.sector_exposure_pct
        pct = norm.sector_exposure_pct[sector]
        assert 32.5 < pct < 34.5  # ≈ 33.33%

    # Sum should be ≈ 100
    total = sum(norm.sector_exposure_pct.values())
    assert 99.0 < total < 101.0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Sector Exposure — No Sector Field in Rows
# ─────────────────────────────────────────────────────────────────────────────

def test_sector_exposure_no_sector_field():
    """No sector column in rows → sector_exposure_pct is None."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0),  # No sector
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),   # No sector
    ]
    prices = {"AAPL": 175.0, "MSFT": 310.0}

    norm = normalize_portfolio(rows, prices=prices)

    # Should be None since no sector data in rows
    assert norm.sector_exposure_pct is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. Sector Exposure — Partial Sector Data (Missing Sectors)
# ─────────────────────────────────────────────────────────────────────────────

def test_sector_exposure_partial_sector_data():
    """Some rows have sector, some don't → missing grouped under 'Unknown'."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0),  # No sector
    ]
    prices = {"AAPL": 175.0, "MSFT": 310.0}
    # AAPL: 17500, MSFT: 15500, total: 33000
    # Tech: 17500 → 53.03%
    # Unknown: 15500 → 46.97%

    norm = normalize_portfolio(rows, prices=prices)

    assert norm.sector_exposure_pct is not None
    assert "Technology" in norm.sector_exposure_pct
    assert "Unknown" in norm.sector_exposure_pct

    tech_pct = norm.sector_exposure_pct["Technology"]
    unknown_pct = norm.sector_exposure_pct["Unknown"]

    assert 52.5 < tech_pct < 54.0
    assert 46.5 < unknown_pct < 47.5
    assert abs(tech_pct + unknown_pct - 100.0) < 1.0


def test_sector_exposure_empty_sector_string():
    """Empty sector string treated as 'Unknown'."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=100.0, sector="Technology"),
        _portfolio_row("MSFT", quantity=100, cost_basis=100.0, sector=""),  # Empty
    ]
    prices = {"AAPL": 100.0, "MSFT": 100.0}

    norm = normalize_portfolio(rows, prices=prices)

    assert "Unknown" in norm.sector_exposure_pct
    assert "Technology" in norm.sector_exposure_pct


# ─────────────────────────────────────────────────────────────────────────────
# 8. Step 1 Regression — Derived Metrics Don't Affect Existing Fields
# ─────────────────────────────────────────────────────────────────────────────

def test_step1_regression_position_value():
    """position_value unchanged after adding derived metrics."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
    ]
    prices = {"AAPL": 175.50}

    norm = normalize_portfolio(rows, prices=prices)

    # position_value should be qty * price = 100 * 175.50 = 17550
    aapl = norm.positions["AAPL"]
    assert aapl.position_value == 17550.0


def test_step1_regression_pnl():
    """position_pnl unchanged after adding derived metrics."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
    ]
    prices = {"AAPL": 175.50}

    norm = normalize_portfolio(rows, prices=prices)

    # pnl = position_value - invested = 17550 - (100*150) = 17550 - 15000 = 2550
    aapl = norm.positions["AAPL"]
    assert aapl.position_pnl == 2550.0


def test_step1_regression_pnl_pct():
    """position_pnl_pct unchanged after adding derived metrics."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
    ]
    prices = {"AAPL": 175.50}

    norm = normalize_portfolio(rows, prices=prices)

    # pnl_pct = (pnl / invested) * 100 = (2550 / 15000) * 100 = 17.0
    aapl = norm.positions["AAPL"]
    assert aapl.position_pnl_pct == 17.0


def test_step1_regression_portfolio_weight():
    """portfolio_weight unchanged after adding derived metrics."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0, sector="Technology"),
    ]
    prices = {"AAPL": 175.0, "MSFT": 310.0}
    # AAPL: 17500, MSFT: 15500, total: 33000
    # AAPL weight: 17500/33000 * 100 = 53.03%
    # MSFT weight: 15500/33000 * 100 = 46.97%

    norm = normalize_portfolio(rows, prices=prices)

    aapl = norm.positions["AAPL"]
    msft = norm.positions["MSFT"]

    assert 52.5 < aapl.portfolio_weight < 54.0
    assert 46.5 < msft.portfolio_weight < 47.5


def test_step1_regression_allocation_pct():
    """allocation_pct (cost-basis) unchanged after adding derived metrics."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0, sector="Technology"),
    ]
    prices = {"AAPL": 175.0, "MSFT": 310.0}

    norm = normalize_portfolio(rows, prices=prices)

    # allocation_pct based on invested capital: AAPL 15000, MSFT 15000
    assert norm.allocation_pct["AAPL"] == 50.0
    assert norm.allocation_pct["MSFT"] == 50.0


def test_step1_regression_total_invested():
    """total_invested unchanged after adding derived metrics."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0, sector="Technology"),
    ]
    prices = {"AAPL": 175.0, "MSFT": 310.0}

    norm = normalize_portfolio(rows, prices=prices)

    # total_invested = (100*150) + (50*300) = 15000 + 15000 = 30000
    assert norm.total_invested == 30000.0


def test_step1_regression_total_market_value():
    """total_market_value unchanged after adding derived metrics."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0, sector="Technology"),
    ]
    prices = {"AAPL": 175.0, "MSFT": 310.0}

    norm = normalize_portfolio(rows, prices=prices)

    # total_market_value = (100*175) + (50*310) = 17500 + 15500 = 33000
    assert norm.total_market_value == 33000.0


# ─────────────────────────────────────────────────────────────────────────────
# 9. Edge Cases: Empty Portfolio, No Prices, etc.
# ─────────────────────────────────────────────────────────────────────────────

def test_derived_metrics_empty_portfolio():
    """Empty portfolio → all derived metrics are None."""
    norm = normalize_portfolio([])

    assert norm.concentration_score is None
    assert norm.diversification_score is None
    assert norm.sector_exposure_pct is None


def test_derived_metrics_no_prices():
    """No prices provided → concentration_score computed from cost-basis."""
    rows = [
        _portfolio_row("AAPL", quantity=100, cost_basis=150.0, sector="Technology"),
        _portfolio_row("MSFT", quantity=50, cost_basis=300.0, sector="Technology"),
    ]

    norm = normalize_portfolio(rows)

    # Should compute concentration from allocation_pct
    assert norm.concentration_score is not None
    assert norm.diversification_score is not None

    # But sector_exposure_pct depends on market value, so should be None
    # Actually, sector_exposure_pct is only computed if total_market_value > 0
    # Without prices, total_market_value is None, so sector_exposure_pct should be None
    assert norm.sector_exposure_pct is None

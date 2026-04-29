"""
tests/test_macro_signals.py — Step 4 Macro Signals unit tests.
Pure unit tests — no DB, no network.

Tests:
- _fetch_vix: present / missing / high-stress boundary
- _fetch_yield_curve: T10Y2Y present / inverted / missing
- _compute_inflation_trend: rising / falling / stable / boundary / insufficient data
- _compute_fed_trend: hiking / cutting / holding / boundary / insufficient data
- MarketAnalyzerAgent.run(): trend labels in macro_signals, partial data, signal isolation

Run: cd backend && python -m pytest tests/test_macro_signals.py -v
"""
from datetime import date as _date
from unittest.mock import AsyncMock, MagicMock

import pytest

from intelligence.agents.market_analyzer import (
    _compute_fed_trend,
    _compute_inflation_trend,
    _fetch_vix,
    _fetch_yield_curve,
    MarketAnalyzerAgent,
)


# ─── mock helpers ────────────────────────────────────────────────────────────

def _pool_fetchrow(return_value):
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=return_value)
    return pool


def _pool_fetch(return_value):
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=return_value)
    return pool


def _rows(*values):
    """Build list of dict rows as asyncpg would return."""
    return [{"value": v} for v in values]


# ─────────────────────────────────────────────────────────────────────────────
# 1. VIX
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_vix_present():
    assert await _fetch_vix(_pool_fetchrow({"value": 27.5})) == 27.5


@pytest.mark.asyncio
async def test_fetch_vix_missing():
    assert await _fetch_vix(_pool_fetchrow(None)) is None


@pytest.mark.asyncio
async def test_fetch_vix_high_stress_boundary():
    result = await _fetch_vix(_pool_fetchrow({"value": 35.0}))
    assert result == 35.0
    assert result >= 35.0  # exactly on the HIGH STRESS threshold


@pytest.mark.asyncio
async def test_fetch_vix_normal():
    result = await _fetch_vix(_pool_fetchrow({"value": 18.0}))
    assert result == 18.0
    assert result < 25.0  # below elevated threshold


# ─────────────────────────────────────────────────────────────────────────────
# 2. Yield Curve (T10Y2Y)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_yield_curve_present():
    assert await _fetch_yield_curve(_pool_fetchrow({"value": 0.45})) == 0.45


@pytest.mark.asyncio
async def test_fetch_yield_curve_inverted():
    result = await _fetch_yield_curve(_pool_fetchrow({"value": -0.50}))
    assert result == -0.50
    assert result < -0.10  # below inverted threshold


@pytest.mark.asyncio
async def test_fetch_yield_curve_flat():
    result = await _fetch_yield_curve(_pool_fetchrow({"value": 0.10}))
    assert result == 0.10
    assert -0.10 <= result < 0.25  # flat zone


@pytest.mark.asyncio
async def test_fetch_yield_curve_missing():
    assert await _fetch_yield_curve(_pool_fetchrow(None)) is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Inflation Trend
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inflation_rising():
    # delta = 3.9 - 3.0 = +0.9 > 0.5 → RISING
    pool = _pool_fetch(_rows(3.9, 3.3, 3.0))
    assert await _compute_inflation_trend(pool) == "Inflation trend: RISING (3-month)"


@pytest.mark.asyncio
async def test_inflation_falling():
    # delta = 3.0 - 3.9 = -0.9 < -0.5 → FALLING
    pool = _pool_fetch(_rows(3.0, 3.3, 3.9))
    assert await _compute_inflation_trend(pool) == "Inflation trend: FALLING (3-month)"


@pytest.mark.asyncio
async def test_inflation_stable():
    # delta = 3.2 - 3.0 = +0.2 → within ±0.5 → STABLE
    pool = _pool_fetch(_rows(3.2, 3.1, 3.0))
    assert await _compute_inflation_trend(pool) == "Inflation trend: STABLE (3-month)"


@pytest.mark.asyncio
async def test_inflation_stable_boundary_below_threshold():
    # delta = 3.4 - 3.0 = +0.4 < 0.5 → STABLE (not RISING)
    pool = _pool_fetch(_rows(3.4, 3.0))
    assert await _compute_inflation_trend(pool) == "Inflation trend: STABLE (3-month)"


@pytest.mark.asyncio
async def test_inflation_zero_rows():
    assert await _compute_inflation_trend(_pool_fetch([])) is None


@pytest.mark.asyncio
async def test_inflation_one_row():
    assert await _compute_inflation_trend(_pool_fetch(_rows(3.5))) is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fed Rate Trend
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fed_hiking():
    # delta = 5.5 - 5.0 = +0.5 > 0.10 → HIKING
    pool = _pool_fetch(_rows(5.5, 5.25, 5.0))
    assert await _compute_fed_trend(pool) == "Fed rate: HIKING"


@pytest.mark.asyncio
async def test_fed_cutting():
    # delta = 4.75 - 5.25 = -0.5 < -0.10 → CUTTING
    pool = _pool_fetch(_rows(4.75, 5.0, 5.25))
    assert await _compute_fed_trend(pool) == "Fed rate: CUTTING"


@pytest.mark.asyncio
async def test_fed_holding():
    # delta = 0.0 → HOLDING
    pool = _pool_fetch(_rows(5.5, 5.5, 5.5))
    assert await _compute_fed_trend(pool) == "Fed rate: HOLDING"


@pytest.mark.asyncio
async def test_fed_holding_boundary():
    # delta = 5.34 - 5.25 = +0.09 < 0.10 → HOLDING (not HIKING)
    pool = _pool_fetch(_rows(5.34, 5.25))
    assert await _compute_fed_trend(pool) == "Fed rate: HOLDING"


@pytest.mark.asyncio
async def test_fed_zero_rows():
    assert await _compute_fed_trend(_pool_fetch([])) is None


@pytest.mark.asyncio
async def test_fed_one_row():
    assert await _compute_fed_trend(_pool_fetch(_rows(5.5))) is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. MarketAnalyzerAgent.run() integration
# ─────────────────────────────────────────────────────────────────────────────

def _full_pool(fetch_side_effect, fetchrow_side_effect):
    pool = MagicMock()
    pool.fetch = fetch_side_effect
    pool.fetchrow = fetchrow_side_effect
    return pool


@pytest.mark.asyncio
async def test_run_trend_signals_in_macro_signals():
    """Both trend labels appear in ctx.macro_signals when data is present."""
    today = _date.today()

    async def mock_fetch(query, *args, **kwargs):
        if "ANY($1" in query:
            return [
                {"series_id": "FEDFUNDS", "value": 5.5, "date": today},
                {"series_id": "CPIAUCNS", "value": 3.2, "date": today},
            ]
        if "'CPIAUCNS'" in query:
            return _rows(3.9, 3.3, 3.0)   # RISING
        if "'FEDFUNDS'" in query:
            return _rows(5.5, 5.25, 5.0)  # HIKING
        return []

    async def mock_fetchrow(query, *args, **kwargs):
        if "fx_rates" in query:
            return {"rate": 3.72}
        if "T10Y2Y" in query:
            return {"value": 0.45}
        if "VIXCLS" in query:
            return {"value": 22.0}
        return None

    pool = MagicMock()
    pool.fetch = mock_fetch
    pool.fetchrow = mock_fetchrow

    ctx = await MarketAnalyzerAgent.run(pool)

    assert ctx.vix == 22.0
    assert ctx.yield_curve == 0.45
    assert "Inflation trend: RISING (3-month)" in ctx.macro_signals
    assert "Fed rate: HIKING" in ctx.macro_signals


@pytest.mark.asyncio
async def test_run_partial_data_no_crash():
    """Only FEDFUNDS present — VIX/yield curve None, inflation skipped, fed computed."""
    today = _date.today()

    async def mock_fetch(query, *args, **kwargs):
        if "ANY($1" in query:
            return [{"series_id": "FEDFUNDS", "value": 5.5, "date": today}]
        if "'CPIAUCNS'" in query:
            return []
        if "'FEDFUNDS'" in query:
            return _rows(5.5, 5.5)  # HOLDING
        return []

    async def mock_fetchrow(query, *args, **kwargs):
        return None

    pool = MagicMock()
    pool.fetch = mock_fetch
    pool.fetchrow = mock_fetchrow

    ctx = await MarketAnalyzerAgent.run(pool)

    assert ctx is not None
    assert ctx.vix is None
    assert ctx.yield_curve is None
    assert not any("Inflation trend:" in s for s in ctx.macro_signals)
    assert any("Fed rate:" in s for s in ctx.macro_signals)


@pytest.mark.asyncio
async def test_run_inflation_db_error_does_not_block_fed():
    """RuntimeError in inflation query is isolated; fed signal still appended."""

    async def mock_fetch(query, *args, **kwargs):
        if "ANY($1" in query:
            return []
        if "'CPIAUCNS'" in query:
            raise RuntimeError("DB timeout")
        if "'FEDFUNDS'" in query:
            return _rows(5.5, 5.5, 5.5)  # HOLDING
        return []

    async def mock_fetchrow(query, *args, **kwargs):
        return None

    pool = MagicMock()
    pool.fetch = mock_fetch
    pool.fetchrow = mock_fetchrow

    ctx = await MarketAnalyzerAgent.run(pool)

    assert ctx is not None
    assert not any("Inflation trend:" in s for s in ctx.macro_signals)
    assert "Fed rate: HOLDING" in ctx.macro_signals


@pytest.mark.asyncio
async def test_run_fed_db_error_does_not_block_inflation():
    """RuntimeError in fed query is isolated; inflation signal still appended."""

    async def mock_fetch(query, *args, **kwargs):
        if "ANY($1" in query:
            return []
        if "'CPIAUCNS'" in query:
            return _rows(3.9, 3.3, 3.0)  # RISING
        if "'FEDFUNDS'" in query:
            raise RuntimeError("connection reset")
        return []

    async def mock_fetchrow(query, *args, **kwargs):
        return None

    pool = MagicMock()
    pool.fetch = mock_fetch
    pool.fetchrow = mock_fetchrow

    ctx = await MarketAnalyzerAgent.run(pool)

    assert ctx is not None
    assert "Inflation trend: RISING (3-month)" in ctx.macro_signals
    assert not any("Fed rate:" in s for s in ctx.macro_signals)


@pytest.mark.asyncio
async def test_run_all_signals_missing_no_crash():
    """All queries return empty — neutral context, no trend signals, no crash."""

    async def mock_fetch(query, *args, **kwargs):
        return []

    async def mock_fetchrow(query, *args, **kwargs):
        return None

    pool = MagicMock()
    pool.fetch = mock_fetch
    pool.fetchrow = mock_fetchrow

    ctx = await MarketAnalyzerAgent.run(pool)

    assert ctx is not None
    assert ctx.vix is None
    assert ctx.yield_curve is None
    assert not any("Inflation trend:" in s for s in ctx.macro_signals)
    assert not any("Fed rate:" in s for s in ctx.macro_signals)

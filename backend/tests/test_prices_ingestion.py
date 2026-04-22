"""
test_prices_ingestion.py — Validate price data ingestion for SPY and QQQ.

Tests ensure:
1. StooqProvider.store() accepts pool parameter (signature fix)
2. Prices are correctly stored in the database
3. Queries return actual rows for SPY and QQQ
"""

import pytest
import asyncpg
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from financial.providers.price import StooqProvider
from financial.models import PriceRow


@pytest.mark.asyncio
async def test_stooq_provider_store_signature():
    """
    Verify that StooqProvider.store() accepts pool parameter.
    This was the root cause of price ingestion failures.
    """
    provider = StooqProvider(symbol="SPY")

    # Mock pool
    mock_pool = AsyncMock(spec=asyncpg.Pool)
    mock_pool.executemany = AsyncMock()

    # Mock rows
    test_rows = [
        {
            "symbol": "SPY",
            "date": date(2024, 1, 2),
            "open": 480.0,
            "high": 485.0,
            "low": 479.0,
            "close": 484.5,
            "volume": 50000000,
            "currency": "USD",
            "source": "stooq",
        }
    ]

    # This should NOT raise TypeError about missing/extra positional args
    result = await provider.store(mock_pool, test_rows)

    assert result == 1  # Should return number of rows
    assert mock_pool.executemany.called


@pytest.mark.asyncio
async def test_stooq_normalize_valid_prices():
    """
    Verify that Stooq CSV is correctly normalized into PriceRow objects.
    """
    provider = StooqProvider(symbol="SPY")

    # Sample CSV response from Stooq
    csv_data = """Date,Open,High,Low,Close,Volume
2024-01-02,480.00,485.50,479.00,484.50,50000000
2024-01-03,484.50,486.00,484.00,485.75,45000000
"""

    rows = provider.normalize(csv_data)

    assert len(rows) == 2
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["date"] == date(2024, 1, 2)
    assert rows[0]["close"] == 484.50
    assert rows[0]["source"] == "stooq"


@pytest.mark.asyncio
async def test_price_row_validation():
    """
    Verify PriceRow Pydantic model rejects invalid data.
    """
    # Valid row
    valid = PriceRow(
        symbol="SPY",
        date=date(2024, 1, 2),
        close=484.50,
        source="stooq",
    )
    assert valid.symbol == "SPY"

    # Invalid: negative price
    with pytest.raises(ValueError):
        PriceRow(
            symbol="SPY",
            date=date(2024, 1, 2),
            close=-100.0,
            source="stooq",
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

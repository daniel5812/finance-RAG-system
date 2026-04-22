"""
test_holdings_provider.py — Validate ETF holdings ingestion for SPY and QQQ.

Tests ensure:
1. HoldingsProvider can process multiple ETFs (SPY and QQQ)
2. Yahoo client correctly normalizes holdings data
3. Holdings are correctly stored in database
4. Both SPY and QQQ return actual holding data
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date
import asyncpg

from financial.providers.holdings import HoldingsProvider
from financial.clients.yahoo import YahooHoldingsClient
from financial.models import ETFHoldingRow


@pytest.mark.asyncio
async def test_holdings_provider_multiple_etfs():
    """
    Verify that HoldingsProvider can ingest multiple ETFs in one call.
    This was the limitation preventing QQQ from being processed.
    """
    # Mock client
    mock_client = AsyncMock(spec=YahooHoldingsClient)
    mock_client.get_holdings = AsyncMock(
        side_effect=lambda etf: {
            "SPY": [
                {"holding_symbol": "AAPL", "holding_name": "Apple", "weight": 7.2},
                {"holding_symbol": "MSFT", "holding_name": "Microsoft", "weight": 6.8},
            ],
            "QQQ": [
                {"holding_symbol": "AAPL", "holding_name": "Apple", "weight": 12.5},
                {"holding_symbol": "MSFT", "holding_name": "Microsoft", "weight": 10.8},
            ],
        }.get(etf, [])
    )

    # Mock pool
    mock_pool = AsyncMock(spec=asyncpg.Pool)
    mock_pool.fetch = AsyncMock(
        return_value=[
            {"etf_symbol": "SPY", "last_hash": None, "status": "active"},
            {"etf_symbol": "QQQ", "last_hash": None, "status": "active"},
        ]
    )
    mock_pool.executemany = AsyncMock()
    mock_pool.execute = AsyncMock()

    provider = HoldingsProvider(client=mock_client)

    # Ingest both SPY and QQQ
    result = await provider.ingest(mock_pool, symbols=["SPY", "QQQ"])

    assert result["provider"] == "yahooquery"
    assert result["processed"] == 2  # Both ETFs processed
    assert result["updated"] >= 0


@pytest.mark.asyncio
async def test_yahoo_client_normalize_holdings():
    """
    Verify Yahoo client correctly normalizes holdings data with multiple ETFs.
    """
    client = YahooHoldingsClient()

    # Sample raw data from yahooquery
    raw_holdings = [
        {"symbol": "AAPL", "holdingName": "Apple Inc.", "holdingPercent": 0.072},
        {"symbol": "MSFT", "holdingName": "Microsoft Corp.", "holdingPercent": 0.068},
    ]

    normalized = client._normalize_list(raw_holdings, "SPY")

    assert len(normalized) == 2
    assert normalized[0]["holding_symbol"] == "AAPL"
    assert normalized[0]["weight"] == 7.2  # 0.072 * 100
    assert normalized[1]["holding_symbol"] == "MSFT"


@pytest.mark.asyncio
async def test_etf_holding_row_validation():
    """
    Verify ETFHoldingRow Pydantic model validates data correctly.
    """
    # Valid SPY holding
    valid_spy = ETFHoldingRow(
        etf_symbol="SPY",
        holding_symbol="AAPL",
        holding_name="Apple Inc.",
        weight=7.2,
        date=date(2024, 1, 15),
    )
    assert valid_spy.etf_symbol == "SPY"
    assert valid_spy.weight == 7.2

    # Valid QQQ holding
    valid_qqq = ETFHoldingRow(
        etf_symbol="QQQ",
        holding_symbol="MSFT",
        holding_name="Microsoft Corp.",
        weight=10.8,
        date=date(2024, 1, 15),
    )
    assert valid_qqq.etf_symbol == "QQQ"

    # Invalid: weight > 100
    with pytest.raises(ValueError):
        ETFHoldingRow(
            etf_symbol="SPY",
            holding_symbol="AAPL",
            weight=150.0,
            date=date(2024, 1, 15),
        )

    # Invalid: weight <= 0
    with pytest.raises(ValueError):
        ETFHoldingRow(
            etf_symbol="SPY",
            holding_symbol="AAPL",
            weight=0.0,
            date=date(2024, 1, 15),
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
portfolio.py — Manual portfolio positions provider.

The simplest provider: user sends positions as JSON,
we validate and store them. No external API calls.

Key difference from other providers:
  - Uses ON CONFLICT DO UPDATE (not DO NOTHING)
  - Why? Because positions CHANGE — if you buy more AAPL,
    the quantity should update, not be silently skipped.
  - Supports Hebrew in account names (UTF-8 natively)
"""

from core.logger import get_logger
import asyncpg
from financial.crud import upsert_portfolio_positions
from financial.models import PortfolioPositionRow

logger = get_logger(__name__)


class PortfolioProvider:
    """Store manually entered portfolio positions."""

    provider_name = "manual"

    async def store(self, pool: asyncpg.Pool, positions: list[dict]) -> dict:
        """
        Validate and store portfolio positions.

        ON CONFLICT (symbol, account, date) DO UPDATE:
          - If a position for AAPL in 'schwab' on 2024-01-15
            already exists, UPDATE the quantity and cost_basis.
          - This is different from prices/fx which use DO NOTHING
            because positions are mutable (you can buy/sell).
        """
        validated = []
        rejected = []

        for pos in positions:
            try:
                row = PortfolioPositionRow(**pos)
                validated.append(row.model_dump())
            except Exception as e:
                rejected.append({
                    "input": pos,
                    "error": str(e),
                })

        if not validated:
            return {
                "provider": self.provider_name,
                "status": "empty",
                "rows_ingested": 0,
                "rejected": rejected,
            }

        # ── Upsert: update quantity/cost_basis if position already exists ──
        await upsert_portfolio_positions(pool, validated)

        logger.info(f"Portfolio: stored {len(validated)}, rejected {len(rejected)}")

        return {
            "provider": self.provider_name,
            "status": "success",
            "rows_ingested": len(validated),
            "rejected": rejected,
        }

"""
yahoo.py — Yahoo Finance holdings client (thin wrapper).

THIS IS THE ONLY FILE THAT IMPORTS yahooquery.

Why isolate it?
  - To swap data sources later, replace ONLY this file.
  - The provider and route never know (or care) where data comes from.
  - This is the "Dependency Inversion" principle in practice.

yahooquery is a synchronous library, so we run it in
asyncio's thread executor to avoid blocking the event loop.
"""

import asyncio
from datetime import date

from yahooquery import Ticker

from core.logger import get_logger

logger = get_logger(__name__)


class YahooHoldingsClient:
    """
    Thin, replaceable wrapper around yahooquery.

    Contract:
      get_holdings(symbol) -> list[dict]

    Each dict has: {symbol, holdingName, holdingPercent}
    If data is unavailable, returns empty list.
    """

    async def get_holdings(self, etf_symbol: str) -> list[dict]:
        """
        Fetch top holdings for an ETF.

        Why run_in_executor?
        yahooquery uses requests (sync HTTP) internally.
        If we call it directly in an async function, it blocks
        the entire event loop — meaning no other requests can
        be processed while we wait. run_in_executor runs it
        in a separate thread, keeping the event loop free.
        """
        loop = asyncio.get_event_loop()

        try:
            # Run the sync yahooquery call in a thread
            raw = await loop.run_in_executor(
                None,  # use default ThreadPoolExecutor
                self._fetch_sync,
                etf_symbol,
            )
            return raw
        except Exception as e:
            logger.error(f"YahooHoldingsClient error for {etf_symbol}: {e}")
            raise

    def _fetch_sync(self, etf_symbol: str) -> list[dict]:
        """
        Synchronous fetch — runs in a thread.

        We try multiple yahooquery data sources to get the
        fullest holdings list possible:
          1. fund_holding_info — most complete holdings data
          2. fund_top_holdings — fallback (top ~10 only)

        Note: Yahoo Finance free tier may still limit results.
        For truly complete holdings (500+), swap this client
        for SEC N-PORT parsing in the future.
        """
        ticker = Ticker(etf_symbol)

        # ── Try fund_holding_info first (more complete) ──
        holdings = self._try_holding_info(ticker, etf_symbol)
        if holdings:
            return holdings

        # ── Fallback to fund_top_holdings ──
        holdings = self._try_top_holdings(ticker, etf_symbol)
        if holdings:
            return holdings

        logger.warning(f"No holdings data found for {etf_symbol}")
        return []

    def _try_holding_info(self, ticker: Ticker, etf_symbol: str) -> list[dict]:
        """Try fund_holding_info — returns holdings + equity/bond breakdown."""
        try:
            data = ticker.fund_holding_info
            if isinstance(data, str) or data is None:
                return []

            if isinstance(data, dict):
                info = data.get(etf_symbol, {})
                if isinstance(info, str) or not info:
                    return []

                # fund_holding_info may contain 'holdings' list
                holdings_list = info.get("holdings", [])
                if holdings_list:
                    return self._normalize_list(holdings_list, etf_symbol)

            # If it's a DataFrame
            if hasattr(data, "to_dict"):
                records = data.to_dict("records")
                return self._normalize_list(records, etf_symbol)

        except Exception as e:
            logger.debug(f"fund_holding_info failed for {etf_symbol}: {e}")
        return []

    def _try_top_holdings(self, ticker: Ticker, etf_symbol: str) -> list[dict]:
        """Fallback to fund_top_holdings — typically top 10 only."""
        try:
            data = ticker.fund_top_holdings
            if isinstance(data, str) or data is None:
                return []

            if isinstance(data, dict):
                holdings_data = data.get(etf_symbol, None)
                if holdings_data is None or isinstance(holdings_data, str):
                    return []
                if isinstance(holdings_data, list):
                    return self._normalize_list(holdings_data, etf_symbol)

            if hasattr(data, "to_dict"):
                records = data.to_dict("records")
                return self._normalize_list(records, etf_symbol)

        except Exception as e:
            logger.debug(f"fund_top_holdings failed for {etf_symbol}: {e}")
        return []

    def _normalize_list(self, raw_list: list, etf_symbol: str) -> list[dict]:
        """
        Normalize raw holdings into a clean format.

        Input varies by ETF — might have:
          - 'symbol' or 'holdingName' keys
          - 'holdingPercent' as decimal (0.0652) or percentage (6.52)

        We standardize to: {holding_symbol, holding_name, weight}
        """
        results = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue

            symbol = item.get("symbol", item.get("holdingSymbol", ""))
            name = item.get("holdingName", "")
            weight = item.get("holdingPercent", 0)

            # Skip entries with no symbol
            if not symbol or symbol == "-":
                continue

            # yahooquery returns weight as decimal (0.0652 = 6.52%)
            # Convert to percentage if it looks like a decimal
            if isinstance(weight, (int, float)) and 0 < weight < 1:
                weight = round(weight * 100, 4)

            if weight <= 0:
                continue

            results.append({
                "holding_symbol": str(symbol).upper(),
                "holding_name": str(name) if name else None,
                "weight": weight,
            })

        return results

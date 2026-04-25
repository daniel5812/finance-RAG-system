"""
intelligence/static_data.py — Shared static reference data for the intelligence layer.

Single source of truth for:
  - _SECTOR_MAP: ticker → sector string
  - _SPY_SECTOR_WEIGHTS: sector → approximate % weight in SPY
  - _ASSET_CLASSES: asset class name → set of qualifying sector strings

Used by: PortfolioGapAnalysisAgent, BenchmarkComparisonAgent
"""

# ── SPY sector weights (approximate, as of 2025) ─────────────────────────────
# Source: SPDR portfolio composition, major sector ETFs
_SPY_SECTOR_WEIGHTS: dict[str, float] = {
    "Technology":              31.0,
    "Financials":              13.0,
    "Healthcare":              12.5,
    "Consumer Discretionary":  10.5,
    "Industrials":              8.5,
    "Communication Services":   8.0,
    "Consumer Staples":         5.5,
    "Energy":                   4.0,
    "Materials":                2.5,
    "Real Estate":              2.5,
    "Utilities":                2.0,
}

# ── Asset class membership ────────────────────────────────────────────────────
_ASSET_CLASSES: dict[str, set[str]] = {
    "US Equities": {
        "Technology", "Financials", "Healthcare", "Consumer Discretionary",
        "Industrials", "Communication Services", "Consumer Staples", "Energy",
        "Materials", "Utilities", "Real Estate",
        "US Broad Market", "US Total Market", "US Large Cap", "US Small Cap",
        "Technology Heavy",
    },
    "International Equities": {
        "International Developed", "Emerging Markets",
    },
    "Fixed Income": {
        "US Bond Market", "Long-Term Bonds", "Short-Term Bonds",
        "Intermediate Bonds", "Investment Grade Bonds", "High Yield Bonds",
        "Emerging Market Bonds",
    },
    "Commodities": {"Commodities"},
    "Real Estate": {"Real Estate"},
}

# ── Ticker → sector map ───────────────────────────────────────────────────────
# Covers common US large-cap stocks, sector ETFs, broad-market ETFs, and
# fixed-income ETFs. Add tickers here to improve sector coverage.
_SECTOR_MAP: dict[str, str] = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "GOOG": "Technology", "META": "Technology", "NVDA": "Technology",
    "AMD": "Technology", "INTC": "Technology", "CRM": "Technology",
    "ORCL": "Technology", "CSCO": "Technology", "ADBE": "Technology",
    "QCOM": "Technology", "TXN": "Technology", "AVGO": "Technology",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "HD": "Consumer Discretionary",
    "MCD": "Consumer Discretionary", "SBUX": "Consumer Discretionary",
    # Financials
    "JPM": "Financials", "GS": "Financials", "BAC": "Financials",
    "WFC": "Financials", "V": "Financials", "MA": "Financials",
    "MS": "Financials", "C": "Financials", "BLK": "Financials",
    # Healthcare
    "JNJ": "Healthcare", "PFE": "Healthcare", "MRK": "Healthcare",
    "ABBV": "Healthcare", "LLY": "Healthcare", "UNH": "Healthcare",
    "BMY": "Healthcare", "AMGN": "Healthcare", "GILD": "Healthcare",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "SLB": "Energy", "EOG": "Energy",
    # Consumer Staples
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "WMT": "Consumer Staples", "COST": "Consumer Staples", "PM": "Consumer Staples",
    # Communication Services
    "NFLX": "Communication Services", "DIS": "Communication Services",
    "T": "Communication Services", "VZ": "Communication Services",
    # Industrials
    "BA": "Industrials", "CAT": "Industrials", "GE": "Industrials",
    "RTX": "Industrials", "HON": "Industrials", "UPS": "Industrials",
    # Materials
    "LIN": "Materials", "APD": "Materials", "NEM": "Materials",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
    # Real Estate
    "AMT": "Real Estate", "PLD": "Real Estate", "CCI": "Real Estate",
    # Commodities
    "GLD": "Commodities", "SLV": "Commodities", "USO": "Commodities",
    # Sector ETFs
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Healthcare", "XLU": "Utilities", "XLB": "Materials",
    "XLC": "Communication Services", "XLI": "Industrials", "XLRE": "Real Estate",
    # Broad-market ETFs
    "SPY": "US Broad Market", "IVV": "US Broad Market", "VOO": "US Broad Market",
    "VTI": "US Total Market", "QQQ": "Technology Heavy",
    "IWM": "US Small Cap", "DIA": "US Large Cap",
    # International
    "VEA": "International Developed", "IEFA": "International Developed",
    "VWO": "Emerging Markets", "EEM": "Emerging Markets",
    # Real estate ETF
    "VNQ": "Real Estate",
    # Fixed income ETFs
    "AGG": "US Bond Market", "BND": "US Bond Market",
    "TLT": "Long-Term Bonds", "SHY": "Short-Term Bonds", "IEF": "Intermediate Bonds",
    "HYG": "High Yield Bonds", "LQD": "Investment Grade Bonds",
    "EMB": "Emerging Market Bonds",
}

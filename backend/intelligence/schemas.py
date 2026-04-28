"""
intelligence/schemas.py — Structured I/O contracts for every agent in the
Investment Intelligence Layer.

Design rules:
  • Every agent has a typed input and a typed output.
  • All fields are Optional with safe defaults so partial data never crashes the pipeline.
  • confidence fields use "high/medium/low/none" strings throughout.
  • score fields are float 0.0–1.0.
  • The final IntelligenceReport is the single object injected into LLM context.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────

class MarketRegime(str, Enum):
    RISK_ON      = "risk_on"       # easy money, growth favoured
    RISK_OFF     = "risk_off"      # tight money, defensive favoured
    STAGFLATION  = "stagflation"   # high inflation + slowing growth
    RECESSION    = "recession"     # GDP contraction
    RECOVERY     = "recovery"      # post-recession expansion
    NEUTRAL      = "neutral"       # mixed or insufficient data


class RecommendationAction(str, Enum):
    BUY              = "buy"
    HOLD             = "hold"
    REDUCE           = "reduce"
    AVOID            = "avoid"
    INSUFFICIENT_DATA = "insufficient_data"


class AssetType(str, Enum):
    STOCK   = "stock"
    ETF     = "etf"
    BOND    = "bond"
    CRYPTO  = "crypto"
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────
# Agent: UserProfiler output
# ─────────────────────────────────────────────────────────────

class UserInvestmentProfile(BaseModel):
    user_id: str
    risk_tolerance: str = "medium"          # low / medium / high
    experience_level: str = "intermediate"  # beginner / intermediate / expert
    preferred_style: str = "deep"           # simple / deep
    interests: list[str] = Field(default_factory=list)
    time_horizon: str = "medium"            # short / medium / long
    custom_persona: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Agent: MarketAnalyzer output
# ─────────────────────────────────────────────────────────────

class MarketContext(BaseModel):
    regime: MarketRegime = MarketRegime.NEUTRAL
    fed_rate: Optional[float] = None        # FEDFUNDS latest value
    inflation: Optional[float] = None       # CPIAUCNS latest value
    unemployment: Optional[float] = None    # UNRATE latest value
    gdp_latest: Optional[float] = None      # GDP latest value
    usd_ils_rate: Optional[float] = None    # latest USD/ILS
    yield_curve: Optional[float] = None     # 10Y-2Y Treasury spread (DGS10 - DGS2)
    vix: Optional[float] = None             # CBOE Volatility Index (VIXCLS)
    regime_confidence: str = "low"          # high / medium / low
    macro_signals: list[str] = Field(default_factory=list)
    data_staleness_warning: Optional[str] = None  # set if macro data > 7 days old


# ─────────────────────────────────────────────────────────────
# Agent: AssetProfiler output
# ─────────────────────────────────────────────────────────────

class AssetProfile(BaseModel):
    ticker: str
    asset_type: AssetType = AssetType.UNKNOWN
    sector: Optional[str] = None                           # e.g. "Technology", "Financials"
    recent_price: Optional[float] = None
    price_7d_change_pct: Optional[float] = None            # short-term momentum
    price_30d_change_pct: Optional[float] = None           # medium-term trend
    price_volatility_signal: str = "unknown"               # low / medium / high (categorical)
    annualized_vol: Optional[float] = None                 # actual annualized vol (e.g. 0.22 = 22%)
    beta_vs_spy: Optional[float] = None                    # beta relative to SPY
    momentum: Optional[str] = None                         # strong_up / up / flat / down / strong_down
    etf_top_holdings: list[str] = Field(default_factory=list)
    data_freshness: str = "unknown"                        # days since last price
    source_confidence: str = "low"                         # high / medium / low


# ─────────────────────────────────────────────────────────────
# Agent: ScoringEngine output (DETERMINISTIC — no LLM)
# ─────────────────────────────────────────────────────────────

class AssetScore(BaseModel):
    ticker: str
    market_fit_score: float = 0.5       # how well asset fits current regime
    user_fit_score: float = 0.5         # how well asset fits user profile
    diversification_score: float = 0.5  # how much it reduces concentration
    risk_alignment_score: float = 0.5   # asset risk vs user risk tolerance
    momentum_score: float = 0.5         # trend alignment score
    composite_score: float = 0.5        # weighted aggregate
    score_factors: dict[str, str] = Field(default_factory=dict)
    # human-readable factor explanations, e.g.:
    # {"market_fit": "Risk-off regime favours defensive; growth stocks penalised"}
    data_coverage: str = "partial"      # full / partial / minimal


# ─────────────────────────────────────────────────────────────
# Per-Position Enrichment (computed from prices and cost_basis)
# ─────────────────────────────────────────────────────────────

class PositionDetail(BaseModel):
    """
    Deterministically computed enrichment for a single position.
    All fields are optional — missing prices → null fields (never zero or synthetic values).
    """
    entry_date: Optional[date] = None
    current_price: Optional[float] = None
    position_value: Optional[float] = None      # qty × current_price
    position_pnl: Optional[float] = None        # position_value − qty × cost_basis
    position_pnl_pct: Optional[float] = None    # (pnl / invested_value) × 100
    portfolio_weight: Optional[float] = None    # (position_value / total_market_value) × 100


# ─────────────────────────────────────────────────────────────
# Data Normalization Layer output
# ─────────────────────────────────────────────────────────────

class NormalizedPortfolio(BaseModel):
    """
    Deterministically computed financial metrics from raw portfolio_positions rows.
    All arithmetic is done in data_normalizer.py — the LLM MUST NOT recompute these.

    Schema note: cost_basis = avg price paid per unit (per schema.sql comment).
    total_invested = SUM(quantity × cost_basis) per position.

    Enrichment fields (all optional, computed when prices are available):
      - positions: dict[str, PositionDetail] — per-position market metrics
      - total_market_value: total position_value across all positions with known prices
      - prices_as_of: staleness indicator — date of most recent price lookup
    """
    total_positions: int = 0
    total_invested: Optional[float] = None          # SUM(quantity × cost_basis) — total capital deployed
    allocation_pct: dict[str, float] = Field(default_factory=dict)   # ticker → % of total_invested
    largest_position_ticker: Optional[str] = None
    largest_position_pct: Optional[float] = None    # % of total_invested
    currency: str = "USD"

    # Enrichment fields (NEW)
    positions: dict[str, PositionDetail] = Field(default_factory=dict)  # ticker → computed detail
    total_market_value: Optional[float] = None      # SUM(qty × price) — total market value
    prices_as_of: Optional[date] = None             # staleness label

    data_note: str = (
        "Allocation % is based on cost_basis × quantity (invested capital). "
        "Current market value and P&L are NOT available without live prices."
    )


# ─────────────────────────────────────────────────────────────
# Agent: PortfolioGapAnalysis output
# ─────────────────────────────────────────────────────────────

class SectorWeight(BaseModel):
    sector: str
    portfolio_pct: float     # % of portfolio in this sector
    benchmark_pct: float     # SPY reference weight
    gap_pct: float           # portfolio - benchmark (negative = underweight)


class PortfolioGapAnalysis(BaseModel):
    """
    Portfolio-level analysis run when no specific tickers are mentioned.
    Compares sector distribution against a benchmark and identifies missing asset classes.
    """
    sector_weights: list[SectorWeight] = Field(default_factory=list)
    missing_asset_classes: list[str] = Field(default_factory=list)    # e.g. ["Fixed Income", "International"]
    overweight_sectors: list[str] = Field(default_factory=list)       # sectors > 10% above benchmark
    underweight_sectors: list[str] = Field(default_factory=list)      # sectors > 10% below benchmark
    concentration_score: float = 0.0                                   # HHI-based 0-1 (higher = more concentrated)
    diversification_gaps: list[str] = Field(default_factory=list)     # human-readable gap descriptions
    suggested_directions: list[str] = Field(default_factory=list)     # actionable diversification directions
    data_coverage: str = "partial"                                     # full / partial / none


# ─────────────────────────────────────────────────────────────
# Validation Agent output
# ─────────────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    """
    Sanity-check output from ValidationAgent.
    Flags logical contradictions and numeric inconsistencies in the IntelligenceReport.
    If issues are found, pipeline_confidence is downgraded before reaching the LLM.
    """
    passed: bool = True
    flags: list[str] = Field(default_factory=list)          # human-readable issues found
    confidence_override: Optional[str] = None               # if set, replaces pipeline_confidence


# ─────────────────────────────────────────────────────────────
# Agent: PortfolioFit output
# ─────────────────────────────────────────────────────────────

class PortfolioFitAnalysis(BaseModel):
    tickers_in_portfolio: list[str] = Field(default_factory=list)
    tickers_mentioned: list[str] = Field(default_factory=list)
    already_held: list[str] = Field(default_factory=list)   # tickers_mentioned ∩ portfolio
    concentration_risk: str = "unknown"                     # low / medium / high (by value, not count)
    dominant_ticker: Optional[str] = None                   # ticker with highest allocation by value
    dominant_sector: Optional[str] = None                   # future: when sector data available
    current_exposure_summary: str = ""
    normalized_portfolio: Optional[NormalizedPortfolio] = None
    # e.g. "Portfolio is 60% tech (AAPL, MSFT, NVDA); adding GOOGL increases concentration"


# ─────────────────────────────────────────────────────────────
# Step 3: Benchmark Comparison output
# ─────────────────────────────────────────────────────────────

class BenchmarkSnapshot(BaseModel):
    """
    Metrics for a single benchmark (SPY or QQQ) at comparison time.
    hhi is suppressed (None) when holdings coverage < 80% to avoid
    misleading comparisons from partial data.
    """
    symbol: str
    hhi: Optional[float] = None              # None when coverage_pct < 80%
    holding_count: Optional[int] = None      # rows fetched from etf_holdings
    coverage_pct: Optional[float] = None     # SUM(weight) of fetched holdings
    top_sectors: dict[str, float] = Field(default_factory=dict)  # sector → %
    data_note: Optional[str] = None          # set when HHI suppressed or sectors partial


class BenchmarkComparison(BaseModel):
    """
    Deterministic comparison of the user portfolio against SPY and QQQ.
    All arithmetic is computed in BenchmarkComparisonAgent — the LLM MUST NOT
    recompute or contradict these values.

    weight_basis indicates which portfolio weight source was used:
      "market_value" — PositionDetail.portfolio_weight (requires prices)
      "cost_basis"   — NormalizedPortfolio.allocation_pct (always available)
      "mixed"        — market_value for priced positions, cost_basis for unpriced
    """
    portfolio_hhi: Optional[float] = None
    weight_basis: str = "cost_basis"
    benchmarks: list[BenchmarkSnapshot] = Field(default_factory=list)
    concentration_vs_spy: Optional[str] = None   # "more_concentrated"|"comparable"|"less_concentrated"
    concentration_vs_qqq: Optional[str] = None
    overweight_vs_spy: list[str] = Field(default_factory=list)   # ["NVDA: port=12.1% spy=4.1% (+8.0pp)"]
    underweight_vs_spy: list[str] = Field(default_factory=list)
    portfolio_overlap_spy_pct: Optional[float] = None
    portfolio_overlap_qqq_pct: Optional[float] = None
    data_note: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Agent: Recommendation output
# ─────────────────────────────────────────────────────────────

class AssetRecommendation(BaseModel):
    ticker: str
    action: RecommendationAction = RecommendationAction.INSUFFICIENT_DATA
    confidence: str = "low"             # high / medium / low
    reasoning: str = ""                 # LLM-written narrative
    trade_offs: str = ""                # LLM-written trade-off summary
    risks: list[str] = Field(default_factory=list)
    composite_score: Optional[float] = None


# ─────────────────────────────────────────────────────────────
# Final Intelligence Report — injected into LLM context
# ─────────────────────────────────────────────────────────────

class IntelligenceReport(BaseModel):
    """
    Single structured object produced by the Intelligence Layer.
    Every field is Optional — partial reports are valid and useful.
    The context_builder converts this into a prompt-injectable string.
    """
    user_profile: Optional[UserInvestmentProfile] = None
    market_context: Optional[MarketContext] = None
    asset_profiles: list[AssetProfile] = Field(default_factory=list)
    portfolio_fit: Optional[PortfolioFitAnalysis] = None
    normalized_portfolio: Optional[NormalizedPortfolio] = None   # pre-computed financial metrics
    portfolio_gap_analysis: Optional[PortfolioGapAnalysis] = None  # sector/class gap vs benchmark
    benchmark_comparison: Optional[BenchmarkComparison] = None   # Step 3: SPY/QQQ comparison
    recommendations: list[AssetRecommendation] = Field(default_factory=list)
    asset_scores: list[AssetScore] = Field(default_factory=list)
    validation_result: Optional[ValidationResult] = None         # post-generation sanity check

    # Pipeline provenance
    agents_ran: list[str] = Field(default_factory=list)
    agents_skipped: list[str] = Field(default_factory=list)
    pipeline_confidence: str = "low"   # high / medium / low — set deterministically, never by LLM

    # LLM mode — determines which response structure the LLM should use
    # "explanation": factual, concise answer
    # "synthesis": advisory portfolio-level analysis (no specific assets queried)
    # "document_analysis": document extraction and analysis
    llm_mode: str = "explanation"

    @property
    def has_recommendations(self) -> bool:
        return bool(self.recommendations) and any(
            r.action != RecommendationAction.INSUFFICIENT_DATA
            for r in self.recommendations
        )

    @property
    def has_market_context(self) -> bool:
        return self.market_context is not None and self.market_context.regime != MarketRegime.NEUTRAL

    @property
    def is_empty(self) -> bool:
        return (
            not self.user_profile
            and not self.market_context
            and not self.asset_profiles
            and not self.normalized_portfolio
            and not self.recommendations
        )

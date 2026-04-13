import asyncio
import json
from intelligence.schemas import (
    IntelligenceReport, MarketContext, MarketRegime, AssetProfile,
    AssetType, UserInvestmentProfile, PortfolioFitAnalysis,
    NormalizedPortfolio, PortfolioGapAnalysis, SectorWeight
)
from intelligence.context_builder import build_intelligence_context

async def verify_context_builder():
    print("--- Testing Context Builder with New Signals ---")
    
    report = IntelligenceReport(
        pipeline_confidence="high",
        llm_mode="synthesis",
        agents_ran=["MarketAnalyzerAgent", "PortfolioFitAgent", "PortfolioGapAnalysisAgent"]
    )
    
    # 1. Market Context
    report.market_context = MarketContext(
        regime=MarketRegime.RISK_OFF,
        fed_rate=5.25,
        inflation=3.1,
        unemployment=3.8,
        gdp_latest=2.1,
        yield_curve=-0.15,
        vix=28.5,
        regime_confidence="high",
        macro_signals=["Yield curve inversion", "Rising VIX"]
    )
    
    # 2. User Profile
    report.user_profile = UserInvestmentProfile(
        user_id="test_user",
        risk_tolerance="medium",
        experience_level="intermediate",
        preferred_style="deep",
        time_horizon="long"
    )
    
    # 3. Portfolio Fit
    report.portfolio_fit = PortfolioFitAnalysis(
        current_exposure_summary="Portfolio is 40% Technology, 20% Financials.",
        concentration_risk="high",
        dominant_ticker="AAPL",
        dominant_sector="Technology",
        already_held=["AAPL", "MSFT"]
    )
    
    # 4. Gap Analysis
    report.portfolio_gap_analysis = PortfolioGapAnalysis(
        data_coverage="full",
        concentration_score=0.28,
        sector_weights=[
            SectorWeight(sector="Technology", portfolio_pct=40.0, benchmark_pct=28.0, gap_pct=12.0),
            SectorWeight(sector="Energy", portfolio_pct=2.0, benchmark_pct=5.0, gap_pct=-3.0)
        ],
        overweight_sectors=["Technology"],
        underweight_sectors=["Energy"],
        missing_asset_classes=["Fixed Income"],
        diversification_gaps=["Heavy tech concentration"],
        suggested_directions=["Add defensive bond exposure"]
    )
    
    # context = build_intelligence_context(report)
    # print(context.encode('utf-8'))
    context = build_intelligence_context(report)
    
    # Verify presence of new fields
    assert "Fed Funds Rate: 5.25%" in context
    assert "Inflation (CPI): 3.1%" in context
    assert "Unemployment: 3.8%" in context
    assert "GDP Growth (latest): +2.1%" in context
    assert "Yield Curve (10Y-2Y): -0.150%" in context
    assert "VIX: 28.5" in context
    assert "Concentration Risk: HIGH" in context
    assert "Dominant Asset:     AAPL" in context
    assert "Dominant Sector:    Technology" in context
    
    print("\n--- Context Builder Verification PASSED ---")

if __name__ == "__main__":
    asyncio.run(verify_context_builder())

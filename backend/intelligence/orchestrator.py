"""
intelligence/orchestrator.py — IntelligenceOrchestrator

Responsibility:
  Decide which agents to run for a given query, execute them (with parallelism
  where safe), and return a single IntelligenceReport to chat_service.py.

Entry point:
  IntelligenceOrchestrator.run(...)

Agent execution rules:
  - ALWAYS run: UserProfilerAgent (pure transform, instant)
  - ALWAYS run when pool available: MarketAnalyzerAgent (reads global macro)
  - CONDITIONAL on tickers present: AssetProfilerAgent, ScoringEngineAgent,
    PortfolioFitAgent, RecommendationAgent
  - ADVISORY queries WITHOUT tickers → run PortfolioGapAnalysisAgent instead
  - ADVISORY/ANALYTICAL queries: full pipeline
  - FACTUAL queries (e.g. "what is the fed rate?"): market only, skip scoring

LLM mode selection:
  - "document_analysis": document/filing analysis query
  - "synthesis": advisory query without specific tickers (portfolio-level)
  - "explanation": everything else (factual, with specific tickers)

Pipeline parallelism:
  - MarketAnalyzerAgent + AssetProfilerAgent + PortfolioFitAgent run in parallel
    (they all read different DB tables and have no dependencies on each other)
  - ScoringEngineAgent runs after all three above complete (needs their outputs)
  - RecommendationAgent runs after ScoringEngineAgent
  - PortfolioGapAnalysisAgent runs after PortfolioFitAgent (needs normalized portfolio)

Failure isolation:
  - Each agent is wrapped in try/except
  - Failed agents contribute empty/default values
  - report.agents_skipped is populated for observability
  - The pipeline NEVER crashes chat_service.py — it always returns a report

Multi-tenancy:
  - owner_id is passed to PortfolioFitAgent only
  - MarketAnalyzer and AssetProfiler query global tables (no owner_id needed)
  - UserProfilerAgent is a pure transform (no DB)
"""

from __future__ import annotations

import asyncio
import re

import asyncpg

from core.logger import get_logger
from intelligence.agents.asset_profiler import AssetProfilerAgent
from intelligence.agents.market_analyzer import MarketAnalyzerAgent
from intelligence.agents.portfolio_fit import PortfolioFitAgent
from intelligence.agents.portfolio_gap_analysis import PortfolioGapAnalysisAgent
from intelligence.agents.recommendation import RecommendationAgent
from intelligence.agents.scoring_engine import ScoringEngineAgent
from intelligence.agents.user_profiler import UserProfilerAgent
from intelligence.agents.validation import ValidationAgent
from intelligence.schemas import IntelligenceReport, MarketContext, UserInvestmentProfile

logger = get_logger(__name__)

# ── Ticker extraction (conservative — only explicit ALLCAPS tokens 1-5 chars) ─
_TICKER_RE = re.compile(r'\b([A-Z]{1,5})\b')
_TICKER_BLACKLIST = {
    "I", "A", "AN", "THE", "AND", "OR", "IS", "IN", "IF", "BE",
    "DO", "CAN", "MAY", "BY", "TO", "OF", "FOR", "ON", "AT",
    "YES", "NO", "US", "UK", "EU", "GDP", "CPI", "FED", "USD",
    "ILS", "EUR", "GBP", "JPY", "CHF", "FX", "ETF", "SEC", "AI",
    "ML", "IT", "TV", "CEO", "CFO", "IPO", "ESG", "PE", "YTD",
}

# Intent keywords that trigger full pipeline
_ADVISORY_KEYWORDS = {
    "recommend", "recommendation", "buy", "sell", "invest", "should i",
    "worth", "good investment", "portfolio", "position", "add", "hold",
    "reduce", "increase", "allocate", "allocation", "exposure",
    # Hebrew
    "כדאי", "להשקיע", "המלצה", "לקנות", "למכור", "תיק", "חשיפה",
}

# Keywords that indicate document analysis mode
_DOCUMENT_KEYWORDS = {
    "report", "filing", "annual", "quarterly", "10-k", "10-q", "document",
    "read", "analyze", "analysis of", "what does the", "according to",
    "based on the document", "in the report", "from the document",
}


class IntelligenceOrchestrator:
    """
    Top-level controller for the Investment Intelligence Layer.
    Called from chat_service.py after context retrieval.
    """

    @staticmethod
    async def run(
        question: str,
        intent: str,                     # factual / analytical / advisory
        raw_profile: dict | None,        # from UserProfileService.get_profile()
        owner_id: str | None,
        pool: asyncpg.Pool | None,
    ) -> IntelligenceReport:
        """
        Build IntelligenceReport for the current request.
        Always returns a valid IntelligenceReport — never raises.
        """
        report = IntelligenceReport()

        try:
            # ── Stage 0: UserProfilerAgent (instant, no DB) ──────────────
            user_profile = UserProfilerAgent.run(raw_profile)
            report.user_profile = user_profile
            report.agents_ran.append("UserProfilerAgent")

            # ── Determine LLM mode ────────────────────────────────────────
            tickers = _extract_tickers(question)
            llm_mode = _select_llm_mode(question, intent, tickers)
            report.llm_mode = llm_mode

            if not pool:
                report.agents_skipped.append("all_db_agents: no pool")
                report.pipeline_confidence = "none"
                return report

            # ── Decide pipeline depth ────────────────────────────────────
            run_full = _needs_full_pipeline(question, intent, tickers)

            # ── Stage 1: Parallel DB reads ───────────────────────────────
            # MarketAnalyzer, AssetProfiler, PortfolioFit are independent
            parallel_tasks: dict[str, asyncio.Task] = {}

            parallel_tasks["market"] = asyncio.create_task(
                MarketAnalyzerAgent.run(pool)
            )

            if run_full and tickers:
                parallel_tasks["assets"] = asyncio.create_task(
                    AssetProfilerAgent.run(tickers, pool)
                )

            if run_full and owner_id:
                parallel_tasks["portfolio"] = asyncio.create_task(
                    PortfolioFitAgent.run(tickers, owner_id, pool)
                )

            # Await all parallel tasks
            parallel_results = {}
            for name, task in parallel_tasks.items():
                try:
                    parallel_results[name] = await task
                    report.agents_ran.append(f"{name.capitalize()}Agent")
                except Exception as exc:
                    logger.warning(
                        f'{{"event": "orchestrator", "agent": "{name}", '
                        f'"status": "failed", "error": "{exc}"}}'
                    )
                    report.agents_skipped.append(f"{name}Agent: {exc}")

            # Populate report from parallel results
            market_ctx: MarketContext = parallel_results.get("market", MarketContext())
            report.market_context = market_ctx

            asset_profiles = parallel_results.get("assets", [])
            report.asset_profiles = asset_profiles

            portfolio_fit = parallel_results.get("portfolio")
            if portfolio_fit:
                report.portfolio_fit = portfolio_fit
                # Surface the normalized portfolio at the top-level report
                if portfolio_fit.normalized_portfolio:
                    report.normalized_portfolio = portfolio_fit.normalized_portfolio

            # ── Portfolio Gap Analysis (synthesis mode / no tickers) ─────
            # Runs when advisory/analytical intent but no specific tickers — provides
            # portfolio-level structural analysis as the primary intelligence output.
            if run_full and not tickers and report.normalized_portfolio:
                try:
                    port_tickers_list = (
                        report.portfolio_fit.tickers_in_portfolio
                        if report.portfolio_fit else []
                    )
                    gap_analysis = PortfolioGapAnalysisAgent.run(
                        normalized_portfolio=report.normalized_portfolio,
                        portfolio_tickers=port_tickers_list,
                    )
                    report.portfolio_gap_analysis = gap_analysis
                    report.agents_ran.append("PortfolioGapAnalysisAgent")
                except Exception as exc:
                    logger.warning(
                        f'{{"event": "orchestrator", "agent": "PortfolioGapAnalysisAgent", '
                        f'"status": "failed", "error": "{exc}"}}'
                    )
                    report.agents_skipped.append(f"PortfolioGapAnalysisAgent: {exc}")

            # ── Stage 2: Scoring (depends on stage 1) ───────────────────
            if run_full and asset_profiles:
                try:
                    port_tickers = (
                        report.portfolio_fit.tickers_in_portfolio
                        if report.portfolio_fit else []
                    )
                    scores = ScoringEngineAgent.run(
                        asset_profiles=asset_profiles,
                        market_context=market_ctx,
                        user_profile=user_profile,
                        portfolio_tickers=port_tickers,
                    )
                    report.asset_scores = scores
                    report.agents_ran.append("ScoringEngineAgent")
                except Exception as exc:
                    logger.warning(
                        f'{{"event": "orchestrator", "agent": "ScoringEngineAgent", '
                        f'"status": "failed", "error": "{exc}"}}'
                    )
                    report.agents_skipped.append(f"ScoringEngineAgent: {exc}")
                    scores = []

                # ── Stage 3: Recommendations (depends on scoring) ────────
                if report.asset_scores:
                    try:
                        recommendations = await RecommendationAgent.run(
                            scores=report.asset_scores,
                            asset_profiles=asset_profiles,
                            market_context=market_ctx,
                            user_profile=user_profile,
                        )
                        report.recommendations = recommendations
                        report.agents_ran.append("RecommendationAgent")
                    except Exception as exc:
                        logger.warning(
                            f'{{"event": "orchestrator", "agent": "RecommendationAgent", '
                            f'"status": "failed", "error": "{exc}"}}'
                        )
                        report.agents_skipped.append(f"RecommendationAgent: {exc}")

            else:
                if run_full:
                    report.agents_skipped.append("ScoringEngineAgent: no tickers")
                    report.agents_skipped.append("RecommendationAgent: no scores")
                else:
                    report.agents_skipped.append("full_pipeline: factual_query")

            # ── Pipeline confidence (base — deterministic from data quality) ─
            report.pipeline_confidence = _compute_pipeline_confidence(report)
            _confidence_before_validation = report.pipeline_confidence

            # ── Stage 4: Validation (runs AFTER base confidence is set) ─────
            # ValidationAgent may downgrade pipeline_confidence if it finds issues.
            _downgrade_happened = False
            _validation_flags_count = 0
            try:
                validation_result = ValidationAgent.run(report)
                report.validation_result = validation_result
                report.agents_ran.append("ValidationAgent")

                _validation_flags_count = len(validation_result.flags) if validation_result.flags else 0

                if validation_result.confidence_override:
                    _downgrade_happened = (validation_result.confidence_override != _confidence_before_validation)
                    report.pipeline_confidence = validation_result.confidence_override

                # ─ Validation Stage: Track confidence changes ─
                logger.info(
                    f'{{"event": "validation_stage_complete", '
                    f'"confidence_before": "{_confidence_before_validation}", '
                    f'"confidence_after": "{report.pipeline_confidence}", '
                    f'"downgrade_happened": {_downgrade_happened}, '
                    f'"validation_flags_count": {_validation_flags_count}, '
                    f'"validation_passed": {validation_result.passed}}}'
                )
            except Exception as exc:
                logger.warning(
                    f'{{"event": "orchestrator", "agent": "ValidationAgent", '
                    f'"status": "failed", "error": "{exc}"}}'
                )
                report.agents_skipped.append(f"ValidationAgent: {exc}")

            logger.info(
                f'{{"event": "intelligence_orchestrator", "status": "ok", '
                f'"ran": {report.agents_ran}, '
                f'"tickers": {tickers}, '
                f'"llm_mode": "{report.llm_mode}", '
                f'"confidence": "{report.pipeline_confidence}"}}'
            )

        except Exception as exc:
            logger.error(
                f'{{"event": "intelligence_orchestrator", "status": "critical_error", '
                f'"error": "{exc}"}}'
            )
            report.agents_skipped.append(f"orchestrator_error: {exc}")
            report.pipeline_confidence = "none"

        return report


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _extract_tickers(text: str) -> list[str]:
    """Extract plausible ticker symbols from question/context text."""
    candidates = _TICKER_RE.findall(text)
    return [t for t in dict.fromkeys(candidates) if t not in _TICKER_BLACKLIST][:5]


def _select_llm_mode(question: str, intent: str, tickers: list[str]) -> str:
    """
    Determine how the LLM should frame its response.

    - "document_analysis": user asking to analyze a specific document/filing
    - "synthesis": advisory query at portfolio level, no specific tickers
    - "explanation": specific asset query, factual, or default
    """
    q_lower = question.lower()

    # 1. Document focused -> document_analysis
    if any(kw in q_lower for kw in _DOCUMENT_KEYWORDS):
        return "document_analysis"

    # 2. General strategy / no specific assets -> advisory
    is_general_advisory = not tickers and (
        intent == "advisory" or any(kw in q_lower for kw in _ADVISORY_KEYWORDS)
    )
    if is_general_advisory:
        return "advisory"

    # 3. Specific assets mentioned
    if tickers:
        # Check if the user is asking about the portfolio's relationship to the assets
        is_portfolio_query = any(kw in q_lower for kw in ("portfolio", "my positions", "allocation", "holdings"))
        return "synthesis" if is_portfolio_query else "explanation"

    # 4. Fallback to explanation for basic factual queries
    return "explanation"


def _needs_full_pipeline(question: str, intent: str, tickers: list[str]) -> bool:
    """
    Return True if scoring and recommendation agents should run.
    Advisory queries always do. Factual queries without tickers skip it.
    Portfolio-level advisory (no tickers) also runs for portfolio gap analysis.
    """
    if intent == "advisory":
        return True
    q_lower = question.lower()
    if any(kw in q_lower for kw in _ADVISORY_KEYWORDS):
        return True
    if intent == "analytical" and tickers:
        return True
    return False


def _compute_pipeline_confidence(report: IntelligenceReport) -> str:
    """Compute overall pipeline confidence from agent data quality."""
    mc = report.market_context

    # Synthesis/Advisory mode: confidence based on portfolio gap analysis + market
    if report.llm_mode in ("synthesis", "advisory"):
        if report.portfolio_gap_analysis and report.portfolio_gap_analysis.data_coverage == "full":
            return "high" if mc and mc.regime_confidence in ("high", "medium") else "medium"
        if report.normalized_portfolio and mc:
            return "medium"
        return "low"

    # Explanation/asset mode: confidence from scores and market data
    if report.asset_scores and any(s.data_coverage == "full" for s in report.asset_scores):
        return "medium" if mc else "low"
    return "low"  # safe floor — never return None

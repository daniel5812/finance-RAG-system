"""
intelligence/context_builder.py

Responsibility:
  Convert an IntelligenceReport into a structured, LLM-injectable text block.

Design:
  - Output is inserted into the user message BEFORE the user's question.
  - Each section is clearly labelled and delimited.
  - Empty/None sections are omitted entirely.
  - Never passes raw SQL rows or internal scores to LLM — only human-readable summaries.
  - Recommendations are presented with their deterministic action labels
    so the LLM cannot contradict them.
  - LLM mode is surfaced so the system prompt can activate the right response mode.
  - New sections: portfolio gap analysis, yield curve, VIX, beta, annualized vol,
    momentum, sector per asset.
"""

from __future__ import annotations

from intelligence.schemas import (
    IntelligenceReport, NormalizedPortfolio, PortfolioGapAnalysis,
    RecommendationAction, ValidationResult,
)


_DIVIDER = "─" * 60


def build_intelligence_context(report: IntelligenceReport) -> str:
    """
    Render the IntelligenceReport as a structured prompt block.
    Returns an empty string if the report is empty (safe fallback).
    """
    if report.is_empty:
        return ""

    # ─ Context Builder: Track what's being injected ─
    from core.logger import get_logger
    logger = get_logger(__name__)

    # Log which blocks will be included (for observability)
    logger.info(
        f'{{"event": "intelligence_context_building", '
        f'"has_user_profile": {bool(report.user_profile)}, '
        f'"has_market_context": {bool(report.market_context)}, '
        f'"has_asset_profiles": {bool(report.asset_profiles)}, '
        f'"has_normalized_portfolio": {bool(report.normalized_portfolio)}, '
        f'"has_portfolio_fit": {bool(report.portfolio_fit)}, '
        f'"has_portfolio_gap_analysis": {bool(report.portfolio_gap_analysis)}, '
        f'"has_asset_scores": {bool(report.asset_scores)}, '
        f'"has_recommendations": {bool(report.recommendations)}, '
        f'"has_validation_result": {bool(report.validation_result)}, '
        f'"pipeline_confidence": "{report.pipeline_confidence}"}}'
    )

    sections: list[str] = [
        "╔══ INVESTMENT INTELLIGENCE LAYER ══╗",
        f"Pipeline confidence: {(report.pipeline_confidence or 'low').upper()}",
        f"LLM Mode: {(report.llm_mode or 'explanation').upper()}",
        f"Agents ran: {', '.join(report.agents_ran) or 'none'}",
    ]

    # ── User Profile ────────────────────────────────────────────────────────
    if report.user_profile:
        up = report.user_profile
        interests = ", ".join(up.interests[:8]) if up.interests else "none identified"
        sections.append(_DIVIDER)
        sections.append(
            f"[USER PROFILE]\n"
            f"  Risk Tolerance:   {up.risk_tolerance}\n"
            f"  Experience:       {up.experience_level}\n"
            f"  Style:            {up.preferred_style}\n"
            f"  Time Horizon:     {up.time_horizon}\n"
            f"  Interests:        {interests}"
        )

    # ── Market Context ──────────────────────────────────────────────────────
    if report.market_context:
        mc = report.market_context
        sections.append(_DIVIDER)
        regime_label = mc.regime.value.upper().replace("_", "-")
        lines = [f"[MARKET CONTEXT — {regime_label}] (confidence: {mc.regime_confidence})"]
        for signal in mc.macro_signals:
            lines.append(f"  • {signal}")
        if mc.fed_rate is not None:
            lines.append(f"  • Fed Funds Rate: {mc.fed_rate:.2f}%")
        if mc.inflation is not None:
            lines.append(f"  • Inflation (CPI): {mc.inflation:.1f}%")
        if mc.unemployment is not None:
            lines.append(f"  • Unemployment: {mc.unemployment:.1f}%")
        if mc.gdp_latest is not None:
            lines.append(f"  • GDP Growth (latest): {mc.gdp_latest:+.1f}%")
        if mc.usd_ils_rate:
            lines.append(f"  • USD/ILS rate: {mc.usd_ils_rate:.4f}")

        # Always show indicators if they exist
        if mc.yield_curve is not None:
            yc_label = (
                "inverted — recession risk" if mc.yield_curve < -0.10 else
                "flat — slowing growth" if mc.yield_curve < 0.25 else
                "positive — normal expansion"
            )
            lines.append(f"  • Yield Curve (10Y-2Y): {mc.yield_curve:+.3f}% [{yc_label}]")
        if mc.vix is not None:
            vix_label = "HIGH STRESS" if mc.vix >= 35 else "Elevated" if mc.vix >= 25 else "Normal"
            lines.append(f"  • VIX: {mc.vix:.1f} [{vix_label}]")
        if mc.data_staleness_warning:
            lines.append(f"  ⚠ {mc.data_staleness_warning}")
        sections.append("\n".join(lines))

    # ── Asset Profiles ──────────────────────────────────────────────────────
    if report.asset_profiles:
        sections.append(_DIVIDER)
        sections.append("[ASSET PROFILES]")
        for ap in report.asset_profiles:
            price_str = f"${ap.recent_price:.2f}" if ap.recent_price else "N/A"
            chg_30d   = f"{ap.price_30d_change_pct:+.1f}% (30d)" if ap.price_30d_change_pct is not None else ""
            chg_7d    = f"{ap.price_7d_change_pct:+.1f}% (7d)" if ap.price_7d_change_pct is not None else ""

            # Volatility: prefer real annualized value
            if ap.annualized_vol is not None:
                vol_str = f"vol:{ap.price_volatility_signal} ({ap.annualized_vol*100:.1f}% ann.)"
            else:
                vol_str = f"vol:{ap.price_volatility_signal}"

            # Beta
            beta_str = f" | β={ap.beta_vs_spy:.2f}" if ap.beta_vs_spy is not None else ""

            # Momentum
            momentum_str = f" | momentum:{ap.momentum}" if ap.momentum else ""

            # Sector
            sector_str = f" | {ap.sector}" if ap.sector else ""

            etf_str = (
                f" | top holdings: {', '.join(ap.etf_top_holdings[:3])}"
                if ap.etf_top_holdings else ""
            )
            sections.append(
                f"  {ap.ticker} ({ap.asset_type.value.upper()}){sector_str} — "
                f"price: {price_str}  {chg_7d}  {chg_30d}  {vol_str}"
                f"{beta_str}{momentum_str}{etf_str}"
                f"  [data: {ap.data_freshness}, confidence: {ap.source_confidence}]"
            )

    # ── Normalized Portfolio (pre-computed financial metrics) ────────────────
    if report.normalized_portfolio:
        sections.append(_DIVIDER)
        sections.append(_render_normalized_portfolio(report.normalized_portfolio))

    # ── Portfolio Gap Analysis ───────────────────────────────────────────────
    if report.portfolio_gap_analysis:
        sections.append(_DIVIDER)
        sections.append(_render_gap_analysis(report.portfolio_gap_analysis))

    # ── Portfolio Fit ───────────────────────────────────────────────────────
    if report.portfolio_fit:
        pf = report.portfolio_fit
        sections.append(_DIVIDER)
        fit_lines = [
            "[PORTFOLIO FIT]",
            f"  {pf.current_exposure_summary}",
        ]
        if pf.concentration_risk != "unknown":
            fit_lines.append(f"  Concentration Risk: {pf.concentration_risk.upper()}")
        if pf.dominant_ticker:
            fit_lines.append(f"  Dominant Asset:     {pf.dominant_ticker}")
        if pf.dominant_sector:
            fit_lines.append(f"  Dominant Sector:    {pf.dominant_sector}")
        if pf.already_held:
            fit_lines.append(f"  Already held:       {', '.join(pf.already_held)}")
        
        sections.append("\n".join(fit_lines))

    # ── Scores ──────────────────────────────────────────────────────────────
    if report.asset_scores:
        sections.append(_DIVIDER)
        sections.append("[ASSET SCORES — deterministic, not LLM-generated]")
        for s in report.asset_scores:
            sections.append(
                f"  {s.ticker}: composite={s.composite_score:.2f} "
                f"(market={s.market_fit_score:.2f}, user={s.user_fit_score:.2f}, "
                f"diversify={s.diversification_score:.2f}, risk={s.risk_alignment_score:.2f}, "
                f"momentum={s.momentum_score:.2f})"
                f"  [coverage: {s.data_coverage}]"
            )
            # Surface the most informative factor
            for factor_key in ("risk_alignment", "market_fit", "momentum"):
                if factor_key in s.score_factors:
                    sections.append(f"    → {s.score_factors[factor_key]}")
                    break

    # ── Recommendations ─────────────────────────────────────────────────────
    if report.recommendations:
        sections.append(_DIVIDER)
        sections.append(
            "[INVESTMENT RECOMMENDATIONS — actions are deterministic; "
            "DO NOT contradict these in your response]"
        )
        for r in report.recommendations:
            action_str = r.action.value.upper()
            conf_str   = f"[{r.confidence} confidence]"
            sections.append(f"\n  ► {r.ticker}: {action_str} {conf_str}")
            if r.reasoning:
                sections.append(f"    Reasoning:   {r.reasoning}")
            if r.trade_offs:
                sections.append(f"    Trade-offs:  {r.trade_offs}")
            if r.risks:
                for risk in r.risks:
                    sections.append(f"    Risk:        • {risk}")

    # ── Validation Result ────────────────────────────────────────────────────
    if report.validation_result:
        sections.append(_DIVIDER)
        sections.append(_render_validation(report.validation_result))

    sections.append("╚══ END INTELLIGENCE LAYER ══╝")
    return "\n".join(sections)


# ─────────────────────────────────────────────────────────────
# Render helpers
# ─────────────────────────────────────────────────────────────

def _render_normalized_portfolio(np: NormalizedPortfolio) -> str:
    """
    Render pre-computed portfolio financial metrics for LLM consumption.
    These values are authoritative — the LLM MUST NOT recalculate them.
    """
    lines = [
        "[NORMALIZED PORTFOLIO — pre-computed, DO NOT recalculate]",
        f"  Total positions: {np.total_positions}",
    ]
    if np.total_invested is not None:
        lines.append(f"  Total invested capital: {np.currency} {np.total_invested:,.2f}")
    else:
        lines.append("  Total invested capital: unavailable (missing cost_basis data)")

    if np.allocation_pct:
        lines.append("  Allocation by invested capital:")
        for ticker, pct in list(np.allocation_pct.items())[:10]:  # cap at 10 for brevity
            lines.append(f"    {ticker}: {pct:.1f}%")
        if len(np.allocation_pct) > 10:
            lines.append(f"    ... and {len(np.allocation_pct) - 10} more positions")
    else:
        lines.append("  Allocation: unavailable")

    lines.append(f"  Note: {np.data_note}")
    return "\n".join(lines)


def _render_gap_analysis(gap: PortfolioGapAnalysis) -> str:
    """
    Render portfolio structural gap analysis for LLM consumption.
    """
    lines = [
        f"[PORTFOLIO GAP ANALYSIS — vs SPY benchmark] (data coverage: {gap.data_coverage})",
        f"  Concentration score (HHI): {gap.concentration_score:.3f} "
        f"({'HIGH — concentrated' if gap.concentration_score > 0.25 else 'moderate' if gap.concentration_score > 0.15 else 'well-spread'})",
    ]

    # Top sector weights (most relevant ones)
    if gap.sector_weights:
        lines.append("  Sector allocation vs SPY benchmark:")
        for sw in gap.sector_weights[:8]:   # top 8 by portfolio weight
            if sw.portfolio_pct > 0 or sw.benchmark_pct > 0:
                gap_indicator = f"(Δ{sw.gap_pct:+.0f}pp)"
                lines.append(
                    f"    {sw.sector:<30} portfolio: {sw.portfolio_pct:5.1f}%  "
                    f"SPY: {sw.benchmark_pct:5.1f}%  {gap_indicator}"
                )

    if gap.overweight_sectors:
        lines.append(f"  ⚠ Overweight vs SPY: {'; '.join(gap.overweight_sectors[:3])}")

    if gap.underweight_sectors:
        lines.append(f"  ⚠ Underweight vs SPY: {'; '.join(gap.underweight_sectors[:3])}")

    if gap.missing_asset_classes:
        lines.append(f"  ✗ Missing asset classes: {', '.join(gap.missing_asset_classes)}")

    lines.append("  Diversification gaps:")
    for g in gap.diversification_gaps:
        lines.append(f"    • {g}")

    lines.append("  Suggested directions:")
    for d in gap.suggested_directions:
        lines.append(f"    → {d}")

    return "\n".join(lines)


def _render_validation(vr: ValidationResult) -> str:
    """
    Render validation status. If flags exist, the LLM must acknowledge limited confidence.
    """
    if vr.passed:
        return "[VALIDATION] ✓ All pipeline checks passed — data is internally consistent."

    flag_lines = "\n".join(f"    ⚠ {f}" for f in vr.flags)
    override_note = (
        f" Pipeline confidence downgraded to: {vr.confidence_override.upper()}."
        if vr.confidence_override else ""
    )
    return f"[VALIDATION] ⚠ Found potential logical inconsistencies:\n{flag_lines}\n{override_note}"

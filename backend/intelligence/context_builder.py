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
"""

from __future__ import annotations

from intelligence.schemas import IntelligenceReport, NormalizedPortfolio, RecommendationAction, ValidationResult


_DIVIDER = "─" * 60


def build_intelligence_context(report: IntelligenceReport) -> str:
    """
    Render the IntelligenceReport as a structured prompt block.
    Returns an empty string if the report is empty (safe fallback).
    """
    if report.is_empty:
        return ""

    sections: list[str] = [
        "╔══ INVESTMENT INTELLIGENCE LAYER ══╗",
        f"Pipeline confidence: {report.pipeline_confidence.upper()}",
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
        if mc.usd_ils_rate:
            lines.append(f"  • USD/ILS rate: {mc.usd_ils_rate:.4f}")
        sections.append("\n".join(lines))

    # ── Asset Profiles ──────────────────────────────────────────────────────
    if report.asset_profiles:
        sections.append(_DIVIDER)
        sections.append("[ASSET PROFILES]")
        for ap in report.asset_profiles:
            price_str = f"${ap.recent_price:.2f}" if ap.recent_price else "N/A"
            chg_30d   = f"{ap.price_30d_change_pct:+.1f}% (30d)" if ap.price_30d_change_pct is not None else ""
            chg_7d    = f"{ap.price_7d_change_pct:+.1f}% (7d)" if ap.price_7d_change_pct is not None else ""
            vol       = f"vol:{ap.price_volatility_signal}"
            etf_str   = (
                f" | top holdings: {', '.join(ap.etf_top_holdings[:3])}"
                if ap.etf_top_holdings else ""
            )
            sections.append(
                f"  {ap.ticker} ({ap.asset_type.value.upper()}) — "
                f"price: {price_str}  {chg_7d}  {chg_30d}  {vol}"
                f"{etf_str}"
                f"  [data: {ap.data_freshness}, confidence: {ap.source_confidence}]"
            )

    # ── Normalized Portfolio (pre-computed financial metrics) ────────────────
    if report.normalized_portfolio:
        sections.append(_DIVIDER)
        sections.append(_render_normalized_portfolio(report.normalized_portfolio))

    # ── Portfolio Fit ───────────────────────────────────────────────────────
    if report.portfolio_fit:
        pf = report.portfolio_fit
        sections.append(_DIVIDER)
        sections.append(
            f"[PORTFOLIO FIT]\n"
            f"  {pf.current_exposure_summary}"
        )
        if pf.already_held:
            sections.append(f"  Already held: {', '.join(pf.already_held)}")

    # ── Scores ──────────────────────────────────────────────────────────────
    if report.asset_scores:
        sections.append(_DIVIDER)
        sections.append("[ASSET SCORES — deterministic, not LLM-generated]")
        for s in report.asset_scores:
            sections.append(
                f"  {s.ticker}: composite={s.composite_score:.2f} "
                f"(market={s.market_fit_score:.2f}, user={s.user_fit_score:.2f}, "
                f"diversify={s.diversification_score:.2f}, risk={s.risk_alignment_score:.2f})"
                f"  [coverage: {s.data_coverage}]"
            )

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
    return (
        f"[VALIDATION — ISSUES DETECTED]{override_note}\n"
        f"  The following inconsistencies were found in the pipeline output.\n"
        f"  You MUST reflect reduced confidence in your response:\n"
        f"{flag_lines}"
    )

"""
Phase 4.3 — Recommendation Classification Rendering tests.

All tests are deterministic: no LLM calls, no network, no DB, no mocks.

Verify that build_intelligence_context renders recommendation actions as
model classification output (MODEL CLASSIFICATION prefix + meaning line),
and that the old bare 'TICKER: ACTION' format is gone.

Run:
    docker compose exec api pytest tests/test_recommendation_context_rendering.py -v
"""
from __future__ import annotations

from intelligence.context_builder import _action_meaning, build_intelligence_context
from intelligence.schemas import (
    AssetRecommendation,
    IntelligenceReport,
    RecommendationAction,
)


def _make_report(action: RecommendationAction = RecommendationAction.HOLD) -> IntelligenceReport:
    return IntelligenceReport(
        recommendations=[
            AssetRecommendation(
                ticker="NVDA",
                action=action,
                confidence="medium",
                composite_score=0.60,
            )
        ]
    )


def test_recommendation_context_contains_model_classification_prefix():
    """Recommendation line must carry 'MODEL CLASSIFICATION' prefix, not bare ticker:action."""
    output = build_intelligence_context(_make_report())
    assert "MODEL CLASSIFICATION" in output, (
        "context_builder must render recommendations with 'MODEL CLASSIFICATION' prefix"
    )


def test_recommendation_context_includes_classification_meaning():
    """Context must include a 'Classification meaning:' line with non-empty text."""
    output = build_intelligence_context(_make_report())
    assert "Classification meaning:" in output, (
        "context_builder must include 'Classification meaning:' for each recommendation"
    )
    for line in output.splitlines():
        if "Classification meaning:" in line:
            meaning_text = line.split("Classification meaning:", 1)[1].strip()
            assert meaning_text, "Classification meaning must have non-empty text after the label"
            break


def test_recommendation_context_no_bare_ticker_action_line():
    """Old bare 'NVDA: HOLD' format must no longer appear in context output."""
    output = build_intelligence_context(_make_report())
    assert "NVDA: HOLD" not in output, (
        "context_builder must not render bare 'NVDA: HOLD' — use 'MODEL CLASSIFICATION' prefix instead"
    )


def test_action_meaning_covers_all_actions():
    """_action_meaning must return a specific non-empty string for every RecommendationAction value."""
    known_actions = {
        RecommendationAction.BUY,
        RecommendationAction.HOLD,
        RecommendationAction.REDUCE,
        RecommendationAction.AVOID,
        RecommendationAction.INSUFFICIENT_DATA,
    }
    for action in RecommendationAction:
        meaning = _action_meaning(action)
        assert meaning, f"_action_meaning({action!r}) must return a non-empty string"
        if action in known_actions:
            assert meaning != "see scoring context above", (
                f"Known action {action!r} must have a specific meaning entry, not the generic fallback"
            )

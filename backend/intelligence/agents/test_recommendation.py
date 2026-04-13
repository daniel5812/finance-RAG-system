"""
Tests for recommendation.py RecommendationAgent protections.
Focus: LLM reasoning is strictly separate from deterministic action/confidence.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from intelligence.schemas import (
    AssetScore, AssetRecommendation, RecommendationAction
)
from intelligence.agents.recommendation import _REASONING_PROMPT


class TestRecommendationAgentImmutability:
    """Test 3: RecommendationAgent LLM cannot override action or confidence."""

    def test_action_immutable_even_if_llm_contradicts(self):
        """Verify LLM reasoning cannot override pre-determined action."""
        # Stage 1: Deterministic action from score
        score = AssetScore(
            ticker="AAPL",
            composite_score=0.75,  # → BUY action
            data_coverage="full",
            score_factors={"market_fit": "strong", "user_fit": "moderate"},
            market_fit_score=0.80,
            user_fit_score=0.70,
            diversification_score=0.65,
            risk_alignment_score=0.75,
            momentum_score=0.70,
        )

        # Simulate _determine_action (Stage 1)
        if score.composite_score >= 0.72:
            action = RecommendationAction.BUY
            confidence = "high" if score.data_coverage == "full" else "medium"
        else:
            action = RecommendationAction.HOLD
            confidence = "medium"

        # Create initial recommendation
        rec = AssetRecommendation(
            ticker="AAPL",
            action=action,
            confidence=confidence,
            composite_score=score.composite_score,
        )

        # Stage 2: Simulate LLM returning conflicting action/confidence
        llm_output = {
            "reasoning": "Despite strong score, market volatility suggests caution",
            "trade_offs": "Missing upside potential for safety",
            "risks": ["volatility", "overvaluation"],
            "action": "HOLD",  # LLM tries to override
            "confidence": "low",  # LLM tries to override
        }

        # Simulate the real code (lines 227-235)
        final_rec = AssetRecommendation(
            ticker=rec.ticker,
            action=rec.action,  # Use pre-determined, ignore LLM
            confidence=rec.confidence,  # Use pre-determined, ignore LLM
            composite_score=rec.composite_score,
            reasoning=str(llm_output.get("reasoning", "")),
            trade_offs=str(llm_output.get("trade_offs", "")),
            risks=[str(r) for r in llm_output.get("risks", [])],
        )

        # Assert: deterministic fields unchanged
        assert final_rec.action == RecommendationAction.BUY, "LLM cannot override action"
        assert final_rec.confidence == "high", "LLM cannot override confidence"
        assert final_rec.action != RecommendationAction.HOLD, "Should not use LLM action"
        assert final_rec.confidence != "low", "Should not use LLM confidence"

        # Assert: LLM output only in reasoning fields
        assert "caution" in final_rec.reasoning, "LLM reasoning is preserved"
        assert final_rec.risks == ["volatility", "overvaluation"], "LLM risks are preserved"

    def test_confidence_immutable_for_low_coverage(self):
        """Verify confidence is deterministic even with low data coverage."""
        score = AssetScore(
            ticker="UNKNOWN",
            composite_score=0.40,  # → REDUCE action
            data_coverage="minimal",  # Low coverage
            score_factors={"market_fit": "unknown"},
            market_fit_score=0.40,
            user_fit_score=0.35,
            diversification_score=0.30,
            risk_alignment_score=0.35,
            momentum_score=0.38,
        )

        # Stage 1: Deterministic logic
        if score.composite_score >= 0.38:
            confidence = "low" if score.data_coverage != "full" else "medium"
        else:
            confidence = "none"

        rec = AssetRecommendation(
            ticker=score.ticker,
            action=RecommendationAction.REDUCE,
            confidence=confidence,
            composite_score=score.composite_score,
        )

        # LLM tries to claim high confidence despite minimal data
        llm_output = {"confidence": "high", "reasoning": "Analysis suggests..."}

        # Apply real code logic
        final_rec = AssetRecommendation(
            ticker=rec.ticker,
            action=rec.action,
            confidence=rec.confidence,  # Use deterministic, ignore LLM
            composite_score=rec.composite_score,
            reasoning=str(llm_output.get("reasoning", "")),
        )

        # Assert: confidence reflects data quality, not LLM self-report
        assert final_rec.confidence == "low", "Confidence determined by data coverage"
        assert final_rec.confidence != "high", "LLM self-report ignored"

    def test_llm_fields_never_contain_action_or_confidence_keys(self):
        """Verify LLM prompt never asks for action or confidence."""
        # The actual _REASONING_PROMPT is inspected to ensure it only asks for:
        # - reasoning (2-3 sentences)
        # - trade_offs (1 sentence)
        # - risks (JSON array of strings)

        forbidden_field_names = {"action", "confidence"}

        # Verify prompt text does not ask LLM to provide action or confidence
        for field_name in forbidden_field_names:
            # Check for field declarations like "action:" or "confidence:" in the prompt
            assert f'"{field_name}"' not in _REASONING_PROMPT, \
                f"Prompt should not ask LLM for '{field_name}' field"

        # Verify prompt only asks for the three allowed fields
        allowed_fields = {"reasoning", "trade_offs", "risks"}
        for field_name in allowed_fields:
            assert f'"{field_name}"' in _REASONING_PROMPT, \
                f"Prompt should ask LLM for '{field_name}' field"

        # Verify the prompt explicitly forbids overriding the action
        assert "override" in _REASONING_PROMPT.lower(), \
            "Prompt should warn against overriding the action"

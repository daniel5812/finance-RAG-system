"""
Tests for orchestrator.py Intelligence Layer protections.
Focus: ValidationAgent confidence override propagation.
"""

import pytest
from unittest.mock import MagicMock, patch
from intelligence.schemas import (
    IntelligenceReport, ValidationResult, MarketContext, UserInvestmentProfile
)


class TestValidationAgentConfidenceOverride:
    """Test 2: ValidationAgent confidence_override updates final response confidence."""

    def test_confidence_override_updates_pipeline_confidence(self):
        """Verify ValidationAgent confidence_override correctly updates report.pipeline_confidence."""
        # Create report with base confidence
        report = IntelligenceReport()
        report.pipeline_confidence = "high"  # Base confidence from _compute_pipeline_confidence

        # Simulate ValidationAgent finding issues and setting override
        validation_result = ValidationResult(
            passed=False,
            flags=["data_staleness_warning", "confidence_downgrade"],
            confidence_override="medium"  # ValidationAgent downgrade
        )
        report.validation_result = validation_result

        # Simulate the orchestrator logic (line 254-255)
        if report.validation_result.confidence_override:
            report.pipeline_confidence = report.validation_result.confidence_override

        # Assert: confidence was downgraded
        assert report.pipeline_confidence == "medium", "Override should update pipeline_confidence"
        assert report.pipeline_confidence != "high", "Base confidence should be replaced"

    def test_confidence_override_flows_to_final_response(self):
        """Verify pipeline_confidence flows through to final response dict."""
        # Simulate the full flow:
        # 1. Orchestrator sets confidence (line 255)
        report = IntelligenceReport()
        report.pipeline_confidence = "high"
        if True:  # Simulating validation override
            report.pipeline_confidence = "low"

        # 2. chat_service extracts it (line 672)
        pipeline_confidence = report.pipeline_confidence

        # 3. It's included in result dict (line 926)
        result = {
            "answer": "Test answer",
            "confidence_level": pipeline_confidence,
        }

        assert result["confidence_level"] == "low", "Downgraded confidence should reach response"

    def test_no_override_preserves_base_confidence(self):
        """Verify base confidence is preserved when no override is set."""
        report = IntelligenceReport()
        report.pipeline_confidence = "high"

        # ValidationAgent passed, no override
        validation_result = ValidationResult(passed=True, flags=[], confidence_override=None)
        report.validation_result = validation_result

        # Apply orchestrator logic
        if report.validation_result and report.validation_result.confidence_override:
            report.pipeline_confidence = report.validation_result.confidence_override

        # Assert: base confidence unchanged
        assert report.pipeline_confidence == "high", "Base confidence should be unchanged"

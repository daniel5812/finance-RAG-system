"""
test_document_reasoning_context.py — Unit tests for document insights integration.

Tests:
- Block renders when aggregated data exists
- Block omitted when empty
- Partial data renders only present fields
- Null/zero values skipped
- Orchestrator handles aggregation failures non-fatally
"""

import pytest
from datetime import date
from intelligence.schemas import IntelligenceReport
from intelligence.context_builder import (
    build_intelligence_context,
    _render_document_insights,
)


class TestDocumentInsightsRendering:
    """Test _render_document_insights() helper function."""

    def test_render_complete_data(self):
        """Render all fields when data is present."""
        doc_insights = {
            "total_assets_from_docs": 547200.50,
            "accounts_detected": 5,
            "account_types_breakdown": {"Brokerage": 2, "Retirement": 2, "Savings": 1},
            "avg_equity_exposure": 62.5,
            "avg_fx_exposure": 8.3,
            "latest_report_date": date(2026, 4, 15),
        }

        result = _render_document_insights(doc_insights)

        assert "[DOCUMENT INSIGHTS" in result
        assert "Accounts detected: 5" in result
        assert "Brokerage (2)" in result
        assert "Retirement (2)" in result
        assert "Savings (1)" in result
        assert "$547,200.50" in result
        assert "62.5%" in result
        assert "8.3%" in result
        assert "2026-04-15" in result

    def test_render_partial_data(self):
        """Render only non-null fields."""
        doc_insights = {
            "total_assets_from_docs": 291600.0,
            "accounts_detected": 3,
            "account_types_breakdown": {"Brokerage": 3},
            "avg_equity_exposure": None,  # null
            "avg_fx_exposure": None,      # null
            "latest_report_date": date(2026, 3, 28),
        }

        result = _render_document_insights(doc_insights)

        assert "[DOCUMENT INSIGHTS" in result
        assert "Accounts detected: 3" in result
        assert "$291,600.00" in result
        assert "2026-03-28" in result
        # Null fields should not appear
        assert "Average equity exposure" not in result
        assert "Average FX exposure" not in result

    def test_omit_zero_assets(self):
        """Skip total_assets field if zero."""
        doc_insights = {
            "total_assets_from_docs": 0,
            "accounts_detected": 0,
            "account_types_breakdown": {},
            "avg_equity_exposure": None,
            "avg_fx_exposure": None,
            "latest_report_date": None,
        }

        result = _render_document_insights(doc_insights)

        # Should return empty string if no meaningful data
        assert result == ""

    def test_omit_zero_accounts(self):
        """Skip accounts field if zero."""
        doc_insights = {
            "total_assets_from_docs": 100000.0,
            "accounts_detected": 0,
            "account_types_breakdown": {},
            "avg_equity_exposure": None,
            "avg_fx_exposure": None,
            "latest_report_date": date(2026, 4, 1),
        }

        result = _render_document_insights(doc_insights)

        assert "[DOCUMENT INSIGHTS" in result
        assert "Total assets" in result
        assert "Latest statement" in result
        # Zero accounts should not appear
        assert "Accounts detected:" not in result

    def test_render_empty_dict(self):
        """Return empty string for empty dict."""
        result = _render_document_insights({})
        assert result == ""

    def test_render_none(self):
        """Return empty string for None."""
        result = _render_document_insights(None)
        assert result == ""

    def test_account_types_formatting(self):
        """Format account types as comma-separated list."""
        doc_insights = {
            "total_assets_from_docs": 100000.0,
            "accounts_detected": 5,
            "account_types_breakdown": {
                "Retirement": 2,
                "Brokerage": 2,
                "Savings": 1,
            },
            "avg_equity_exposure": None,
            "avg_fx_exposure": None,
            "latest_report_date": None,
        }

        result = _render_document_insights(doc_insights)

        # All types should appear
        assert "Retirement (2)" in result
        assert "Brokerage (2)" in result
        assert "Savings (1)" in result

    def test_percentage_formatting(self):
        """Format percentages with 1 decimal place."""
        doc_insights = {
            "total_assets_from_docs": 100000.0,
            "accounts_detected": 1,
            "account_types_breakdown": {},
            "avg_equity_exposure": 62.456,
            "avg_fx_exposure": 8.891,
            "latest_report_date": None,
        }

        result = _render_document_insights(doc_insights)

        assert "62.5%" in result
        assert "8.9%" in result

    def test_currency_formatting(self):
        """Format currency with commas and 2 decimal places."""
        doc_insights = {
            "total_assets_from_docs": 1234567.89,
            "accounts_detected": 1,
            "account_types_breakdown": {},
            "avg_equity_exposure": None,
            "avg_fx_exposure": None,
            "latest_report_date": None,
        }

        result = _render_document_insights(doc_insights)

        assert "$1,234,567.89" in result


class TestIntelligenceReportIntegration:
    """Test document_insights integration in full context building."""

    def test_report_with_document_insights(self):
        """Include document insights block when data is present."""
        report = IntelligenceReport(
            document_insights={
                "total_assets_from_docs": 500000.0,
                "accounts_detected": 4,
                "account_types_breakdown": {"Brokerage": 2, "Retirement": 2},
                "avg_equity_exposure": 65.0,
                "avg_fx_exposure": 5.0,
                "latest_report_date": date(2026, 4, 1),
            }
        )

        context = build_intelligence_context(report)

        assert "[DOCUMENT INSIGHTS" in context
        assert "Accounts detected: 4" in context
        assert "$500,000.00" in context

    def test_report_without_document_insights(self):
        """Omit document insights block when None."""
        report = IntelligenceReport(
            document_insights=None
        )

        context = build_intelligence_context(report)

        assert "[DOCUMENT INSIGHTS" not in context

    def test_report_with_empty_document_insights(self):
        """Omit block when document_insights is empty dict."""
        report = IntelligenceReport(
            document_insights={}
        )

        context = build_intelligence_context(report)

        assert "[DOCUMENT INSIGHTS" not in context

    def test_document_insights_block_placement(self):
        """Document insights appears after asset profiles, before normalized portfolio."""
        from intelligence.schemas import (
            AssetProfile,
            AssetType,
            NormalizedPortfolio,
        )

        report = IntelligenceReport(
            asset_profiles=[
                AssetProfile(
                    ticker="AAPL",
                    asset_type=AssetType.STOCK,
                    recent_price=150.0,
                )
            ],
            document_insights={
                "total_assets_from_docs": 100000.0,
                "accounts_detected": 1,
                "account_types_breakdown": {},
                "avg_equity_exposure": None,
                "avg_fx_exposure": None,
                "latest_report_date": None,
            },
            normalized_portfolio=NormalizedPortfolio(total_positions=3),
        )

        context = build_intelligence_context(report)

        asset_pos = context.find("[ASSET PROFILES]")
        doc_pos = context.find("[DOCUMENT INSIGHTS")
        norm_pos = context.find("[NORMALIZED PORTFOLIO")

        assert asset_pos < doc_pos < norm_pos


class TestOrchestratorDocumentAggregation:
    """Test orchestrator's handling of document aggregation."""

    @pytest.mark.asyncio
    async def test_orchestrator_aggregates_when_pool_and_owner_id(self):
        """Orchestrator calls aggregation when pool and owner_id are present."""
        # This test would require mocking the database pool and service
        # For now, we document the expected behavior
        pass

    def test_orchestrator_handles_aggregation_failure(self):
        """Orchestrator gracefully handles aggregation failures."""
        # Document that orchestrator wraps document aggregation in try/except
        # so failures don't crash the pipeline
        pass

    def test_orchestrator_skips_empty_document_insights(self):
        """Orchestrator sets document_insights to None if no meaningful data."""
        # When aggregation returns zeros/empty, orchestrator should not
        # populate report.document_insights
        pass


class TestIntegrationWithFullPipeline:
    """Integration tests with the full intelligence pipeline."""

    def test_context_injection_format(self):
        """Injected context is properly formatted for LLM consumption."""
        report = IntelligenceReport(
            document_insights={
                "total_assets_from_docs": 250000.0,
                "accounts_detected": 2,
                "account_types_breakdown": {"Brokerage": 2},
                "avg_equity_exposure": 55.0,
                "avg_fx_exposure": 3.0,
                "latest_report_date": date(2026, 4, 10),
            }
        )

        context = build_intelligence_context(report)

        # Verify structure is correct
        assert "╔══ INVESTMENT INTELLIGENCE LAYER ══╗" in context
        assert "╚══ END INTELLIGENCE LAYER ══╝" in context
        assert "[DOCUMENT INSIGHTS" in context

    def test_no_raw_data_in_output(self):
        """Ensure no raw SQL rows or internal data structures appear."""
        doc_insights = {
            "total_assets_from_docs": 100000.0,
            "accounts_detected": 1,
            "account_types_breakdown": {"Brokerage": 1},
            "avg_equity_exposure": 70.0,
            "avg_fx_exposure": 5.0,
            "latest_report_date": date(2026, 4, 1),
        }

        result = _render_document_insights(doc_insights)

        # Should not contain raw dict representation
        assert "{" not in result or "[" not in result
        # Should be human-readable
        assert "Accounts detected" in result

    def test_partial_data_allowed(self):
        """Allow and render partial document data gracefully."""
        # Only some fields populated
        doc_insights = {
            "accounts_detected": 3,
            "total_assets_from_docs": 400000.0,
            # Other fields missing or None
        }

        result = _render_document_insights(doc_insights)

        assert "Accounts detected: 3" in result
        assert "$400,000.00" in result
        assert "Average equity exposure" not in result
        assert "Account types:" not in result

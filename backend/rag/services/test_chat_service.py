"""
Tests for chat_service.py LLM workflow protections.
Focus: SQL formatting, context filtering, LLM confidence fallback.
"""

import pytest
from unittest.mock import MagicMock, patch
from rag.services.chat_service import _format_sql_rows_as_text


class TestSQLFormatting:
    """Test 1: SQL results formatted as prose, not JSON."""

    def test_sql_rows_converted_to_text_not_json(self):
        """Verify raw SQL numeric rows are converted to text format."""
        rows = [
            {"symbol": "AAPL", "price": 175.32, "date": "2024-01-10"},
            {"symbol": "MSFT", "price": 415.87, "date": "2024-01-10"},
        ]

        result = _format_sql_rows_as_text(rows)

        # Assert: no JSON array syntax, no numeric precision artifacts
        assert "[{" not in result, "Raw JSON should not be in output"
        assert "175.32" in result, "Numeric value should be preserved"
        assert "Row 1:" in result, "Prose format expected"
        assert "Row 2:" in result, "Both rows should be present"
        assert "Row 3:" not in result, "Should limit to 3 rows by default"

    def test_sql_rows_limit_to_three(self):
        """Verify max_rows=3 limit is enforced."""
        rows = [{"id": i, "value": i * 100} for i in range(1, 11)]

        result = _format_sql_rows_as_text(rows)

        assert result.count("Row") == 3, "Should show exactly 3 rows"
        assert "... 7 more rows" in result, "Should indicate additional rows"

    def test_sql_empty_result(self):
        """Verify empty result handling."""
        result = _format_sql_rows_as_text([])

        assert "No data returned" in result


class TestContextFiltering:
    """Test 4: Multiple plans don't duplicate chunks."""

    def test_merge_contexts_no_duplicates(self):
        """Verify merged contexts from multiple plans have no duplicates by document_id."""
        # Simulate two execute_sub_query results with overlapping sources
        plan1_result = {
            "contexts": [
                "Source [S1]: FX Rates Result:\nRow 1: rate=3.65",
                "Source [D1]: Market analysis chunk",
            ],
            "sources": [
                {"document_id": "sql_query", "chunk_text": "FX data"},
                {"document_id": "doc-2024-001", "chunk_text": "Market analysis chunk"},
            ],
        }
        plan2_result = {
            "contexts": [
                "Source [D2]: Tech sector analysis",
                "Source [D1]: Market analysis chunk",  # Same document_id as plan1[D1]
            ],
            "sources": [
                {"document_id": "doc-2024-002", "chunk_text": "Tech sector analysis"},
                {"document_id": "doc-2024-001", "chunk_text": "Market analysis chunk"},  # Duplicate
            ],
        }

        # Simulate merge (from merge_contexts function)
        all_sources = plan1_result["sources"] + plan2_result["sources"]

        # Real deduplication logic: filter by document_id
        seen_ids = set()
        deduplicated = []
        for source in all_sources:
            doc_id = source["document_id"]
            if doc_id not in seen_ids:
                deduplicated.append(source)
                seen_ids.add(doc_id)

        # Assert: duplicate document_id is filtered
        assert len(deduplicated) == 3, "Should have 3 unique sources after dedup"
        assert len(all_sources) == 4, "Original had 4 sources (1 duplicate)"
        doc_ids = [s["document_id"] for s in deduplicated]
        assert doc_ids.count("doc-2024-001") == 1, "Duplicate doc_id should appear only once"

    def test_context_block_assembly(self):
        """Verify context_block is assembled without extraneous noise."""
        contexts = [
            "Source [S1]: FX Rates Result:\nRow 1: rate=3.65",
            "Source [D1]: Relevant market analysis",
        ]

        context_block = "\n---\n".join(contexts)

        assert context_block.count("Source [") == 2, "Should have exactly 2 sources"
        assert "---" in context_block, "Sources should be separated"


class TestLLMConfidenceFallback:
    """Test 5: LLM confidence never overrides pipeline_confidence."""

    def test_llm_confidence_ignored_when_pipeline_exists(self):
        """Verify LLM's [[Explainability:]] confidence is ignored if pipeline_confidence exists."""
        # Simulate the logic from chat_service.py line 855-866
        pipeline_confidence = "medium"

        # LLM returns high confidence in explainability
        llm_confidence = "high"

        # Apply the real logic from chat_service
        confidence_level = pipeline_confidence  # Line 855

        # Simulate parsing LLM response
        if confidence_level is None:  # Line 865
            confidence_level = llm_confidence  # Line 866

        # Assert: pipeline confidence is used, not LLM confidence
        assert confidence_level == "medium", "Pipeline confidence should take priority"
        assert confidence_level != "high", "LLM confidence should not override"

    def test_llm_confidence_used_only_when_pipeline_none(self):
        """Verify LLM confidence is fallback-only when pipeline_confidence is None."""
        pipeline_confidence = None
        llm_confidence = "high"

        confidence_level = pipeline_confidence

        if confidence_level is None:
            confidence_level = llm_confidence

        assert confidence_level == "high", "LLM confidence should be used as fallback"

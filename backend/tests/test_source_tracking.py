"""
Phase 4B.1 — Source tracking normalization tests.

Tests the _doc_ids_for_source_check helper that prevents false-positive
STRICT SOURCE VIOLATION errors when SQL results appear alongside a
user-supplied document_ids filter.

Run: docker compose exec api pytest tests/test_source_tracking.py -v
"""
import pytest
from rag.services.chat_service import _doc_ids_for_source_check, _SQL_INTERNAL_SOURCE_IDS


# ── Helpers ────────────────────────────────────────────────────────────────────

def _src(document_id: str) -> dict:
    return {"document_id": document_id, "chunk_text": "x", "vector_score": 1.0, "rerank_score": 1.0}


# ── SQL internal ID exclusion ─────────────────────────────────────────────────

def test_sql_source_excluded_from_check():
    """sql_query must not appear in the ids used for source-violation check."""
    sources = [_src("sql_query")]
    result = _doc_ids_for_source_check(sources)
    assert result == set()


def test_sql_source_not_violation_against_uuid():
    """
    selected_ids = {uuid}, retrieved contains only sql_query
    → no violation (sql is not a user document).
    """
    sources = [_src("sql_query")]
    selected_ids = {"238194a5-a5b9-40d8-bf9c-f2188b03c612"}
    retrieved_doc_ids = _doc_ids_for_source_check(sources)
    violation = bool(selected_ids and not retrieved_doc_ids.issubset(selected_ids))
    assert not violation


def test_multiple_sql_sources_all_excluded():
    sources = [_src("sql_query"), _src("sql_query")]
    result = _doc_ids_for_source_check(sources)
    assert result == set()


# ── Vector source still strict ────────────────────────────────────────────────

def test_vector_mismatch_still_violation():
    """doc_2 retrieved but only doc_1 selected → real violation."""
    sources = [_src("doc_1"), _src("doc_2")]
    selected_ids = {"doc_1"}
    retrieved_doc_ids = _doc_ids_for_source_check(sources)
    violation = bool(selected_ids and not retrieved_doc_ids.issubset(selected_ids))
    assert violation


def test_vector_match_no_violation():
    sources = [_src("doc_1")]
    selected_ids = {"doc_1"}
    retrieved_doc_ids = _doc_ids_for_source_check(sources)
    violation = bool(selected_ids and not retrieved_doc_ids.issubset(selected_ids))
    assert not violation


def test_empty_selected_ids_never_violation():
    """No document filter provided → subset check is skipped (selected empty)."""
    sources = [_src("sql_query"), _src("doc_99")]
    selected_ids: set = set()
    retrieved_doc_ids = _doc_ids_for_source_check(sources)
    violation = bool(selected_ids and not retrieved_doc_ids.issubset(selected_ids))
    assert not violation


# ── Mixed SQL + vector ────────────────────────────────────────────────────────

def test_mixed_sql_and_matching_vector_no_violation():
    """SQL fact + matching doc UUID → no violation."""
    sources = [_src("sql_query"), _src("doc_abc")]
    selected_ids = {"doc_abc"}
    retrieved_doc_ids = _doc_ids_for_source_check(sources)
    violation = bool(selected_ids and not retrieved_doc_ids.issubset(selected_ids))
    assert not violation


def test_mixed_sql_and_mismatched_vector_still_violation():
    """SQL fact present, but doc_xyz is not in selected → real violation detected."""
    sources = [_src("sql_query"), _src("doc_xyz")]
    selected_ids = {"doc_abc"}
    retrieved_doc_ids = _doc_ids_for_source_check(sources)
    violation = bool(selected_ids and not retrieved_doc_ids.issubset(selected_ids))
    assert violation


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_unknown_source_excluded():
    """document_id='unknown' is already excluded (existing behaviour)."""
    sources = [_src("unknown")]
    result = _doc_ids_for_source_check(sources)
    assert "unknown" not in result


def test_missing_document_id_excluded():
    sources = [{"chunk_text": "x", "vector_score": 1.0, "rerank_score": 1.0}]
    result = _doc_ids_for_source_check(sources)
    assert result == set()


def test_empty_sources():
    assert _doc_ids_for_source_check([]) == set()


def test_sql_internal_source_ids_constant():
    """The constant must contain the SQL internal ID used by citation assembly."""
    assert "sql_query" in _SQL_INTERNAL_SOURCE_IDS


def test_arbitrary_uuid_not_excluded():
    """A real-looking UUID must pass through, not be treated as SQL internal."""
    uid = "238194a5-a5b9-40d8-bf9c-f2188b03c612"
    sources = [_src(uid)]
    result = _doc_ids_for_source_check(sources)
    assert uid in result


def test_sql_like_string_not_excluded_if_not_exact():
    """'sql_query_extra' is not in _SQL_INTERNAL_SOURCE_IDS — passes through."""
    sources = [_src("sql_query_extra")]
    result = _doc_ids_for_source_check(sources)
    assert "sql_query_extra" in result

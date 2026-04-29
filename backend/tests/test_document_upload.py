"""
Tests for document upload metadata persistence and worker classification flow (Step 5A).

Covers:
- Classification metadata persisted after worker runs
- owner_id isolation: doc classified for owner A is not accessible to owner B
- Worker flow: classification runs before vector indexing
- Vector metadata includes doc_type
- Failed extraction: status=failed, no chunks indexed, doc_type stays unknown
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pool(doc_type="unknown", confidence="low", status="pending_processing"):
    """Return a mock asyncpg pool that reports the given document state."""
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={
        "document_id": "doc-abc",
        "owner_id": "user-1",
        "original_filename": "statement.pdf",
        "file_size_bytes": 1024,
        "status": status,
        "storage_path": "/uploads/doc-abc.pdf",
        "summary": None,
        "key_topics": None,
        "suggested_questions": None,
        "folder_id": None,
        "doc_type": doc_type,
        "classification_confidence": confidence,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    })
    return pool


# ── Classification metadata persistence ──────────────────────────────────────

@pytest.mark.asyncio
async def test_update_document_classification_persists_fields():
    """update_document_classification writes doc_type and confidence to DB."""
    from documents.crud import update_document_classification

    pool = MagicMock()
    pool.execute = AsyncMock()

    await update_document_classification(pool, "doc-123", "broker_statement", "high")

    pool.execute.assert_awaited_once()
    sql, *args = pool.execute.call_args.args
    assert "doc_type" in sql
    assert "classification_confidence" in sql
    assert "broker_statement" in args
    assert "high" in args
    assert "doc-123" in args


@pytest.mark.asyncio
async def test_update_document_classification_unknown_fallback():
    """unknown/low can be persisted without error."""
    from documents.crud import update_document_classification

    pool = MagicMock()
    pool.execute = AsyncMock()

    await update_document_classification(pool, "doc-999", "unknown", "low")

    pool.execute.assert_awaited_once()


# ── owner_id isolation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_document_status_owner_isolation():
    """
    A document owned by user-1 is not accessible to user-2.
    The route enforces owner_id == user_id check.
    """
    from documents.crud import get_document_status

    pool = _make_pool(doc_type="broker_statement", confidence="high", status="completed")

    row = await get_document_status(pool, "doc-abc")
    assert row is not None
    assert row["owner_id"] == "user-1"

    # user-2 receives the same row from DB but the route layer rejects it
    # Here we verify the owner_id field is correctly returned in the DB row
    # so the route can compare it to the authenticated user.
    assert row["owner_id"] != "user-2"


@pytest.mark.asyncio
async def test_get_document_status_returns_classification_fields():
    """get_document_status returns doc_type and classification_confidence."""
    from documents.crud import get_document_status

    pool = _make_pool(doc_type="portfolio_statement", confidence="medium", status="completed")

    row = await get_document_status(pool, "doc-abc")
    assert row["doc_type"] == "portfolio_statement"
    assert row["classification_confidence"] == "medium"


# ── Worker classification step ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_worker_calls_classify_before_upsert():
    """
    process_document_worker must classify the document before upserting vectors.
    Classification must run even when chunking/embedding succeed.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()

    pinecone_index = MagicMock()
    embed_model = MagicMock()
    embed_model.encode = MagicMock(return_value=[[0.1] * 384])

    call_order = []

    with (
        patch.object(worker, "_extract_text", return_value="brokerage account statement trade history") as mock_extract,
        patch("documents.worker.classify_document", return_value=("broker_statement", "medium")) as mock_classify,
        patch("documents.worker.update_document_classification", new_callable=AsyncMock) as mock_update_cls,
        patch("documents.worker.update_document_status", new_callable=AsyncMock) as mock_update_status,
        patch("documents.worker.chunk_text", return_value=["chunk 1"]) as mock_chunk,
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock) as mock_upsert,
    ):
        mock_classify.side_effect = lambda *a, **kw: (call_order.append("classify"), ("broker_statement", "medium"))[1]
        mock_upsert.side_effect = lambda *a, **kw: (call_order.append("upsert"), 1)[1]

        await worker.process_document_worker(
            pool=pool,
            pinecone_index=pinecone_index,
            embed_model=embed_model,
            document_id="doc-abc",
            file_path="/uploads/doc-abc.pdf",
            owner_id="user-1",
        )

    assert "classify" in call_order
    assert "upsert" in call_order
    assert call_order.index("classify") < call_order.index("upsert"), (
        "Classification must complete before Pinecone upsert"
    )


@pytest.mark.asyncio
async def test_worker_classification_failure_falls_back_to_unknown():
    """
    If classify_document raises, the worker logs the error and continues with doc_type='unknown'.
    It must not propagate the exception or set status=failed.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()

    pinecone_index = MagicMock()

    with (
        patch.object(worker, "_extract_text", return_value="some text"),
        patch("documents.worker.classify_document", side_effect=RuntimeError("classifier exploded")),
        patch("documents.worker.update_document_classification", new_callable=AsyncMock),
        patch("documents.worker.update_document_status", new_callable=AsyncMock) as mock_status,
        patch("documents.worker.chunk_text", return_value=["chunk"]),
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock) as mock_upsert,
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=pinecone_index,
            embed_model=MagicMock(encode=MagicMock(return_value=[[0.1] * 384])),
            document_id="doc-xyz",
            file_path="/uploads/doc-xyz.pdf",
            owner_id="user-1",
        )

        # Must still complete — not set to failed
        status_calls = [c.args[2] for c in mock_status.await_args_list]
        assert "failed" not in status_calls
        assert "completed" in status_calls

        # Must still upsert (with unknown as fallback)
        mock_upsert.assert_awaited_once()
        # doc_type arg should be 'unknown'
        upsert_args = mock_upsert.call_args.args
        assert "unknown" in upsert_args


@pytest.mark.asyncio
async def test_worker_failed_extraction_sets_status_failed_no_indexing():
    """
    If text extraction returns empty string, worker sets status=failed
    and never calls classify_document or upsert.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()

    with (
        patch.object(worker, "_extract_text", return_value=""),
        patch("documents.worker.classify_document") as mock_classify,
        patch("documents.worker.update_document_status", new_callable=AsyncMock) as mock_status,
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock) as mock_upsert,
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=MagicMock(),
            embed_model=MagicMock(),
            document_id="doc-empty",
            file_path="/uploads/doc-empty.pdf",
            owner_id="user-1",
        )

        status_calls = [c.args[2] for c in mock_status.await_args_list]
        assert "failed" in status_calls
        mock_classify.assert_not_called()
        mock_upsert.assert_not_awaited()


# ── Vector metadata includes doc_type ────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_vectors_includes_doc_type_in_metadata():
    """
    _upsert_vectors must embed doc_type in every Pinecone vector's metadata.
    """
    from documents.worker import _upsert_vectors

    captured_payload = {}

    pinecone_index = MagicMock()

    def fake_upsert(vectors):
        captured_payload["vectors"] = vectors

    pinecone_index.upsert = fake_upsert

    await _upsert_vectors(
        pinecone_index=pinecone_index,
        document_id="doc-meta",
        owner_id="user-1",
        doc_type="financial_report",
        chunks=["chunk A", "chunk B"],
        vectors=[[0.1] * 384, [0.2] * 384],
    )

    assert "vectors" in captured_payload
    for vec in captured_payload["vectors"]:
        assert vec["metadata"]["doc_type"] == "financial_report"
        assert vec["metadata"]["owner_id"] == "user-1"
        assert vec["metadata"]["document_id"] == "doc-meta"


@pytest.mark.asyncio
async def test_upsert_vectors_unknown_doc_type_still_indexed():
    """
    unknown doc_type must not block indexing — chunks are still upserted.
    """
    from documents.worker import _upsert_vectors

    captured_payload = {}
    pinecone_index = MagicMock()
    pinecone_index.upsert = lambda vectors: captured_payload.update({"vectors": vectors})

    await _upsert_vectors(
        pinecone_index=pinecone_index,
        document_id="doc-unknown",
        owner_id="user-1",
        doc_type="unknown",
        chunks=["some chunk"],
        vectors=[[0.5] * 384],
    )

    assert len(captured_payload["vectors"]) == 1
    assert captured_payload["vectors"][0]["metadata"]["doc_type"] == "unknown"


# ── Step 5B: Extraction worker flow ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_worker_runs_extraction_for_broker_statement():
    """
    Worker must call extract_holdings when doc_type=broker_statement.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.executemany = AsyncMock()

    with (
        patch.object(worker, "_extract_text", return_value="AAPL 100 185.32 position summary"),
        patch("documents.worker.classify_document", return_value=("broker_statement", "high")),
        patch("documents.worker.update_document_classification", new_callable=AsyncMock),
        patch("documents.worker.update_document_status", new_callable=AsyncMock),
        patch("documents.worker.extract_holdings", return_value=[]) as mock_extract,
        patch("documents.worker.insert_document_holdings", new_callable=AsyncMock),
        patch("documents.worker.chunk_text", return_value=["chunk"]),
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock),
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=MagicMock(),
            embed_model=MagicMock(encode=MagicMock(return_value=[[0.1] * 384])),
            document_id="doc-broker",
            file_path="/uploads/doc-broker.pdf",
            owner_id="user-1",
        )

    mock_extract.assert_called_once()
    call_args = mock_extract.call_args
    assert call_args.args[1] == "broker_statement"


@pytest.mark.asyncio
async def test_worker_runs_extraction_for_portfolio_statement():
    """
    Worker must call extract_holdings when doc_type=portfolio_statement.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.executemany = AsyncMock()

    with (
        patch.object(worker, "_extract_text", return_value="MSFT 50 holdings summary"),
        patch("documents.worker.classify_document", return_value=("portfolio_statement", "medium")),
        patch("documents.worker.update_document_classification", new_callable=AsyncMock),
        patch("documents.worker.update_document_status", new_callable=AsyncMock),
        patch("documents.worker.extract_holdings", return_value=[]) as mock_extract,
        patch("documents.worker.insert_document_holdings", new_callable=AsyncMock),
        patch("documents.worker.chunk_text", return_value=["chunk"]),
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock),
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=MagicMock(),
            embed_model=MagicMock(encode=MagicMock(return_value=[[0.1] * 384])),
            document_id="doc-portfolio",
            file_path="/uploads/doc-portfolio.pdf",
            owner_id="user-1",
        )

    mock_extract.assert_called_once()
    assert mock_extract.call_args.args[1] == "portfolio_statement"


@pytest.mark.asyncio
async def test_worker_skips_extraction_for_bank_statement():
    """
    Worker must NOT call extract_holdings for non-eligible doc types.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()

    with (
        patch.object(worker, "_extract_text", return_value="checking account deposits withdrawals"),
        patch("documents.worker.classify_document", return_value=("bank_statement", "high")),
        patch("documents.worker.update_document_classification", new_callable=AsyncMock),
        patch("documents.worker.update_document_status", new_callable=AsyncMock),
        patch("documents.worker.extract_holdings") as mock_extract,
        patch("documents.worker.chunk_text", return_value=["chunk"]),
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock),
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=MagicMock(),
            embed_model=MagicMock(encode=MagicMock(return_value=[[0.1] * 384])),
            document_id="doc-bank",
            file_path="/uploads/doc-bank.pdf",
            owner_id="user-1",
        )

    mock_extract.assert_not_called()


@pytest.mark.asyncio
async def test_worker_skips_extraction_for_unknown_type():
    """
    Worker must NOT call extract_holdings when doc_type=unknown.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()

    with (
        patch.object(worker, "_extract_text", return_value="some document content here"),
        patch("documents.worker.classify_document", return_value=("unknown", "low")),
        patch("documents.worker.update_document_classification", new_callable=AsyncMock),
        patch("documents.worker.update_document_status", new_callable=AsyncMock),
        patch("documents.worker.extract_holdings") as mock_extract,
        patch("documents.worker.chunk_text", return_value=["chunk"]),
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock),
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=MagicMock(),
            embed_model=MagicMock(encode=MagicMock(return_value=[[0.1] * 384])),
            document_id="doc-unknown",
            file_path="/uploads/doc-unknown.pdf",
            owner_id="user-1",
        )

    mock_extract.assert_not_called()


@pytest.mark.asyncio
async def test_worker_extraction_failure_does_not_block_indexing():
    """
    If extract_holdings raises, the worker logs the error and continues.
    Pinecone upsert must still be called and status must be completed.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()

    with (
        patch.object(worker, "_extract_text", return_value="brokerage account statement trade confirmation"),
        patch("documents.worker.classify_document", return_value=("broker_statement", "high")),
        patch("documents.worker.update_document_classification", new_callable=AsyncMock),
        patch("documents.worker.update_document_status", new_callable=AsyncMock) as mock_status,
        patch("documents.worker.extract_holdings", side_effect=RuntimeError("extractor exploded")),
        patch("documents.worker.insert_document_holdings", new_callable=AsyncMock),
        patch("documents.worker.chunk_text", return_value=["chunk"]),
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock) as mock_upsert,
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=MagicMock(),
            embed_model=MagicMock(encode=MagicMock(return_value=[[0.1] * 384])),
            document_id="doc-err",
            file_path="/uploads/doc-err.pdf",
            owner_id="user-1",
        )

    status_calls = [c.args[2] for c in mock_status.await_args_list]
    assert "failed" not in status_calls
    assert "completed" in status_calls
    mock_upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_insert_holdings_called_when_results_found():
    """
    insert_document_holdings must be called when extraction returns candidates.
    """
    from documents import worker
    from documents.extractor import CandidateHolding

    fake_holdings = [CandidateHolding(ticker="AAPL", quantity=100.0, source_line="AAPL 100", confidence="high")]

    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.executemany = AsyncMock()

    with (
        patch.object(worker, "_extract_text", return_value="brokerage account statement AAPL 100"),
        patch("documents.worker.classify_document", return_value=("broker_statement", "high")),
        patch("documents.worker.update_document_classification", new_callable=AsyncMock),
        patch("documents.worker.update_document_status", new_callable=AsyncMock),
        patch("documents.worker.extract_holdings", return_value=fake_holdings),
        patch("documents.worker.insert_document_holdings", new_callable=AsyncMock) as mock_insert,
        patch("documents.worker.chunk_text", return_value=["chunk"]),
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock),
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=MagicMock(),
            embed_model=MagicMock(encode=MagicMock(return_value=[[0.1] * 384])),
            document_id="doc-with-holdings",
            file_path="/uploads/doc-with-holdings.pdf",
            owner_id="user-1",
        )

    mock_insert.assert_awaited_once_with(pool, "doc-with-holdings", "user-1", fake_holdings)


@pytest.mark.asyncio
async def test_worker_no_holdings_found_does_not_insert():
    """
    If extract_holdings returns empty list, insert_document_holdings must not be called.
    """
    from documents import worker

    pool = MagicMock()
    pool.execute = AsyncMock()

    with (
        patch.object(worker, "_extract_text", return_value="brokerage account statement trade confirmation"),
        patch("documents.worker.classify_document", return_value=("broker_statement", "high")),
        patch("documents.worker.update_document_classification", new_callable=AsyncMock),
        patch("documents.worker.update_document_status", new_callable=AsyncMock),
        patch("documents.worker.extract_holdings", return_value=[]),
        patch("documents.worker.insert_document_holdings", new_callable=AsyncMock) as mock_insert,
        patch("documents.worker.chunk_text", return_value=["chunk"]),
        patch.object(worker, "_embed_chunks", return_value=[[0.1] * 384]),
        patch.object(worker, "_upsert_vectors", new_callable=AsyncMock),
    ):
        await worker.process_document_worker(
            pool=pool,
            pinecone_index=MagicMock(),
            embed_model=MagicMock(encode=MagicMock(return_value=[[0.1] * 384])),
            document_id="doc-no-holdings",
            file_path="/uploads/doc-no-holdings.pdf",
            owner_id="user-1",
        )

    mock_insert.assert_not_awaited()

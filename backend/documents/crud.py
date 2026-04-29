import asyncpg
from typing import Optional, List, Dict, Any

async def create_document(
    pool: asyncpg.Pool,
    document_id: str,
    owner_id: str,
    original_filename: str,
    content_type: str,
    file_size_bytes: int,
    storage_path: str,
    status: str = "pending_processing",
    folder_id: Optional[int] = None
) -> None:
    """Insert a new document metadata row into the database."""
    await pool.execute(
        """
        INSERT INTO documents
            (id, owner_id, original_filename, content_type, file_size_bytes, storage_path, status, folder_id)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        document_id,
        owner_id,
        original_filename,
        content_type,
        file_size_bytes,
        storage_path,
        status,
        folder_id,
    )

async def get_document_status(pool: asyncpg.Pool, document_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a single document's metadata by ID.
    Returns None if the document is not found.
    """
    row = await pool.fetchrow(
        """
        SELECT
            id::text AS document_id,
            owner_id,
            original_filename,
            file_size_bytes,
            status,
            storage_path,
            summary,
            key_topics,
            suggested_questions,
            folder_id,
            doc_type,
            classification_confidence,
            created_at,
            updated_at
        FROM documents
        WHERE id = $1
        """,
        document_id,
    )
    return dict(row) if row else None

async def update_document_status(pool: asyncpg.Pool, document_id: str, status: str) -> None:
    """Update a document's processing status."""
    await pool.execute(
        """
        UPDATE documents
        SET status = $1, updated_at = NOW()
        WHERE id = $2
        """,
        status,
        document_id,
    )

async def get_user_completed_documents(pool: asyncpg.Pool, user_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all completed documents belonging to this user.
    Only documents with status='completed' are eligible for retrieval.
    """
    rows = await pool.fetch(
        """
        SELECT id::text AS document_id, original_filename
        FROM documents
        WHERE owner_id = $1
          AND status   = 'completed'
        ORDER BY created_at DESC
        """,
        user_id,
    )
    return [dict(r) for r in rows]

async def get_user_documents(
    pool: asyncpg.Pool,
    user_id: str,
    folder_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch all documents belonging to this user.
    Pass folder_id to filter by folder.
    """
    if folder_id is not None:
        rows = await pool.fetch(
            """
            SELECT
                id::text AS document_id,
                owner_id,
                original_filename,
                file_size_bytes,
                status,
                summary,
                key_topics,
                suggested_questions,
                folder_id,
                doc_type,
                classification_confidence,
                created_at,
                updated_at
            FROM documents
            WHERE owner_id = $1
              AND folder_id = $2
            ORDER BY created_at DESC
            """,
            user_id,
            folder_id,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT
                id::text AS document_id,
                owner_id,
                original_filename,
                file_size_bytes,
                status,
                summary,
                key_topics,
                suggested_questions,
                folder_id,
                doc_type,
                classification_confidence,
                created_at,
                updated_at
            FROM documents
            WHERE owner_id = $1
            ORDER BY created_at DESC
            """,
            user_id,
        )
    return [dict(r) for r in rows]

async def delete_document(pool: asyncpg.Pool, document_id: str) -> None:
    """Delete a document metadata row."""
    await pool.execute("DELETE FROM documents WHERE id = $1", document_id)

# ── Folder CRUD ─────────────────────────────────────────────────────────────

async def create_folder(pool: asyncpg.Pool, owner_id: str, name: str) -> Dict[str, Any]:
    """Insert a new folder row and return it."""
    row = await pool.fetchrow(
        """
        INSERT INTO document_folders (name, owner_id)
        VALUES ($1, $2)
        RETURNING id, name, owner_id, created_at
        """,
        name,
        owner_id,
    )
    return dict(row)


async def list_folders(pool: asyncpg.Pool, owner_id: str) -> List[Dict[str, Any]]:
    """Return all folders belonging to this user."""
    rows = await pool.fetch(
        """
        SELECT id, name, owner_id, created_at
        FROM document_folders
        WHERE owner_id = $1
        ORDER BY created_at ASC
        """,
        owner_id,
    )
    return [dict(r) for r in rows]


async def get_folder(pool: asyncpg.Pool, folder_id: int, owner_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single folder, scoped to owner. Returns None if not found."""
    row = await pool.fetchrow(
        """
        SELECT id, name, owner_id, created_at
        FROM document_folders
        WHERE id = $1 AND owner_id = $2
        """,
        folder_id,
        owner_id,
    )
    return dict(row) if row else None


async def delete_folder(pool: asyncpg.Pool, folder_id: int, owner_id: str) -> None:
    """Delete a folder scoped to owner (documents.folder_id set to NULL via FK ON DELETE SET NULL)."""
    await pool.execute(
        "DELETE FROM document_folders WHERE id = $1 AND owner_id = $2",
        folder_id,
        owner_id,
    )


async def set_document_folder(
    pool: asyncpg.Pool,
    document_id: str,
    folder_id: Optional[int],
    owner_id: str,
) -> None:
    """Assign or unassign a document from a folder (scoped to owner)."""
    await pool.execute(
        """
        UPDATE documents
        SET folder_id = $1, updated_at = NOW()
        WHERE id = $2 AND owner_id = $3
        """,
        folder_id,
        document_id,
        owner_id,
    )


# ── Document Classification ──────────────────────────────────────────────────

async def update_document_classification(
    pool: asyncpg.Pool,
    document_id: str,
    doc_type: str,
    confidence: str,
) -> None:
    """Persist classification result after deterministic keyword analysis."""
    await pool.execute(
        """
        UPDATE documents
        SET doc_type = $1, classification_confidence = $2, updated_at = NOW()
        WHERE id = $3
        """,
        doc_type,
        confidence,
        document_id,
    )


# ── Document Holdings ────────────────────────────────────────────────────────

async def insert_document_holdings(
    pool: asyncpg.Pool,
    document_id: str,
    owner_id: str,
    holdings: list,
) -> int:
    """
    Batch-insert extracted holding candidates.

    Args:
        holdings: list of CandidateHolding dataclass instances from extractor.py.

    Returns:
        Number of rows inserted.
    """
    rows = [
        (document_id, owner_id, h.ticker, h.quantity, h.source_line, h.confidence)
        for h in holdings
    ]
    await pool.executemany(
        """
        INSERT INTO document_holdings
            (document_id, owner_id, ticker, quantity, source_line, confidence)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        rows,
    )
    return len(rows)


async def get_document_holdings(
    pool: asyncpg.Pool,
    document_id: str,
    owner_id: str,
) -> List[Dict[str, Any]]:
    """
    Fetch all holding candidates for a document, scoped to owner.
    source_line is excluded — internal audit column, not returned to callers.
    """
    rows = await pool.fetch(
        """
        SELECT
            id,
            document_id::text,
            owner_id,
            ticker,
            quantity,
            confidence,
            created_at
        FROM document_holdings
        WHERE document_id = $1
          AND owner_id    = $2
        ORDER BY created_at ASC
        """,
        document_id,
        owner_id,
    )
    return [dict(r) for r in rows]


# ── Financial Statement ──────────────────────────────────────────────────────

async def insert_financial_statement(
    pool: asyncpg.Pool,
    document_id: str,
    owner_id: str,
    data,  # FinancialStatementData — avoid circular import; duck-typed
) -> None:
    """
    Upsert extracted financial statement fields for a document.
    ON CONFLICT (document_id) re-runs are idempotent — overwrites all fields.
    owner_id isolation is enforced by the UNIQUE(document_id) constraint plus
    the WHERE clause on get, not by the insert itself.
    """
    await pool.execute(
        """
        INSERT INTO document_financial_statements (
            document_id, owner_id,
            provider, account_type, account_number,
            report_date, period_start, period_end,
            ending_balance, annual_deposits, investment_gains, management_fees,
            track_name, equity_exposure_pct, fx_exposure_pct
        ) VALUES (
            $1, $2,
            $3, $4, $5,
            $6::date, $7::date, $8::date,
            $9, $10, $11, $12,
            $13, $14, $15
        )
        ON CONFLICT (document_id) DO UPDATE SET
            owner_id            = EXCLUDED.owner_id,
            provider            = EXCLUDED.provider,
            account_type        = EXCLUDED.account_type,
            account_number      = EXCLUDED.account_number,
            report_date         = EXCLUDED.report_date,
            period_start        = EXCLUDED.period_start,
            period_end          = EXCLUDED.period_end,
            ending_balance      = EXCLUDED.ending_balance,
            annual_deposits     = EXCLUDED.annual_deposits,
            investment_gains    = EXCLUDED.investment_gains,
            management_fees     = EXCLUDED.management_fees,
            track_name          = EXCLUDED.track_name,
            equity_exposure_pct = EXCLUDED.equity_exposure_pct,
            fx_exposure_pct     = EXCLUDED.fx_exposure_pct
        """,
        document_id,
        owner_id,
        data.provider,
        data.account_type,
        data.account_number,
        data.report_date,
        data.period_start,
        data.period_end,
        data.ending_balance,
        data.annual_deposits,
        data.investment_gains,
        data.management_fees,
        data.track_name,
        data.equity_exposure_pct,
        data.fx_exposure_pct,
    )


async def get_financial_statement(
    pool: asyncpg.Pool,
    document_id: str,
    owner_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetch the financial statement record for a document, scoped to owner.
    Returns None if not found or if owner_id does not match.
    """
    row = await pool.fetchrow(
        """
        SELECT
            document_id::text,
            owner_id,
            provider,
            account_type,
            account_number,
            report_date::text,
            period_start::text,
            period_end::text,
            ending_balance,
            annual_deposits,
            investment_gains,
            management_fees,
            track_name,
            equity_exposure_pct,
            fx_exposure_pct,
            created_at
        FROM document_financial_statements
        WHERE document_id = $1
          AND owner_id    = $2
        """,
        document_id,
        owner_id,
    )
    return dict(row) if row else None


# ── Document Metadata ────────────────────────────────────────────────────────

async def update_document_metadata(pool: asyncpg.Pool, document_id: str, summary: str, key_topics: list, suggested_questions: list) -> None:
    """Update document summary and key topics."""
    import json
    await pool.execute(
        """
        UPDATE documents
        SET summary = $1, key_topics = $2, suggested_questions = $3, updated_at = NOW()
        WHERE id = $4
        """,
        summary, json.dumps(key_topics), json.dumps(suggested_questions), document_id
    )

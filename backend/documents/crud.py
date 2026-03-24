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
    status: str = "pending_processing"
) -> None:
    """Insert a new document metadata row into the database."""
    await pool.execute(
        """
        INSERT INTO documents
            (id, owner_id, original_filename, content_type, file_size_bytes, storage_path, status)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7)
        """,
        document_id,
        owner_id,
        original_filename,
        content_type,
        file_size_bytes,
        storage_path,
        status,
    )

async def get_document_status(pool: asyncpg.Pool, document_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a single document's metadata by ID.
    Returns None if the document is not found.
    """
    row = await pool.fetchrow(
        """
        SELECT
            id,
            owner_id,
            original_filename,
            file_size_bytes,
            status,
            storage_path,
            summary,
            key_topics,
            suggested_questions,
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

async def get_user_documents(pool: asyncpg.Pool, user_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all documents belonging to this user.
    """
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

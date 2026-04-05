"""
documents/schemas.py — Pydantic models for the document pipeline.
New models are added here as each stage is implemented.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, field_validator


class RoutingResponse(BaseModel):
    """
    Structured output from the routing LLM call.

    relevant_document_ids:
        The LLM picks which of the user's documents are relevant.
        We validate these against the DB list before trusting them.

    optimized_search_queries:
        1-3 professional financial search queries.
        Trade jargon → precise terminology.
        e.g.: "how much did I make" → "cumulative investment return 2024"
    """
    relevant_document_ids: List[str]
    optimized_search_queries: List[str]

    @field_validator("optimized_search_queries")
    @classmethod
    def at_most_three_queries(cls, v: List[str]) -> List[str]:
        # Allow empty list (LLM may return [] when no docs are relevant)
        # Trim silently if over-generated
        return v[:3] if len(v) > 3 else v


class DocumentUploadResponse(BaseModel):
    """
    Returned immediately (HTTP 202) when a document is accepted for processing.
    The client stores document_id and uses it to poll status via GET /documents/{id}.
    """
    document_id: str        # UUID — safe to expose (non-sequential)
    status: str             # Always "accepted" at upload time
    original_filename: str  # Echo back so the client can confirm the right file


class DocumentStatusResponse(BaseModel):
    """
    Returned by GET /documents/{id}.
    Reflects the document's current position in the processing pipeline.

    Status lifecycle:
        pending_processing → processing → completed | failed
    """
    document_id: str
    owner_id: str
    original_filename: str
    file_size_bytes: int | None
    status: str             # pending_processing | processing | completed | failed
    created_at: datetime
    updated_at: datetime
    storage_path: str | None = None   # only exposed for debugging; hide in production
    folder_id: Optional[int] = None


import json
import asyncio
import hashlib
from fastapi import APIRouter, HTTPException, Depends
from typing import Any
from sentence_transformers import SentenceTransformer
from pydantic import BaseModel, Field
from core.dependencies import get_pinecone, get_embed_model
from core.logger import get_logger
from rag.processing import chunk_text
from rag import vector_store
from rag.services.summary_service import generate_source_overview
from documents.crud import update_document_metadata
from core.db import get_pool
import asyncpg

logger = get_logger(__name__)
router = APIRouter()

class IngestRequest(BaseModel):
    documents: list[str] = Field(..., min_length=1)
    role: str = "public"          # "public" | "admin"

@router.post("/ingest")
async def ingest_documents(
    request: IngestRequest,
    pinecone_index: Any = Depends(get_pinecone),
    embed_model: SentenceTransformer = Depends(get_embed_model),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Upload text documents → embed → upsert to Pinecone."""

    if not pinecone_index:
        raise HTTPException(500, "Pinecone not connected")

    if not request.documents:
        raise HTTPException(400, "No documents provided")

    loop = asyncio.get_running_loop()
    ingested_ids = []

    for i, doc_text in enumerate(request.documents):
        # C4: Smart chunking — split long documents
        chunks = chunk_text(doc_text)
        doc_base_id = hashlib.md5(doc_text.encode()).hexdigest()

        for chunk_idx, chunk in enumerate(chunks):
            chunk_id = f"{doc_base_id}_c{chunk_idx}" if len(chunks) > 1 else doc_base_id

            # Embed in ThreadPool
            vector = await loop.run_in_executor(
                None,
                embed_model.encode,
                chunk
            )

            # Upsert to vector store
            await vector_store.upsert(
                pinecone_index=pinecone_index,
                chunk_id=chunk_id,
                vector=vector,
                text=chunk,
                role=request.role,
                chunk_index=chunk_idx,
                total_chunks=len(chunks),
                doc_id=doc_base_id,
            )

        ingested_ids.append(doc_base_id)
        
        # ── Step 2: Generate Source Overview (Background) ──
        try:
            overview = await generate_source_overview(doc_text)
            await update_document_metadata(
                pool, doc_base_id, 
                overview["summary"], 
                overview["key_topics"], 
                overview["suggested_questions"]
            )
        except Exception as e:
            logger.warning(f"Metadata update failed for {doc_base_id}: {e}")

        logger.info(json.dumps({"event": "doc_ingested", "doc_index": i+1, "total": len(request.documents), "doc_id": doc_base_id, "chunks": len(chunks)}))

    logger.info(json.dumps({"event": "ingestion_complete", "count": len(ingested_ids)}))

    return {
        "ingested": len(ingested_ids),
        "ids": ingested_ids
    }

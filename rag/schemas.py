from pydantic import BaseModel, Field
from typing import Optional, List

class ChatQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_role: str = "employee"   # "employee" | "admin"
    owner_id: Optional[str] = None  # when set → document-aware routing (Stage 4)

class SourceNode(BaseModel):
    document_id: str
    filename: Optional[str] = None
    chunk_text: str
    vector_score: float
    rerank_score: float

class LatencyBreakdown(BaseModel):
    embedding: float
    routing: float = 0.0
    retrieval: float
    rerank: float = 0.0
    generation: float = 0.0
    total: float

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceNode]
    source_type: str
    latency_breakdown: LatencyBreakdown

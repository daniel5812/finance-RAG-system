from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_role: str = "employee"   # "employee" | "admin"
    owner_id: Optional[str] = None  # when set → document-aware routing (Stage 4)
    history: List[ChatMessage] = []
    session_id: Optional[str] = None
    document_ids: Optional[List[str]] = None

class ChatSession(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: Any
    updated_at: Any

class ChatMessagesResponse(BaseModel):
    messages: List[Dict[str, Any]]

class QueryPlan(BaseModel):
    source: Literal["vector", "sql", "financial_api"]
    query: str

class MultiQueryPlan(BaseModel):
    plans: List[QueryPlan]

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

class CitationNode(BaseModel):
    source_type: Literal["sql", "document"]
    id: str # document_id or "sql_query"
    display_name: str # filename or first few chars of query
    context: str # the actual text used

class ChatResponse(BaseModel):
    answer: str
    sources: List[dict]
    citations: Dict[str, dict] = {}
    suggested_questions: List[str] = []
    source_type: str
    latency_breakdown: Dict[str, float]
    query_execution: Optional[dict] = None
    # Explainability fields
    reasoning_summary: Optional[str] = None
    confidence_level: Optional[Literal["low", "medium", "high"]] = None

class UserSettings(BaseModel):
    user_id: str
    custom_persona: Optional[str] = None
    updated_at: Optional[Any] = None

class UserProfileUpdate(BaseModel):
    risk_tolerance: Optional[Literal["low", "medium", "high"]] = None
    preferred_style: Optional[Literal["simple", "deep"]] = None
    experience_level: Optional[Literal["beginner", "intermediate", "expert"]] = None
    custom_persona: Optional[str] = Field(None, max_length=500)
    interests: Optional[List[str]] = Field(None, max_length=20)

class UserProfileResponse(BaseModel):
    user_id: str
    risk_tolerance: str = "medium"
    preferred_style: str = "deep"
    experience_level: str = "intermediate"
    custom_persona: Optional[str] = None
    interests: List[str] = []
    past_queries: List[str] = []
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None


# ── Hybrid Retrieval Planner schemas ─────────────────────────────────────────

class VectorFilter(BaseModel):
    owner_id: str
    doc_type: Optional[str] = None
    ticker: Optional[str] = None

class PlanStep(BaseModel):
    step_id: int
    source_type: Literal["SQL", "VECTOR", "NO_MATCH"]
    intent_type: str
    parameters: Dict[str, Any] = {}
    sql_template_id: Optional[str] = None
    vector_filter: Optional[VectorFilter] = None
    priority: int = 1
    execution_mode: Literal["parallel", "sequential"] = "sequential"
    profile_hint: Optional[Dict[str, Any]] = None

class PlanMeta(BaseModel):
    total_steps: int
    is_hybrid: bool
    fusion_required: bool

class HybridQueryPlan(BaseModel):
    steps: List[PlanStep]
    plan_meta: PlanMeta

class StepResult(BaseModel):
    step_id: int
    source_type: Literal["SQL", "VECTOR", "NO_MATCH"]
    intent_type: str
    data: List[Any] = []
    status: Literal["ok", "empty", "error"] = "empty"
    error_message: Optional[str] = None

class RetrievalSummary(BaseModel):
    has_sql: bool
    has_vector: bool
    is_partial: bool
    advisory_context: Optional[Dict[str, Any]] = None

class FusionResult(BaseModel):
    structured_data: Dict[str, Any] = {}
    supporting_context: List[Any] = []
    missing_data_notes: List[str] = []
    retrieval_summary: RetrievalSummary

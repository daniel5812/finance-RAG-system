from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


IntentV2 = Literal[
    "etf_holdings",
    "price_lookup",
    "fx_rate",
    "macro_series",
    "no_match",
]


class DebugQueryV2(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class NormalizedQuestion(BaseModel):
    original_question: str
    canonical_question: str
    tokens: List[str] = Field(default_factory=list)


class QueryPlanV2(BaseModel):
    intent: IntentV2
    source: Literal["sql", "none"] = "none"
    supported: bool
    reason: Optional[str] = None
    query_template: Optional[str] = None
    sql: Optional[str] = None
    params: Dict[str, str] = Field(default_factory=dict)


class RetrievalResultV2(BaseModel):
    executed: bool
    success: bool = False
    executed_query: Optional[str] = None
    row_count: int = 0
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class AssembledContextV2(BaseModel):
    text: str
    row_count: int = 0
    truncated: bool = False


class DebugTraceV2(BaseModel):
    original_question: str
    canonical_question: str
    intent: IntentV2
    source: Literal["sql", "none"]
    params: Dict[str, str] = Field(default_factory=dict)
    executed_query: Optional[str] = None
    row_count: int = 0
    success: bool = False
    assembled_context: str
    normalized_question: NormalizedQuestion
    plan: QueryPlanV2
    retrieval: RetrievalResultV2
    context: AssembledContextV2


class ChatResponseV2(BaseModel):
    answer: str
    source_type: Literal["sql", "none"]
    citations: List[str] = Field(default_factory=list)
    debug_trace: Optional[DebugTraceV2] = None

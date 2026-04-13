"""
observability/schemas.py — Pydantic event models for the observability system.

Event hierarchy:
  TraceEvent   — what happened at each pipeline stage
  ErrorEvent   — what failed, categorized by domain
  LLMTrace     — what the LLM saw, was told, and did
  RequestRun   — per-request summary record (stored in Postgres)

Design rule: every event is self-contained and human-readable via `summary`.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Enumerations ────────────────────────────────────────────────────────────


class EventStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILED  = "failed"
    SKIPPED = "skipped"


class EventSeverity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    ERROR    = "error"
    CRITICAL = "critical"


class ErrorCategory(str, Enum):
    """Separates infrastructure failures from logic failures for fast triage."""
    INFRA    = "INFRA"    # DB down, Redis timeout, network
    PIPELINE = "PIPELINE" # Agent failures, retrieval errors, orchestrator crash
    DATA     = "DATA"     # Missing columns, bad data shapes, null values
    BUSINESS = "BUSINESS" # Validation rule violations, score out of range
    SECURITY = "SECURITY" # Auth failure, prompt injection, rate limit


class PipelineStage(str, Enum):
    """Every stage the request passes through — in order."""
    REQUEST_START    = "request_start"
    CACHE            = "cache"
    CONDENSE         = "condense"
    ROUTER           = "router"
    SQL_RETRIEVAL    = "sql_retrieval"
    VECTOR_RETRIEVAL = "vector_retrieval"
    RERANKING        = "reranking"
    NORMALIZATION    = "normalization"
    USER_PROFILER    = "user_profiler"
    MARKET_ANALYZER  = "market_analyzer"
    ASSET_PROFILER   = "asset_profiler"
    PORTFOLIO_FIT    = "portfolio_fit"
    SCORING          = "scoring"
    RECOMMENDATION   = "recommendation"
    VALIDATION       = "validation"
    LLM_PROMPT_BUILD = "llm_prompt_build"
    LLM_EXECUTION    = "llm_execution"
    RESPONSE         = "response"


class LLMBehaviorFlag(str, Enum):
    FOLLOWED_SYSTEM       = "followed_system"
    DEVIATED              = "deviated"
    ARITHMETIC_ATTEMPTED  = "arithmetic_attempted"
    HALLUCINATION_RISK    = "hallucination_risk"
    IGNORED_RECOMMENDATION = "ignored_recommendation"
    UNSUPPORTED_CLAIMS    = "unsupported_claims"
    CONFIDENCE_MISMATCH   = "confidence_mismatch"
    SHALLOW_REASONING     = "shallow_reasoning"
    REPEATED_STATEMENTS   = "repeated_statements"
    MISSING_SIGNALS       = "missing_signals"
    LACK_OF_SYNTHESIS     = "lack_of_synthesis"


# ── Core Event Models ────────────────────────────────────────────────────────


class TraceEvent(BaseModel):
    """
    A single observable event at a specific pipeline stage.

    Designed for humans first:
      - `summary` is what you read in a log grep
      - `data` is what you parse in a script
      - `debug` is what you open when something is wrong
    """
    req_id:     str
    stage:      PipelineStage
    event_name: str
    status:     EventStatus      = EventStatus.SUCCESS
    severity:   EventSeverity    = EventSeverity.INFO
    latency_ms: Optional[float]  = None
    summary:    str              = ""
    data:       dict[str, Any]   = Field(default_factory=dict)
    debug:      Optional[dict[str, Any]] = None
    timestamp:  float            = Field(default_factory=time.time)


class ErrorEvent(BaseModel):
    """
    A categorized failure event. Category separates INFRA from logic bugs.

    error_code convention: STAGE_NOUN_VERB  e.g. "VECTOR_RETRIEVAL_TIMEOUT"
    """
    req_id:         str
    stage:          PipelineStage
    error_category: ErrorCategory
    error_code:     str
    message:        str
    traceback:      Optional[str]     = None
    data:           dict[str, Any]    = Field(default_factory=dict)
    timestamp:      float             = Field(default_factory=time.time)


# ── LLM Introspection Models ─────────────────────────────────────────────────


class LLMInputBlocks(BaseModel):
    """
    What the LLM actually received. Helps answer: "Did the intelligence block reach the model?"
    """
    has_normalized_portfolio: bool = False
    has_market_context:       bool = False
    has_validation_block:     bool = False
    has_vector_context:       bool = False
    has_sql_context:          bool = False
    has_portfolio_context:    bool = False
    intelligence_block_chars: int  = 0
    context_block_chars:      int  = 0
    # Rough estimate: 1 token ≈ 4 chars for English financial text
    estimated_prompt_tokens:  int  = 0


class LLMConstraints(BaseModel):
    """
    Which rules were active for this LLM call.
    All True means full FORBIDDEN OPERATIONS mode was applied.
    """
    forbidden_operations_applied: bool = True
    no_arithmetic_mode:           bool = True
    cite_only_directive:          bool = True
    intelligence_block_injected:  bool = False


class LLMOutputStructure(BaseModel):
    """
    What came back from the LLM, parsed at the structural level.
    """
    has_explainability_block:  bool           = False
    has_suggested_questions:   bool           = False
    recommendation_action:     Optional[str]  = None  # BUY/HOLD/REDUCE/AVOID from system
    confidence_source:         str            = "none"  # "pipeline" | "llm_fallback" | "none"
    confidence_level:          Optional[str]  = None
    response_length_chars:     int            = 0
    suggested_questions_count: int            = 0


class LLMBehaviorAnalysis(BaseModel):
    """
    Did the LLM follow the rules? Purely deterministic — no LLM call to evaluate this.

    classification:
      "followed_system"      — action matches, no arithmetic detected, confidence from pipeline
      "deviated"             — action mismatch or confidence override detected
      "added_unsupported_claims" — potential hallucination markers found
    """
    classification:     str                      = "followed_system"
    reasoning_quality:  str                      = "unknown"  # high_quality_reasoning | surface_level | incomplete_use_of_context | unknown
    flags:              list[LLMBehaviorFlag]     = Field(default_factory=list)
    validation_flags:   list[str]                = Field(default_factory=list)
    arithmetic_markers: list[str]                = Field(default_factory=list)
    notes:              str                      = ""


class LLMTrace(BaseModel):
    """Complete LLM introspection record for one request."""
    req_id:           str
    input_blocks:     LLMInputBlocks
    constraints:      LLMConstraints
    output_structure: LLMOutputStructure
    behavior:         LLMBehaviorAnalysis
    latency_ms:       float = 0.0
    timestamp:        float = Field(default_factory=time.time)


# ── Request Summary ──────────────────────────────────────────────────────────


class RequestRun(BaseModel):
    """
    One record per request in Postgres. The durable audit of what happened.
    Stages are stored as individual events in Redis; this is the rolled-up view.
    """
    req_id:                      str
    user_id:                     str            = "unknown"
    path:                        str            = ""
    method:                      str            = ""
    status_code:                 int            = 0
    total_latency_ms:            float          = 0.0
    stage_count:                 int            = 0
    error_count:                 int            = 0
    cache_hit:                   bool           = False
    cache_type:                  Optional[str]  = None   # "exact" | "semantic" | "stale" | None
    intent:                      Optional[str]  = None
    intelligence_confidence:     Optional[str]  = None
    llm_behavior_classification: Optional[str]  = None
    sources_retrieved:           int            = 0
    request_type:                str            = "user"  # "user" | "admin"
    timestamp:                   float          = Field(default_factory=time.time)

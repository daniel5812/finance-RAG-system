import re
import time
import json
import asyncio
import traceback
from typing import AsyncGenerator
from fastapi import HTTPException

from core.config import *
from core.logger import get_logger, trace_latency
from core.llm_client import ChatAgentClient
from core.cache import redis_get, redis_set, generate_cache_key, cached_embed, semantic_cache_lookup, semantic_cache_store
from core.security import content_filter
from rag.processing import dynamic_filter
from rag import vector_store
from core import connections
import core.state as state
from core.state import LLM_SEMAPHORE
from documents.routing import route_and_search
from sentence_transformers import SentenceTransformer
from rag.schemas import ChatQuery
from core.prompts import CHAT_SYSTEM_PROMPT, CHAT_STREAM_PROMPT, INTENT_LABELS, PORTFOLIO_CONTEXT_TEMPLATE, CONDENSE_QUESTION_PROMPT, MEM_SUMMARY_PROMPT, SESSION_TITLE_PROMPT, build_conversation_context
from core.session_memory import SessionMemoryStore, SummaryBuilder
import asyncpg
from uuid import UUID
from core.dependencies import get_pinecone
from core.audit import log_audit_event
from typing import Any


from rag.orchestrator import QueryOrchestrator
from rag.sql_tool import run_sql_query
from rag.router import _rewrite_for_semantic_search
from rag.planner import build_plan as _hybrid_build_plan
from rag.executor import execute_plan as _hybrid_execute_plan
from rag.fusion import fuse as _hybrid_fuse
from financial.services.user_profile_service import UserProfileService
from intelligence.orchestrator import IntelligenceOrchestrator
from intelligence.context_builder import build_intelligence_context

from observability.service import obs
from observability.schemas import (
    PipelineStage, EventStatus, EventSeverity, ErrorCategory,
    LLMTrace, LLMConstraints, RequestRun,
)
from observability.analyzer import (
    analyze_llm_behavior, build_llm_input_blocks, build_llm_output_structure,
)

logger = get_logger(__name__)

# ── Conversation Memory Settings ──
MEMORY_SUMMARY_THRESHOLD = 6   # minimum messages before we summarize
MEMORY_SUMMARY_INTERVAL  = 6   # re-summarize every N new messages after threshold

# ── Numeric Shortcut Guard ──
# Matches bare option selectors that users type when they mean to click a suggestion button
_NUMERIC_SHORTCUT_RE = re.compile(
    r'^(\d{1,2}|[a-d]|(option|choice|select|pick)\s+[\da-d])$',
    re.IGNORECASE
)

NUMERIC_SHORTCUT_RESPONSE = (
    "It looks like you typed a number or letter to select an option. "
    "Please **click one of the suggested question buttons** below the previous answer, "
    "or type your full question directly."
)

def is_numeric_shortcut(question: str) -> bool:
    """
    Return True if the input is a bare option selector (1, 2, a, b, 'option 1', etc.)
    that the user typed instead of clicking a follow-up button.

    Intentionally narrow: does NOT catch 'explain step 1' or 'option A looks risky'
    because those are real questions with surrounding text.
    """
    return bool(_NUMERIC_SHORTCUT_RE.match(question.strip()))

# ── Intent Classification (lightweight, rule-based) ──

ADVISORY_KEYWORDS = [
    "should", "suggest", "recommend", "advice", "opinion", "strategy",
    "כדאי", "מציע", "המלצה", "אסטרטגיה", "חוות דעת",
]
ANALYTICAL_KEYWORDS = [
    "why", "how", "analyze", "explain", "compare", "impact", "trend",
    "risk", "exposure", "diversification", "concentration", "performance",
    "למה", "איך", "ניתוח", "השפעה", "מגמה", "סיכון", "חשיפה",
    "פיזור", "ריכוזיות", "ביצועים", "השוואה",
]
SIMULATION_KEYWORDS = [
    "what if", "if we", "assume", "scenario", "hypothetical", "suppose",
    "מה אם", "נניח ש", "תרחיש", "היפותטי", "מה יקרה אם",
]

def is_simulation_query(question: str) -> bool:
    """Detect if the query is a 'what-if' or hypothetical scenario."""
    q = question.lower()
    return any(kw in q for kw in SIMULATION_KEYWORDS)

async def condense_question(history: list, question: str, summary: str | None = None) -> str:
    """Rewrite follow-up question into a standalone query using conversation history.

    If a rolling summary is provided, it is prepended above the recent messages so that
    entities discussed many turns ago (tickers, currencies, portfolio topics) are not lost.
    """
    if not history and not summary:
        return question

    if summary:
        recent = "\n".join([f"{m.role}: {m.content}" for m in history[-3:]])
        history_text = f"[Prior conversation summary]:\n{summary}\n\n[Recent messages]:\n{recent}"
    else:
        history_text = "\n".join([f"{m.role}: {m.content}" for m in history[-5:]])

    prompt = CONDENSE_QUESTION_PROMPT.format(history=history_text, question=question)

    try:
        condensed = await ChatAgentClient.generate(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        return condensed.strip()
    except Exception as e:
        logger.warning(f"Question condensation failed: {e}")
        return question

async def summarize_history(history: list) -> str | None:
    """Summarize older messages to keep the context window clean."""
    if not history or len(history) < MEMORY_SUMMARY_THRESHOLD:
        return None
    
    # Summarize everything except the last 3 messages
    to_summarize = history[:-3]
    history_text = "\n".join([f"{m.role}: {m.content}" for m in to_summarize])
    prompt = MEM_SUMMARY_PROMPT.format(history=history_text)
    
    try:
        summary = await ChatAgentClient.generate(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        return summary.strip()
    except Exception as e:
        logger.warning(f"History summarization failed: {e}")
        return None

async def get_memory(pool: asyncpg.Pool | None, session_id: str | None, owner_id: str | None, history: list) -> str | None:
    """
    Return a conversation summary from Redis, built from history.

    Behavior:
    - Always try to load stored summary from Redis (regardless of message count)
    - If not found, build new summary only if history >= 3 messages
    - Uses Redis (not DB) for fast access, scoped by owner_id + session_id
    - Builds summary from pure function (no LLM calls)
    """
    # Always try to use stored summary from Redis first (don't gate on message count)
    if session_id and owner_id:
        stored = await SessionMemoryStore.get(owner_id, session_id)
        if stored:
            return stored

    # Only build new summary if history is long enough (SummaryBuilder minimum)
    msg_count = len(history)
    if msg_count < 3:  # SummaryBuilder.build returns None for < 3 messages
        return None

    # Build new summary from history (pure function, no LLM call)
    summary = SummaryBuilder.build(history)
    if summary and session_id and owner_id:
        await SessionMemoryStore.set(owner_id, session_id, summary)  # Wait for write to complete
    return summary


async def save_message_to_db(pool: asyncpg.Pool, session_id: str, role: str, content: str, citations: dict = None, latency: dict = None, suggested_questions: list = None):
    """Persist a message to the database."""
    if not session_id:
        return
    needs_title = False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO chat_messages (session_id, role, content, citations, latency, suggested_questions) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                UUID(session_id), role, content,
                json.dumps(citations or {}), json.dumps(latency or {}), json.dumps(suggested_questions or [])
            )
            await conn.execute(
                "UPDATE chat_sessions SET updated_at = NOW() WHERE id = $1",
                UUID(session_id)
            )
            # Check title before releasing the connection — no LLM call yet
            if role == 'user':
                row = await conn.fetchrow("SELECT title FROM chat_sessions WHERE id = $1", UUID(session_id))
                needs_title = row and row['title'] == 'New Conversation'
    except Exception as e:
        logger.error(f"Failed to save message to DB: {e}")
        return

    # Title generation runs OUTSIDE the DB connection so the pool isn't starved
    if needs_title:
        try:
            title_prompt = SESSION_TITLE_PROMPT.format(message=content)
            title = await ChatAgentClient.generate(
                messages=[{"role": "user", "content": title_prompt}],
                temperature=0.7
            )
            title = title.strip().strip('"').strip("'")
        except Exception as te:
            logger.warning(f"Failed to generate AI title: {te}")
            title = (content[:37] + '...') if len(content) > 40 else content
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE chat_sessions SET title = $1 WHERE id = $2",
                    title, UUID(session_id)
                )
            return title
        except Exception as e:
            logger.error(f"Failed to update session title: {e}")

def classify_intent(question: str) -> str:
    """Rule-based intent classification. Returns: factual / analytical / advisory."""
    q = question.lower()
    if any(kw in q for kw in ADVISORY_KEYWORDS):
        return "advisory"
    if any(kw in q for kw in ANALYTICAL_KEYWORDS):
        return "analytical"
    return "factual"

# ── Portfolio Awareness ──

async def fetch_portfolio_context(pool: asyncpg.Pool, owner_id: str | None) -> str | None:
    """Fetch user portfolio positions and format as natural-language context."""
    if not owner_id or not pool:
        return None
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT symbol, quantity, cost_basis, currency, account "
                "FROM portfolio_positions WHERE source = 'manual' AND user_id = $1 "
                "ORDER BY date DESC LIMIT 50",
                owner_id
            )
            if not rows:
                return None
            lines = []
            for r in rows:
                line = f"{r['symbol']}: {r['quantity']} units"
                if r['cost_basis']:
                    line += f" (avg cost {r['cost_basis']} {r['currency']})"
                if r['account'] and r['account'] != 'default':
                    line += f" [{r['account']}]"
                lines.append(line)
            return PORTFOLIO_CONTEXT_TEMPLATE.format(positions="\n".join(lines))
    except Exception as e:
        logger.warning(f"Portfolio context fetch failed: {e}")
        return None

def build_user_message(
    context_block: str,
    question: str,
    intent: str,
    portfolio_ctx: str | None,
    intelligence_block: str = "",
    conversation_context: str = "",
) -> str:
    """Assemble the final user message with context, intelligence layer, and portfolio data."""
    parts = []

    # Intelligence block goes FIRST — the LLM must read it before any other context
    if intelligence_block:
        parts.append(intelligence_block)

    # Conversation context (from prior turns) — advisory only
    if conversation_context:
        parts.append(conversation_context)

    if context_block:
        parts.append(
            "--- BEGIN RETRIEVED CONTEXT (cite-only, do NOT compute from this) ---\n"
            f"{context_block}\n"
            "--- END RETRIEVED CONTEXT ---\n"
            "[SYSTEM DIRECTIVE]: "
            "CITE figures, dates, and statements from the above context using [S#] or [D#] tags. "
            "Do NOT perform arithmetic on these values. "
            "If a number appears here but NOT in the INVESTMENT INTELLIGENCE LAYER block, "
            "cite it as-is and do NOT derive totals, ratios, or percentages from it."
        )
    if portfolio_ctx:
        parts.append(portfolio_ctx)
    parts.append(f"[Intent: {intent}]")
    parts.append(f"Question:\n{question}")
    return "\n\n".join(parts)

async def regenerate_response(pinecone_index: Any, question: str, cache_key: str, user_role: str = "employee"):
    # 🛡️ Backpressure: background task — skip if LLM is busy (user already got stale response)
    if LLM_SEMAPHORE.locked():
        logger.info(json.dumps({"event": "bg_regeneration_skipped", "reason": "llm_busy"}))
        return

    try:
        logger.info(json.dumps({"event": "bg_regeneration_start"}))

        loop = asyncio.get_running_loop()
        query_vector = await cached_embed(question, loop)
        matches = await vector_store.search(pinecone_index, query_vector, user_role, DYNAMIC_TOP_K)

        good_matches = dynamic_filter(matches)
        relevant_contexts = [m["metadata"]["text"] for m in good_matches]

        if not relevant_contexts:
            return

        context_block = "\n---\n".join(relevant_contexts)

        # 🛡️ Backpressure: acquire semaphore for LLM call
        await LLM_SEMAPHORE.acquire()
        try:
            answer = await ChatAgentClient.generate(
                messages=[
                    {"role": "system", "content": "Answer strictly based on context."},
                    {"role": "user", "content": f"Context:\n{context_block}\n\nQuestion:\n{question}"}
                ]
            )
        finally:
            LLM_SEMAPHORE.release()

        result = {
            "answer": answer,
            "sources": relevant_contexts,
            "source_type": "generated"
        }

        await redis_set(cache_key, {
            "data": result,
            "timestamp": time.time()
        })

        logger.info(json.dumps({"event": "bg_regeneration_done"}))

    except Exception as e:
        logger.error(f"Background regeneration failed: {e}")

# ── SQL Result Formatter: Convert rows to text to reduce arithmetic exposure ──
def _format_sql_rows_as_text(rows: list[dict], max_rows: int = 3) -> str:
    """
    Format SQL result rows as simple text lines instead of JSON.
    Avoids structured numeric data to reduce LLM arithmetic temptation.
    Schema-agnostic: works for any table type.
    """
    if not rows:
        return "No data returned."

    lines = []
    for i, row in enumerate(rows[:max_rows], 1):
        # Convert each row dict to simple key=value pairs
        pairs = [f"{k}={v}" for k, v in row.items()]
        lines.append(f"Row {i}: {', '.join(pairs)}")

    if len(rows) > max_rows:
        lines.append(f"(... {len(rows) - max_rows} more rows)")

    return "\n".join(lines)

# ── Hybrid Retrieval Helpers ─────────────────────────────────────────────────

_SQL_LABEL_MAP = {
    "fx_rate":      "FX Rates",
    "macro_series": "Macro Indicators",
    "price_lookup": "Market Prices",
    "etf_holdings": "ETF Holdings",
}

# Template SQL strings — params are planner-resolved (not raw user input)
_SQL_TEMPLATES = {
    # Fix A: use real fx_rates schema columns (base_currency, quote_currency, date)
    "fx_rate_latest":    "SELECT base_currency, quote_currency, rate, date FROM fx_rates WHERE base_currency='{base}' AND quote_currency='{quote}' ORDER BY date DESC LIMIT 1",
    "macro_series_12":   "SELECT series_id, value, date FROM macro_series WHERE series_id='{series_id}' ORDER BY date DESC LIMIT 12",
    "price_lookup_30d":  "SELECT symbol, date, close FROM prices WHERE symbol='{ticker}' ORDER BY date DESC LIMIT 30",
    # Fix B: etf_holdings planner resolves to {"symbol": ...}, not {"ticker": ...}
    "etf_holdings_top20":"SELECT etf_symbol, holding_symbol, weight FROM etf_holdings WHERE etf_symbol='{symbol}' ORDER BY weight DESC LIMIT 20",
}


def _make_sql_runner(pool):
    """Return async sql_runner(template_id, params) → list[dict] for the Executor."""
    async def _runner(template_id: str, params: dict) -> list[dict]:
        template = _SQL_TEMPLATES.get(template_id)
        if not template or not pool:
            return []
        # Fix C: surface SQL failures as raised exceptions so Executor records status="error"
        sql = template.format(**{k: str(v) for k, v in params.items()})
        result = await run_sql_query(pool, sql)
        if result and isinstance(result[0], dict) and "error" in result[0]:
            raise RuntimeError(result[0]["error"])
        return result
    return _runner


def _make_vector_runner(query_text: str, pool, pinecone_index, embed_model, rerank_model, query: "ChatQuery", loop):
    """Return async vector_runner(VectorFilter) → list[dict] for the Executor."""
    async def _runner(vf) -> list[dict]:
        try:
            q_vec = await cached_embed(query_text, loop)
            if query.owner_id:
                route_result = await route_and_search(
                    pool=pool, embed_model=embed_model, pinecone_index=pinecone_index,
                    rerank_model=rerank_model, question=query_text, user_id=vf.owner_id,
                    top_k=DYNAMIC_TOP_K, document_ids=query.document_ids,
                )
                chunks = route_result["chunks"]
            else:
                filter_metadata = {"doc_type": vf.doc_type} if vf.doc_type else None
                matches = await vector_store.search(
                    pinecone_index, q_vec, query.user_role, top_k=5,
                    filter_metadata=filter_metadata,
                )
                chunks = dynamic_filter(matches)
            if chunks:
                from rag.reranker import rerank_chunks
                chunks = await rerank_chunks(rerank_model, query_text, chunks, top_n=5)
            return chunks
        except Exception as e:
            logger.warning(f"hybrid vector_runner failed: {e}")
            return []
    return _runner


def _fusion_to_context(fusion_result) -> tuple:
    """Convert FusionResult → (contexts, sources, citations, metrics) for downstream use."""
    contexts, sources, citations = [], [], {}
    metrics = {"sql": 0.0, "embed": 0.0, "retrieval": 0.0, "rerank": 0.0, "routing": 0.0}

    for intent_type, rows in (fusion_result.structured_data or {}).items():
        label = _SQL_LABEL_MAP.get(intent_type, "Financial Data")
        row_limit = 20 if intent_type == "etf_holdings" else 3
        sql_text = f"{label} Result:\n{_format_sql_rows_as_text(rows, max_rows=row_limit)}"
        tag = f"[S{len(contexts)+1}]"
        contexts.append(f"Source {tag}: {sql_text}")
        citations[tag] = {"source_type": "sql", "id": "sql_query",
                          "display_name": f"Source: {label} Table", "context": sql_text}
        sources.append({"document_id": "sql_query", "chunk_text": sql_text,
                        "vector_score": 1.0, "rerank_score": 1.0})

    for chunk in (fusion_result.supporting_context or []):
        if not isinstance(chunk, dict):
            continue
        meta = chunk.get("metadata", {}) or {}
        text = meta.get("text") or chunk.get("text", "")
        if not text:
            continue
        doc_id = meta.get("document_id", "unknown")
        filename = meta.get("filename")
        tag = f"[D{len(contexts)+1}]"
        contexts.append(f"Source {tag}: {text}")
        citations[tag] = {"source_type": "document", "id": doc_id,
                          "display_name": filename or "Document", "context": text}
        sources.append({"document_id": doc_id, "filename": filename, "chunk_text": text,
                        "vector_score": round(chunk.get("score", 0.0), 4),
                        "rerank_score": round(chunk.get("rerank_score", 0.0), 4)})

    return contexts, sources, citations, metrics


async def execute_sub_query(pool, pinecone_index, embed_model, rerank_model, plan, query: ChatQuery, loop, user_role: str):
    sql_time = 0.0
    embed_time = 0.0
    retrieval_time = 0.0
    rerank_time = 0.0
    routing_time = 0.0
    
    contexts = []
    sources = []
    
    citation_mapping = {}
    
    if plan.source == "sql":
        t_sql = time.time()
        logger.info(f"executing_sql: {plan.query}")
        result = await run_sql_query(pool, plan.query)
        sql_time = time.time() - t_sql

        # Explicit fallback if SQL returns no data or error
        if result and "error" not in result[0]:
            logger.info(f"sql_results: {len(result)} rows")

            # 🛡️ Security: Mask internal schema/queries, provide safe labels
            table_label = "Financial Data"
            q_lower = plan.query.lower()
            if "fx_rates" in q_lower: table_label = "FX Rates"
            elif "etf_holdings" in q_lower: table_label = "ETF Holdings"
            elif "macro_series" in q_lower: table_label = "Macro Indicators"
            elif "prices" in q_lower: table_label = "Market Prices"

            sql_text = f"{table_label} Result:\n{_format_sql_rows_as_text(result)}"
            tag = f"[S{len(contexts) + 1}]"
            contexts.append(f"Source {tag}: {sql_text}")

            citation_mapping[tag] = {
                "source_type": "sql",
                "id": "sql_query",
                "display_name": f"Source: {table_label} Table",
                "context": sql_text
            }
            sources.append({
                "document_id": "sql_query",
                "chunk_text": sql_text,
                "vector_score": 1.0,
                "rerank_score": 1.0
            })
        else:
            # ─ Fallback: SQL failed, switching to vector ─
            logger.info(json.dumps({
                "event": "fallback_triggered",
                "fallback_stage": "sql_to_vector",
                "reason": "sql_no_results" if not result else "sql_error",
                "original_intent": getattr(plan, "intent", None),
            }))
            plan.source = "vector"
            # Infer context hint from the failed SQL query to guide semantic rewriting
            context_hint = "document_analysis"  # default
            if "fx_rates" in plan.query.lower():
                context_hint = "fx_rate"
            elif "prices" in plan.query.lower():
                context_hint = "price_lookup"
            elif "macro_series" in plan.query.lower():
                context_hint = "macro_series"
            elif "etf_holdings" in plan.query.lower():
                context_hint = "etf_holdings"
            # Rewrite question for semantic search: removes fillers, stop words, adds context suffix
            plan.query = _rewrite_for_semantic_search(query.question, context_hint)

    if plan.source == "vector":
        t_emb = time.time()
        query_vector = await cached_embed(plan.query, loop)
        embed_time = time.time() - t_emb
        
        t_ret = time.time()
        if query.owner_id:
            try:
                t_route = time.time()
                route_result = await route_and_search(
                    pool=pool,
                    embed_model=embed_model,
                    pinecone_index=pinecone_index,
                    rerank_model=rerank_model,
                    question=plan.query,
                    user_id=query.owner_id,
                    top_k=DYNAMIC_TOP_K,
                    document_ids=query.document_ids,
                )
                routing_time = time.time() - t_route
                chunks = route_result["chunks"]
            except Exception:
                chunks = []
        else:
            try:
                # ── Apply document_ids filter if present ──
                filter_metadata = None
                if query.document_ids:
                    filter_metadata = {"doc_id": {"$in": query.document_ids}}
                
                matches = await vector_store.search(
                    pinecone_index, 
                    query_vector, 
                    user_role, 
                    top_k=5, 
                    filter_metadata=filter_metadata
                )
                chunks = dynamic_filter(matches)
            except Exception:
                chunks = []
        retrieval_time = time.time() - t_ret
        
        t_rerank = time.time()
        if chunks:
            from rag.reranker import rerank_chunks
            reranked = await rerank_chunks(rerank_model, plan.query, chunks, top_n=5)
            for m in reranked:
                text = m["metadata"]["text"]
                tag = f"[D{len(contexts) + 1}]"
                contexts.append(f"Source {tag}: {text}")
                citation_mapping[tag] = {
                    "source_type": "document",
                    "id": m["metadata"].get("document_id", "unknown"),
                    "display_name": m["metadata"].get("filename", "Document"),
                    "context": text
                }
                sources.append({
                    "document_id": m["metadata"].get("document_id", "unknown"),
                    "filename": m["metadata"].get("filename"),
                    "chunk_text": text,
                    "vector_score": round(m["score"], 4),
                    "rerank_score": round(m.get("rerank_score", 0.0), 4)
                })
        rerank_time = time.time() - t_rerank
        
    return {
        "contexts": contexts,
        "sources": sources,
        "citation_mapping": citation_mapping,
        "metrics": {
            "sql": sql_time,
            "embed": embed_time,
            "retrieval": retrieval_time,
            "rerank": rerank_time,
            "routing": routing_time
        }
    }

@trace_latency("context_merge")
def merge_contexts(results: list[dict]) -> tuple[list[str], list[dict], dict, dict]:
    """
    Unify contexts, sources, and metrics from multiple plans.
    Also merges citation_mapping.
    """
    all_contexts = []
    all_sources = []
    all_metrics = {"sql": 0.0, "embed": 0.0, "routing": 0.0, "retrieval": 0.0, "rerank": 0.0}
    all_citations = {}

    for r in results:
        all_contexts.extend(r["contexts"])
        all_sources.extend(r["sources"])
        all_citations.update(r.get("citation_mapping", {}))
        for k in all_metrics:
            all_metrics[k] += r["metrics"].get(k, 0.0)

    return all_contexts, all_sources, all_metrics, all_citations


async def generate_chat_response(pool: asyncpg.Pool, pinecone_index: Any, embed_model: SentenceTransformer, rerank_model: Any, query: ChatQuery) -> dict:
    t0 = time.time()
    await state.incr_metric(state.METRIC_TOTAL)
    # 🔹 0. NUMERIC SHORTCUT GUARD — user typed "1" or "a" instead of clicking a button
    if is_numeric_shortcut(query.question):
        logger.info(json.dumps({"event": "numeric_shortcut_rejected", "input_length": len(query.question.strip())}))
        if query.session_id:
            asyncio.create_task(save_message_to_db(pool, query.session_id, "user", query.question))
            asyncio.create_task(save_message_to_db(pool, query.session_id, "assistant", NUMERIC_SHORTCUT_RESPONSE))
        return {
            "answer": NUMERIC_SHORTCUT_RESPONSE,
            "sources": [],
            "citations": {},
            "suggested_questions": [],
            "source_type": "generated",
            "latency_breakdown": {"total": 0.0},
        }

    # 🔹 1. CACHE CHECK (before condense_question to avoid unnecessary LLM call)
    cache_key_input = f"{query.user_role}:{query.owner_id or ''}:{query.question}"
    cache_key = generate_cache_key(cache_key_input)
    current_time = time.time()

    cache_entry = await redis_get(cache_key)

    if cache_entry is not None:
        age = current_time - cache_entry["timestamp"]

        # 🟡 SOFT EXPIRED → Return stale + background refresh
        if age > CACHE_SOFT_TTL:
            logger.info(json.dumps({"event": "cache_stale", "action": "return_stale_and_refresh"}))
            obs.emit(PipelineStage.CACHE, "cache_stale",
                     summary="Exact cache stale — returning stale response + background refresh",
                     data={"age_s": round(age, 1)})
            asyncio.create_task(
                regenerate_response(pinecone_index, query.question, cache_key, query.user_role)
            )
            cached = cache_entry["data"]
            cached["source_type"] = "stale"
            if query.session_id:
                asyncio.create_task(save_message_to_db(pool, query.session_id, "user", query.question))
                asyncio.create_task(save_message_to_db(pool, query.session_id, "assistant", cached["answer"], cached.get("citations"), {}))
            return cached

        # 🟢 VALID
        else:
            logger.info(json.dumps({"event": "cache_hit"}))
            obs.emit(PipelineStage.CACHE, "cache_hit",
                     summary="Exact cache hit — skipping pipeline",
                     data={"age_s": round(age, 1)})
            await state.incr_metric(state.METRIC_HIT)
            cached = cache_entry["data"]
            cached["source_type"] = "cache"
            if query.session_id:
                asyncio.create_task(save_message_to_db(pool, query.session_id, "user", query.question))
                asyncio.create_task(save_message_to_db(pool, query.session_id, "assistant", cached["answer"], cached.get("citations"), {}))
            return cached

    await state.incr_metric(state.METRIC_MISS)
    obs.emit(PipelineStage.CACHE, "cache_miss",
             summary="No exact cache hit — proceeding to full pipeline",
             status=EventStatus.WARNING)

    # 🔹 0. CONDENSE QUESTION (only on cache miss)
    # Load stored summary early so condense_question can resolve references from older turns
    condensation_summary = await SessionMemoryStore.get(query.owner_id, query.session_id) if query.session_id and query.owner_id else None
    standalone_question = await condense_question(query.history, query.question, summary=condensation_summary)
    logger.info(f"standalone_question: {standalone_question}")

    if not pinecone_index:
        raise HTTPException(500, "Vector store not connected")

    loop = asyncio.get_running_loop()
    query_vector = await cached_embed(query.question, loop)
    
    # 🔹 1.5 SEMANTIC CACHE LOOKUP
    sem_result = await semantic_cache_lookup(query_vector, query.user_role, owner_id=query.owner_id)
    if sem_result is not None:
        logger.info(json.dumps({"event": "semantic_cache_hit"}))
        obs.emit(PipelineStage.CACHE, "semantic_cache_hit",
                 summary="Semantic cache hit — semantically similar cached response returned",
                 data={"cache_type": "semantic"})
        await state.incr_metric(state.METRIC_HIT)
        sem_result["source_type"] = "semantic_cache"
        if query.session_id:
            asyncio.create_task(save_message_to_db(pool, query.session_id, "user", query.question))
            asyncio.create_task(save_message_to_db(pool, query.session_id, "assistant", sem_result["answer"], sem_result.get("citations"), {}))
        return sem_result

    # 🔹 2. HYBRID RETRIEVAL PLANNING
    t_plan = time.time()
    hybrid_plan = _hybrid_build_plan(standalone_question, query.owner_id or "")
    plan_time = time.time() - t_plan
    obs.emit(
        PipelineStage.ROUTER, "router_plan_built",
        summary=f"{hybrid_plan.plan_meta.total_steps} step(s) — hybrid={hybrid_plan.plan_meta.is_hybrid}",
        latency_ms=plan_time * 1000,
        data={"step_count": hybrid_plan.plan_meta.total_steps,
              "is_hybrid": hybrid_plan.plan_meta.is_hybrid},
    )

    # 🔹 3. HYBRID RETRIEVAL EXECUTION + FUSION
    t_ret_start = time.time()
    _step_results = await _hybrid_execute_plan(
        hybrid_plan, query.owner_id or "",
        sql_runner=_make_sql_runner(pool),
        vector_runner=_make_vector_runner(standalone_question, pool, pinecone_index, embed_model, rerank_model, query, loop),
    )
    fusion_result = _hybrid_fuse(hybrid_plan, _step_results)
    retrieval_time = time.time() - t_ret_start

    relevant_contexts, sources, citations, metrics = _fusion_to_context(fusion_result)

    # ─ After Context Assembly: High-signal routing & context metadata ─
    has_sql_context = any(s.get("source_type") == "sql" for s in sources)
    has_vector_context = any(s.get("source_type") != "sql" for s in sources)
    sql_row_count = sum(
        len(s.get("chunk_text", "").split("\n"))
        for s in sources if s.get("source_type") == "sql"
    )
    document_chunk_count = len([s for s in sources if s.get("source_type") != "sql"])

    logger.info(json.dumps({
        "event": "context_assembly_complete",
        "request_id": getattr(query, "request_id", None),
        "owner_id_exists": bool(query.owner_id),
        "plan_steps": hybrid_plan.plan_meta.total_steps,
        "is_hybrid": hybrid_plan.plan_meta.is_hybrid,
        "has_sql_context": has_sql_context,
        "has_vector_context": has_vector_context,
        "sql_row_count": sql_row_count,
        "document_chunk_count": document_chunk_count,
        "context_count": len(relevant_contexts),
    }))

    obs.emit(
        PipelineStage.VECTOR_RETRIEVAL, "retrieval_complete",
        summary=f"Retrieved {len(relevant_contexts)} context chunk(s) from {hybrid_plan.plan_meta.total_steps} plan step(s)",
        latency_ms=retrieval_time * 1000,
        data={
            "context_count": len(relevant_contexts),
            "source_count":  len(sources),
            "sql_ms":        round(metrics.get("sql", 0) * 1000, 1),
            "embed_ms":      round(metrics.get("embed", 0) * 1000, 1),
            "rerank_ms":     round(metrics.get("rerank", 0) * 1000, 1),
        },
    )

    # 🔹 5. Generation
    context_block = "\n---\n".join(relevant_contexts) if relevant_contexts else ""
    intent = classify_intent(standalone_question)
    portfolio_ctx = await fetch_portfolio_context(pool, query.owner_id)

    # Fetch user profile early — needed by both the Intelligence Layer and the system prompt
    user_profile = None
    if query.owner_id:
        try:
            user_profile = await UserProfileService.get_profile(pool, query.owner_id)
        except Exception as _e:
            logger.warning(f"Early profile fetch failed: {_e}")

    # Check for scenario simulation intent
    is_sim = is_simulation_query(standalone_question)
    if is_sim:
        intent = "simulation" # Override for prompt injection or specialized handling
        logger.info(json.dumps({"event": "simulation_detected", "question": standalone_question[:50]}))

    # 🔹 5.5 INVESTMENT INTELLIGENCE LAYER
    # Runs between retrieval and LLM synthesis. Failure is isolated — never crashes the pipeline.
    intelligence_block = ""
    pipeline_confidence: str | None = None   # deterministic — overrides LLM self-reported confidence
    _intelligence_report = None
    _system_action: str | None = None
    _confidence_before_validation: str | None = None
    _downgrade_happened: bool = False
    _skip_intelligence = (
        bool(hybrid_plan.steps)
        and all(s.source_type == "SQL" and s.intent_type == "etf_holdings"
                for s in hybrid_plan.steps)
    )
    t_intel = time.time()
    try:
        if _skip_intelligence:
            raise RuntimeError("__skip_intelligence__")
        intelligence_report = await IntelligenceOrchestrator.run(
            question=standalone_question,
            intent=intent,
            raw_profile=user_profile,   # may be None — orchestrator handles gracefully
            owner_id=query.owner_id,
            pool=pool,
        )
        _intelligence_report = intelligence_report
        _confidence_before_validation = intelligence_report.pipeline_confidence
        pipeline_confidence = intelligence_report.pipeline_confidence
        intelligence_block = build_intelligence_context(intelligence_report)
        _val_flags = (
            intelligence_report.validation_result.flags
            if intelligence_report.validation_result else []
        )
        _val_flags_count = len(_val_flags)

        # Detect if validation downgraded confidence
        if intelligence_report.validation_result and intelligence_report.validation_result.confidence_override:
            if intelligence_report.validation_result.confidence_override != _confidence_before_validation:
                _downgrade_happened = True
                pipeline_confidence = intelligence_report.validation_result.confidence_override

        _system_action = (
            intelligence_report.recommendation.action
            if getattr(intelligence_report, "recommendation", None) else None
        )

        # ─ After Intelligence Pipeline: Confidence tracking & validation state ─
        logger.info(json.dumps({
            "event": "intelligence_pipeline_complete",
            "selected_action": str(_system_action) if _system_action else None,
            "confidence_before_validation": _confidence_before_validation,
            "final_confidence": pipeline_confidence,
            "downgrade_happened": _downgrade_happened,
            "validation_flags_count": _val_flags_count,
            "agents_ran": intelligence_report.agents_ran,
            "has_recommendations": intelligence_report.has_recommendations,
        }))

        logger.info(json.dumps({
            "event": "intelligence_layer_complete",
            "agents_ran": intelligence_report.agents_ran,
            "confidence": pipeline_confidence,
            "has_recommendations": intelligence_report.has_recommendations,
            "validation_passed": (
                intelligence_report.validation_result.passed
                if intelligence_report.validation_result else None
            ),
        }))
        obs.emit(
            PipelineStage.VALIDATION, "intelligence_layer_complete",
            summary=f"Intelligence pipeline done — confidence={pipeline_confidence}, action={_system_action}",
            latency_ms=(time.time() - t_intel) * 1000,
            data={
                "agents_ran":          intelligence_report.agents_ran,
                "confidence":          pipeline_confidence,
                "system_action":       _system_action,
                "has_recommendations": intelligence_report.has_recommendations,
                "validation_passed":   (intelligence_report.validation_result.passed
                                        if intelligence_report.validation_result else None),
                "validation_flags":    _val_flags,
            },
        )
    except Exception as intel_err:
        if str(intel_err) != "__skip_intelligence__":
            logger.warning(json.dumps({"event": "intelligence_layer_failed", "error": str(intel_err)}))
            obs.emit_error(
                stage=PipelineStage.USER_PROFILER,
                error_category=ErrorCategory.PIPELINE,
                error_code="INTELLIGENCE_LAYER_FAILED",
                message=str(intel_err),
                exc=intel_err,
            )
        _val_flags = []
        _val_flags_count = 0
        _confidence_before_validation = None
        _downgrade_happened = False

    # Build memory: load stored summary or create from history
    history_summary = await get_memory(pool, query.session_id, query.owner_id, query.history)
    conversation_context = build_conversation_context(history_summary)

    user_message = build_user_message(context_block, standalone_question, intent, portfolio_ctx,
                                      intelligence_block=intelligence_block,
                                      conversation_context=conversation_context)
    t_gen = time.time()

    # 🔹 6. Context Flags for Guidance Layer
    has_portfolio = portfolio_ctx is not None
    is_new_session = not query.history
    # HAS_CONTEXT: were chunks actually retrieved for this query?
    has_context = len(relevant_contexts) > 0
    # HAS_DOCUMENTS: does the user have any successfully indexed documents?
    has_any_docs = False
    if query.owner_id:
        try:
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM documents WHERE owner_id = $1 AND status = 'completed'",
                    query.owner_id
                )
                has_any_docs = count > 0
        except Exception as e:
            logger.warning(f"Failed to check document count: {e}")

    # 🔹 7. Prepend Flags to System Prompt
    system_content = (
        f"CONTEXT_FLAGS:\n"
        f"HAS_CONTEXT={has_context}\n"
        f"HAS_DOCUMENTS={has_any_docs}\n"
        f"HAS_PORTFOLIO={has_portfolio}\n"
        f"IS_NEW_SESSION={is_new_session}\n\n"
        f"{CHAT_SYSTEM_PROMPT}"
    )
    messages = [{"role": "system", "content": system_content}]

    # 🔹 6. Personalization: User Profile Injection (Stage: Proactive Advisor)
    # user_profile was already fetched early (before intelligence layer) — reuse it here
    if query.owner_id and user_profile:
        try:
            profile_block = UserProfileService.format_profile_for_prompt(user_profile)
            messages.append({"role": "system", "content": profile_block})

            # Legacy persona support (or merged)
            if user_profile.get("custom_persona"):
                messages.append({
                    "role": "system",
                    "content": f"USER PERSONAL BEHAVIOR PREFERENCES:\n{user_profile['custom_persona']}\n\nStrictly follow these conversational style or analysis preferences if they do not violate safety rules."
                })

            # Trigger dynamic profile update in background
            logger.info(json.dumps({"event": "profile_update_triggered", "user_id": query.owner_id}))
            asyncio.create_task(UserProfileService.update_profile_from_query(pool, query.owner_id, standalone_question))
            
        except Exception as e:
            logger.warning(f"Failed to fetch or update user profile: {e}")
    
    if history_summary:
        messages.append({"role": "system", "content": f"Context Summary of previous conversation:\n{history_summary}"})
        # Keep only the last 3 messages if we have a summary
        for m in query.history[-3:]:
            messages.append({"role": m.role, "content": m.content})
    else:
        # No summary needed yet, keep all (up to 6)
        for m in query.history[-6:]:
            messages.append({"role": m.role, "content": m.content})
    
    messages.append({"role": "user", "content": user_message})

    # 🔹 Save User Message to DB
    if query.session_id:
        asyncio.create_task(save_message_to_db(pool, query.session_id, "user", query.question))

    # 🔹 LLM PROMPT BUILD — record what we're about to send
    _llm_input_blocks = build_llm_input_blocks(intelligence_block, context_block, portfolio_ctx)
    obs.emit(
        PipelineStage.LLM_PROMPT_BUILD, "prompt_assembled",
        summary=(
            f"Prompt assembled — ~{_llm_input_blocks.estimated_prompt_tokens} tokens, "
            f"blocks: portfolio={_llm_input_blocks.has_normalized_portfolio}, "
            f"market={_llm_input_blocks.has_market_context}, "
            f"validation={_llm_input_blocks.has_validation_block}, "
            f"vector={_llm_input_blocks.has_vector_context}"
        ),
        data=_llm_input_blocks.model_dump(),
    )

    try:
        await asyncio.wait_for(LLM_SEMAPHORE.acquire(), timeout=LLM_WAIT_TIMEOUT)
    except asyncio.TimeoutError:
        obs.emit_error(
            stage=PipelineStage.LLM_EXECUTION,
            error_category=ErrorCategory.INFRA,
            error_code="LLM_SEMAPHORE_TIMEOUT",
            message=f"LLM semaphore wait exceeded {LLM_WAIT_TIMEOUT}s — server overloaded",
        )
        raise HTTPException(503, "Server busy — too many concurrent LLM requests. Try again in a few seconds.")

    # ─ Right Before LLM Call: Precondition metrics ─
    _context_size_chars = len(context_block)
    _user_msg_size_chars = len(user_message)
    _estimated_tokens = round((_context_size_chars + _user_msg_size_chars) / 4)  # rough approximation
    _has_validation_block = bool(_intelligence_report and _intelligence_report.validation_result)
    _has_normalized_portfolio = bool(_intelligence_report and _intelligence_report.normalized_portfolio)

    logger.info(json.dumps({
        "event": "llm_call_preconditions",
        "pipeline_confidence": pipeline_confidence,
        "context_size_chars": _context_size_chars,
        "user_message_size_chars": _user_msg_size_chars,
        "estimated_tokens": _estimated_tokens,
        "sql_row_count": sql_row_count if 'sql_row_count' in locals() else 0,
        "document_chunk_count": document_chunk_count if 'document_chunk_count' in locals() else 0,
        "has_validation_block": _has_validation_block,
        "has_normalized_portfolio": _has_normalized_portfolio,
    }))

    t_llm = time.time()
    try:
        answer = await ChatAgentClient.generate(messages=messages)
    finally:
        LLM_SEMAPHORE.release()
    _llm_latency_ms = (time.time() - t_llm) * 1000
    obs.emit(
        PipelineStage.LLM_EXECUTION, "llm_call_done",
        summary=f"LLM responded in {round(_llm_latency_ms)}ms — {len(answer)} chars",
        latency_ms=_llm_latency_ms,
        data={"response_chars": len(answer)},
    )

    suggested_questions = []
    reasoning_summary = None
    # confidence_level: always use the deterministic pipeline_confidence when available.
    # The LLM's self-reported confidence (from [[Explainability:]]) is accepted only as
    # a fallback when no intelligence layer ran (e.g., factual queries with no portfolio data).
    confidence_level = pipeline_confidence   # may be None if intelligence layer didn't run

    if "[[Explainability:" in answer:
        try:
            parts = answer.split("[[Explainability:")
            main_content = parts[0].strip()
            exp_part = parts[1].split("]]")[0].strip()
            exp_data = json.loads(exp_part)
            reasoning_summary = exp_data.get("reasoning_summary")
            # Only use LLM's confidence as fallback — deterministic confidence takes priority
            if confidence_level is None:
                confidence_level = exp_data.get("confidence_level")
            
            # Remove the suggested questions part if it exists after explainability
            after_exp = parts[1].split("]]")[1] if len(parts[1].split("]]")) > 1 else ""
            answer = main_content
            # Re-attach suggested questions to the search if they were stripped
            if "[[SuggestedQuestions:" in after_exp:
                answer += f"\n\n[[SuggestedQuestions:{after_exp.split('[[SuggestedQuestions:')[1]}"
            elif "[[SuggestedQuestions:" in main_content:
                # it might be before explainability in some cases, though prompt says after
                pass
        except Exception as e:
            logger.warning(f"Failed to parse explainability metadata: {e}")

    if "[[SuggestedQuestions:" in answer:
        try:
            parts = answer.split("[[SuggestedQuestions:")
            answer = parts[0].strip()
            questions_part = parts[1].split("]]")[0].strip()
            suggested_questions = json.loads(questions_part)
        except Exception as e:
            logger.warning(f"Failed to parse suggested questions: {e}")

    gen_time = time.time() - t_gen
    total_time = time.time() - t0

    # 🔹 LLM INTROSPECTION — build and emit the full LLM trace
    try:
        _llm_output = build_llm_output_structure(
            answer=answer,
            suggested_questions=suggested_questions,
            pipeline_confidence=pipeline_confidence,
            reasoning_summary=reasoning_summary,
            system_action=_system_action,
        )
        _llm_behavior = analyze_llm_behavior(
            response=answer,
            pipeline_confidence=pipeline_confidence,
            system_action=_system_action,
            validation_flags=_val_flags,
            input_blocks=_llm_input_blocks,
        )
        _llm_trace = LLMTrace(
            req_id=obs._req_id(),
            input_blocks=_llm_input_blocks,
            constraints=LLMConstraints(
                forbidden_operations_applied=True,
                no_arithmetic_mode=True,
                cite_only_directive=True,
                intelligence_block_injected=bool(intelligence_block),
            ),
            output_structure=_llm_output,
            behavior=_llm_behavior,
            latency_ms=_llm_latency_ms,
        )
        obs.emit_llm_trace(_llm_trace)
        obs.emit(
            PipelineStage.RESPONSE, "response_finalized",
            summary=(
                f"Response ready — behavior={_llm_behavior.classification}, "
                f"confidence={pipeline_confidence}, flags={[f.value for f in _llm_behavior.flags]}"
            ),
            latency_ms=total_time * 1000,
            data={
                "behavior":   _llm_behavior.classification,
                "flags":      [f.value for f in _llm_behavior.flags],
                "confidence": pipeline_confidence,
                "total_ms":   round(total_time * 1000, 1),
                "sources":    len(sources),
            },
            severity=EventSeverity.WARNING if _llm_behavior.classification != "followed_system" else EventSeverity.INFO,
        )
    except Exception as _trace_err:
        logger.warning(f"LLM trace build failed (non-fatal): {_trace_err}")

    result = {
        "answer": answer,
        "sources": sources,
        "citations": citations,
        "suggested_questions": suggested_questions,
        "source_type": "generated",
        "reasoning_summary": reasoning_summary,
        "confidence_level": confidence_level,
        "latency_breakdown": {
            "planning": round(plan_time, 3),
            "sql": round(metrics["sql"], 3),
            "embedding": round(metrics["embed"], 3),
            "routing":   round(metrics["routing"], 3),
            "retrieval": round(retrieval_time, 3),
            "rerank":    round(metrics["rerank"], 3),
            "generation": round(gen_time, 3),
            "total": round(time.time() - t0, 3)
        }
    }

    # 🔹 Save Assistant Message to DB
    if query.session_id:
        # Include reasoning/confidence in metadata (stored in latency column for now)
        metadata = result["latency_breakdown"].copy()
        metadata["reasoning_summary"] = reasoning_summary
        metadata["confidence_level"] = confidence_level

        asyncio.create_task(save_message_to_db(
            pool, query.session_id, "assistant", answer, citations, metadata, suggested_questions
        ))

        # Update session memory before response completes (ensure write is visible on next request)
        try:
            new_summary = SummaryBuilder.build(query.history + [type('Message', (), {'role': 'assistant', 'content': answer})])
            if new_summary:
                await SessionMemoryStore.set(query.owner_id, query.session_id, new_summary)
        except Exception as e:
            logger.warning(f"Failed to update session memory after response: {e}")

    # 🔹 6. Store in Redis Cache + Semantic Cache
    await redis_set(cache_key, {
        "data": result,
        "timestamp": time.time()
    })
    await semantic_cache_store(query_vector, query.user_role, cache_key, owner_id=query.owner_id)

    # 🔹 8. Strict Source Control Logging & Validation
    retrieved_ids = {s['document_id'] for s in sources if s.get('document_id') and s['document_id'] != 'unknown'}
    selected_ids = set(query.document_ids or [])

    source_violation = False
    if selected_ids and not retrieved_ids.issubset(selected_ids):
        source_violation = True
        logger.error(f"STRICT SOURCE VIOLATION: Retrieved {retrieved_ids} is not subset of Selected {selected_ids}")

    # Extract display names from actual citations for debugging visibility
    selected_source_names = [c.get("display_name") or c.get("id") for c in citations.values()]

    logger.info(json.dumps({
        "event": "query_processed",
        "selected_sources": selected_source_names,
        "retrieved_sources": list(retrieved_ids),
        "source_violation": source_violation,
        "mode": "sync",
        "question_hash": generate_cache_key(query.question)[:8],
        "total_s": round(total_time, 3),
        "embed_s": round(metrics["embed"], 3),
        "retrieval_s": round(retrieval_time, 3),
        "rerank_s": round(metrics["rerank"], 3),
        "generation_s": round(gen_time, 3)
    }))

    await state.record_value(state.LIST_LATENCY, total_time)

    # 🔹 Audit Log (Metadata only, NO content)
    asyncio.create_task(log_audit_event(
        pool=pool,
        event_type="chat",
        user_id=query.owner_id,
        resource_id=query.session_id,
        action="read",
        status="success",
        metadata={
            "latency_ms": int(total_time * 1000),
            "message_length": len(query.question),
            "response_length": len(result["answer"]),
            "source_count": len(result["sources"]),
            "is_cache_hit": result.get("source_type") in ["cache", "semantic_cache"]
        }
    ))

    return result



# ── Stream Stage 1 ───────────────────────────────────────────────────────────

async def _prepare_or_short_circuit_stream(
    pool: asyncpg.Pool, query: "ChatQuery", pinecone_index: Any, t0: float
) -> dict:
    """Metric init, numeric shortcut guard, exact cache, semantic cache early returns.
    Returns dict with 'short_circuit' bool. If True, 'packets' has all SSE strings to
    yield before returning. If False, also provides cache_key, standalone_question,
    query_vector, loop for downstream stages."""
    await state.incr_metric(state.METRIC_TOTAL)

    if is_numeric_shortcut(query.question):
        logger.info(json.dumps({"event": "numeric_shortcut_rejected", "input_length": len(query.question.strip())}))
        if query.session_id:
            asyncio.create_task(save_message_to_db(pool, query.session_id, "user", query.question))
            asyncio.create_task(save_message_to_db(pool, query.session_id, "assistant", NUMERIC_SHORTCUT_RESPONSE))
        await state.decr_active_streams()
        return {
            "short_circuit": True,
            "packets": [
                f"data: {json.dumps({'type': 'meta', 'sources': [], 'source_type': 'generated'})}\n\n",
                f"data: {json.dumps({'type': 'token', 'content': NUMERIC_SHORTCUT_RESPONSE})}\n\n",
                f"data: {json.dumps({'type': 'done', 'total_time': 0.0})}\n\n",
            ],
        }

    cache_key_input = f"{query.user_role}:{query.owner_id or ''}:{query.question}"
    cache_key = generate_cache_key(cache_key_input)
    cache_entry = await redis_get(cache_key)
    if cache_entry is not None:
        age = time.time() - cache_entry["timestamp"]
        cached = cache_entry["data"]
        if age > CACHE_SOFT_TTL:
            asyncio.create_task(regenerate_response(pinecone_index, query.question, cache_key, query.user_role))
            source_type = "stale"
        else:
            await state.incr_metric(state.METRIC_HIT)
            source_type = "cache"
        if query.session_id:
            asyncio.create_task(save_message_to_db(pool, query.session_id, "user", query.question))
            asyncio.create_task(save_message_to_db(pool, query.session_id, "assistant", cached["answer"], cached.get("citations"), {}))
        await state.decr_active_streams()
        return {
            "short_circuit": True,
            "packets": [
                f"data: {json.dumps({'type': 'meta', 'sources': cached.get('sources', []), 'source_type': source_type})}\n\n",
                f"data: {json.dumps({'type': 'token', 'content': cached['answer']})}\n\n",
                f"data: {json.dumps({'type': 'done', 'total_time': round(time.time() - t0, 3)})}\n\n",
            ],
        }

    await state.incr_metric(state.METRIC_MISS)

    if not pinecone_index:
        await state.decr_active_streams()
        return {
            "short_circuit": True,
            "packets": [f"data: {json.dumps({'type': 'error', 'msg': 'Vector store not connected'})}\n\n"],
        }

    logger.info(json.dumps({"event": "prepare_memory_load_start", "session_id": query.session_id}))
    try:
        condensation_summary = (
            await SessionMemoryStore.get(query.owner_id, query.session_id)
            if query.session_id and query.owner_id else None
        )
        logger.info(json.dumps({"event": "prepare_memory_load_done", "has_summary": bool(condensation_summary)}))
    except Exception as e:
        logger.exception(json.dumps({"event": "prepare_memory_load_error", "exception": str(e)}))
        condensation_summary = None

    standalone_question = await condense_question(query.history, query.question, summary=condensation_summary)

    loop = asyncio.get_running_loop()
    query_vector = await cached_embed(standalone_question, loop)

    sem_result = await semantic_cache_lookup(query_vector, query.user_role, owner_id=query.owner_id)
    if sem_result is not None:
        await state.incr_metric(state.METRIC_HIT)
        if query.session_id:
            asyncio.create_task(save_message_to_db(pool, query.session_id, "user", query.question))
            asyncio.create_task(save_message_to_db(pool, query.session_id, "assistant", sem_result["answer"], sem_result.get("citations"), {}))
        await state.decr_active_streams()
        return {
            "short_circuit": True,
            "packets": [
                f"data: {json.dumps({'type': 'meta', 'sources': sem_result.get('sources', []), 'source_type': 'semantic_cache'})}\n\n",
                f"data: {json.dumps({'type': 'token', 'content': sem_result['answer']})}\n\n",
                f"data: {json.dumps({'type': 'done', 'total_time': round(time.time() - t0, 3)})}\n\n",
            ],
        }

    return {
        "short_circuit": False,
        "packets": [],
        "cache_key": cache_key,
        "standalone_question": standalone_question,
        "query_vector": query_vector,
        "loop": loop,
    }


# ── Stream Stage 2 ───────────────────────────────────────────────────────────

async def _run_retrieval_stage(
    pool: asyncpg.Pool, pinecone_index: Any,
    embed_model: SentenceTransformer, rerank_model: Any,
    query: "ChatQuery", standalone_question: str,
    query_vector: Any, loop: asyncio.AbstractEventLoop,
) -> dict:
    """Build plan → execute → fuse → fusion_to_context.
    Returns retrieval dict: hybrid_plan, plan_time, retrieval_time,
    relevant_contexts, sources, citations, metrics, context_block."""
    t_plan = time.time()
    hybrid_plan = _hybrid_build_plan(standalone_question, query.owner_id or "")
    plan_time = time.time() - t_plan
    logger.info(json.dumps({"event": "stage_retrieval_plan_built",
                             "steps": hybrid_plan.plan_meta.total_steps,
                             "hybrid": hybrid_plan.plan_meta.is_hybrid}))

    t_ret = time.time()
    _step_results = await _hybrid_execute_plan(
        hybrid_plan, query.owner_id or "",
        sql_runner=_make_sql_runner(pool),
        vector_runner=_make_vector_runner(
            standalone_question, pool, pinecone_index, embed_model, rerank_model, query, loop),
    )
    fusion_result = _hybrid_fuse(hybrid_plan, _step_results)
    retrieval_time = time.time() - t_ret

    relevant_contexts, sources, citations, metrics = _fusion_to_context(fusion_result)

    # Contract guards
    if not isinstance(sources, list):
        logger.warning(json.dumps({"event": "retrieval_contract_violation", "field": "sources"}))
        sources = []
    if not isinstance(citations, dict):
        logger.warning(json.dumps({"event": "retrieval_contract_violation", "field": "citations"}))
        citations = {}
    if not isinstance(relevant_contexts, list):
        relevant_contexts = []

    context_block = "\n---\n".join(relevant_contexts) if relevant_contexts else ""
    logger.info(json.dumps({"event": "stage_retrieval_complete",
                             "context_count": len(relevant_contexts),
                             "source_count": len(sources),
                             "plan_time_ms": round(plan_time * 1000, 1),
                             "retrieval_time_ms": round(retrieval_time * 1000, 1)}))
    return {
        "hybrid_plan": hybrid_plan, "plan_time": plan_time,
        "retrieval_time": retrieval_time, "relevant_contexts": relevant_contexts,
        "sources": sources, "citations": citations, "metrics": metrics,
        "context_block": context_block,
    }


# ── Stream Stage 3 ───────────────────────────────────────────────────────────

async def _build_guidance_stage(
    pool: asyncpg.Pool, query: "ChatQuery",
    standalone_question: str, context_block: str, sources: list,
) -> dict:
    """Portfolio context, user profile, has_documents, intent, intelligence layer.
    Returns guidance dict consumed by prompt builder and observability stages."""
    portfolio_ctx = await fetch_portfolio_context(pool, query.owner_id)
    has_portfolio = portfolio_ctx is not None
    is_new_session = not query.history
    has_context = bool(context_block)

    user_profile = None
    profile_block = ""
    if query.owner_id:
        try:
            user_profile = await UserProfileService.get_profile(pool, query.owner_id)
            profile_block = UserProfileService.format_profile_for_prompt(user_profile)
            asyncio.create_task(UserProfileService.update_profile_from_query(pool, query.owner_id, standalone_question))
        except Exception as e:
            logger.warning(f"Failed to fetch user profile in stream: {e}")

    has_any_docs = False
    if query.owner_id:
        try:
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM documents WHERE owner_id = $1 AND status = 'completed'",
                    query.owner_id)
                has_any_docs = (count or 0) > 0
        except Exception as e:
            logger.warning(f"Failed to check document count in stream: {e}")

    intent = classify_intent(standalone_question)
    if is_simulation_query(standalone_question):
        intent = "simulation"

    _system_action = "EXPLANATION" if not has_portfolio else "SYNTHESIS"
    if intent == "advisory":
        _system_action = "ADVISORY"

    intelligence_block = ""
    pipeline_confidence: str | None = None
    try:
        intelligence_report = await IntelligenceOrchestrator.run(
            question=standalone_question, intent=intent,
            raw_profile=user_profile, owner_id=query.owner_id, pool=pool,
        )
        pipeline_confidence = intelligence_report.pipeline_confidence
        intelligence_block = build_intelligence_context(intelligence_report)
        logger.info(json.dumps({"event": "stage_guidance_intelligence_complete",
                                 "agents_ran": intelligence_report.agents_ran,
                                 "confidence": pipeline_confidence}))
    except Exception as intel_err:
        logger.warning(json.dumps({"event": "intelligence_layer_failed_stream", "error": str(intel_err)}))

    _llm_input_blocks = build_llm_input_blocks(intelligence_block, context_block, portfolio_ctx)
    logger.info(json.dumps({"event": "stage_guidance_complete", "has_portfolio": has_portfolio,
                             "has_any_docs": has_any_docs, "intent": intent,
                             "has_intelligence": bool(intelligence_block)}))
    return {
        "portfolio_ctx": portfolio_ctx, "has_portfolio": has_portfolio,
        "is_new_session": is_new_session, "has_context": has_context,
        "user_profile": user_profile, "profile_block": profile_block,
        "has_any_docs": has_any_docs, "intent": intent,
        "intelligence_block": intelligence_block, "pipeline_confidence": pipeline_confidence,
        "_system_action": _system_action, "_llm_input_blocks": _llm_input_blocks,
    }


# ── Stream Stage 4 ───────────────────────────────────────────────────────────

async def _build_prompt_stage(
    pool: asyncpg.Pool, query: "ChatQuery",
    standalone_question: str, guidance: dict, retrieval: dict,
) -> list[dict]:
    """System prompt, user message, history summary → final stream_messages list."""
    system_content = (
        f"CONTEXT_FLAGS:\n"
        f"HAS_CONTEXT={guidance['has_context']}\n"
        f"HAS_DOCUMENTS={guidance['has_any_docs']}\n"
        f"HAS_PORTFOLIO={guidance['has_portfolio']}\n"
        f"IS_NEW_SESSION={guidance['is_new_session']}\n\n"
        f"{guidance['profile_block']}\n"
        f"{CHAT_STREAM_PROMPT}"
    )
    history_summary = await get_memory(pool, query.session_id, query.owner_id, query.history)
    conversation_context = build_conversation_context(history_summary)

    user_message = build_user_message(
        retrieval["context_block"], standalone_question,
        guidance["intent"], guidance["portfolio_ctx"],
        intelligence_block=guidance["intelligence_block"],
        conversation_context=conversation_context,
    )

    stream_messages = [{"role": "system", "content": system_content}]
    if history_summary:
        stream_messages.append({"role": "system", "content": f"Context Summary of previous conversation:\n{history_summary}"})
        for m in query.history[-3:]:
            stream_messages.append({"role": m.role, "content": m.content})
    else:
        for m in query.history[-6:]:
            stream_messages.append({"role": m.role, "content": m.content})
    stream_messages.append({"role": "user", "content": user_message})

    logger.info(json.dumps({"event": "stage_prompt_complete", "message_count": len(stream_messages),
                             "has_history_summary": bool(history_summary)}))
    return stream_messages


# ── Stream Stage 5 ───────────────────────────────────────────────────────────

async def _stream_llm_stage(
    stream_messages: list[dict], deadline: float, result_bag: dict
) -> AsyncGenerator[str, None]:
    """Run ChatAgentClient.generate_stream, filter [[ ]] metadata, yield token events.
    Caller must hold LLM_SEMAPHORE. Populates result_bag['full_answer'] and result_bag['gen_time']."""
    t3 = time.time()
    collected_tokens: list[str] = []
    in_metadata_block = False

    stream = ChatAgentClient.generate_stream(messages=stream_messages)
    async for token in stream:
        if time.time() > deadline:
            logger.warning(json.dumps({"event": "stream_timeout", "max_duration_s": MAX_STREAM_DURATION}))
            yield f"data: {json.dumps({'type': 'error', 'msg': 'Stream timed out'})}\n\n"
            break

        collected_tokens.append(token)

        if "[[" in token:
            in_metadata_block = True
            clean_part = token.split("[[")[0]
            if clean_part:
                yield f"data: {json.dumps({'type': 'token', 'content': clean_part})}\n\n"
            continue

        if "]]" in token:
            in_metadata_block = False
            clean_part = token.split("]]")[-1]
            if clean_part:
                yield f"data: {json.dumps({'type': 'token', 'content': clean_part})}\n\n"
            continue

        if not in_metadata_block:
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

    result_bag["full_answer"] = "".join(collected_tokens)
    result_bag["gen_time"] = time.time() - t3


# ── Stream Stage 6 ───────────────────────────────────────────────────────────

async def _finalize_result_stage(
    pool: asyncpg.Pool, query: "ChatQuery",
    full_answer: str, retrieval: dict, guidance: dict,
    gen_time: float, t0: float, cache_key: str,
) -> tuple[dict, list[str]]:
    """Parse explainability/suggested questions, save messages, build result dict,
    cache write, latency breakdown, source validation logging.
    Returns (result, title_packets)."""
    sources   = retrieval["sources"]
    citations = retrieval["citations"]
    metrics   = retrieval["metrics"]
    plan_time      = retrieval["plan_time"]
    retrieval_time = retrieval["retrieval_time"]
    pipeline_confidence = guidance["pipeline_confidence"]

    reasoning_summary = None
    confidence_level  = pipeline_confidence
    suggested_questions: list = []
    answer = full_answer

    if "[[Explainability:" in answer:
        try:
            parts = answer.split("[[Explainability:")
            main_text = parts[0].strip()
            exp_part  = parts[1].split("]]")[0].strip()
            exp_data  = json.loads(exp_part)
            reasoning_summary = exp_data.get("reasoning_summary")
            if confidence_level is None:
                confidence_level = exp_data.get("confidence_level")
            after_exp = parts[1].split("]]")[1] if len(parts[1].split("]]")) > 1 else ""
            answer = main_text
            if "[[SuggestedQuestions:" in after_exp:
                answer += f"\n\n[[SuggestedQuestions:{after_exp.split('[[SuggestedQuestions:')[1]}"
        except Exception as e:
            logger.warning(f"Failed to parse explainability in stream: {e}")

    if "[[SuggestedQuestions:" in answer:
        try:
            parts = answer.split("[[SuggestedQuestions:")
            answer = parts[0].strip()
            suggested_questions = json.loads(parts[1].split("]]")[0].strip())
        except Exception as e:
            logger.warning(f"Failed to parse suggested questions in stream: {e}")
            suggested_questions = []

    safe_answer, _ = content_filter(answer)
    total_time = time.time() - t0

    title_packets: list[str] = []
    if query.session_id:
        metadata = {
            "total_time": round(total_time, 3), "generation_time": round(gen_time, 3),
            "reasoning_summary": reasoning_summary, "confidence_level": confidence_level,
        }
        new_title = await save_message_to_db(pool, query.session_id, "user", query.question)
        if new_title:
            title_packets.append(f"data: {json.dumps({'type': 'title', 'content': new_title})}\n\n")
        asyncio.create_task(save_message_to_db(
            pool, query.session_id, "assistant", safe_answer, citations, metadata, suggested_questions))

        # Update session memory after successful response (ensure write completes)
        try:
            new_summary = SummaryBuilder.build(query.history + [type('Message', (), {'role': 'assistant', 'content': safe_answer})])
            if new_summary:
                await SessionMemoryStore.set(query.owner_id, query.session_id, new_summary)
        except Exception as e:
            logger.warning(f"Failed to update session memory after stream response: {e}")

    result = {
        "answer": safe_answer,
        "sources":    sources    if isinstance(sources, list) else [],
        "citations":  citations  if isinstance(citations, dict) else {},
        "suggested_questions": suggested_questions,
        "source_type": "generated",
        "reasoning_summary": reasoning_summary,
        "confidence_level":  confidence_level,
        "latency_breakdown": {
            "planning":   round(plan_time, 3),
            "sql":        round(metrics.get("sql", 0), 3),
            "embedding":  round(metrics.get("embed", 0), 3),
            "routing":    round(metrics.get("routing", 0), 3),
            "retrieval":  round(retrieval_time, 3),
            "rerank":     round(metrics.get("rerank", 0), 3),
            "generation": round(gen_time, 3),
            "total":      round(total_time, 3),
        },
    }

    await redis_set(cache_key, {"data": result, "timestamp": time.time()})
    await state.record_value(state.LIST_LATENCY, total_time)

    retrieved_ids = {s["document_id"] for s in sources
                     if s.get("document_id") and s["document_id"] != "unknown"}
    selected_ids  = set(query.document_ids or [])
    source_violation = bool(selected_ids and not retrieved_ids.issubset(selected_ids))
    if source_violation:
        logger.error(f"STRICT SOURCE VIOLATION [STREAM]: Retrieved {retrieved_ids} is not subset of Selected {selected_ids}")

    # Extract display names from actual citations for debugging visibility
    selected_source_names = [c.get("display_name") or c.get("id") for c in citations.values()]

    logger.info(json.dumps({
        "event": "query_processed", "mode": "stream",
        "selected_sources": selected_source_names, "retrieved_sources": list(retrieved_ids),
        "source_violation": source_violation,
        "question_hash": generate_cache_key(query.question)[:8],
        "total_s": round(total_time, 3),
        "embed_s": round(metrics.get("embed", 0), 3),
        "retrieval_s": round(retrieval_time, 3),
        "rerank_s": round(metrics.get("rerank", 0), 3),
        "generation_s": round(gen_time, 3),
    }))
    logger.info(json.dumps({"event": "stage_finalize_result_complete",
                             "total_time_ms": round(total_time * 1000, 1)}))
    return result, title_packets


# ── Stream Stage 7 ───────────────────────────────────────────────────────────

async def _finalize_observability_stage(
    pool: asyncpg.Pool, query: "ChatQuery",
    full_answer: str, result: dict, guidance: dict,
    gen_time: float, t0: float,
) -> list[str]:
    """Final meta packet, done packet, LLM introspection, audit log.
    Returns the two terminal SSE packets."""
    total_time = time.time() - t0
    pipeline_confidence = guidance["pipeline_confidence"]
    _system_action    = guidance["_system_action"]
    _llm_input_blocks = guidance["_llm_input_blocks"]
    intelligence_block = guidance["intelligence_block"]

    packets = [
        f"data: {json.dumps({'type': 'meta', 'reasoning_summary': result.get('reasoning_summary'), 'confidence_level': result.get('confidence_level'), 'suggested_questions': result.get('suggested_questions', []), 'latency': result['latency_breakdown']})}\n\n",
        f"data: {json.dumps({'type': 'done', 'total_time': round(total_time, 3), 'generation_time': round(gen_time, 3), 'answer_length': len(full_answer)})}\n\n",
    ]

    try:
        _llm_output = build_llm_output_structure(
            answer=full_answer, suggested_questions=result.get("suggested_questions", []),
            pipeline_confidence=pipeline_confidence,
            reasoning_summary=result.get("reasoning_summary"), system_action=_system_action,
        )
        _llm_behavior = analyze_llm_behavior(
            response=full_answer, pipeline_confidence=pipeline_confidence,
            system_action=_system_action, validation_flags=[],
            input_blocks=_llm_input_blocks,
        )
        _llm_trace = LLMTrace(
            req_id=obs._req_id(), input_blocks=_llm_input_blocks,
            constraints=LLMConstraints(
                forbidden_operations_applied=True, no_arithmetic_mode=True,
                cite_only_directive=True, intelligence_block_injected=bool(intelligence_block),
            ),
            output_structure=_llm_output, behavior=_llm_behavior,
            latency_ms=gen_time * 1000,
        )
        obs.emit_llm_trace(_llm_trace)
    except Exception as introspection_err:
        logger.warning(f"LLM Introspection failed in stream: {introspection_err}")

    asyncio.create_task(log_audit_event(
        pool=pool, event_type="chat", user_id=query.owner_id,
        resource_id=query.session_id, action="read", status="success",
        metadata={
            "mode": "stream", "latency_ms": int(total_time * 1000),
            "message_length": len(query.question), "response_length": len(full_answer),
            "source_count": len(result.get("sources", [])), "is_cache_hit": False,
        },
    ))
    logger.info(json.dumps({"event": "stage_finalize_obs_complete",
                             "total_time_ms": round(total_time * 1000, 1)}))
    return packets


# ── generate_stream_response: 7-stage orchestrator ───────────────────────────

async def generate_stream_response(
    pool: asyncpg.Pool, pinecone_index: Any,
    embed_model: SentenceTransformer, rerank_model: Any,
    query: ChatQuery,
) -> AsyncGenerator[str, None]:
    t0 = time.time()

    try:
        # Stage 1 — prepare / short-circuit
        logger.info(json.dumps({"event": "stage_prepare_start"}))
        stage1 = await _prepare_or_short_circuit_stream(pool, query, pinecone_index, t0)
        for pkt in stage1["packets"]:
            yield pkt
        if stage1["short_circuit"]:
            return

        cache_key           = stage1["cache_key"]
        standalone_question = stage1["standalone_question"]
        query_vector        = stage1["query_vector"]
        loop                = stage1["loop"]

        # Stage 2 — retrieval
        logger.info(json.dumps({"event": "stage_retrieval_start"}))
        retrieval = await _run_retrieval_stage(
            pool, pinecone_index, embed_model, rerank_model,
            query, standalone_question, query_vector, loop,
        )

        # Stage 3 — guidance
        logger.info(json.dumps({"event": "stage_guidance_start"}))
        guidance = await _build_guidance_stage(
            pool, query, standalone_question,
            retrieval["context_block"], retrieval["sources"],
        )

        # Stage 4 — prompt build
        logger.info(json.dumps({"event": "stage_prompt_start"}))
        stream_messages = await _build_prompt_stage(pool, query, standalone_question, guidance, retrieval)

        # Initial meta packet (client receives sources before LLM starts)
        yield (
            f"data: {json.dumps({'type': 'meta', 'sources': retrieval['sources'], 'citations': retrieval['citations'], 'source_type': 'generated', 'latency': {'embedding': round(retrieval['metrics'].get('embed', 0), 3), 'retrieval': round(retrieval['retrieval_time'], 3)}})}\n\n"
        )

        deadline   = time.time() + MAX_STREAM_DURATION
        result_bag: dict = {}

        try:
            await asyncio.wait_for(LLM_SEMAPHORE.acquire(), timeout=LLM_WAIT_TIMEOUT)
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'msg': 'Server busy — too many concurrent LLM requests. Try again in a few seconds.'})}\n\n"
            await state.decr_active_streams()
            return

        try:
            # Stage 5 — LLM streaming
            logger.info(json.dumps({"event": "stage_stream_llm_start"}))
            async for pkt in _stream_llm_stage(stream_messages, deadline, result_bag):
                yield pkt

            full_answer = result_bag.get("full_answer", "")
            gen_time    = result_bag.get("gen_time", 0.0)

            # Stage 6 — finalize result
            logger.info(json.dumps({"event": "stage_finalize_result_pre"}))
            result, title_packets = await _finalize_result_stage(
                pool, query, full_answer, retrieval, guidance, gen_time, t0, cache_key)
            logger.info(json.dumps({"event": "stage_finalize_result_post"}))
            for pkt in title_packets:
                yield pkt

            # Stage 7 — finalize observability
            logger.info(json.dumps({"event": "stage_finalize_obs_pre"}))
            for pkt in await _finalize_observability_stage(
                    pool, query, full_answer, result, guidance, gen_time, t0):
                yield pkt
            logger.info(json.dumps({"event": "stage_finalize_obs_post"}))

        except Exception as e:
            logger.exception(json.dumps({
                "event": "stream_crash",
                "exception": str(e),
            }))
        finally:
            LLM_SEMAPHORE.release()
            await state.decr_active_streams()

    except Exception as e:
        logger.exception(json.dumps({
            "event": "stream_crash_prepare_stage",
            "exception": str(e),
            "message": "Crash in prepare/retrieval/guidance stages",
        }))

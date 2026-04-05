# Router (`backend/rag/router.py`)

## Role
Sits between user input and data execution. Classifies intent, builds deterministic execution plans.

## Public Interface
```python
class QueryPlanner:
    @staticmethod
    async def plan(question: str) -> MultiQueryPlan
```
Returns `MultiQueryPlan(plans=[QueryPlan(source, query), ...])` — unchanged contract with `chat_service.py`.

## Execution Flow
```
user question
    → LLM (ROUTER_PROMPT) → intent JSON
    → per-plan: normalize → fx_direction → validate → build SQL
    → MultiQueryPlan returned to chat_service.py
```

## ROUTER_PROMPT Rules
- Input: Hebrew or English
- Output: structured JSON only — no SQL, no code, no markdown
- Parameters always normalized to English (ISO codes, FRED IDs)
- Mixed queries (structured + analysis) → both a sql plan AND a document_analysis plan

## Downstream Contract
`chat_service.py` receives `MultiQueryPlan` and:
- Executes `source="sql"` plans via `run_sql_query(pool, plan.query)`
- Executes `source="vector"` plans via Pinecone similarity search
- Fetches portfolio context separately via `fetch_portfolio_context(pool, owner_id)` — not via router plans

## What Router Does NOT Do
- Does not execute queries
- Does not generate dynamic SQL
- Does not inject `owner_id` into SQL (portfolio routes to vector for this reason)
- Does not modify `schemas.py` or `chat_service.py`

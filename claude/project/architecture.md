# Architecture

## System Diagram
```
Frontend (React/TypeScript/Vite)
    ↓ HTTP/SSE
NGINX (rate limiting, SSE streaming, load balancing)
    ↓
FastAPI nodes (horizontally scalable, stateless)
    ├── PostgreSQL 16   — financial time-series, user data, audit logs
    ├── Redis 7         — semantic caching, rate limiting, task queue
    └── Pinecone        — vector embeddings for document search

Background Worker (worker_entrypoint.py)
    — document indexing queue (popped from Redis)
    — scheduled financial data ingestion
```

## Backend Layers

### `backend/core/` — Infrastructure
- `connections.py` — ML model lifecycle (sentence-transformers loaded at startup)
- `cache.py` — Three-tier caching: exact-match, embedding similarity, semantic
- `llm_client.py` — OpenAI abstraction (all LLM calls go through here)
- `config.py` — All env vars; single source of truth
- `auth.py` — JWT + Google OAuth
- `security.py` — PII filtering, prompt injection detection (runs before every LLM call)
- `prompts.py` — All LLM prompts; `CHAT_SYSTEM_PROMPT` contains FORBIDDEN OPERATIONS block

### `backend/rag/` — Core Intelligence
- `router.py` — Multi-source planner: intent JSON → deterministic SQL + vector plans
- `sql_tool.py` — Read-only SQL; whitelist-enforced table access
- `vector_store.py` — Pinecone abstraction; all queries filtered by `owner_id`
- `reranker.py` — Cross-encoder re-ranking of retrieved chunks
- `services/chat_service.py` — Central orchestrator: parallel SQL + vector, intelligence layer, fuse context, call LLM

### `backend/intelligence/` — Investment Intelligence Layer
- `schemas.py` — Pydantic contracts for all agent I/O; `IntelligenceReport`, `NormalizedPortfolio`, `ValidationResult`
- `data_normalizer.py` — Pure normalization: `normalize_portfolio(rows) → NormalizedPortfolio`; computes `total_invested`, `allocation_pct`; no DB/LLM
- `orchestrator.py` — Pipeline controller; 5-stage execution; always returns a valid report (never raises)
- `context_builder.py` — Renders `IntelligenceReport` → structured LLM-injectable text block
- `agents/user_profiler.py` — Pure transform: raw profile dict → `UserInvestmentProfile`
- `agents/market_analyzer.py` — Reads `macro_indicators`, `fx_rates`; classifies market regime
- `agents/asset_profiler.py` — Reads `asset_prices`, `etf_holdings`; builds `AssetProfile` per ticker
- `agents/portfolio_fit.py` — Reads `portfolio_positions`; uses `normalize_portfolio()`; HHI by invested capital
- `agents/scoring_engine.py` — **Zero LLM calls**; composite = `0.30*market + 0.25*user + 0.20*diversify + 0.25*risk`
- `agents/recommendation.py` — Deterministic action (score thresholds); LLM writes reasoning text only
- `agents/validation.py` — Post-pipeline sanity checks; 5 rules; can downgrade `pipeline_confidence`

### `backend/financial/` — Data Ingestion
- `providers/` — FX (Bank of Israel), macro (FRED), ETF holdings (Yahoo), SEC filings, portfolio
- Scheduled ingestion runs in `worker_entrypoint.py`

### `backend/documents/` — Document Lifecycle
- Upload → Redis queue → worker → PyPDF extract → chunk (500 chars, 50 overlap) → embed → Pinecone upsert
- Every document tagged with `owner_id`

## Chat Request Flow
```
POST /chat  (also POST /chat/stream — identical pipeline, tokens streamed via nginx)
  → semantic cache lookup (Redis)
  → if miss: router.py decomposes query into plans
  → asyncio.gather(sql_tool, vector_store)
  → reranker.py scores retrieved chunks
  → chat_service.py fuses SQL + vector context

  → INVESTMENT INTELLIGENCE LAYER (step 5.5)
      Stage 0: UserProfilerAgent (instant, no DB)
      Stage 1 (parallel): MarketAnalyzerAgent + AssetProfilerAgent + PortfolioFitAgent
      Stage 2: ScoringEngineAgent (deterministic — no LLM)
      Stage 3: RecommendationAgent (deterministic action + LLM reasoning text)
      Stage 4: _compute_pipeline_confidence() (deterministic base confidence)
      Stage 5: ValidationAgent (may downgrade confidence — always last)
      → build_intelligence_context() → [NORMALIZED PORTFOLIO] + [VALIDATION] sections

  → build_user_message (intelligence block + cite-only context + portfolio)
  → security.py PII filter
  → OpenAI synthesis (LLM FORBIDDEN from computing or inventing figures)
  → confidence_level = pipeline_confidence (deterministic) or LLM fallback if None
  → cache result + return
```

## Key Design Decisions
- **Stateless API**: All state in Postgres/Redis. Scale with `--scale api=N`.
- **Multi-tenancy**: Every query (SQL + Pinecone + cache) scoped by `owner_id`. Never bypass.
- **Security layer**: `security.py` runs before every LLM call. No direct OpenAI calls allowed.
- **SQL safety**: `sql_tool.py` is read-only with a table whitelist. Never add write operations.

## Logging & Debugging
Every request gets a unique `X-Request-ID`. Logs are structured JSON.
```bash
docker logs ml_foundations-api-1 | grep "req_id=<id>"
docker logs ml_foundations-api-1 | grep "router_decision"
```

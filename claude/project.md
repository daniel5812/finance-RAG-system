# Project

System: Hybrid Financial RAG Platform — SQL retrieval (structured data) + vector retrieval (documents, filings, knowledge) + external data ingestion + deterministic intelligence layer + user profiling + layered caching. Multi-tenant.

## Stack
- Frontend: React + TypeScript + Vite
- Backend: FastAPI (stateless)
- Database: PostgreSQL 16 (SQL-first retrieval)
- Cache/Queue: Redis 7
- Vector Store: Pinecone (document embedding + active retrieval for filings, reports, knowledge base)
- LLM: OpenAI (synthesis layer via llm_client.py)
- Auth: Google OAuth2 + JWT
- Proxy: NGINX

## Run (Docker)
```
cd backend && docker-compose up -d --build
cd frontend && npm install && npm run dev
GET http://localhost:8000/health
```

## Run (no Docker)
```
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
# separate terminal: python worker_entrypoint.py
```

## Env Variables
Backend: OPENAI_API_KEY, PINECONE_API_KEY, FRED_API_KEY, GOOGLE_CLIENT_ID, JWT_SECRET_KEY, DATABASE_URL, REDIS_HOST, DOCUMENT_UPLOAD_DIR
Frontend: VITE_GOOGLE_CLIENT_ID

## Backend Layers
- core/: connections, cache, llm_client, config, auth, security, prompts
- rag/: router (planner, source selector), sql_tool, vector_store, context_fusion, chat_service
- intelligence/: orchestrator, agents (7), data_normalizer, schemas, context_builder
- financial/: providers (fx, macro, etf, filings, portfolio)
- documents/: upload, extract, chunk, embed, upsert

## Database

| Table | Purpose | Key Columns |
|---|---|---|
| users | Accounts, profiles | user_id, email, risk_tolerance, experience_level |
| prices | OHLCV stock/ETF | symbol, date, close |
| fx_rates | FX rates | base_currency, quote_currency, rate, date |
| macro_series | FRED indicators | series_id, value, date |
| filings | SEC filings | ticker, form_type, filed_at |
| etf_holdings | ETF composition | etf_symbol, holding_symbol, weight |
| portfolio_positions | User portfolio | user_id, symbol, quantity, avg_cost |
| documents | Uploaded docs | owner_id, filename, status |
| document_chunks | Chunked text | document_id, chunk_text, embedding_id |
| audit_logs | Admin trail | user_id, action, created_at |

## SQL Whitelist (sql_tool.py, read-only)
prices, fx_rates, macro_series, filings, etf_holdings, portfolio_positions

## Providers
- fx.py: Bank of Israel API
- macro.py: FRED (CPI, GDP, FEDFUNDS, UNRATE)
- etf.py: Yahoo Finance
- filings.py: SEC EDGAR
- portfolio.py: portfolio data aggregation

## Architecture

**Retrieval Layer (Hybrid SQL + Vector) — MVP CORE IMPLEMENTED**
- Planner: IMPLEMENTED (backend/rag/planner.py); determines SQL/VECTOR/HYBRID per intent; tested
- Executor: IMPLEMENTED (backend/rag/executor.py); runs steps with error resilience; tested
- Fusion: IMPLEMENTED (backend/rag/fusion.py); merges results into structured_data + supporting_context; tested
- Retrieval pipeline: plan → execute → fuse flow verified via integration tests
- Metadata-aware vector retrieval: owner_id always required; doc_type + ticker filters applied when detectable
- Hybrid orchestration: SQL and vector run in parallel when both needed — not a fallback chain
- SQL path: structured DB queries (prices, fx, macro, filings, portfolio, etf)
- Vector path: Pinecone semantic search (uploaded docs, filings, knowledge base)
- Hybrid path: both executed in parallel → Fusion layer merges results
- Chat service integration: COMPLETE (backend/rag/services/chat_service.py now uses hybrid pipeline for both sync and streaming responses)
- Observability: enhanced with stage-level logging, selected_sources, retrieved_sources

**Ingestion**
- External providers (FRED, SEC EDGAR, Yahoo Finance, Bank of Israel) → DB + vector store
- Document upload pipeline → chunked + embedded → Pinecone

**Intelligence Layer**
- 7-agent deterministic pipeline (UserProfiler → scoring → ValidationAgent)
- User profile used as advisory context only; never overrides retrieved data

**Caching (layered)**
- Exact cache (Redis): identical query string
- Semantic cache (Redis): embedding similarity
- Retrieval cache: materialized SQL result sets
- Data/provider cache: external API responses with TTL

**LLM Role**
- Synthesis and reasoning only; no raw data computation, no param generation, no confidence override

## Roadmap

**Phase 1 — Deterministic Core (COMPLETE)**
- SQL-first retrieval, deterministic intelligence layer (7 agents), multi-tenant isolation, semantic caching, LLM synthesis only

**Phase 2 — Hybrid Retrieval & Source Orchestration (IMPLEMENTED)**
- Planner: IMPLEMENTED (IntentParser → ParamExtractor → SourceSelector → ProfileAnnotator → PlanBuilder); tested
- Executor: IMPLEMENTED with error resilience and SQL validation; tested
- Fusion: IMPLEMENTED with plan-aware summary logic; tested
- Retrieval pipeline: plan → execute → fuse integrated; integration tests added
- Metadata-aware vector retrieval (owner_id, doc_type, ticker); hybrid orchestration rules

**Phase 3 — Conversation Memory & Context Awareness**
- Rolling conversation summary (per session)
- Inject history summary into prompt construction
- Enable multi-turn reasoning
- Foundation for context-aware follow-up questions
- Priority: establish conversation context before expanding data sources

**Phase 4 — External Data Expansion**
- Expand macro series coverage
- Improve filings ingestion and retrieval usage
- Add additional financial data sources
- Improve data freshness and coverage breadth

**Phase 5 — User Profiling & Personalization**
- User profile store (risk tolerance, experience, preferences)
- Profile injected as advisory context into intelligence layer
- Profile never overrides retrieved data or deterministic scores

**Phase 6 — Layered Caching & Evaluation**
- Exact, semantic, embedding, retrieval, and data/provider cache layers
- owner_id in all cache keys; TTL discipline per layer
- Evaluation suite: unit (agents, normalizer), integration (full hybrid pipeline), E2E (Playwright)

**Phase 7 — DevOps & Production Readiness**
- CI/CD: lint (black, ruff), test (pytest, playwright), build, deploy (staging/prod)
- Docker hardening (non-root, minimal base images)
- Secrets management (vault rotation)
- Monitoring: Prometheus metrics + structured JSON logging
- Security: rate limiting, RBAC enforcement, audit logging
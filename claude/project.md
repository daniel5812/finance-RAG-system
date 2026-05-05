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
- macro.py: FRED (CPI, GDP, FEDFUNDS, UNRATE, VIXCLS, T10Y2Y); store() signature fixed to accept pool (2026-04-23); depends on FRED_API_KEY configuration
- etf.py: Yahoo Finance
- filings.py: SEC EDGAR
- portfolio.py: portfolio data aggregation; returns empty if user has no holdings
- price.py: YFinancePriceProvider supports startup seed (SPY, QQQ) + manual/admin backfill via POST /financial/ingest/prices/backfill endpoint; default backfill universe: SPY, QQQ, VOO, AAPL, MSFT, NVDA, TSLA, AMZN, GOOGL, META; configurable via PRICE_BACKFILL_SYMBOLS + PRICE_BACKFILL_DEFAULT_DAYS; chat path does NOT call providers

## Step 3 — Benchmark Comparison (COMPLETE)

**Feature**: Portfolio vs SPY/QQQ benchmark analysis
- Relative concentration: portfolio HHI vs benchmark HHI
- Coverage validation: HHI computed ONLY when benchmark holdings weight ≥80%
- Overweight/underweight detection (delta ≥2.0pp threshold)
- Sector mapping (SPY static, QQQ from holdings)
- Portfolio overlap calculation
- Weight basis detection (market_value, cost_basis, mixed)

**Core Invariant**:
- HHI suppression rule: coverage < 80% → HHI = None + data_note explaining why
- Test guard assertions enforce weight sums ≥80% to prevent regressions

**Implementation** (COMPLETE):
- BenchmarkComparisonAgent: deterministic agent (no LLM)
- BenchmarkSnapshot / BenchmarkComparison schemas
- fetch_benchmark_holdings(): SQL query to etf_holdings table
- Context builder: [BENCHMARK COMPARISON] section with HHI comparison labels
- Orchestrator integration: runs after MarketAnalyzer
- Tests: 20 passing, 2 fixed (test data coverage alignment)

## Step 4 — Macro Signals (COMPLETE)

**Feature**: Market regime indicators from FRED data
- **VIX signal**: VIXCLS volatility regime (recent value + trend direction)
- **Yield curve signal**: T10Y2Y term premium regime (recent value + trend direction)
- **Inflation trend**: CPIAUCNS latest 3-row trend (up/down/stable)
- **Fed rate trend**: FEDFUNDS latest 3-row trend (up/down/stable)

**Computation**:
- All signals computed deterministically in MarketAnalyzerAgent (no LLM)
- Signals extracted from macro_series SQL table (FRED-sourced data)
- No schema changes; no orchestrator restructuring
- Context builder: [MARKET CONTEXT] section includes macro signals when available

**Missing-Data Behavior**:
- Missing series rows → signal omitted (no fallback estimation)
- Insufficient trend rows (< 3) → trend omitted
- No fake data; each signal failure is isolated
- LLM receives only precomputed macro context (no generation role)

**Data Seeding**:
- Added VIXCLS and T10Y2Y to macro series seed (backend/financial/providers/macro.py)
- Existing CPIAUCNS + FEDFUNDS series already in seed

**Implementation** (COMPLETE):
- MarketAnalyzerAgent: reads macro_series, computes signals deterministically
- Signal schemas: VIXSignal, YieldCurveSignal (value + trend_label)
- Context builder: renders existing MarketContext fields (macro_signals)
- Tests: 25 passing (backend/tests/test_macro_signals.py)
- Regression suite: 47 tests passing (including benchmark comparison)

---

## Phase 4D — Price Backfill Foundation (COMPLETE)

**Feature**: Admin/manual ingestion of historical price data via YFinancePriceProvider

**Endpoint**: POST /financial/ingest/prices/backfill
- Optional body: `{ "symbols": ["AAPL", "MSFT"], "days": 365 }`
- Defaults: all 10 symbols in PRICE_BACKFILL_SYMBOLS (or default set); PRICE_BACKFILL_DEFAULT_DAYS

**Configuration**:
- PRICE_BACKFILL_SYMBOLS: comma-separated list (default: SPY,QQQ,VOO,AAPL,MSFT,NVDA,TSLA,AMZN,GOOGL,META)
- PRICE_BACKFILL_DEFAULT_DAYS: lookback window (default: 252 trading days)

**Architecture**:
- Backfill is external data ingestion only; no chat path involvement
- YFinancePriceProvider called from /financial/ingest/prices/backfill only
- Per-symbol failure isolation; one symbol error does not block others
- Startup seed (SPY, QQQ) unchanged; backfill supplements
- Chat queries local prices table (no provider calls)

**Validation**:
- 13 tests (test_price_backfill.py): all passed
- Manual backfill: all 10 default symbols succeeded
- DB coverage: AAPL, AMZN, GOOGL, META, MSFT, NVDA, QQQ, SPY, TSLA, VOO present post-backfill

**Remaining Debt**:
- No scheduled/cron refresh (manual/admin trigger only; can extend to worker task)
- Auth hardening pending (currently internal/admin route; should add explicit RBAC check)
- Limited to configured universe (broad market coverage still pending)

---

## Phase 4E — Advisory Wording Guard (COMPLETE)

**Feature**: Soft prompt guard to discourage personal investment command wording

**Implementation**:
- ADVISORY_WORDING_GUARD added to PromptAssembler
- NATURAL_ADVISORY_PROMPT includes explicit wording guidance
- CHAT_BEHAVIOR_RULES carves out ticker/security stock-pick questions
- RecommendationAgent reasoning reframed: "scoring-signal analysis" vs "why this action"

**Allowed Behavior**:
- Analytical direction: "The model classifies NVDA as HOLD..."
- Classification explanation: discussing why a score/model produces an output
- Uncertainty qualifiers: "Based on available data..." / "Current signals suggest..."

**Discouraged Behavior**:
- Personal command: "I recommend buying NVDA"
- Directive: "You should hold this stock"
- Bare action: "Reduce your TSLA position" (as imperative)
- Internal classifications should not become personal advice

**Implementation Details**:
- BUY/HOLD/REDUCE/AVOID remain internal deterministic classifications (Stage 2/3)
- LLM synthesis references classifications analytically, not prescriptively
- Soft prompt guard at synthesis time; no hard output filter post-generation

**Tests Passing**:
- 12 advisory wording guard tests
- Recommendation agent reasoning tests
- Final regression: 204 passed, 1 skipped

**Remaining Limitations**:
- Soft guard only; LLM can exceed instructions if prompted incorrectly
- No token-level constraint; relies on prompt clarity
- Manual review still needed for edge-case advisory responses

---

## Architecture

**Retrieval Layer (Hybrid SQL + Vector) — FULLY IMPLEMENTED & TESTED**
- Planner: IMPLEMENTED + tested (backend/rag/planner.py); determines SQL/VECTOR/HYBRID per intent
- Executor: IMPLEMENTED + tested (backend/rag/executor.py); async execution, error resilience, owner_id enforcement
- Fusion: IMPLEMENTED + tested (backend/rag/fusion.py); merges results into structured_data + supporting_context
- Session memory: IMPLEMENTED + tested (conversation history per session, advisory context injection)
- Retrieval pipeline: plan → execute → fuse flow verified via integration tests (46 tests passing)
- Metadata-aware vector retrieval: owner_id always required; doc_type + ticker filters applied when detectable
- Hybrid orchestration: SQL and vector run in parallel when both needed — not a fallback chain
- SQL path: structured DB queries (prices, fx, macro, filings, portfolio, etf)
  - **portfolio_lookup**: queries portfolio_positions per user; empty result returns valid "no data" state
  - **etf_holdings**: pure SQL factual queries (no intelligence layer, direct response style)
- Vector path: Pinecone semantic search (uploaded docs, filings, knowledge base)
- Hybrid path: both executed in parallel → Fusion layer merges results
- Chat service integration: COMPLETE (backend/rag/services/chat_service.py now uses hybrid pipeline for both sync and streaming responses)
- Observability: enhanced with stage-level logging, selected_sources, retrieved_sources
- **Factual vs Advisory split**: pure SQL queries (etf_holdings, portfolio_lookup) skip intelligence layer; hybrid/vector queries run full 7-agent pipeline
- **Source coverage note**: Ingestion path fixes applied; runtime SQL validation for SPY/QQQ still pending

**Ingestion**
- External providers (FRED, SEC EDGAR, Yahoo Finance, Bank of Israel) → DB + vector store
- Document upload pipeline → chunked + embedded → Pinecone

**Intelligence Layer**
- 7-agent deterministic pipeline (UserProfiler → scoring → ValidationAgent)
- User profile used as advisory context only; never overrides retrieved data

**System Behavior Modes**
- **Factual mode** (etf_holdings, portfolio_lookup, price_lookup, fx_rate, data_availability_lookup): SQL-only paths; intelligence layer skipped; profile not injected; direct answer style; no vector fallback
- **Advisory mode** (hybrid, vector, multi-intent queries): full 7-agent pipeline runs; profile injected as context; reasoning-based synthesis

**PromptAssembly V2**
- Citation wiring: [S#] for SQL results; [D#] for document/vector results
- mode_hint parameter: factual | advisory (controls intelligence layer invocation)
- V2 integrated into both sync and streaming chat paths
- Legacy path preserved behind feature flag

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

**Phase 2 — Hybrid Retrieval & Source Orchestration (FULLY IMPLEMENTED & TESTED)**
- Planner: IMPLEMENTED + tested (IntentParser → ParamExtractor → SourceSelector → ProfileAnnotator → PlanBuilder)
- Executor: IMPLEMENTED + tested with async execution, error resilience, SQL validation, owner_id enforcement
- Fusion: IMPLEMENTED + tested with plan-aware summary logic and missing_data tracking
- Session memory: IMPLEMENTED + tested (per-session conversation history, advisory context injection)
- Retrieval pipeline: plan → execute → fuse integrated; integration tests verified; 46 tests passing
- Metadata-aware vector retrieval (owner_id, doc_type, ticker); hybrid orchestration rules enforced

**Phase 3 — Conversation Memory & Context Awareness**
- Rolling conversation summary (per session)
- Inject history summary into prompt construction
- Enable multi-turn reasoning
- Foundation for context-aware follow-up questions
- Priority: establish conversation context before expanding data sources

**Phase 4 — External Data Expansion (COMPLETE)**
- ✅ Expanded macro series coverage: VIX, yield curve, inflation trend, fed rate trend
- ✅ PromptAssembly V2: [S#]/[D#] citation wiring; mode_hint factual/advisory
- ✅ QueryUnderstanding V2: free-form routing; Hebrew ETF holdings; data_availability_lookup
- ✅ Portfolio derived metrics: concentration_score, diversification_score, sector_exposure_pct
- ✅ Price backfill foundation: POST /financial/ingest/prices/backfill; 10-symbol default universe
- ✅ Advisory wording guard: soft prompt guard; analytical direction vs personal command
- Next: scheduled price refresh, admin route auth hardening, filings retrieval improvement

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
- Security: rate limiting, RBAC enforcement, audit logging                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           
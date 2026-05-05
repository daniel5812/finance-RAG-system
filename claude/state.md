# State

## Feature Completion Status

| Step | Feature | Status | Notes |
|---|---|---|---|
| 1 | Portfolio Enrichment | COMPLETE | Sector, asset_score, risk_classification |
| 2 | Portfolio Holdings Analysis | COMPLETE | HHI, concentration labels, sector weights |
| 3 | Benchmark Comparison | COMPLETE | SPY/QQQ coverage gate, HHI suppression @ <80%, test data aligned |
| 4 | Macro Signals | COMPLETE | VIX, yield curve, inflation trend, fed rate trend; deterministic extraction |
| 4A | **PromptAssembly V2** | **COMPLETE** | **mode_hint factual/advisory; [S#]/[D#] citations; V2 wired into sync/streaming** |
| 4B | **QueryUnderstanding & Routing** | **COMPLETE** | **free-form free-form; Hebrew ETF holdings; data_availability_lookup; 7-intent router** |
| 4C | **Portfolio Derived Metrics** | **COMPLETE** | **concentration_score, diversification_score, sector_exposure_pct** |
| 4D | **Price Backfill Foundation** | **COMPLETE** | **POST /financial/ingest/prices/backfill; 10-symbol default universe; config-driven** |
| 4E | **Advisory Wording Guard** | **COMPLETE** | **analytical direction allowed; personal command wording discouraged; soft prompt guard** |

---

## Step 3 — Benchmark Comparison (Completed 2026-04-28)

**What Was Fixed**:
1. Test data inconsistency: benchmark holdings weights summed to ~70%, not ≥80%
2. HHI suppression was working correctly; tests violated coverage assumption
3. Added explicit weight sum assertions to prevent future regressions
4. Fixed SPY/QQQ holding lists to reach exactly 80%+ coverage

**Implementation Validated**:
- BenchmarkComparisonAgent: deterministic, no LLM
- Coverage gate: HHI = None when coverage < 80% (strict, no fallback)
- Test suite: 22 tests (20 passing + 2 fixed)
- Guard assertions: `assert sum(h["weight"] for h in holdings) >= 80.0`

**System Behavior Confirmed**:
- Portfolio overlap correctly calculated (ticker presence)
- Sector mapping: SPY static, QQQ from holdings + _SECTOR_MAP
- Weight basis detection: market_value | cost_basis | mixed
- Overweight/underweight: delta ≥2.0pp threshold

---

## Step 4 — Macro Signals (Completed 2026-04-29)

**What Was Implemented**:
1. VIX signal (VIXCLS): volatility regime + trend direction
2. Yield curve signal (T10Y2Y): term premium regime + trend direction
3. Inflation trend (CPIAUCNS): 3-row CPI trend (up/down/stable)
4. Fed rate trend (FEDFUNDS): 3-row funds rate trend (up/down/stable)

**Computation & Architecture**:
- All signals computed deterministically in MarketAnalyzerAgent (Stage 1, no LLM)
- Pure function: macro_series SQL table → signal extraction
- No schema changes; no orchestrator restructuring
- Context builder: [MARKET CONTEXT] section includes macro_signals when available

**Missing-Data Behavior**:
- Missing series → signal omitted (no fallback estimation)
- Insufficient rows (< 3 for trend) → trend omitted; latest value included
- Each signal failure is isolated; no fake data
- LLM receives only precomputed macro context (no generation role)

**Data Integration**:
- Added VIXCLS and T10Y2Y to macro seed (backend/financial/providers/macro.py)
- Existing CPIAUCNS + FEDFUNDS already in seed
- No changes to macro_series table schema

**Test Suite**:
- 25 macro signal tests (backend/tests/test_macro_signals.py): complete data, partial rows, missing series, trend edge cases
- 47 regression tests passing (macro + benchmark comparison integration)
- Guard assertions: trend calculations validated; missing-data paths exercised

**System Behavior Confirmed**:
- Signal extraction deterministic and reproducible
- Missing-data handling correct (graceful degradation)
- Trend detection accurate (3-row comparison logic)
- No LLM inference of trends

---

## Phase 4A — PromptAssembly V2 (Completed 2026-05-05)

**What Was Implemented**:
- PromptAssembler refactored with V2 citation handling
- mode_hint parameter: factual | advisory
- SQL citations use [S#] format; document/vector citations use [D#]
- V2 wired into both sync and streaming chat paths
- Legacy PromptAssembler path preserved behind feature flag

**Implementation**:
- backend/intelligence/prompt_assembly.py: PromptAssembler V2 class
- Citation assignment: PromptAssembler owns all [S#]/[D#] mapping
- Factual mode: SQL context only; skips intelligence layer
- Mode hint injectable at synthesis time

**Tests Passing**:
- test_prompt_assembly.py: 18 tests
- Streaming + sync paths: regression coverage

---

## Phase 4B — QueryUnderstanding & Routing Enhancements (Completed 2026-05-05)

**What Was Implemented**:
1. **Deterministic Query Understanding**: free-form Hebrew/English routing without LLM
2. **Intent Types**: fx_rate, price_lookup, etf_holdings, macro_series, document_lookup, data_availability_lookup, advisory, no_match
3. **Hebrew ETF Holdings**: phrases like "מה יש בתוך SPY?" and "מהם המרכיבים של קרן SPY?" → etf_holdings SQL
4. **Data Availability Lookup**: "של איזה מניות כן יש לך?" → SQL query on prices table; returns available symbols
5. **Alias & Company Mapping**: Apple/AAPL, Tesla/TSLA, NVDA; S&P/SPY, Nasdaq/QQQ

**Implementation**:
- backend/rag/planner.py: IntentParser handles Hebrew aliases
- Intent table: 8 intent types with SQL/VECTOR/HYBRID routing
- ParamExtractor: Hebrew → English conversion
- SourceSelector: deterministic per-intent source assignment

**Tests Passing**:
- test_query_understanding.py: 35 tests
- test_planner.py: broader planner suite (218 passed, 1 skipped)

---

## Phase 4C — Portfolio Derived Metrics (Completed 2026-05-05)

**What Was Implemented**:
- NormalizedPortfolio now includes:
  - concentration_score (0–1; 0 = diversified, 1 = concentrated)
  - diversification_score (inverse of concentration)
  - sector_exposure_pct (dict of sector → percentage)
- data_normalizer computes deterministically

**Implementation**:
- backend/intelligence/data_normalizer.py: derives metrics from allocation_pct
- No schema changes; metrics computed at normalization time
- Intelligence pipeline preserves BenchmarkComparison and document_insights fields

**Tests Passing**:
- test_data_normalizer.py: portfolio + benchmark + derived metrics (25 passed, 2 skipped)

---

## Phase 4D — Price Backfill Foundation (Completed 2026-05-05)

**What Was Implemented**:
- POST /financial/ingest/prices/backfill endpoint
- Manual/admin ingestion of price data via YFinancePriceProvider
- Default universe: SPY, QQQ, VOO, AAPL, MSFT, NVDA, TSLA, AMZN, GOOGL, META
- Configurable via env vars: PRICE_BACKFILL_SYMBOLS, PRICE_BACKFILL_DEFAULT_DAYS

**Architecture**:
- Backfill route: external data ingestion only (no chat path)
- YFinancePriceProvider called from admin/backfill endpoint only
- Chat path: queries local prices table; no provider calls
- Failure isolation: per-symbol failures do not cascade
- Startup seed: unchanged (SPY, QQQ small seed continues)

**Validation**:
- 13 tests (test_price_backfill.py) passing
- Manual backfill succeeded for all 10 default symbols
- DB coverage after backfill: AAPL, AMZN, GOOGL, META, MSFT, NVDA, QQQ, SPY, TSLA, VOO

**Remaining Limitations**:
- Not broad market coverage (only default 10 symbols; additional symbols via PRICE_BACKFILL_SYMBOLS config)
- Backfill route lacks explicit RBAC layer (auth hardening pending)
- No scheduled/cron refresh (manual + admin only)

---

## Phase 4E — Advisory Wording Guard (Completed 2026-05-05)

**What Was Implemented**:
- ADVISORY_WORDING_GUARD added to PromptAssembler
- NATURAL_ADVISORY_PROMPT includes wording guard instructions
- CHAT_BEHAVIOR_RULES carves out ticker/security stock-pick questions from bare BUY/HOLD/REDUCE/AVOID
- RecommendationAgent reasoning reframed from "why this action" to "scoring-signal analysis"

**System Behavior**:
- **Allowed**: analytical direction, classification of scoring model output, uncertainty qualifiers
- **Discouraged**: personal investment commands (e.g., "I recommend NVDA", "You should buy X", "Hold X" as imperative)
- BUY/HOLD/REDUCE/AVOID remain internal deterministic classifications
- No hard output filter; soft prompt-level guard at synthesis time

**Tests Passing**:
- test_advisory_wording_guard.py: 12 tests
- test_recommendation.py: broader recommendation suite
- Final regression: 204 passed, 1 skipped

**Remaining Limitations**:
- Soft prompt guard, not hard post-generation filter (LLM can still exceed guard)
- No explicit token-level constraint; relies on prompt clarity
- Manual advisory responses still possible if LLM ignores instructions

---

## What Is Working
- Auth (OAuth2 + JWT), multi-tenant isolation (owner_id scoping)
- Document upload → Pinecone indexing
- Portfolio CRUD + CSV/PDF import
- Semantic caching (Redis)
- SSE streaming (nginx)
- Admin RBAC dashboard + latency metrics
- Multi-source planner (intent JSON → hardcoded SQL)
- Hebrew language support
- Intelligence Layer (7-agent, deterministic scoring + BenchmarkComparisonAgent)
- Data normalization (cost_basis, allocation_pct)
- ValidationAgent (5 checks, confidence downgrade)
- Benchmark Comparison (portfolio vs SPY/QQQ, HHI coverage gate, sector mapping)
- Hybrid retrieval fully integrated into chat_service (sync + streaming paths)
- SQL + VECTOR + HYBRID responses working end-to-end
- Source citations ([S1], [D1], etc.) correctly displayed in UI
- Observability: selected_sources and retrieved_sources now reflect actual cited sources
- Stream pipeline refactored into staged helpers (prepare → retrieval → guidance → prompt → stream → finalize)
- **PromptAssembler V2**: [S#]/[D#] citation wiring; mode_hint factual/advisory support
- **QueryUnderstanding V2**: free-form intent routing (fx_rate, price_lookup, etf_holdings, macro_series, document_lookup, data_availability_lookup, advisory, no_match); Hebrew/English aliases
- **Data Availability Lookup**: SQL query to prices table returns available symbols deterministically
- **Hebrew ETF Holdings Routing**: phrases like "מה יש בתוך SPY?" route to SQL holdings
- **Portfolio Derived Metrics**: concentration_score, diversification_score, sector_exposure_pct in NormalizedPortfolio
- **Price Backfill Endpoint**: POST /financial/ingest/prices/backfill; 10-symbol default; manual/admin ingestion
- **Advisory Wording Guard**: soft prompt guard in PromptAssembler; analytical direction allowed, personal command wording discouraged

## Known Issues
- Portfolio SQL cannot safely inject owner_id in router → routes to vector (chat_service.py independently calls fetch_portfolio_context)
- Only selected Hebrew/company aliases are supported; long-tail ticker aliases remain limited
- FRED: only 4 series (CPIAUCNS, FEDFUNDS, GDP, UNRATE)
- _FILLER_RE doesn't strip Hebrew (acceptable — preserves financial terms)
- Returns/P&L never computed (cost_basis insufficient) — LLM FORBIDDEN from estimating
- dominant_sector always None (no DB data) — use dominant_ticker instead
- ValidationAgent skipped when no asset scores (correct — no scores to validate)
- Follow-up question suggestions are best-effort (parsed from LLM metadata) and will improve after conversation memory is strengthened
- No conversation memory: system is stateless per request (no history summary or multi-turn context)
- Follow-up questions are not context-aware (depend on single response only)
- Core price coverage expanded to default 10 symbols after backfill; still not broad market coverage
- Advisory wording guard is prompt-level, not hard output filter
- Backfill route auth hardening pending (currently internal/admin without explicit RBAC layer)

## Completed — Deterministic Foundation (not final architecture)
- SQL retrieval pipeline: intent JSON → hardcoded SQL, deterministic path
- Intelligence Layer: 7 agents, deterministic scoring, ValidationAgent (can only downgrade)
- Data normalization: cost_basis, allocation_pct, deduplication (newest-row-wins)
- Multi-tenant isolation: owner_id filtering on all queries/cache
- Hebrew language support: keyword detection + alias normalization
- Production hardening (2026-04-05): fixed 7 bugs (numerical errors, LLM override, fake confidence)

## Retrieval MVP — FULLY IMPLEMENTED & TESTED
- Planner: IMPLEMENTED + tested (IntentParser → ParamExtractor → SourceSelector → ProfileAnnotator → PlanBuilder → QueryPlan)
- Executor: IMPLEMENTED + tested (async execution, error resilience, SQL template validation, owner_id enforcement)
- Fusion: IMPLEMENTED + tested (plan-aware summary, SQL/VECTOR separation, missing_data tracking)
- Session memory: IMPLEMENTED + tested (conversation history per session; advisory context injection; no data override)
- Retrieval pipeline: plan → execute → fuse integrated; integration tests added (backend/tests/test_retrieval_pipeline.py); 46 tests passing
- Metadata-aware vector: owner_id always required; doc_type + ticker filters when detectable; hybrid = parallel not fallback
- Chat service integration: COMPLETE (hybrid retrieval fully integrated into chat_service; streaming + sync paths use Planner → Executor → Fusion)
- Observability: COMPLETE (retrieved_sources, selected_sources, stage-level logs, crash isolation)

## Ingestion & Data Coverage

**Fixes Implemented (2026-04-23)**
- backend/financial/providers/price.py: store() signature corrected to accept pool parameter
- backend/financial/providers/macro.py: store() signature corrected to accept pool parameter
- backend/main.py: holdings seed expanded from ["SPY"] to ["SPY", "QQQ"]
- Tests added: price ingestion validation, holdings provider tests
- ETF factual routing (etf_holdings → SQL, no intelligence layer) — COMPLETE
- Portfolio SQL grounding (portfolio_lookup SQL path) — COMPLETE
- Empty-result handling (explicit injection of empty state into context) — COMPLETE

**Pending Validation**
- SQL source coverage for SPY/QQQ at runtime (ingestion path fixed; runtime table population still requires validation)
- Comparative multi-symbol retrieval depends on actual row presence in prices/holdings tables
- No fallback claims made until SQL queries return actual data rows for seeded symbols

## Current Known Limitations

- **Empty portfolio**: system correctly returns "no data" state when portfolio_positions table is empty; user must add holdings via CSV/PDF import
- **Macro data availability**: depends on FRED_API_KEY configuration; if unconfigured, macro_series queries return empty (no fallback to estimation)
- **Portfolio comparison**: P&L and returns never computed (cost_basis insufficient for LLM estimation; forbidden by design)

## Next Phases (see project.md for full roadmap)

**Phase 2 — Hybrid Retrieval & Source Orchestration (COMPLETE)**
- Planner, Executor, Fusion: core MVP implemented + tested

**Phase 3 — Conversation Memory & Context Awareness (CORE IMPLEMENTED)**
- Rolling conversation summary (per session) — DONE
- Inject history summary into prompt construction — DONE
- Multi-turn reasoning foundation established
- Next: response style simplification (remove rigid advisory structure for factual queries) → improve perceived intelligence layer quality → validate SQL source coverage (SPY/QQQ)

**Phase 4 — External Data Expansion (COMPLETE)**
- ✅ 4A: PromptAssembly V2 with [S#]/[D#] citations
- ✅ 4B: QueryUnderstanding V2 with Hebrew ETF routing + data_availability_lookup
- ✅ 4C: Portfolio derived metrics (concentration_score, diversification_score, sector_exposure)
- ✅ 4D: Price backfill foundation (10-symbol default; admin/manual ingestion)
- ✅ 4E: Advisory wording guard (soft prompt guard; analytical direction allowed)

**Phase 4.1 — Scheduled/Cron Price Refresh (PENDING)**
- Extend backfill into recurring task
- Implement scheduled job for daily/weekly price updates
- Monitor ingestion success/failure

**Phase 4.2 — Admin Route Security Hardening (PENDING)**
- Add explicit RBAC layer to /financial/ingest/prices/backfill
- Validate admin_id + role before accepting backfill requests
- Audit logging for all ingestion operations

**Phase 4.3 — Context Builder Recommendation Review (OPTIONAL)**
- If advisory wording guard insufficient, review context_builder recommendation rendering
- Consider additional output filtering or style constraints

**Step 5 — Financial Document Ingestion**
- PDF & statements reasoning (SEC filings, prospectuses, financial statements)
- Vector retrieval for document-based queries
- Cross-reference document data with SQL portfolio/market data

**Phase 5 — User Profiling & Personalization**
- Profile store; advisory context injection; no data override

**Phase 6 — Layered Caching & Evaluation**
- Full cache layer stack; evaluation suite (unit + integration + E2E)

**Phase 7 — DevOps & Production Readiness**
- CI/CD, Docker hardening, secrets management, monitoring, RBAC enforcement
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        
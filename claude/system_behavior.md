# System Behavior

## Request Flow
1. Layered cache lookup (exact → semantic, Redis)
2. If miss: router.py decomposes query → intent JSON + source selection (SQL / vector / hybrid)
3. Validate params: normalize → FX direction → validate → build query plan per source
4. Execute selected source(s): SQL retrieval and/or vector retrieval (parallel when hybrid)
5. context_fusion layer: merge SQL results + vector chunks + user profile context
6. Intelligence Layer (7-stage pipeline)
   - Stage 0: UserProfiler (instant)
   - Stage 1 (parallel): MarketAnalyzer + AssetProfiler + PortfolioFit
   - Stage 2: ScoringEngine (deterministic)
   - Stage 3: Recommendation (deterministic action + LLM reasoning only)
   - Stage 4: _compute_pipeline_confidence (deterministic)
   - Stage 5: ValidationAgent (can only downgrade)
7. build_intelligence_context() → [NORMALIZED PORTFOLIO] + [VALIDATION]
8. build_user_message (intelligence context + citations + optional conversation summary)
9. (NEW) conversation context injection:
   - If session history exists → include summarized context
   - If no history → proceed stateless
10. security.py PII filter → OpenAI (synthesis only, no SQL injection) → confidence → cache + return

## Retrieval Layer — Planner → Executor → Fusion

### Planner (IMPLEMENTED: backend/rag/planner.py + backend/rag/schemas.py)

**Components**
- IntentParser — query → intent_list (keyword + alias matching, no LLM)
- ParamExtractor — per intent → validated params or `status: invalid`
- SourceSelector — params + system_context → `SQL | VECTOR | NO_MATCH` per intent
- ProfileAnnotator — appends `profile_hint` to steps (advisory only, no param mutation)
- PlanBuilder — assembles final `QueryPlan` + `plan_meta`

**Flow**
1. IntentParser → `intent_list`
2. ParamExtractor → `[{intent, params, status}]`
3. SourceSelector → `[{intent, params, source_type}]`
4. ProfileAnnotator → attach `profile_hint` where relevant
5. PlanBuilder → `QueryPlan`

**Intent Types**

| Type | Source | Params |
|---|---|---|
| fx_rate | sql | base, quote (ISO) |
| price_lookup | sql | ticker (1-5 chars) |
| macro_series | sql | series_id (FRED ID) |
| etf_holdings | sql | symbol (1-5 chars) |
| document_lookup / filing_lookup | vector | ticker? |
| knowledge_query | vector | — |
| no_match | vector (owner_id only) | — |
| hybrid | sql + vector | per-step params |

**SQL Templates**
```
fx_rate:      SELECT rate, date FROM fx_rates WHERE base_currency='{base}' AND quote_currency='{quote}' ORDER BY date DESC LIMIT 1
price_lookup: SELECT symbol, close, date FROM prices WHERE symbol='{ticker}' ORDER BY date DESC LIMIT 30
macro_series: SELECT series_id, value, date FROM macro_series WHERE series_id='{series_id}' ORDER BY date DESC LIMIT 12
etf_holdings: SELECT holding_symbol, weight FROM etf_holdings WHERE etf_symbol='{symbol}' ORDER BY weight DESC LIMIT 20
```

**Source Selection Rules**
- SQL intent + valid params → `SQL`
- SQL intent + invalid params → `NO_MATCH` → `VECTOR` (owner_id filter only)
- document / filing / knowledge intent → `VECTOR`
- No intent detected → `NO_MATCH` → `VECTOR` (owner_id filter only)
- SQL step + distinct document/contextual intent → `HYBRID`
- SQL step + another SQL step → two SQL steps, no VECTOR added

**Hybrid Rules**
- Add VECTOR step only when SQL cannot provide the needed context (narrative, filing text, knowledge)
- Never add VECTOR if SQL result fully answers the intent
- VECTOR step in hybrid must be scoped (doc_type or ticker when detectable)
- Max 1 VECTOR step per plan; max 3 steps total

**vector_filter**
```
vector_filter
  owner_id    string        — always required
  doc_type    filing | upload | knowledge | null
  ticker      string | null — only if explicitly detected; never inferred
```
- Avoid global search (owner_id only) when doc_type or ticker is known

**QueryPlan**
```
QueryPlan
  steps[]
    step_id          int
    source_type      SQL | VECTOR | NO_MATCH
    intent_type      string
    parameters       dict
    sql_template_id  string | null
    vector_filter    {owner_id, doc_type?, ticker?} | null
    priority         int
    execution_mode   parallel | sequential
    profile_hint     dict | null

  plan_meta
    total_steps      int
    is_hybrid        bool
    fusion_required  bool
```

**Planner Does NOT Do**
- Execute queries
- Generate dynamic SQL
- Inject owner_id into SQL params
- Override source selection via LLM

**Implementation Status**
- Schemas: VectorFilter, PlanStep, PlanMeta, HybridQueryPlan (backend/rag/schemas.py)
- Planner: IMPLEMENTED + tested (backend/rag/planner.py, backend/tests/test_planner.py)
- Executor: IMPLEMENTED + tested (backend/rag/executor.py, backend/tests/test_executor.py)
- Fusion: IMPLEMENTED + tested (backend/rag/fusion.py, backend/tests/test_fusion.py)
- Session memory: IMPLEMENTED + tested (conversation history per session; advisory context injection)
- Retrieval pipeline: integration tests present (backend/tests/test_retrieval_pipeline.py) — plan → execute → fuse flow verified; 46 tests passing

**Source Coverage Note**
- Unit and integration tests pass end-to-end
- Multi-symbol comparative answers (SPY/QQQ) depend on actual row presence in SQL tables (prices, etf_holdings)
- Ingestion path issues fixed; runtime SQL validation for these symbols is next validation step

---

### Executor (IMPLEMENTED: backend/rag/executor.py)

**Execution Flow**
1. Receive `QueryPlan` + `owner_id`
2. Group steps by `priority` → ordered buckets
3. Per bucket: `parallel` steps run concurrently; `sequential` steps run one-by-one
4. Collect `StepResult` per step; continue on failure
5. Return `list[StepResult]` when all buckets complete

**Step Execution**
- `SQL` → `sql_tool(template_id, parameters, owner_id)` — owner_id injected by executor
- `VECTOR` → `vector_store.query(vector_filter + owner_id, query_text)` — owner_id always appended
- `NO_MATCH` → `vector_store.query({owner_id}, query_text)` — no doc_type filter

**Error Handling**
- Step timeout → `status: error`, `data: null` — plan continues
- 0 rows / 0 chunks → `status: empty`, `data: []`
- Unhandled exception → `status: error`, log step_id + error type
- All steps error/empty → return full `list[StepResult]`; fusion layer decides

**StepResult**
```
StepResult
  step_id       int
  source_type   SQL | VECTOR | NO_MATCH
  intent_type   string
  data          list | null
  status        ok | empty | error
```

---

### Fusion Layer (IMPLEMENTED: backend/rag/fusion.py)

**Inputs**
- `QueryPlan` — step metadata
- `list[StepResult]` — executor output
- `user_profile` (optional) — advisory only

**Flow**
1. Partition: `sql_results` ← SQL steps `ok`; `vector_results` ← VECTOR/NO_MATCH steps `ok`
2. Collect empty/error steps → generate `missing_data_notes`
3. Build `structured_data` from sql_results (keyed by intent_type, data untouched)
4. Build `supporting_context` from vector_results (chunks with source provenance)
5. Append profile as `advisory_context` in `retrieval_summary`

**Merge Rules**
- SQL data → `structured_data` only; never merged into `supporting_context`
- Vector chunks → `supporting_context` only; never promoted to `structured_data`
- No value recomputation at any stage
- Empty/error step → `missing_data_notes` entry with intent_type + source_type + status
- All steps empty/error → empty structured_data + supporting_context; notes populated
- Profile → `advisory_context` block only; not injected into data fields

**FusionResult**
```
FusionResult
  structured_data      dict[intent_type → data]
  supporting_context   list[{chunk_text, source_doc, step_id}]
  missing_data_notes   list[{intent_type, source_type, status}]
  retrieval_summary    {
    has_sql:           bool
    has_vector:        bool
    is_partial:        bool
    advisory_context:  dict | null
  }
```

---

### No-Match Path

- no_match → VECTOR step with owner_id filter only (no doc_type)
- NO fallback chain; NO router retry; NO SQL on no_match; deterministic path

## User Profile Usage

- UserProfiler (Stage 0) extracts risk_tolerance, experience_level from user record
- Profile injected as advisory context into ScoringEngine and Recommendation stages
- Profile is informational only: never overrides retrieved data, SQL results, or deterministic scores
- Profile absence is non-fatal: pipeline proceeds with reduced personalization context

## Parameter Normalization

Currency Aliases
| Input | ISO |
|---|---|
| dollar, usd, דולר | USD |
| shekel, nis, שקל | ILS |
| euro, eur, אירו | EUR |
| pound, gbp | GBP |
| yen, jpy | JPY |
| franc, chf | CHF |
| cad | CAD |
| aud | AUD |

FX Direction (set-based, order ignored)
- USD + ILS → base=USD, quote=ILS (always)
- USD + X → base=USD, quote=X
- X only → base=USD, quote=X
- None → reject → no_match (synthesis)

Macro Mapping
| Input | FRED ID |
|---|---|
| inflation, cpi, אינפלציה | CPIAUCNS |
| interest rate, fed rate, ריבית | FEDFUNDS |
| gdp, תוצר | GDP |
| unemployment, unrate, אבטלה | UNRATE |

Validation Rules
| Type | Param | Rule |
|---|---|---|
| fx_rate | base, quote | in {USD, ILS, EUR, GBP, JPY, CHF, CAD, AUD} |
| price_lookup | ticker | ^[A-Z]{1,5}$ |
| macro_series | series_id | in {CPIAUCNS, FEDFUNDS, GDP, UNRATE} |
| etf_holdings | symbol | ^[A-Z]{1,5}$ |

Sanitization
- Strip non-alphanumeric/underscore, uppercase, cap 20 chars

Semantic Rewrite
- Strip English filler phrases
- Remove English stop words
- Hebrew passes through
- Cap 10 tokens
- Add context suffix

## Intelligence Layer

Pipeline Stages
0. UserProfiler (instant, no DB)
1. (parallel) MarketAnalyzer + AssetProfiler + PortfolioFit
2. ScoringEngine (deterministic: 0.30*market + 0.25*user + 0.20*diversify + 0.25*risk)
3. Recommendation (deterministic action + LLM reasoning)
4. _compute_pipeline_confidence (deterministic)
5. ValidationAgent (can only downgrade, runs LAST)

Agents
| Agent | Type |
|---|---|
| UserProfiler | Pure transform |
| MarketAnalyzer | DB reads: macro, fx |
| AssetProfiler | DB reads: prices, etf_holdings |
| PortfolioFit | DB reads + normalization |
| ScoringEngine | FULLY DETERMINISTIC (no LLM) |
| Recommendation | Deterministic action + LLM reasoning |
| ValidationAgent | 5 sanity checks; downgrades confidence |

Data Normalization (data_normalizer.py)
- Pure function, no DB/LLM
- normalize_portfolio(rows) → NormalizedPortfolio
- Deduplicates: newest row wins
- total_invested = SUM(quantity × cost_basis)
- allocation_pct = position_value / total_invested * 100
- data_note: returns/P&L NOT computable (needs live prices)

ValidationAgent Rules
- Check 1: All scores in [0.0, 1.0]
- Check 2: Action ↔ composite_score consistency
- Check 3: confidence=high requires asset_scores + fed_rate
- Check 4: recommendation.confidence=high requires data_coverage=full
- Check 5: allocation_pct sum 99–101%
- Downgrade: len(flags) >= 3 → low; any flags + high → medium

Context Builder
- [NORMALIZED PORTFOLIO — pre-computed, DO NOT recalculate]
- [VALIDATION] with flags + confidence_override
- Inserted before Portfolio Fit

## LLM Constraints (Synthesis Only)
- NO parameter generation (router handles all SQL-param extraction)
- NO portfolio recalculation (data_normalizer output is immutable)
- NO confidence override (ValidationAgent sets pipeline_confidence deterministically)
- NO fallback routing (no-match → vector only, never retry SQL)
- NO source selection override (router determines SQL/vector/hybrid; LLM cannot change it)
- NO P&L estimation (cost_basis insufficient; LLM forbidden from extrapolating returns)
- Conversation summary is advisory context only (similar to user profile)
- LLM must not treat history as authoritative data over retrieved SQL/vector results                                                                                                                                                                                                                                                                                                                                                                                                                     
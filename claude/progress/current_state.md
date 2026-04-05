# Current State

## What Is Working
- Full auth flow (Google OAuth2 + JWT)
- Multi-tenant data isolation (`owner_id` scoping throughout)
- Document upload → Pinecone indexing pipeline
- Portfolio CRUD + CSV/PDF import
- Semantic caching (Redis)
- SSE streaming via nginx
- Admin RBAC dashboard with latency metrics
- Multi-source planner layer in `router.py` (COMPLETED)
- Hebrew language support in planner (COMPLETED)

## Investment Intelligence Layer — PRODUCTION HARDENED (2026-04-05)

New package: `backend/intelligence/`

### Agents
| Agent | File | Type | Status |
|---|---|---|---|
| UserProfilerAgent | `intelligence/agents/user_profiler.py` | Pure transform | DONE |
| MarketAnalyzerAgent | `intelligence/agents/market_analyzer.py` | Deterministic DB reads | DONE |
| AssetProfilerAgent | `intelligence/agents/asset_profiler.py` | DB reads (prices, etf_holdings) | DONE |
| ScoringEngineAgent | `intelligence/agents/scoring_engine.py` | **FULLY DETERMINISTIC** | DONE |
| PortfolioFitAgent | `intelligence/agents/portfolio_fit.py` | DB reads + normalization | DONE |
| RecommendationAgent | `intelligence/agents/recommendation.py` | Deterministic action + LLM reasoning | DONE |
| **ValidationAgent** | `intelligence/agents/validation.py` | **Post-pipeline sanity checks** | **NEW** |
| IntelligenceOrchestrator | `intelligence/orchestrator.py` | Routes + parallel execution | DONE |
| ContextBuilder | `intelligence/context_builder.py` | Report → LLM string | DONE |

### New: Data Normalization Layer
- File: `intelligence/data_normalizer.py` (NEW)
- Pure function, no DB/LLM calls
- `normalize_portfolio(rows)` → `NormalizedPortfolio`
- Deduplicates by ticker (newest row wins; DB sorted DESC by date)
- `total_invested = SUM(quantity × cost_basis)` per ticker (cost_basis = per-unit per schema.sql)
- `allocation_pct[ticker] = position_value / total_invested * 100`
- Explicit `data_note`: returns/P&L NOT computable (requires live market prices)
- Graceful fallback on empty rows or exception

### New: ValidationAgent (Post-Pipeline Sanity Check)
- Runs AFTER `_compute_pipeline_confidence()` — can only downgrade, never upgrade
- Check 1: All score sub-fields in [0.0, 1.0]
- Check 2: Recommendation action ↔ composite_score consistency (same thresholds as scoring_engine)
- Check 3: `pipeline_confidence=high` requires asset_scores + fed_rate data
- Check 4: `recommendation.confidence=high` requires `data_coverage=full`
- Check 5: `allocation_pct` sum must be 99–101% (rounding tolerance)
- Downgrade rules: `len(flags) >= 3` → `confidence_override=low`; any flags + confidence=high → medium

### Schema Changes (schemas.py)
Two new Pydantic models added to `IntelligenceReport`:
- `NormalizedPortfolio` — pre-computed portfolio metrics; LLM MUST NOT recompute
- `ValidationResult` — `passed: bool`, `flags: list[str]`, `confidence_override: Optional[str]`
- `PortfolioFitAnalysis` — added `normalized_portfolio`, `dominant_ticker` fields
- `IntelligenceReport` — added `normalized_portfolio`, `validation_result` fields; `pipeline_confidence` docstring updated: "set deterministically, never by LLM"

### Integration Points
- `chat_service.py` — Intelligence Layer runs at step 5.5 (after retrieval, before LLM)
- `build_user_message()` — accepts `intelligence_block` param; injected before retrieved context
- **FIXED: Streaming path** — intelligence layer was completely absent from streaming path; now runs full `IntelligenceOrchestrator` on `/chat/stream` as well
- **FIXED: Confidence override** — both sync and streaming paths: `pipeline_confidence` from IntelligenceReport is always the source of truth; LLM `[[Explainability:]]` confidence is only used as fallback when `pipeline_confidence is None`
- User profile fetched early (before intelligence layer, reused at step 6)
- Router — `investment_recommendation` intent type routes to vector + triggers Intelligence Layer

### System Prompt (core/prompts.py)
- **FORBIDDEN OPERATIONS block** placed at the absolute TOP of `CHAT_SYSTEM_PROMPT` — overrides everything
- 5 explicit 🚫 bans:
  1. NEVER perform arithmetic (add, subtract, multiply, divide)
  2. NEVER invent financial figures not in intelligence block or document context
  3. NEVER compute returns/P&L from raw data (quantity, cost_basis) — requires market prices
  4. NEVER override BUY/HOLD/REDUCE/AVOID actions
  5. NEVER invent confidence levels — use ONLY `pipeline_confidence` from intelligence block header
- Rule 7 added: NORMALIZED PORTFOLIO block is authoritative — do NOT recompute
- Rule 8 added: VALIDATION block — must acknowledge reduced confidence, use qualifiers throughout

### Context Builder (context_builder.py)
- `_render_normalized_portfolio()` — renders `[NORMALIZED PORTFOLIO — pre-computed, DO NOT recalculate]` with total positions, total invested, allocation by invested capital (capped at 10), data_note
- `_render_validation()` — renders `[VALIDATION]` section; flags each ⚠ issue; notes confidence_override
- Normalized portfolio inserted before Portfolio Fit section in context block

### build_user_message() Directive (chat_service.py)
- Changed from generic "Extract and cite figures" to: `"CITE figures using [S#] or [D#] tags. Do NOT perform arithmetic. If a number appears here but NOT in the INTELLIGENCE LAYER block, cite it as-is and do NOT derive totals, ratios, or percentages from it."`
- Block label changed from "primary source" to "cite-only, do NOT compute from this"

## Planner Layer — Current Implementation
- File: `backend/rag/router.py`
- LLM outputs intent JSON only — no SQL generation
- All SQL built from hardcoded Python templates
- Full validation pipeline: normalize → FX direction → validate → build
- Fallback chain: per-plan rejection → structured detector → vector (last resort)
- Hebrew: currency, macro, and keyword detection fully extended
- New intent: `investment_recommendation` → routes to vector + triggers Intelligence Layer

## Architecture: Full Pipeline (Current)
```
User query
  → cache check
  → condense_question
  → QueryPlanner (router.py) — intent classification
  → asyncio.gather(sql_tool, vector_store)  — parallel retrieval
  → merge_contexts

  👉 INVESTMENT INTELLIGENCE LAYER
     Stage 0: UserProfilerAgent (instant, no DB)
     Stage 1 (parallel): MarketAnalyzerAgent + AssetProfilerAgent + PortfolioFitAgent
       └─ PortfolioFitAgent calls data_normalizer.normalize_portfolio() internally
     Stage 2: ScoringEngineAgent (deterministic composite score)
     Stage 3: RecommendationAgent (deterministic action + LLM reasoning text only)
     Stage 4: _compute_pipeline_confidence() (base deterministic confidence)
     Stage 5: ValidationAgent (may downgrade pipeline_confidence — ALWAYS runs last)
     → build_intelligence_context() → structured block with [NORMALIZED PORTFOLIO] + [VALIDATION]

  → build_user_message (intelligence block + cite-only retrieved context + portfolio)
  → LLM synthesis — FORBIDDEN from computing, FORBIDDEN from inventing figures
  → confidence_level = pipeline_confidence (deterministic) or LLM fallback
  → response
```

## Next Steps
- Unit tests for `ValidationAgent` (deterministic, easy to test with input/expected pairs)
- Unit tests for `normalize_portfolio()` — edge cases: empty portfolio, NULL cost_basis, multi-currency
- Integration test: full pipeline with mock DB pool
- Tune scoring thresholds based on real user feedback
- Consider caching `MarketContext` in Redis (global, changes daily — TTL 1h)
- Add sector data to AssetProfile (`dominant_sector` currently always `None`)

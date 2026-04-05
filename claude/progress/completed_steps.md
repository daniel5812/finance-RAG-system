# Completed Steps

## Production Hardening Pass — Investment Intelligence System (2026-04-05)

### What Was Done
Fixed 7 critical production problems causing LOW-QUALITY and INCORRECT outputs:
1. Numerical errors (deposits miscomputed, balances confused with flows)
2. Data misinterpretation (balance vs deposit, exposure vs returns)
3. LLM overriding deterministic system logic
4. Generic responses ignoring user profile
5. Hallucinations (fake yields, wrong interest rates)
6. Fake confidence (always "high" regardless of data quality)
7. No validation layer

### Files Changed / Created
| File | Action | Summary |
|---|---|---|
| `intelligence/data_normalizer.py` | **NEW** | Pure normalization layer; `normalize_portfolio()` computes total_invested, allocation_pct from quantity × cost_basis (per-unit) |
| `intelligence/agents/validation.py` | **NEW** | Post-pipeline ValidationAgent; 5 sanity checks; can downgrade `pipeline_confidence` |
| `intelligence/schemas.py` | Modified | Added `NormalizedPortfolio`, `ValidationResult` models; updated `PortfolioFitAnalysis`, `IntelligenceReport` |
| `intelligence/agents/portfolio_fit.py` | Modified | HHI now value-based (via normalized allocation_pct); `dominant_ticker` by value; returns `normalized_portfolio` |
| `intelligence/orchestrator.py` | Modified | Added ValidationAgent as Stage 5 (after base confidence); surfaces `normalized_portfolio` to report |
| `intelligence/context_builder.py` | Modified | Added `[NORMALIZED PORTFOLIO]` and `[VALIDATION]` sections; render helpers added |
| `core/prompts.py` | Modified | FORBIDDEN OPERATIONS block at top of system prompt; rules 7–8 added to Intelligence Layer section |
| `rag/services/chat_service.py` | Modified | Fixed streaming path (was missing intelligence layer entirely); fixed confidence override (deterministic takes priority); updated `build_user_message()` directive to cite-only |

### Critical Bugs Fixed
1. **Streaming path had NO intelligence layer** — `/chat/stream` users received zero agent context; full `IntelligenceOrchestrator.run()` now added to streaming path
2. **ValidationAgent placement** — was initially inside scoring block (before `_compute_pipeline_confidence()`); moved AFTER so validation can only downgrade, never be overwritten
3. **HHI computed from row count, not value** — `Counter(r["symbol"])` was doubly wrong (count-based + inflated by multi-row snapshots); fixed to use `allocation_pct` from NormalizedPortfolio
4. **Confidence was always LLM self-reported** — `[[Explainability:]]` confidence from LLM is now only used as fallback; `pipeline_confidence` from IntelligenceReport always takes priority

### Design Invariants Established
- LLM is FORBIDDEN from performing arithmetic
- LLM is FORBIDDEN from inventing financial figures
- Returns/P&L are NEVER computable from `cost_basis` alone (requires live prices — not in DB)
- `pipeline_confidence` is set deterministically; LLM cannot override it
- ValidationAgent always runs LAST (Stage 5) and can only downgrade confidence

---

## Multi-Source Planner Refactor (`router.py`)

### What Was Done
Replaced LLM-generated SQL with a two-stage approach:
1. LLM classifies intent and extracts typed parameters (JSON only)
2. Python mapper builds hardcoded SQL strings from validated params

### Steps Completed (in order)
1. **Design Review** — Architecture approved: intent JSON → Python mapper → `QueryPlan`
2. **Prompt Design** — `ROUTER_PROMPT` with 6 intent types, normalization rules, 5 examples, mixed query rules
3. **Integration Plan** — Normalize → FX direction → validate → build pipeline specified
4. **Implementation** — `router.py` fully rewritten; all helper functions added
5. **Safety Refinements** — FX direction made set-based; semantic rewrite capped at 10 tokens; portfolio SQL replaced with vector route (owner_id safety)
6. **Hebrew Support** — Currency aliases, macro keywords, structured fallback keywords extended for Hebrew

### Constraints Honored
- `schemas.py` not modified
- `chat_service.py` not modified
- No `{owner_id}` literal SQL ever reaches `run_sql_query`
- Vector is always last fallback
- All param values validated before SQL interpolation

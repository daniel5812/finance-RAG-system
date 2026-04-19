# Engineering Rules

## Hard Stop
Multi-tenant breach, security boundary crossing, or data leakage -> REJECT immediately.

## Multi-Tenancy (non-negotiable)
- Every Postgres query must filter by `owner_id` or `user_id`
- Every vector query must include `owner_id` in metadata filtering
- Every cache key for user data must include `owner_id`
- Never return data from one user to another

## Sensitive Data
- API keys, JWT, and PII must never appear in logs, responses, errors, or comments
- If exposed, rotate credentials immediately

## LLM Security
- All LLM-facing inputs must pass through `security.py`
- Never call OpenAI directly outside `llm_client.py`
- Never log raw input or raw output without PII filtering

## LLM Rules
- The LLM must not choose the data source
- The LLM must not compute financial values
- The LLM must not infer missing data
- The LLM must not override deterministic outputs
- The LLM must not re-rank or filter retrieval results
- The LLM must only synthesize the assembled context into a response
- Intent classification is deterministic (no LLM-led routing)

## Retrieval Finality
- If a SQL plan returns zero rows, the system returns an explicit "no data" state
- NO implicit fallback to vector retrieval is allowed
- If a question requires both SQL and vector data, this must be declared in the plan upfront
- A planner failure is visible; a retriever failure is visible; silent fallback chains are forbidden

## Failure State Clarity
- Invalid ticker format (e.g., "XYZ123" with digits) → explicit validation error, not silent rejection
- Missing ingestion data (e.g., "NEWCO" with no prices) → explicit "no data available" message, NOT vector fallback
- Multi-intent partial failure → return available results + explicitly list missing parts; NEVER infer or guess missing values
- Never choose a fallback source without an explicit plan directive

## SQL Safety
- `sql_tool.py` remains read-only and whitelist-based
- Never expand the whitelist without justification and review
- Never add write operations
- Validate all parameters before execution

## Pipeline Rules
- Every stage must be testable independently
- No stage may depend on side-effects from another stage
- No stage may mix responsibilities owned by another stage
- No implicit fallback branches are allowed
- Every stage must emit structured output
- Planning must complete before retrieval begins
- Retrieval must complete before context assembly begins
- Validation must run after generation and before return

## Caching Rules
- **Plan Cache:** Ticker-specific SQL plans (e.g., `prices WHERE symbol='TSLA'`) are never served from cache to a different ticker. A plan hit is only valid if the cached plan's query parameters match the current question's entities.
- **Semantic Cache:** All cached answers are tagged with a "ticker fingerprint" (extracted significant tokens from the question). A cache hit is only returned if the current question's fingerprint matches the stored entry's fingerprint, preventing TSLA answers from being served for XYZ123 queries.
- Cache keys must include `owner_id` to prevent cross-tenant cache hits.
- Exact-match cache (Redis) is safe because the key includes the full question text.

## Context Rules
- Max context size must be enforced
- Context must be minimal, structured, and relevant
- SQL and vector retrieval must not mix unless the plan explicitly says so
- Hidden context injection is not allowed
- Raw retrieval output must not be passed directly to the LLM without deterministic reduction
- All retrieved chunks must include a `source_type` ("sql" or "document") for citation accuracy

## Observability Rules
- Every stage must log inputs, outputs, and metrics
- Every query must emit:
  - `normalized_question`
  - `plan`
  - `executed_query`
  - `retrieved_rows`
  - `assembled_context`
  - `final_prompt_size`
  - `answer`
- Logging must make it possible to debug retrieval and context assembly before touching prompt behavior

## Auth
- All user-data routes must validate JWT and extract `owner_id`
- Admin routes must verify RBAC role
- Google OAuth client ID must come from env only

## Coding Constraints
- No large refactors without explicit approval
- No breaking multi-tenant isolation
- No direct OpenAI calls
- No write operations via SQL tool
- No assumptions when context is unclear

## Production Principles
- Incremental over big-bang
- Stability over cleverness
- Observable by default
- Retrieval first, generation last
- Fail loudly at boundaries

## Per-Change Checklist
- New endpoints: verify `owner_id` scope
- New SQL: verify parameterization and whitelist coverage
- New LLM code: verify `llm_client.py` and `security.py` usage
- New pipeline stage: verify isolated tests and structured logs
- New context logic: verify size limits and deterministic selection rules
- New dependencies: add only if strictly required

## Retired V1 Patterns
These patterns are not valid targets for new work:
- LLM-led routing
- implicit fallback chains
- hidden context injection
- mixed-responsibility orchestration
- intelligence-layer decision logic as part of the core LLM response path

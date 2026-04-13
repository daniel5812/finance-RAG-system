# Engineering Rules

## Hard Stop
Multi-tenant breach, security boundary crossing, or data leakage → REJECT immediately.

## Multi-Tenancy (non-negotiable)
- Every Postgres query → filter by owner_id or user_id
- Every Pinecone query → include owner_id in metadata filter
- Every cache key for user data → include owner_id
- Never return data from one user to another

## Sensitive Data
- API keys, JWT, PII never in: logs, responses, errors, comments
- If exposed → rotate credentials immediately

## LLM Security
- All inputs → security.py (PII filtering + injection detection)
- Never direct OpenAI calls — via llm_client.py
- Never log raw input/responses without PII filtering

## SQL Safety
- sql_tool.py: table whitelist + read-only
- Never expand whitelist without justification + Reviewer approval
- Never add write operations
- Validate all params before interpolation

## Auth
- All user-data routes → validate JWT + extract owner_id
- Admin routes → verify RBAC role
- Google OAuth client ID → env only, never hardcoded

## Coding Constraints
- No large refactors — minimum change per task
- No breaking multi-tenant isolation
- No direct OpenAI calls
- No write operations via SQL tool
- No skipping Reviewer
- No assumptions — if context unclear → ask

## Production Principles
- Incremental > big-bang
- Stability > cleverness
- Observable by default
- Fail loudly at boundaries

## Per-Change Checklist
- New endpoints → owner_id scope check
- New SQL → parameterized + whitelist checked
- New LLM code → via llm_client.py + security.py
- New dependencies → only if strictly required
- Read files before editing

## Design Invariants (non-negotiable)
- pipeline_confidence set deterministically; LLM cannot override
- LLM [[Explainability:]] confidence is fallback ONLY when pipeline_confidence is None
- ValidationAgent always last (Stage 5); can only downgrade
- NormalizedPortfolio pre-computed; LLM MUST NOT recompute
- Returns/P&L NEVER computable from cost_basis alone
- total_invested = SUM(quantity × cost_basis)
- allocation_pct = position_value / total_invested * 100
- HHI value-based (allocation_pct), NOT count-based
- Deduplication: newest row wins

# Coding Rules

## Global Constraints (all agents, always)
- **No large refactors.** Minimum change to satisfy the task. Refactors are separate tasks with their own spec.
- **No breaking multi-tenant isolation.** Every SQL query and Pinecone search must be scoped by `owner_id`. Cache keys for user data must include `owner_id`.
- **No direct OpenAI calls.** All LLM calls go through `backend/core/llm_client.py`.
- **No write operations via SQL tool.** `sql_tool.py` is read-only. Do not add write operations.
- **No skipping Reviewer.** Builder output is not done until Reviewer issues APPROVED.
- **No assumptions.** If context is unclear → ask. Do not infer unstated system behavior.

## Production Principles
- **Incremental over big-bang.** Ship smallest change that moves forward. Validate before next task.
- **Stability over cleverness.** Extend existing patterns; don't introduce new abstractions.
- **Observability by default.** Every new code path gets a structured log line.
- **Fail loudly at boundaries.** Validate all external inputs (uploads, API responses, scheduled data). Trust internal contracts.

## Specific Rules
- New endpoints → `owner_id` scope check before returning data
- New SQL → parameterized queries, checked against `sql_tool.py` table whitelist
- New LLM-facing code → through `llm_client.py` and `security.py`
- New dependencies → only when strictly required; update `requirements.txt` or `package.json`
- Read files before editing — never modify code you haven't read

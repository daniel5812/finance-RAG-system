# Safety Rules

## Hard Stop Rule
If any change risks breaking multi-tenant isolation, crossing a security boundary, or causing data leakage:
**Stop immediately. Do not proceed. Escalate to Orchestrator.**

## Multi-Tenancy (non-negotiable)
- Every Postgres query touching user data must filter by `owner_id` or `user_id`
- Every Pinecone query must include `owner_id` in metadata filter
- Every cache key for user-specific data must include `owner_id`
- Never return data from one user to another — not even in error messages

## Sensitive Data
- API keys, JWT secrets, and PII must never appear in:
  - Log output
  - API responses
  - Error messages
  - Code comments
- Rotate credentials if accidentally exposed — do not just remove from code

## LLM Security
- All LLM inputs pass through `security.py` (PII filtering + prompt injection detection)
- Never call OpenAI directly — always through `backend/core/llm_client.py`
- Never log raw user input or LLM responses without PII filtering

## SQL Safety
- `sql_tool.py` enforces a table whitelist and read-only mode
- Do not expand the whitelist without Orchestrator justification and Reviewer approval
- Do not add write operations to the SQL tool under any circumstances
- All SQL params must be validated before interpolation (see `router.py` validation pipeline)

## Auth
- All API routes that return user data must validate JWT and extract `owner_id` from token
- Admin routes must verify RBAC role before returning data
- Google OAuth client ID must come from env — never hardcoded

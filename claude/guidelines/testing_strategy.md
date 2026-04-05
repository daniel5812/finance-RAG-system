# Testing Strategy

## Test Layers

| Layer | Tool | Location |
|---|---|---|
| Backend unit + integration | pytest | `backend/tests/` |
| Frontend unit | Vitest | `frontend/src/` |
| Frontend E2E | Playwright | `frontend/` |

## Commands
```bash
cd backend && pytest
cd frontend && npm test
cd frontend && npm run test:watch
cd frontend && npx playwright test
```

## What to Test on Every Router Change

Cover all intent types and all fallback levels. See `claude/agents/tester.md` for the full test case matrix.

### Minimum Router Test Coverage
- All 6 intent types produce correct `QueryPlan`
- Hebrew input produces English-normalized params
- Missing required params → `document_analysis` fallback (not an exception)
- Unknown intent type → `document_analysis` fallback (not an exception)
- FX direction: USD+ILS always → USD/ILS regardless of input order
- JSON parse failure + structured keyword → deterministic SQL fallback
- JSON parse failure + no keyword → vector fallback (last resort)
- No `{owner_id}` literal appears in any SQL string

## Determinism Requirement
The planner must be testable without an LLM. All SQL strings are hardcoded — tests should verify exact output strings, not just `source` field.

## Multi-Tenancy Tests
Any test that queries user data must:
- Confirm data from user A is not returned to user B
- Confirm `owner_id` is present in all cache keys for user-specific operations

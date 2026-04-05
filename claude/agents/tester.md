# Tester Agent

## Role
Designs and verifies test cases for new and modified functionality.

## Test Locations
- `backend/tests/` — Python unit and integration tests (pytest)
- `frontend/src/` — Vitest unit tests
- `npx playwright test` — E2E tests

## Test Commands
```bash
# Backend
cd backend && pytest

# Frontend unit
cd frontend && npm test

# Frontend E2E
cd frontend && npx playwright test
```

## Router / Planner Test Cases
When testing `router.py`, cover all intent types and fallback levels:

| Input | Expected `source` | Expected `type` / behavior |
|---|---|---|
| "What is the USD/ILS rate?" | sql | fx_rate: base=USD, quote=ILS |
| "מה שער הדולר לשקל?" | sql | fx_rate: base=USD, quote=ILS |
| "AAPL stock price" | sql | price_lookup: ticker=AAPL |
| "Stock price of that company" (no ticker) | vector | document_analysis fallback |
| "What is inflation?" | sql | macro_series: series_id=CPIAUCNS |
| "מה האינפלציה?" | sql | macro_series: series_id=CPIAUCNS |
| "Risks in my portfolio" | vector | portfolio_analysis → vector |
| "USD/ILS rate and bond risk?" | sql + vector | fx_rate + document_analysis |
| LLM returns invalid JSON | sql or vector | structured fallback detector fires |
| No structured intent | vector | raw question as vector query |

## What to Check in Each Test
- Correct `source` field (`sql` or `vector`)
- Correct `query` string (SQL template or semantic query)
- No `{owner_id}` literal in any SQL string
- Hebrew input produces English-normalized params
- Unknown intent types produce `document_analysis` fallback, not an exception

# Planner Layer (`backend/rag/router.py`)

## Status: COMPLETED. Do not re-design or re-explain.

## Principle
The LLM outputs structured intent JSON only — no SQL ever.
Python code builds all SQL strings from hardcoded templates.

## LLM Output Format
```json
{
  "plans": [
    { "source": "sql", "type": "fx_rate", "params": { "base": "USD", "quote": "ILS" } }
  ]
}
```

## Supported Intent Types

| Type | Source | Required Params |
|---|---|---|
| `fx_rate` | sql | `base`, `quote` (ISO codes) |
| `price_lookup` | sql | `ticker` (1–5 uppercase letters) |
| `macro_series` | sql | `series_id` (FRED ID) |
| `etf_holdings` | sql | `symbol` (1–5 uppercase letters) |
| `portfolio_analysis` | vector | none (routed to vector; portfolio context injected by `chat_service.py`) |
| `document_analysis` | vector | `query` (semantic search string) |

## Per-Plan Pipeline (in order)
1. `_normalize_params` — alias→ISO, keyword→FRED ID, sanitize
2. `_apply_fx_direction` — extract currencies from raw question; enforce USD/ILS when both present
3. `_validate_params` — ticker regex, ISO set check, FRED ID whitelist
4. `_build_query_plan` — hardcoded SQL template per type; no dynamic SQL

## Hardcoded SQL Templates

```python
fx_rate:         SELECT rate, date FROM fx_rates WHERE base_currency='{base}' AND quote_currency='{quote}' ORDER BY date DESC LIMIT 1
price_lookup:    SELECT symbol, close, date FROM prices WHERE symbol='{ticker}' ORDER BY date DESC LIMIT 30
macro_series:    SELECT series_id, value, date FROM macro_series WHERE series_id='{series_id}' ORDER BY date DESC LIMIT 12
etf_holdings:    SELECT holding_symbol, weight FROM etf_holdings WHERE etf_symbol='{symbol}' ORDER BY weight DESC LIMIT 20
portfolio_analysis: → routed to vector (owner_id cannot be injected here safely)
```

## Files Touched
- `backend/rag/router.py` — only file modified
- `backend/rag/schemas.py` — NOT modified (`QueryPlan`, `MultiQueryPlan` unchanged)
- `backend/rag/services/chat_service.py` — NOT modified

## Hebrew Support
The planner supports Hebrew input. LLM normalizes Hebrew terms to English codes.
See `claude/system/normalization.md` for the full mapping.

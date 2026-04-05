# Data Sources & Schema

## Database Tables (`schema.sql`)

| Table | Purpose | Key Columns |
|---|---|---|
| `users` | User accounts, profiles | `user_id`, `email`, `risk_tolerance`, `experience_level` |
| `prices` | OHLCV stock/ETF prices | `symbol`, `date`, `close` — index on `(symbol, date)` |
| `fx_rates` | FX exchange rates | `base_currency`, `quote_currency`, `rate`, `date` |
| `macro_series` | FRED macro indicators | `series_id`, `value`, `date` |
| `filings` | SEC filing metadata | `ticker`, `form_type`, `filed_at` |
| `etf_holdings` | ETF composition | `etf_symbol`, `holding_symbol`, `weight` |
| `portfolio_positions` | User portfolio | `user_id`, `symbol`, `quantity`, `avg_cost` |
| `documents` | Uploaded document metadata | `owner_id`, `filename`, `status` |
| `document_chunks` | Chunked document text | `document_id`, `chunk_text`, `embedding_id` |
| `audit_logs` | Admin audit trail | `user_id`, `action`, `created_at` |

All tables have `created_at` and `source` fields.

## Financial Data Providers (`backend/financial/providers/`)

| Provider | Data | Source |
|---|---|---|
| `fx.py` | FX rates | Bank of Israel API |
| `macro.py` | CPI, GDP, FEDFUNDS, UNRATE | FRED API |
| `etf.py` | ETF holdings / weights | Yahoo Finance |
| `filings.py` | SEC filings | SEC EDGAR |
| `portfolio.py` | User portfolio import | CSV / PDF upload |

## SQL Query Whitelist (enforced in `sql_tool.py`)
Only these tables are accessible via the SQL tool:
`prices`, `fx_rates`, `macro_series`, `filings`, `etf_holdings`, `portfolio_positions`

## Planner Intent → SQL Mapping
See `claude/system/planner.md` for the full intent-to-SQL mapping used by `router.py`.

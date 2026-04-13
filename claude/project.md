# Project

System: AI Investment Intelligence Engine — decision-support RAG with semantic caching, multi-tenant.

## Stack
- Frontend: React + TypeScript + Vite
- Backend: FastAPI (stateless)
- Database: PostgreSQL 16
- Cache/Queue: Redis 7
- Vector Store: Pinecone
- LLM: OpenAI (via llm_client.py)
- Auth: Google OAuth2 + JWT
- Proxy: NGINX

## Run (Docker)
```
cd backend && docker-compose up -d --build
cd frontend && npm install && npm run dev
GET http://localhost:8000/health
```

## Run (no Docker)
```
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
# separate terminal: python worker_entrypoint.py
```

## Env Variables
Backend: OPENAI_API_KEY, PINECONE_API_KEY, FRED_API_KEY, GOOGLE_CLIENT_ID, JWT_SECRET_KEY, DATABASE_URL, REDIS_HOST, DOCUMENT_UPLOAD_DIR
Frontend: VITE_GOOGLE_CLIENT_ID

## Backend Layers
- core/: connections, cache, llm_client, config, auth, security, prompts
- rag/: router (planner), sql_tool, vector_store, reranker, chat_service
- intelligence/: orchestrator, agents (7), data_normalizer, schemas, context_builder
- financial/: providers (fx, macro, etf, filings, portfolio)
- documents/: upload, extract, chunk, embed, upsert

## Database

| Table | Purpose | Key Columns |
|---|---|---|
| users | Accounts, profiles | user_id, email, risk_tolerance, experience_level |
| prices | OHLCV stock/ETF | symbol, date, close |
| fx_rates | FX rates | base_currency, quote_currency, rate, date |
| macro_series | FRED indicators | series_id, value, date |
| filings | SEC filings | ticker, form_type, filed_at |
| etf_holdings | ETF composition | etf_symbol, holding_symbol, weight |
| portfolio_positions | User portfolio | user_id, symbol, quantity, avg_cost |
| documents | Uploaded docs | owner_id, filename, status |
| document_chunks | Chunked text | document_id, chunk_text, embedding_id |
| audit_logs | Admin trail | user_id, action, created_at |

## SQL Whitelist (sql_tool.py, read-only)
prices, fx_rates, macro_series, filings, etf_holdings, portfolio_positions

## Providers
- fx.py: Bank of Israel API
- macro.py: FRED (CPI, GDP, FEDFUNDS, UNRATE)
- etf.py: Yahoo Finance
- filings.py: SEC EDGAR
- portfolio.py: CSV / PDF upload

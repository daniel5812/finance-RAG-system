# Project

System: AI Investment Intelligence Engine with a production-grade backend and an LLM layer being redefined as a deterministic, testable RAG pipeline.

## Stack
- Frontend: React + TypeScript + Vite
- Backend: FastAPI
- Database: PostgreSQL 16
- Cache: Redis 7
- Vector Store: Pinecone
- LLM: OpenAI via `llm_client.py`
- Auth: Google OAuth2 + JWT
- Proxy: NGINX

## Run (Docker)
```sh
cd backend && docker-compose up -d --build
cd frontend && npm install && npm run dev
```

## Run (no Docker)
```sh
cd backend
python -m venv venv
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Env Variables
Backend: `OPENAI_API_KEY`, `PINECONE_API_KEY`, `FRED_API_KEY`, `GOOGLE_CLIENT_ID`, `JWT_SECRET_KEY`, `DATABASE_URL`, `REDIS_HOST`, `DOCUMENT_UPLOAD_DIR`

Frontend: `VITE_GOOGLE_CLIENT_ID`

## Backend Layers
- `core/`: connections, cache, llm_client, config, auth, security, prompts
- `rag/`: planner, sql retrieval, vector retrieval, filtering, context assembly
- `financial/`: fx, macro, ETF, filings, portfolio providers
  - **Price Provider:** yfinance (daily OHLCV ingestion into `prices` table)
  - Note: External dependency; latency varies with market data availability and third-party API responsiveness
- `documents/`: upload, extract, chunk, embed, upsert

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

## Data Freshness Contract

**Price Data (`prices` table):**
- Represents latest available daily market close, ingested via yfinance
- NOT real-time; NOT intraday updates
- Daily refresh cadence; exact refresh time varies based on market hours and third-party API responsiveness
- Stale data gracefully returned if ingestion has not yet occurred for the current day

**FX Data (`fx_rates` table):**
- Latest available rate for the currency pair
- Refresh cadence depends on external FX data provider

**Macro Data (`macro_series` table):**
- Latest value from FRED (Federal Reserve Economic Data)
- Official FRED release schedule applies (weekly, monthly, or quarterly depending on series)

## LLM V2 Architecture

### Pipeline
```text
User Question
  -> Question Normalization
  -> Source Planning
  -> Retrieval
  -> Filtering / Scoring
  -> Context Assembly
  -> LLM Generation
  -> Output Validation
  -> Final Response
```

### Responsibility Boundaries
- Normalizer
  - converts raw user input into a canonical question representation
  - does not retrieve data or choose retrieval mode
- Planner
  - chooses retrieval strategy deterministically in code
  - emits a structured plan with source, template, params, and limits
  - does not execute queries and does not call the LLM
- Retriever
  - executes the plan exactly as defined
  - does not change source selection or invent fallback behavior
- Filter / Scorer
  - reduces retrieval noise with deterministic rules
  - keeps only the evidence needed downstream
- Context Assembler
  - builds a strict, minimal context object for generation
  - enforces context size and provenance
- LLM
  - synthesizes the assembled context into language
  - does not decide, calculate, or infer beyond supplied evidence
- Validator
  - checks that the answer is supported and policy-compliant
  - blocks unsupported output before return

### Core Design Principles
- Separation of concerns
- Deterministic pipeline stages
- Retrieval first, generation last
- Minimal context
- Full observability at every stage

### Why V1 Failed
- Over-coupling
  - planning, retrieval, reasoning, and output behavior were described as one blended flow
- Noisy context
  - too much low-value retrieval context reached the LLM
- Poor observability
  - debugging could not cleanly isolate whether failure came from planning, retrieval, or prompt behavior
- Implicit behavior
  - fallback chains and hidden context injection made the system hard to reason about

### SQL-First Retrieval Policy
- V2 defaults to SQL-first retrieval
- Vector retrieval is optional and can only run when explicitly planned
- SQL and vector should not be combined unless the plan declares that combination
- **No fallback:** If SQL returns empty, the system does not implicitly fall back to vector. The planner decides upfront whether vector is enabled for this request.

### Performance & Safety Improvements
- **Plan Cache Guard:** Ticker-specific SQL plans are not reused across different tickers, preventing silent data contamination.
- **Semantic Cache Fingerprint:** Cached answers include ticker metadata to prevent "TSLA price" answers from being served for "XYZ123" queries.
- **Intent Classification Fix:** Price-data queries ("Explain AAPL stock price trend") are marked as factual, not analytical. This avoids invoking the heavy intelligence layer for simple data lookups, improving latency.
- **Multi-Intent Support:** The planner can emit multiple SQL plans in a single request (e.g., Fed rate + USD/ILS both in one query), merged into a single context block.

### Evaluation and Debugging
Every query must produce a trace with:
- `normalized_question`
- `plan`
- `executed_query`
- `retrieved_rows`
- `assembled_context`
- `final_prompt_size`
- `answer`

Debugging starts with retrieval and context assembly. Prompt tuning is not the first response to system failure.

## SQL Whitelist
Read-only access is limited to:
- `prices`
- `fx_rates`
- `macro_series`
- `filings`
- `etf_holdings`
- `portfolio_positions`

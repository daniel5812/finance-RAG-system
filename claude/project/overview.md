# Project Overview

## What It Is
AI Investment Intelligence Engine — a decision-support system (not a trading bot) for structured financial analysis with document-aware RAG.

Ingests: financial market data, macro indicators, SEC filings, user portfolio positions.
Outputs: analytical insights through multi-tenant RAG with semantic caching.

## Implemented Features
- **Auth & Multi-Tenancy**: Google OAuth2 + JWT. All data strictly scoped by `user_id`.
- **User Personalization**: `risk_tolerance`, `experience_level`, `preferred_style` drive LLM system prompt. AI hook auto-updates user `interests` from chat history.
- **Document Management**: Upload → Extract → Embed → Pinecone. Newly indexed docs auto-selected in UI.
- **Portfolio Management**: Owner-scoped CRUD (`GET/POST/DELETE/import`). CSV and PDF import. `portfolio_positions` injected into LLM context.
- **Admin Dashboard**: RBAC. Admins see audit events, user list, P50/95/99 latency metrics.
- **Semantic Caching**: Redis-backed. Blocks duplicate queries (`< 1s` return). Cache keys include `owner_id`.
- **Streaming**: Token-by-token SSE via nginx.
- **Multi-Source Planner**: `router.py` — LLM outputs intent JSON only (no SQL). Python mapper builds hardcoded SQL. See `claude/system/planner.md`.

## Running the Project

### Backend (Docker — preferred)
```bash
cd backend
docker-compose up -d --build
docker-compose logs -f api
docker-compose logs -f worker
docker-compose down
```

### Backend (without Docker)
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
python worker_entrypoint.py   # separate terminal
```

### Frontend
```bash
cd frontend
npm install
npm run dev
npm run build
npm test
npx playwright test
```

### Health Checks
```
GET http://localhost:8000/health
GET http://localhost:8000/docs
GET http://localhost:8000/metrics
```

## Environment Variables

Backend `.env`: `OPENAI_API_KEY`, `PINECONE_API_KEY`, `FRED_API_KEY`, `GOOGLE_CLIENT_ID`, `JWT_SECRET_KEY`, `DATABASE_URL`, `REDIS_HOST`, `DOCUMENT_UPLOAD_DIR`

Frontend `.env`: `VITE_GOOGLE_CLIENT_ID`

# 🧠 AI Investment Intelligence Engine

A decision-intelligence system for structured financial analysis and document-aware retrieval (RAG).

This system ingests market data, macro indicators, FX rates, ETF holdings, SEC filings, and user portfolio positions — then enables analytical insights, scenario simulations, and explainable decision-support outputs through an advanced multi-tenant RAG, caching, and routing architecture.

❗ **This is NOT a trading bot or automated investing system.**
It is an analytical intelligence layer.

---

## 📦 Project Overview

The system consists of:
- **FastAPI backend** (horizontally scaled via Nginx load balancer)
- **PostgreSQL** (relational financial data & document metadata storage)
- **Redis** (layered semantic caching, rate limiting, and exact-match cache)
- **Pinecone** (vector store for document embeddings)
- **OpenAI** (LLM for generation, chunk embedding, and intelligent query routing)
- **Dockerized infrastructure** (multi-container orchestration)

---

## 🏗 Architecture

```text
       [  Incoming API Requests  ]
                 │
                 ▼
       ┌───────────────────┐
       │ NGINX Load Balancer │
       └───────────────────┘
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
  ┌─────────┐         ┌─────────┐
  │ FastAPI │   ...   │ FastAPI │ (Horizontally Scaled)
  │  Node 1 │         │  Node N │
  └─────────┘         └─────────┘
       │                   │
 ┌─────┼───────────────────┼─────┐
 │     ▼                   ▼     │
 │  ┌─────┐   ┌───────┐ ┌─────┐  │
 │  │Redis│   │Pinecone││  DB  │  │ (Shared State Layer)
 │  └─────┘   └───────┘ └─────┘  │
 └───────────────────────────────┘
```

The API layer is strictly stateless. All persistent state and caching live in PostgreSQL, Redis, or Pinecone, ensuring perfect horizontal scalability and tenant isolation. Requests are fully traceable across the system using correlation IDs.

---

## 🚀 Key Features and Pipelines

### 1️⃣ Document RAG Pipeline (Multi-Tenant)
A secure multi-tenant retrieval-augmented generation engine natively integrated with individual user workspaces.

1. **Ingestion & Indexing:** 
   - PDF uploads are processed by background workers.
   - Flow: `Extract Text` → `Chunk` → `Embed (MiniLM)` → `Upsert to Pinecone`
   - Metadata (`owner_id`, `document_id`) strictly segregates tenant data.
   
2. **Intelligent Query Routing & Multi-Source Synthesis (Stage 9):**
   - User queries are intercepted by a specialized routing LLM.
   - **Compound Query Decomposition**: Multi-part questions (e.g., "Check SPY holdings AND USD rate") are broken into a `MultiQueryPlan`.
   - **Concurrent Retrieval**: SQL queries (Structured) and Vector searches (Unstructured) are executed in parallel (`asyncio.gather`) for minimum latency.
   - **Secure SQL Tool**: Optimized financial queries are executed against a hardened PostgreSQL engine with strict read-only and table-whitelist guardrails.
   - **Context Fusion**: Structured data and textual chunks are merged into a unified analytical context before synthesis.
   - Built-in guardrails detect and retry LLM hallucinations before execution.

### 2️⃣ Layered Semantic Caching
Advanced caching mechanisms to minimize latency and AI costs:
1. **Exact-Match Cache:** Instantly returns answers for identical queries.
2. **Embedding Cache:** Avoids re-encoding identical query strings.
3. **Semantic Cache:** Uses vector similarity to detect *conceptually* identical queries (e.g. "What is my 2024 return?" vs "How much did my portfolio make this year?") and returns cached answers if similarity crosses a rigorous threshold. **Note**: Caches are strictly partitioned by `owner_id`.

### 3️⃣ Data Ingestion Model (Structured Data)
All external data sources follow a resilient provider pipeline (`fetch_raw` → `normalize` → `validate via Pydantic` → `store` → `provenance log`).
- **Idempotency:** Re-running pipelines ignores existing records (ON CONFLICT DO NOTHING).
- **Extensible Providers:** Existing providers include Bank of Israel (FX rates), Yahoo Finance (ETF Holdings), FRED (Macro), and more.

---

## 📊 Structured Data Types

### 1. Prices (Market Data)
- **Purpose:** Daily stock / ETF / index price history.
- **Use Cases:** Returns calculation, volatility, drawdown.

### 2. FX Rates (Currency Data)
- **Purpose:** Exchange rate normalization for cross-currency portfolios.
- **Provider:** Bank of Israel API.

### 3. Macro Series (Economic Indicators)
- **Purpose:** Macroeconomic context (Yield curves, Inflation, GDP).
- **Use Cases:** Interest rate sensitivity, regime detection.

### 4. ETF Holdings
- **Purpose:** Decompose ETF exposure.
- **Use Cases:** Sector exposure, indirect stock exposure, concentration analysis.

### 5. Portfolio Positions
- **Purpose:** User-specific holdings.
- **Use Cases:** Portfolio valuation, risk analysis.

### 6. SEC Filings (Fundamentals)
- **Purpose:** Company fundamental financial data (10-K, 10-Q, 8-K).
- **Use Cases:** Revenue growth analysis, margin tracking, risk factor extraction.

---

## 🔒 Security & Data Integrity
1. **Tenant Isolation:** All document processing, vector querying, and semantic caching are strictly bound by an `owner_id`. Cross-tenant data leakage is structurally impossible.
2. **Pydantic Validation:** All incoming data (APIs, Webhooks, scraping) passes through strict schema validation before DB insertion.
3. **Unique Constraints & Hashing:** Prevents duplicate ingestion. Auditing hashes (SHA256) detect altered source content.
4. **Prompt Injection Protection:** Inputs are validated against heuristics and injection patterns before reaching the LLMs.

---

## 🏁 Design Principles
- **Stateless API:** Easy to horizontally scale.
- **Externalized State:** Postgres + Redis + Pinecone.
- **Provider Abstraction:** Easily add new data sources.
- **Resiliency & Guardrails:** Retry mechanisms on LLM calls, robust LLM schema enforcement (json_object + validation).

---

## 🚦 Getting Started

### 1️⃣ Backend (Docker)
The backend runs in a robust multi-tenant Docker environment.
```bash
cd ml_foundations
docker-compose up -d --build
```
- **API URL**: `http://localhost:8000`
- **Health Check**: `http://localhost:8000/health`
- **Interactive API Docs**: `http://localhost:8000/docs`

### 2️⃣ Frontend (React)
The frontend provides a premium analytical chat interface.
```bash
cd ../insight-ledger
npm install
npm run dev
```
- **UI URL**: `http://localhost:5173`

---

## 🔍 Observability & Logs

The system is designed for deep tracing. Every request carries a unique `X-Request-ID`.

### 📱 Backend Logs
To see real-time AI logic, routing decisions, and SQL execution:
```bash
# All logs
docker logs -f ml_foundations-api-1

# Specific filters (e.g., search for router decisions)
docker logs ml_foundations-api-1 | grep "router_decision"
```

### 🧠 Performance Metrics
In the **Frontend**, use the built-in **Latency Bar** (below each AI message) to see:
- **Planning**: Time spent in the Heuristic / LLM Router.
- **Retrieval**: SQL and Vector execution time.
- **Generation**: LLM synthesis time.

### 📁 Document Processing
Monitor the ingestion queue:
```bash
docker logs -f ml_foundations-worker-1
```

---

*Disclaimer: This system provides analytical decision support. It does not provide investment advice.*
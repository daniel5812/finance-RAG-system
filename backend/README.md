# 🧠 AI Investment Intelligence Engine

A production-grade **Investment Intelligence System** for structured financial analysis, document-aware retrieval (RAG), and deterministic decision support.

This system ingests market data, macro indicators, FX rates, ETF holdings, SEC filings, and user portfolio positions — then transforms them into **scored, explainable investment insights and recommendations**.

❗ This is NOT a trading bot or automated investing system.  
It is a **decision-intelligence layer** designed for analysis, reasoning, and explainability.

---

## 📦 Project Overview

The system is composed of:

- **FastAPI backend** (stateless, horizontally scalable via NGINX)
- **PostgreSQL** (financial data, portfolio, metadata)
- **Redis** (semantic caching, rate limiting)
- **Pinecone** (vector embeddings for document search)
- **OpenAI** (LLM used strictly for explanation and synthesis)
- **Dockerized infrastructure** (multi-container orchestration)

---

## 🏗 Architecture


User Query
↓
Query Planner (router.py)
↓
SQL + Vector Retrieval (parallel)
↓
Investment Intelligence Layer
↓
LLM Explanation Layer
↓
Final Response


The API layer is strictly **stateless**.  
All state is externalized (Postgres, Redis, Pinecone), enabling horizontal scaling and strict tenant isolation.

---

## 🧠 Core Innovation: Investment Intelligence Layer

The system has evolved from a classic RAG pipeline into a **structured reasoning engine**.

### Full Pipeline


Retrieval → Normalization → Agents → Scoring → Recommendation → Validation → LLM


### Agents

- **UserProfilerAgent**
  - Builds structured user investment profile (risk, behavior, preferences)

- **MarketAnalyzerAgent**
  - Classifies macro regime (interest rates, inflation, economic signals)

- **AssetProfilerAgent**
  - Profiles stocks and ETFs using price data and holdings

- **ScoringEngineAgent (Deterministic)**
  - Computes composite score:
    - 30% market fit
    - 25% user fit
    - 20% diversification
    - 25% risk alignment

- **PortfolioFitAgent**
  - Uses normalized portfolio
  - Computes concentration (HHI based on invested value, not row count)

- **RecommendationAgent**
  - Outputs: BUY / HOLD / REDUCE / AVOID
  - Fully deterministic decision
  - LLM generates explanation only

- **ValidationAgent (Critical Layer)**
  - Ensures:
    - score consistency
    - action correctness
    - confidence validity
  - Can downgrade confidence if inconsistencies are detected

---

## ⚙️ Data Normalization Layer

Located at: `backend/intelligence/data_normalizer.py`

Transforms raw DB rows into canonical structured signals:

- `total_invested = SUM(quantity × cost_basis)`
- `allocation_pct` per ticker

This prevents:
- confusion between balances and deposits
- incorrect interpretation of exposure vs performance
- LLM miscalculations

---

## 🧾 Structured Context Blocks

The LLM receives only structured, precomputed signals:

### `[NORMALIZED PORTFOLIO]`
- total invested capital
- allocation per asset
- dominant exposure

### `[VALIDATION]`
- detected inconsistencies
- confidence adjustments

These blocks ensure the LLM operates on **trusted data only**.

---

## 🔒 LLM Constraints (Critical Design)

The LLM is tightly controlled and **not allowed to make decisions**.

### 🚫 Forbidden:
- performing arithmetic (no calculations)
- deriving totals or percentages
- inventing financial numbers
- overriding system recommendations
- inventing confidence levels

### ✅ Allowed:
- explanation
- synthesis
- structured reasoning

All decisions come from deterministic system components.

---

## 🔍 Query Planning & Retrieval

### Multi-Source Planner (`router.py`)

- LLM outputs **intent JSON only**
- SQL queries are built deterministically in Python
- Supports:
  - structured queries (SQL)
  - unstructured queries (vector search)
- Full Hebrew and English support

### Retrieval Strategy

- SQL and vector queries run in parallel (`asyncio.gather`)
- Cross-encoder reranker improves relevance
- Results are merged into a unified context

---

## 📊 Data Sources

### Structured Data (PostgreSQL)

- Prices (stocks, ETFs)
- FX rates (Bank of Israel)
- Macro indicators (FRED)
- ETF holdings (Yahoo Finance)
- Portfolio positions
- SEC filings

### Unstructured Data

- User-uploaded documents → embedded in Pinecone

---

## ⚡ Semantic Caching

Three caching layers:

- Exact-match cache
- Embedding cache
- Semantic similarity cache

All caches are strictly **tenant-isolated (owner_id)**.

---

## 🔒 Security & Data Integrity

- Strict multi-tenant isolation (owner_id enforced everywhere)
- Read-only SQL layer with table whitelist
- Pydantic validation on all ingested data
- Prompt injection protection (`security.py`)
- No direct LLM calls outside controlled pipeline

---

## 📁 Document Pipeline


Upload → Extract → Chunk → Embed → Pinecone


- 500-character chunks (50 overlap)
- owner_id-based isolation
- async worker-based ingestion

---

## 🔁 Chat Flow (End-to-End)


User Query
→ Cache check
→ Router (intent classification)
→ SQL + Vector retrieval
→ Context fusion

→ Investment Intelligence Layer:
User profiling
Market analysis
Asset profiling
Portfolio fit
Scoring (deterministic)
Recommendation (deterministic)
Validation (final guardrail)

→ LLM synthesis (explanation only)
→ Response


---

## 🧪 Observability & Debugging

Every request is tagged with a unique `X-Request-ID`.

### Backend Logs


docker logs -f ml_foundations-api-1
docker logs ml_foundations-api-1 | grep "router_decision"


### Performance Metrics

The frontend displays:
- Planning time
- Retrieval time
- Generation time

---

## 🏁 Design Principles

- Deterministic decision-making (no LLM guessing)
- Explainable AI (transparent reasoning)
- Stateless architecture (horizontally scalable)
- Multi-tenant safety by design
- Fail-safe outputs (no hallucinations)

---

## 🚧 Known Limitations

- Returns / P&L cannot be computed without live market prices
- Sector classification is not yet available
- Limited macro series coverage (FRED)
- Hebrew ticker mapping requires explicit symbol input

---

## 🚀 Roadmap

- Live price enrichment (enable real P&L calculations)
- Sector classification layer
- Market sentiment integration
- Observability dashboard (debug UI)
- Automated evaluation suite

---

## 👤 Author

Daniel Dahan

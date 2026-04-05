# AI Investment Intelligence Engine

A production-grade investment decision-support system that combines:
- structured financial data
- document-aware RAG
- deterministic scoring
- explainable AI reasoning

---

## 🚀 What This System Does

This is NOT a chatbot.

It is an Investment Intelligence System that:
- analyzes user portfolio and documents
- understands market conditions
- profiles assets (stocks, ETFs)
- computes deterministic scores
- generates actionable recommendations (BUY / HOLD / REDUCE / AVOID)
- explains reasoning using LLM (no hallucinations)

---

## 🧠 Architecture

User → Query Planner → SQL + Vector Retrieval  
→ Investment Intelligence Layer  
→ LLM Explanation → Response  

---

## ⚙️ Key Components

### Investment Intelligence Layer
- UserProfilerAgent
- MarketAnalyzerAgent
- AssetProfilerAgent
- ScoringEngineAgent (deterministic)
- PortfolioFitAgent
- RecommendationAgent
- ValidationAgent

### Data Normalization
- normalize_portfolio()
- computes total_invested, allocation_pct
- prevents LLM misinterpretation

### Validation Layer
- ensures consistency between score, action, confidence
- prevents invalid outputs

### LLM Constraints
- no arithmetic
- no hallucination
- no overriding system decisions
- explanation only

---

## 🏗️ Tech Stack

- FastAPI
- PostgreSQL
- Redis
- Pinecone
- OpenAI
- React + TypeScript
- Docker + NGINX

---

## 🚧 Roadmap

- live price enrichment
- sector classification
- observability dashboard
- evaluation suite

---

## 👤 Author

Daniel Dahan
# State

## Current System State
- Authentication, JWT handling, and multi-tenant isolation exist in the current backend
- SQL-backed financial data and document ingestion infrastructure exist
- Vector infrastructure exists for document search, but it is not part of the default LLM v2 path
- The repo still contains legacy architecture language describing a mixed planner, fallback, and intelligence flow
- LLM v2 documentation is being defined before a full implementation rewrite

## Legacy Architecture Still Present
- multi-source routing behavior
- vector fallback patterns
- intelligence-layer terminology
- mixed retrieval and generation narratives

These should be treated as legacy behavior, not as the target architecture for new LLM work.

## LLM V2 Migration Status

### Implemented Today
- security and tenant-isolation foundations
- SQL-backed data sources required for SQL-first retrieval
- LLM integration through controlled client code
- document and vector infrastructure available for future explicit use
- deterministic planner with heuristics fast-track (entity extraction, rule-based plan emission) and LLM router slow-track
- multi-intent SQL query support (multiple plans executed and merged in a single request)
- intent classification (factual/analytical/advisory) with special handling for price-data queries
- caching infrastructure with safety guards:
  - plan cache rejects ticker-specific plans for different tickers
  - semantic cache uses ticker fingerprint validation to prevent cross-ticker contamination
- observability logging at major pipeline stages (planning, retrieval, context assembly, generation)

### Still Evolving
- complete end-to-end v2 orchestration as a unified stateless service
- standardized stage contracts for normalization, filtering, and validation with strict contracts
- mandatory per-query structured trace standardization across all request paths
- strict context-size enforcement with a documented assembly layer
- consistent output validation as a mandatory final gate

### Recent System Improvements (V2 Hardening)
- **Caching Safety:** Plan cache now rejects ticker-specific SQL plans when serving different tickers. Semantic cache includes ticker fingerprint validation to prevent "TSLA" answers being served for "XYZ123" queries.
- **Retrieval Finality:** Removed implicit SQL-to-vector fallback. If SQL returns empty, the system explicitly returns "no data" rather than silently invoking vector search. This makes retrieval behavior deterministic and visible.
- **Intent Classification:** Price-data queries (e.g., "Explain the trend of AAPL stock price") are now correctly classified as factual, not analytical. This prevents unnecessary invocation of the heavy intelligence layer and improves latency.
- **Multi-Intent Support:** The planner now generates multiple SQL plans for single requests (e.g., Fed rate + USD/ILS exchange rate in one query), with automatic result merging.

### Intentionally Excluded From MVP
- memory
- profile personalization
- hybrid retrieval
- intelligence layer as part of the default LLM response path

## What This Means For New Work
- New LLM work should target the v2 pipeline, not extend the legacy mixed architecture
- Retrieval quality and observability take priority over richer prompting
- SQL-first behavior is the default assumption unless a future plan explicitly enables vector retrieval

## Evaluation Trace Requirement
Each query must log:
- `normalized_question`
- `plan`
- `executed_query`
- `retrieved_rows`
- `assembled_context`
- `final_prompt_size`
- `answer`

If a response is poor, investigation should begin with retrieval and context assembly rather than the prompt.

# System Behavior

## LLM V2 Request Flow
The active target architecture is a deterministic retrieval pipeline. The system behavior is defined by the following flow:

1. Normalize question
2. Build plan
3. Execute retrieval
4. Assemble context
5. Call LLM
6. Validate response

The LLM is the last transformation step before validation. It is not a planner, router, calculator, or fallback engine.

## System Guarantees

The V2 pipeline enforces these explicit guarantees:

1. **Deterministic SQL-First Retrieval:** Every question produces a structured plan. If SQL retrieval is planned, the system executes SQL. If SQL returns empty, NO implicit fallback to vector retrieval occurs. The plan is the contract.

2. **No Silent Hallucination:** The LLM never infers missing data, computes financial values, or chooses alternative data sources. Missing data results in an explicit "no data available" message, never a guessed answer.

3. **Explicit Failure Behavior:** Invalid queries (malformed ticker, missing ingestion) return explicit error states. Multi-intent partial failures return available results + explicitly list missing parts. No silent degradation.

4. **Source Transparency:** Every retrieved chunk includes `source_type` (sql or document). The system never mixes sources without explicit plan declaration. Citation accuracy is enforced by design.

5. **Cache Safety by Design:** Plan cache rejects ticker-specific SQL plans for different tickers. Semantic cache includes ticker fingerprint validation + owner_id scoping. Cross-user and cross-ticker contamination is impossible.

6. **Observable Failure Modes:** Every stage fails loudly with explicit error messages, never with partial or degraded results. Heuristics fast-track (< 5ms planning) avoids LLM router when possible for latency predictability.

## Stage Behavior

### 1. Normalize Question
- Input: raw user question
- Output: `normalized_question`
- Responsibilities:
  - canonicalize the question
  - extract deterministic entities and aliases
  - preserve the user's request in a structured form
- Must not:
  - choose retrieval source
  - call SQL or vector tools
  - add hidden context

### 2. Build Plan
- Input: `normalized_question`
- Output: `plan`
- Responsibilities:
  - choose retrieval mode from code-defined rules
  - define query template and parameters
  - define limits, required fields, and validation constraints
  - explicitly declare whether vector retrieval is disabled or enabled
- Must not:
  - call the LLM
  - retrieve data
  - rely on implicit fallback chains

Example plan shape:
```json
{
  "retrieval_mode": "sql",
  "query_template": "latest_fx_rate",
  "params": {
    "base_currency": "USD",
    "quote_currency": "ILS"
  },
  "row_limit": 1,
  "vector_enabled": false
}
```

### 3. Execute Retrieval
- Input: `plan`
- Output: `retrieved_rows`
- Responsibilities:
  - run the exact retrieval defined by the plan
  - return explicit results or explicit failure states
  - keep retrieval execution observable
- Must not:
  - re-plan
  - expand to other data sources silently
  - mix SQL and vector unless `plan` says so
  - silently fall back to vector when SQL returns empty

Retrieval is SQL-first in v2. Vector retrieval is optional and is not part of the default path. It may be added later only when a deterministic plan explicitly enables it.

**Critical:** If a SQL plan returns no rows, the system returns an explicit empty state. No implicit fallback to vector retrieval occurs.

### 4. Assemble Context
- Input: `normalized_question`, `plan`, `retrieved_rows`
- Output: `assembled_context`
- Responsibilities:
  - keep only relevant evidence
  - enforce minimal, structured context
  - preserve provenance from retrieval to generation
- Must not:
  - inject hidden context
  - pass large raw retrieval blobs to the LLM
  - encode business decisions into prompt prose

### 5. Call LLM
- Input: `assembled_context`
- Output: `answer_draft`
- Responsibilities:
  - synthesize provided evidence into clear language
  - keep reasoning bounded to supplied context
- Must not:
  - choose source
  - compute financial values
  - infer missing data
  - override deterministic outputs

### 6. Validate Response
- Input: `answer_draft`, `assembled_context`, `plan`
- Output: `answer`
- Responsibilities:
  - check that the answer is supported by context
  - enforce response structure and guardrails
  - reject unsupported or non-compliant drafts
- Must not:
  - retrieve more data
  - silently patch missing evidence
  - bypass failed upstream stages

## Multi-Intent Query Support

The planner may emit multiple SQL plans in a single request. Example: "What is the Fed rate and USD/ILS exchange rate?" produces:
- One `macro_series` plan (FEDFUNDS)
- One `fx_rate` plan (USD/ILS)

Both plans execute concurrently. Results are merged and assembled into a single context block. The LLM synthesizes both retrieved values in a single response. This is deterministic and explicit — the plan declares intent multiplicity upfront.

## Query Modes: Factual vs Analytical

The system operates in two distinct modes based on intent classification. **Intent classification is deterministic and rule-based** (heuristic keyword matching in `chat_service.py`). It is NOT LLM-driven; the LLM does not decide which mode to use.

### Factual Mode (SQL-First)
Direct data retrieval with minimal synthesis. No intelligence layer.

Query types:
- **price_lookup:** "What is the AAPL stock price?" → retrieves 30 days of price history
- **fx_rate:** "What is the USD/ILS rate?" → retrieves latest FX rate
- **macro_series:** "What is the Fed rate?" → retrieves latest macro indicator (FEDFUNDS, CPI, GDP, unemployment)
- **etf_holdings:** "What are the SPY holdings?" → retrieves ETF composition

Even if the question uses interpretive language ("Explain the trend of AAPL stock price", "Analyze MSFT price movement"), if it contains a price indicator + a named ticker, it remains in **Factual Mode**. The system retrieves the data via SQL and the LLM performs lightweight synthesis only.

### Analytical Mode (Intelligence Layer)
Deeper reasoning and comparative analysis. May invoke portfolio analysis, risk scoring, and recommendations.

Query types:
- **portfolio_analysis:** "What is my portfolio risk exposure?" → analyzes user positions against market context
- **comparative_analysis:** "How do tech stocks compare for diversification?" → comparative reasoning (not a specific ticker price)
- **advisory:** "Should I buy Apple stock?" → recommendation with reasoning
- **market_analysis:** "What is the impact of inflation on bonds?" → causal reasoning over market context

**Key distinction:** If a question asks about a SPECIFIC TICKER's price data without deeper portfolio/market analysis, it is **Factual Mode** regardless of wording.

## Failure Behavior

The system returns explicit failure states rather than silent fallbacks or inferred answers.

### Invalid or Missing Data
- **Invalid ticker (e.g., "XYZ123"):** System validates format at plan execution time. If validation fails, returns: `"Data not available for ticker XYZ123."`
- **Ticker with no ingested data (e.g., "NEWCO"):** SQL query returns zero rows. System returns: `"No pricing data available for NEWCO."` Does NOT fall back to vector search.
- **Missing macro series (e.g., "inflation" without CPIAUCNS ingestion):** SQL query returns empty. System returns: `"No data available for the requested series."` Explicit state, no implicit fallback.

### Multi-Intent Partial Failure
When multiple plans are executed (e.g., "What is the Fed rate and USD/ILS exchange rate?"):
- If BOTH plans return data → synthesize full answer with both values
- If ONE plan returns data and ONE fails → return available data + explicitly state what's missing. Example: `"The Fed rate is 4.50%. Data for USD/ILS exchange rate is not currently available."`
- If BOTH plans fail → return explicit failure message for both intents

This is deterministic: partial results are returned and marked as such. The system never infers or guesses missing values.

### No Implicit Fallback
If the plan declares SQL-first retrieval and SQL returns empty:
- Vector retrieval is NOT triggered
- No alternative data sources are queried
- System returns explicit "no data" message
- User sees a clear failure state, not an irrelevant answer from a different source

## Caching Safety: Two Distinct Layers

The system maintains two independent caches with distinct responsibilities and safety constraints:

### Layer 1: Plan Cache (Semantic, Matched by Query Similarity)
**Purpose:** Avoid re-planning semantically identical questions.

**When used:** 
- After heuristics returns no plan
- Before calling the LLM router (slow track)
- Orchestrator looks up plan by embedding similarity of the normalized question

**Content:** Structured retrieval plans (source mode, query template, parameters, row limits)

**Safety constraint:** 
- **Ticker-specific SQL plans are never reused across different tickers.** A cached plan with `prices WHERE symbol='TSLA'` is rejected if the current question asks about `XYZ123`. This guard is enforced by checking the query string for ticker-specific SQL syntax. Prevents silent cross-ticker data contamination.

### Layer 2: Semantic Answer Cache (Full answers, Matched by Answer Similarity)
**Purpose:** Avoid re-running retrieval and generation for semantically identical questions.

**When used:**
- After planning completes
- After retrieval and context assembly complete
- Before calling LLM (skip generation entirely on hit)
- Subsequent semantically similar questions hit this cache

**Content:** Full answers (synthesis output + sources + citations)

**Safety constraints:**
- **Scoped by `owner_id`** to prevent cross-user cache hits (multi-tenancy)
- **Ticker fingerprint validation:** Each cached answer is tagged with a "ticker fingerprint" (extracted meaningful tokens from the original question, excluding common words). During lookup, if the current question's tickers don't match the cached entry's tickers, the hit is rejected. Example: `"What is TSLA price?"` answer is never served for `"What is XYZ123 price?"` even though both have ~0.95 cosine similarity.

## Sources & Provenance

Every retrieved chunk includes a `source_type`:
- `"sql"`: came from a deterministic SQL query
- `"document"`: came from vector retrieval on uploaded documents

If a query runs only SQL, only `source_type="sql"` chunks appear in the context. Document sources only appear if the plan explicitly enables vector retrieval. This clarity is essential for citation and trust.

## Explicitly Removed From V2
The following behaviors are not part of the v2 architecture and should not be reintroduced into core docs or implementation work:

- implicit fallback logic
- SQL-to-vector fallback when SQL returns empty
- mixed SQL + vector retrieval without explicit plan output
- hidden context injection
- LLM-led routing or source selection
- multi-agent intelligence orchestration as the default response path
- prompt-time decision making that replaces deterministic code paths

## Deterministic Planning Rules
- Every request must produce a structured `plan`.
- The plan must be inspectable before retrieval starts.
- If no valid plan can be built, the system should return an explicit planning failure state.
- Unplanned retrieval is not allowed.
- Undocumented fallback chains are not allowed.

## Observability
Every stage must log:
- inputs
- outputs
- metrics

Required per-query trace:
- `normalized_question`
- `plan`
- `executed_query`
- `retrieved_rows`
- `assembled_context`
- `final_prompt_size`
- `answer`

Metrics should make it possible to isolate where quality degraded:
- normalization success or failure
- planning success or failure
- retrieval latency and row count
- context size before and after filtering
- final prompt size
- validation pass or failure

## Debugging Priority
Debugging starts with:
1. normalization correctness
2. plan correctness
3. retrieval correctness
4. context assembly quality
5. only then LLM prompt or output behavior

Retrieval first, generation last. If retrieval is wrong, the system fails even if the prompt is strong.

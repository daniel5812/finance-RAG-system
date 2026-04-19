# Workflow

## Purpose
This document defines the LLM v2 execution workflow for the backend. The workflow is deterministic, stage-based, and observable. The LLM is used only for synthesis after retrieval and context assembly are complete.

## Pipeline Overview
1. Question Normalization
2. Source Planning
3. Retrieval
4. Filtering / Scoring
5. Context Assembly
6. LLM Generation
7. Output Validation

Execution is strictly sequential unless a stage explicitly documents safe internal parallelism. No stage may hide fallback behavior or make decisions owned by another stage.

## Stage Definitions

### 1. Question Normalization
- Purpose: Convert the raw user question into a canonical, implementation-ready representation.
- Owned by: Normalizer
- Input: raw user question
- Output: `normalized_question`
- Allowed decisions:
  - normalize casing, whitespace, punctuation, and language-specific aliases
  - extract obvious structured entities when deterministic rules exist
  - reject malformed input with an explicit error state
- Forbidden behavior:
  - selecting a data source
  - retrieving data
  - injecting context
  - calling the LLM

### 2. Source Planning
- Purpose: Build a deterministic retrieval plan (or plans) from the normalized question.
- Owned by: Planner
- Input: `normalized_question`
- Output: `plan` or `[multiple plans]`
- Allowed decisions:
  - choose retrieval mode from explicit code rules (heuristics or LLM router)
  - emit one or more SQL plans if the question has multiple intents (e.g., "Fed rate AND USD/ILS rate" → 2 plans)
  - define SQL query template selection and parameter values
  - declare whether vector retrieval is disallowed or explicitly enabled later
  - define retrieval constraints such as row limits and expected fields
- Forbidden behavior:
  - executing retrieval
  - inferring missing facts with the LLM
  - using hidden fallbacks
  - mixing SQL and vector without an explicit plan field
  - assuming a single plan is always correct (multi-intent support is active)

### 3. Retrieval
- Purpose: Execute the plan(s) exactly as written. If multiple plans exist, execute them all (possibly in parallel) and merge results.
- Owned by: Retriever
- Input: `plan` or `[multiple plans]`
- Output: `retrieved_rows` (merged if multiple sources)
- Allowed decisions:
  - parameter binding and execution for approved read paths
  - deterministic error reporting when execution fails
  - returning empty results explicitly (NOT falling back to vector)
  - executing multiple SQL plans concurrently and merging their results
- Forbidden behavior:
  - changing the retrieval strategy
  - rewriting the plan
  - injecting undocumented sources
  - adding vector retrieval unless the plan explicitly allows it
  - silently falling back to a different source if the planned source returns empty

### 4. Filtering / Scoring
- Purpose: Reduce noise and keep only relevant, deterministic evidence.
- Owned by: Filter / Scorer
- Input: `retrieved_rows`, `plan`
- Output: `scored_results`
- Allowed decisions:
  - apply deterministic filters
  - rank or score rows using code-defined rules
  - drop irrelevant rows
- Forbidden behavior:
  - generating prose
  - retrieving more data
  - using the LLM to judge relevance

### 5. Context Assembly
- Purpose: Build the smallest structured context that the LLM needs to answer.
- Owned by: Context Assembler
- Input: `scored_results`, `normalized_question`, `plan`
- Output: `assembled_context`
- Allowed decisions:
  - format evidence into a strict schema
  - enforce context size limits
  - omit low-value or duplicate evidence
- Forbidden behavior:
  - adding hidden context
  - passing through raw noisy retrieval output without reduction
  - embedding business logic into prompt text

### 6. LLM Generation
- Purpose: Turn the assembled context into a user-facing answer.
- Owned by: LLM
- Input: `assembled_context`, prompt template, response instructions
- Output: `answer_draft`
- Allowed decisions:
  - synthesize and explain provided evidence
  - structure language for clarity
  - cite or restate deterministic outputs
- Forbidden behavior:
  - choosing data sources
  - computing financial values
  - inferring missing facts
  - overriding planner, retriever, scorer, or validator outputs

### 7. Output Validation
- Purpose: Verify the generated answer against deterministic constraints before return.
- Owned by: Validator
- Input: `answer_draft`, `assembled_context`, `plan`
- Output: `answer`
- Allowed decisions:
  - reject unsupported claims
  - enforce output schema and response rules
  - return explicit validation failure states
- Forbidden behavior:
  - re-planning retrieval
  - adding new evidence
  - silently correcting missing retrieval

## Strict Execution Flow
1. Receive raw question.
2. Normalize it into a structured canonical form.
3. Build a deterministic plan from code rules.
4. Execute the retrieval defined by the plan.
5. Filter and score retrieved evidence with deterministic rules.
6. Assemble a minimal context block.
7. Call the LLM for synthesis only.
8. Validate the draft answer.
9. Return the validated answer and full stage trace.

## Example Stage I/O

### Example 1: Single-Intent Query
Example user question:
`What was the latest USD/ILS exchange rate?`

### Stage 1: Question Normalization
Input:
```json
{
  "raw_question": "What was the latest USD/ILS exchange rate?"
}
```

Output:
```json
{
  "normalized_question": {
    "text": "latest usd ils exchange rate",
    "intent_hint": "fx_rate",
    "entities": {
      "base_currency": "USD",
      "quote_currency": "ILS"
    }
  }
}
```

### Stage 2: Source Planning
Output:
```json
{
  "plan": {
    "retrieval_mode": "sql",
    "query_template": "latest_fx_rate",
    "params": {
      "base_currency": "USD",
      "quote_currency": "ILS"
    },
    "row_limit": 1,
    "vector_enabled": false
  }
}
```

### Stage 3: Retrieval
Output:
```json
{
  "retrieved_rows": [
    {
      "base_currency": "USD",
      "quote_currency": "ILS",
      "rate": 3.71,
      "date": "2026-04-13"
    }
  ]
}
```

### Stage 4: Filtering / Scoring
Output:
```json
{
  "scored_results": [
    {
      "row_id": "fx:USD:ILS:2026-04-13",
      "score": 1.0,
      "reason": "exact pair match and latest row"
    }
  ]
}
```

### Stage 5: Context Assembly
Output:
```json
{
  "assembled_context": {
    "question_type": "fx_rate",
    "evidence": [
      {
        "date": "2026-04-13",
        "rate": 3.71,
        "base_currency": "USD",
        "quote_currency": "ILS"
      }
    ]
  }
}
```

### Stage 6: LLM Generation
Output:
```json
{
  "answer_draft": "The latest USD/ILS exchange rate in the retrieved data is 3.71 on 2026-04-13."
}
```

### Stage 7: Output Validation
Output:
```json
{
  "answer": "The latest USD/ILS exchange rate in the retrieved data is 3.71 on 2026-04-13."
}
```

### Example 2: Multi-Intent Query
Example user question:
`What is the Fed rate and USD/ILS exchange rate?`

### Stage 2: Source Planning (Multi-Intent)
Output (two plans):
```json
{
  "plans": [
    {
      "retrieval_mode": "sql",
      "query_template": "macro_series",
      "params": {
        "series_id": "FEDFUNDS"
      },
      "row_limit": 1,
      "vector_enabled": false
    },
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
  ]
}
```

### Stage 3: Retrieval (Concurrent Execution)
Both SQL queries execute, results are merged:
```json
{
  "retrieved_rows": [
    {
      "source_type": "sql",
      "series_id": "FEDFUNDS",
      "value": 4.50,
      "date": "2026-04-01"
    },
    {
      "source_type": "sql",
      "base_currency": "USD",
      "quote_currency": "ILS",
      "rate": 3.71,
      "date": "2026-04-13"
    }
  ]
}
```

### Stage 4–7: Assembly, LLM, Validation
The LLM synthesizes both data points in a single response:
"The current Fed funds rate is 4.50% (as of 2026-04-01), and the latest USD/ILS exchange rate is 3.71 (as of 2026-04-13)."

---

## Evaluation and Debugging Trace
Every query must emit a structured trace containing:
- `normalized_question`
- `plan` (single or multi-plan)
- `executed_query` (single or multiple queries)
- `retrieved_rows` (merged across all sources)
- `assembled_context`
- `final_prompt_size`
- `answer`

Debugging starts with retrieval correctness and context quality. Prompt changes are not the first response to a bad answer.

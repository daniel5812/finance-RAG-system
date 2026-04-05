# Fallback Logic

## Principle
Vector is always the last fallback. Structured SQL is preferred when intent can be detected.

## Level 1 — Per-Plan Fallback (normalization or validation failure)
Triggered when a single plan fails during the mapping pipeline.

- Failure at `_normalize_params` → reject plan → substitute `document_analysis`
- Failure at `_apply_fx_direction` (no currencies detected) → reject plan → substitute `document_analysis`
- Failure at `_validate_params` → reject plan → substitute `document_analysis`

Substituted query is produced by `_rewrite_for_semantic_search(question, context_hint)`:
- Strips English filler phrases
- Removes stop words
- Caps at 10 tokens
- Hebrew text passes through unchanged (preserved for semantic search)

## Level 2 — Structured Intent Detector (JSON parse failure)
Triggered when LLM output cannot be parsed as JSON, or all plans are rejected.

Function: `_detect_structured_intent(question: str) -> QueryPlan | None`

Detection order:
1. FX keywords (`שער`, `exchange`, `dollar`, `שקל`, etc.) → extract currencies → SQL fx_rate plan
2. Macro keywords (`אינפלציה`, `inflation`, `ריבית`, `gdp`, etc.) → match FRED ID → SQL macro_series plan
3. Portfolio keywords (`תיק`, `portfolio`, `holdings`, etc.) → vector plan (owner_id safety)
4. Price keywords (`מניה`, `price`, `stock`, etc.) → vector plan (ticker cannot be inferred from keywords)
5. No match → return `None`

## Level 3 — Raw Vector Fallback (last resort)
Only reached when `_detect_structured_intent` returns `None`.

```python
return MultiQueryPlan(plans=[QueryPlan(source="vector", query=question)])
```

Raw question passed as-is to Pinecone.

## Summary Table

| Condition | Result |
|---|---|
| Plan normalization fails | Per-plan `document_analysis` with rewritten query |
| Plan validation fails | Per-plan `document_analysis` with rewritten query |
| FX: no currencies detected | Per-plan `document_analysis` |
| JSON parse fails + FX keywords | SQL `fx_rate` plan with detected currencies |
| JSON parse fails + macro keywords | SQL `macro_series` plan with matched FRED ID |
| JSON parse fails + portfolio keywords | Vector plan |
| JSON parse fails + price keywords | Vector plan (no safe ticker inference) |
| No structured intent detected | Vector with raw question |

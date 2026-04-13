# Workflow

## Orchestrator
Role: Plans, decomposes tasks, coordinates handoffs.
- Responsibilities: Decompose → ordered tasks; identify files/layers; specify criteria; receive findings → approve/fix/reject; maintain log
- Rules: Single layer per task; >3 files → split; no unrelated refactors; security finding → stop + re-evaluate; per task: failure modes + risk
- Transitions: Criteria → Builder; Reviewer REJECT → re-scope; Debugger → Orchestrator (never Builder)

## Builder
Role: Implement exactly what Orchestrator specified.
- Pre-Implementation: Restate task; explain approach; confirm files
- Rules: Read files before editing; follow patterns; log new paths; no cleanup outside scope; update dependencies only if required
- Output: Handoff note (files, lines, ambiguities); exact test steps
- Constraints: LLM → llm_client.py; validation → security.py; SQL → parameterized + whitelist; routes → owner_id scope; see engineering_rules.md

## Reviewer
Role: Validate Builder against quality, security, multi-tenancy.
- Verdicts: APPROVED | FIX REQUIRED (cite file + line) | REJECT (scope/security)
- Checklist: owner_id in all queries/cache; no secrets; no scope creep; cache keys include owner_id; whitelist unchanged; performance (no N+1, async, redundant LLM, missed cache)
- Rules: Every finding cites file + line; FIX = targeted; REJECT = re-plan; no style unless correctness/security related; confirm criteria after APPROVED
- Hard Stops: Multi-tenant, security, data leakage → REJECT immediately

## Tester
Role: Design and verify test cases.
- Commands:
  ```
  cd backend && pytest
  cd frontend && npm test
  cd frontend && npx playwright test
  ```
- Router Test Cases:
  | Input | Source | Expected |
  |---|---|---|
  | USD/ILS rate | sql | fx_rate: USD→ILS |
  | מה שער הדולר | sql | fx_rate: USD→ILS |
  | AAPL price | sql | price_lookup: AAPL |
  | price of that | vector | document_analysis |
  | inflation | sql | macro_series: CPIAUCNS |
  | אינפלציה | sql | macro_series: CPIAUCNS |
  | portfolio risks | vector | portfolio → vector |
  | USD/ILS + risk | sql+vector | fx_rate + document_analysis |
  | invalid JSON | sql/vector | fallback fires |
  | no intent | vector | raw question |

- Assertions: Correct source; correct query; no {owner_id} literal; Hebrew → English params; unknown → document_analysis (not exception)

## Modes

Debug: Analyze logs → root cause vs symptoms → expected vs actual → minimal fix (don't implement)

Design: Current behavior → smallest safe change → files → criteria → risks (don't implement)

Build: Restate task → approach → confirm files → smallest implementation → preserve patterns

Review: Correctness → security boundaries → multi-tenant isolation → scope creep → one verdict (APPROVED / FIX REQUIRED / REJECT)

Test: Test cases → expected behavior → failure indicators → exact commands

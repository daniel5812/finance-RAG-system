# CLAUDE SYSTEM ENTRY

This project uses a modular context system.
Load ONLY relevant files based on the task.

## System Overview

**Hybrid Financial RAG**: SQL (structured facts) + vector search (documents) + external data sources + user profiles + caching layer. Deterministic intelligence layer remains core; LLM used for synthesis only.

## Context Map

Core:
- [claude/core/stack.md](claude/core/stack.md)
- [claude/core/architecture.md](claude/core/architecture.md)
- [claude/core/schema.md](claude/core/schema.md)
- [claude/core/intelligence.md](claude/core/intelligence.md)

Logic:
- [claude/logic/planner.md](claude/logic/planner.md)
- [claude/logic/fallback.md](claude/logic/fallback.md)
- [claude/logic/normalization.md](claude/logic/normalization.md)

Agents:
- [claude/agents/orchestrator.md](claude/agents/orchestrator.md)
- [claude/agents/builder.md](claude/agents/builder.md)
- [claude/agents/reviewer.md](claude/agents/reviewer.md)
- [claude/agents/tester.md](claude/agents/tester.md)

Rules:
- [claude/rules/coding.md](claude/rules/coding.md)
- [claude/rules/safety.md](claude/rules/safety.md)
- [claude/rules/testing.md](claude/rules/testing.md)
- [claude/rules/invariants.md](claude/rules/invariants.md)

Debug:
- [claude/debug/known_issues.md](claude/debug/known_issues.md)
- [claude/debug/history.md](claude/debug/history.md)
- [claude/debug/next_steps.md](claude/debug/next_steps.md)

Full index: [claude/CLAUDE.md](claude/CLAUDE.md)

## Task → Files to Load

| Task | Load |
|---|---|
| Retrieval / source selection | system_behavior.md + schema.md |
| Personalization / user profiles | system_behavior.md |
| SQL queries / data | project.md + schema.md |
| Security / rules | engineering_rules.md |
| Testing | workflow.md |
| New feature | stack.md + architecture.md + engineering_rules.md |
| Bug investigation | architecture.md + known_issues.md + intelligence.md |

## Rules

- Do NOT load all files by default
- Use minimal context required
- Prefer targeted file loading
- If unsure → load [claude/debug/known_issues.md](claude/debug/known_issues.md) first

## Working Method (Agent-Based)

Always operate using one skill at a time:

- analyze_request
- design_change
- implement_change
- review_change
- debug_issue
- test_design
- rag_reasoning_check

Rules:
- Do NOT mix skills in one response
- Follow sequence: analyze → design → build → review → test
- Keep changes minimal and scoped

## Source Selection Guidelines

- **SQL**: structured facts, account data, transactions
- **Vector**: documents, knowledge base, similar queries
- **Hybrid**: multi-source analysis, cross-reference questions

## User Profile Rules

- Profile is **advisory only**
- Never override retrieved data with profile
- Use for context, filtering, and personalization

## Caching Awareness

- Reuse cached results when available
- Always respect `owner_id` isolation
- Invalidate on data mutation
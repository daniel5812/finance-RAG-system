# CLAUDE SYSTEM ENTRY

This project uses a modular context system.
Load ONLY relevant files based on the task.

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
| New feature | stack.md + architecture.md + coding.md + safety.md |
| Router / planner work | planner.md + fallback.md + normalization.md |
| Intelligence layer work | intelligence.md + invariants.md + architecture.md |
| Bug investigation | architecture.md + known_issues.md + intelligence.md |
| Writing tests | tester.md + testing.md + planner.md |
| Code review | reviewer.md + safety.md + coding.md + invariants.md |
| Understanding DB | schema.md + architecture.md |

## Rules

- Do NOT load all files by default
- Use minimal context required
- Prefer targeted file loading
- If unsure → load [claude/debug/known_issues.md](claude/debug/known_issues.md) first

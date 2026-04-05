# CLAUDE SYSTEM ENTRY

This project uses a modular context system.
Load ONLY the files relevant to your current task.

## Context Map

### Project
- [claude/project/overview.md](project/overview.md) — features, running instructions, env vars
- [claude/project/architecture.md](project/architecture.md) — system diagram, layers, request flow
- [claude/project/data_sources.md](project/data_sources.md) — DB schema, tables, SQL whitelist

### System
- [claude/system/planner.md](system/planner.md) — intent types, SQL templates, pipeline (COMPLETED)
- [claude/system/router.md](system/router.md) — router.py contract, what it does and does not do
- [claude/system/fallback_logic.md](system/fallback_logic.md) — 3-level fallback chain
- [claude/system/normalization.md](system/normalization.md) — currency aliases, FRED mapping, Hebrew support

### Agents
- [claude/agents/orchestrator.md](agents/orchestrator.md) — planning, decomposition, handoff rules
- [claude/agents/builder.md](agents/builder.md) — implementation rules, pre-implementation checklist
- [claude/agents/reviewer.md](agents/reviewer.md) — review checklist, verdicts, hard stops
- [claude/agents/tester.md](agents/tester.md) — test cases, test commands, coverage requirements

### Progress
- [claude/progress/current_state.md](progress/current_state.md) — what is working now
- [claude/progress/completed_steps.md](progress/completed_steps.md) — planner refactor history
- [claude/progress/known_issues.md](progress/known_issues.md) — intentional limitations and constraints

### Guidelines
- [claude/guidelines/coding_rules.md](guidelines/coding_rules.md) — global constraints, production principles
- [claude/guidelines/safety_rules.md](guidelines/safety_rules.md) — multi-tenancy, security, auth rules
- [claude/guidelines/testing_strategy.md](guidelines/testing_strategy.md) — test layers, coverage requirements

## Task → Files to Load

| Task | Load |
|---|---|
| New feature | overview.md + architecture.md + coding_rules.md + safety_rules.md |
| Router / planner work | planner.md + router.md + fallback_logic.md + normalization.md |
| Bug investigation | architecture.md + current_state.md + known_issues.md |
| Writing tests | tester.md + testing_strategy.md + planner.md |
| Code review | reviewer.md + safety_rules.md + coding_rules.md |
| Understanding DB | data_sources.md + architecture.md |

## Rules
- Do NOT load all files by default
- Use minimal context required for the task
- Prefer targeted file loading
- If unsure which files are needed — load `current_state.md` first

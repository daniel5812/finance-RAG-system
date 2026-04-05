# CLAUDE SYSTEM ENTRY

This project uses a modular context system.
Load ONLY relevant files based on the task.

## Context Map

Project:
- [claude/project/overview.md](claude/project/overview.md)
- [claude/project/architecture.md](claude/project/architecture.md)
- [claude/project/data_sources.md](claude/project/data_sources.md)

System:
- [claude/system/router.md](claude/system/router.md)
- [claude/system/planner.md](claude/system/planner.md)
- [claude/system/fallback_logic.md](claude/system/fallback_logic.md)
- [claude/system/normalization.md](claude/system/normalization.md)

Agents:
- [claude/agents/orchestrator.md](claude/agents/orchestrator.md)
- [claude/agents/builder.md](claude/agents/builder.md)
- [claude/agents/reviewer.md](claude/agents/reviewer.md)
- [claude/agents/tester.md](claude/agents/tester.md)

Progress:
- [claude/progress/current_state.md](claude/progress/current_state.md)
- [claude/progress/completed_steps.md](claude/progress/completed_steps.md)
- [claude/progress/known_issues.md](claude/progress/known_issues.md)

Guidelines:
- [claude/guidelines/coding_rules.md](claude/guidelines/coding_rules.md)
- [claude/guidelines/safety_rules.md](claude/guidelines/safety_rules.md)
- [claude/guidelines/testing_strategy.md](claude/guidelines/testing_strategy.md)

Full index: [claude/CLAUDE.md](claude/CLAUDE.md)

## Rules

- Do NOT load all files by default
- Use minimal context required
- Prefer targeted file loading
- If unsure → load [claude/progress/current_state.md](claude/progress/current_state.md) first

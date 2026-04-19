# CLAUDE SYSTEM ENTRY

This project uses a modular context system.
Load only the files relevant to the task.

## Context Map

Core:
- [claude/project.md](claude/project.md)
- [claude/system_behavior.md](claude/system_behavior.md)
- [claude/engineering_rules.md](claude/engineering_rules.md)
- [claude/workflow.md](claude/workflow.md)
- [claude/state.md](claude/state.md)

## Task -> Files To Load

| Task | Load |
|---|---|
| New feature | `claude/project.md` + `claude/engineering_rules.md` |
| LLM pipeline work | `claude/workflow.md` + `claude/system_behavior.md` + `claude/engineering_rules.md` |
| Retrieval work | `claude/system_behavior.md` + `claude/engineering_rules.md` |
| Context assembly work | `claude/workflow.md` + `claude/engineering_rules.md` |
| Bug investigation | `claude/system_behavior.md` + `claude/state.md` |
| Writing tests | `claude/workflow.md` + `claude/system_behavior.md` |
| Code review | `claude/engineering_rules.md` + `claude/workflow.md` |
| Understanding architecture | `claude/project.md` + `claude/system_behavior.md` |

## LLM V2 Instructions
- Always preserve pipeline boundaries
- Never introduce implicit logic
- Always log intermediate outputs
- Do not modify LLM behavior before verifying retrieval and context assembly
- Treat the LLM as a synthesis-only component
- Keep all planning, retrieval, filtering, context selection, and validation in deterministic code

## Rules
- Do not load all files by default
- Prefer the minimum context needed
- When working on LLM behavior, start from retrieval and context assembly, not prompt changes
- If the current code conflicts with the v2 docs, treat the docs as the target architecture for new implementation work

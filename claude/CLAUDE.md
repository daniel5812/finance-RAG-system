# CLAUDE SYSTEM ENTRY

Load only the files relevant to your task.

## Task -> Files To Load

| Task | Load |
|---|---|
| New feature | `project.md` + `engineering_rules.md` |
| LLM pipeline work | `workflow.md` + `system_behavior.md` + `engineering_rules.md` |
| Retrieval work | `system_behavior.md` + `engineering_rules.md` |
| Context assembly work | `workflow.md` + `engineering_rules.md` |
| Bug investigation | `system_behavior.md` + `state.md` |
| Writing tests | `workflow.md` + `system_behavior.md` |
| Code review | `engineering_rules.md` + `workflow.md` |
| Understanding architecture | `project.md` + `system_behavior.md` |

## LLM V2 Instructions
- Always respect pipeline separation
- Never introduce implicit logic
- Always log intermediate outputs
- Do not modify LLM behavior before verifying retrieval and context assembly
- Keep the LLM limited to synthesis only

## Full Reference
- [project.md](project.md)
- [system_behavior.md](system_behavior.md)
- [engineering_rules.md](engineering_rules.md)
- [workflow.md](workflow.md)
- [state.md](state.md)

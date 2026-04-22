"""
Hybrid Retrieval Executor.

Runs a HybridQueryPlan step-by-step and returns a list of StepResult.

- Steps sorted by priority (ascending), then processed in declaration order.
- SQL steps: delegate to sql_runner if provided, else return [].
- VECTOR / NO_MATCH steps: delegate to vector_runner if provided, else return [].
- Single step failure never aborts the full execution.
- owner_id is always enforced on vector_filter before dispatch.

No LLM. No Fusion. Sync-safe async interface.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from core.logger import get_logger
from rag.schemas import HybridQueryPlan, PlanStep, StepResult, VectorFilter

logger = get_logger(__name__)

# ── Type aliases for injectable runners ──────────────────────────────────────

# sql_runner(template_id, parameters) → list[dict]
SqlRunner = Callable[[str, dict], Awaitable[list[dict]]]

# vector_runner(vector_filter) → list[dict]
VectorRunner = Callable[[VectorFilter], Awaitable[list[dict]]]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _enforce_owner(step: PlanStep, owner_id: str) -> VectorFilter:
    """Return vector_filter with owner_id guaranteed."""
    vf = step.vector_filter or VectorFilter(owner_id=owner_id)
    if vf.owner_id != owner_id:
        logger.warning(
            f"executor: owner_id mismatch on step {step.step_id} — overriding"
        )
        vf = vf.model_copy(update={"owner_id": owner_id})
    return vf


def _make_result(step: PlanStep, data: list, error: Optional[str] = None) -> StepResult:
    if error:
        status = "error"
    elif data:
        status = "ok"
    else:
        status = "empty"
    return StepResult(
        step_id=step.step_id,
        source_type=step.source_type,
        intent_type=step.intent_type,
        data=data,
        status=status,
        error_message=error,
    )


# ── Per-step dispatch ─────────────────────────────────────────────────────────

async def _run_step(
    step: PlanStep,
    owner_id: str,
    sql_runner: Optional[SqlRunner],
    vector_runner: Optional[VectorRunner],
) -> StepResult:
    try:
        if step.source_type == "SQL":
            if not step.sql_template_id:
                return _make_result(step, [], error="SQL step missing sql_template_id")
            if sql_runner:
                data = await sql_runner(step.sql_template_id, step.parameters)
            else:
                data = []
            return _make_result(step, data)

        else:  # VECTOR or NO_MATCH
            vf = _enforce_owner(step, owner_id)
            if vector_runner:
                data = await vector_runner(vf)
            else:
                data = []
            return _make_result(step, data)

    except Exception as exc:
        logger.error(
            f"executor: step {step.step_id} ({step.intent_type}) failed: {exc}"
        )
        return _make_result(step, [], error=str(exc))


# ── Public entry point ────────────────────────────────────────────────────────

async def execute_plan(
    plan: HybridQueryPlan,
    owner_id: str,
    sql_runner: Optional[SqlRunner] = None,
    vector_runner: Optional[VectorRunner] = None,
) -> list[StepResult]:
    """
    Execute a HybridQueryPlan and return one StepResult per step.

    Args:
        plan:           Output of planner.build_plan().
        owner_id:       Tenant identifier — enforced on every vector_filter.
        sql_runner:     Async callable (template_id, params) → list[dict].
                        Pass None to get empty placeholder data.
        vector_runner:  Async callable (VectorFilter) → list[dict].
                        Pass None to get empty placeholder data.

    Returns:
        List[StepResult] in execution order.
    """
    sorted_steps = sorted(plan.steps, key=lambda s: s.priority)
    results: list[StepResult] = []

    for step in sorted_steps:
        result = await _run_step(step, owner_id, sql_runner, vector_runner)
        results.append(result)
        logger.info(
            f"executor: step {step.step_id} [{step.intent_type}] → {result.status}"
        )

    return results

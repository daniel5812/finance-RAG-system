"""
Hybrid Retrieval Fusion.

Merges a list of StepResult into one FusionResult.

Rules:
- SQL ok  → structured_data[intent_type] = data  (no recomputation)
- VECTOR / NO_MATCH ok → supporting_context (appended)
- empty / error → missing_data_notes
- user_profile → advisory_context only (never overrides data)
- always returns a valid FusionResult even when all steps failed
"""
from __future__ import annotations

from typing import Optional

from rag.schemas import FusionResult, HybridQueryPlan, RetrievalSummary, StepResult


def fuse(
    plan: HybridQueryPlan,
    results: list[StepResult],
    user_profile: Optional[dict] = None,
) -> FusionResult:
    """
    Merge Executor output into a single FusionResult.

    Args:
        plan:         HybridQueryPlan from planner.build_plan().
        results:      List[StepResult] from executor.execute_plan().
        user_profile: Optional dict with risk_tolerance, experience_level, etc.
                      Stored as advisory_context only — never modifies data.

    Returns:
        FusionResult with strict SQL / VECTOR separation.
    """
    structured_data: dict = {}
    supporting_context: list = []
    missing_data_notes: list[str] = []

    for r in results:
        # Include empty SQL results in structured_data so they appear in context
        if r.source_type == "SQL" and r.status in ("ok", "empty"):
            structured_data[r.intent_type] = r.data
        elif r.status == "ok" and r.source_type in ("VECTOR", "NO_MATCH"):
            supporting_context.extend(r.data)
        elif r.status == "error":
            note = f"{r.intent_type} ({r.source_type}): {r.status}"
            if r.error_message:
                note += f" — {r.error_message}"
            missing_data_notes.append(note)

    # Consider planned steps in summary
    plan_has_sql = any(s.source_type == "SQL" for s in plan.steps)
    plan_has_vector = any(s.source_type in ("VECTOR", "NO_MATCH") for s in plan.steps)

    results_has_sql = any(r.source_type == "SQL" and r.status in ("ok", "empty") for r in results)
    results_has_vector = any(r.source_type in ("VECTOR", "NO_MATCH") and r.status == "ok" for r in results)

    # Summary includes both planned intent and actual retrieval
    has_sql = plan_has_sql or results_has_sql
    has_vector = plan_has_vector or results_has_vector

    # Partial if any step failed or expected planned steps are missing from results
    is_partial = bool(missing_data_notes) or (len(results) < len(plan.steps))

    advisory_context: Optional[dict] = None
    if user_profile:
        advisory_context = {k: v for k, v in user_profile.items() if v is not None}
        if not advisory_context:
            advisory_context = None

    return FusionResult(
        structured_data=structured_data,
        supporting_context=supporting_context,
        missing_data_notes=missing_data_notes,
        retrieval_summary=RetrievalSummary(
            has_sql=has_sql,
            has_vector=has_vector,
            is_partial=is_partial,
            advisory_context=advisory_context,
        ),
    )

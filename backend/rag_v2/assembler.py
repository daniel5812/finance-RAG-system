from __future__ import annotations

from typing import Any, Dict, List

from rag_v2.schemas import AssembledContextV2


def assemble_context(rows: List[Dict[str, Any]], failed_intents: List[str] | None = None) -> AssembledContextV2:
    limited_rows = rows[:5]
    lines: list[str] = []

    # Add successful rows with clear formatting
    for row in limited_rows:
        parts = [f"{key}: {value}" for key, value in row.items()]
        lines.append("- " + ", ".join(parts))

    # Add explicit notes for failed queries
    if failed_intents:
        if lines:  # Only add separator if we have successful rows
            lines.append("")
        lines.append("MISSING DATA:")
        for intent in failed_intents:
            lines.append(f"- {intent}: No data available for this query")

    if not lines:
        text = "No data available. All queries returned no results."
    else:
        text = "\n".join(lines)

    return AssembledContextV2(
        text=text,
        row_count=len(limited_rows),
        truncated=len(rows) > 5,
    )

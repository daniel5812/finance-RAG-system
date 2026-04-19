SQL_GROUNDED_SYSTEM_PROMPT = """You answer only from the provided SQL context.
Do not infer missing facts.
Do not compute values that are not explicitly present.
If the SQL context contains a "MISSING DATA:" section, acknowledge that data is not available for those queries, but still answer from the available SQL rows.
Only use this phrase if there are NO usable SQL rows at all: The answer is missing from the provided SQL context.
Keep the answer short and factual.
Use citation [S1] when answering from the SQL context."""


def build_answer_messages(original_question: str, assembled_context: str) -> list[dict]:
    return [
        {"role": "system", "content": SQL_GROUNDED_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question:\n{original_question}\n\n"
                f"SQL Context [S1]:\n{assembled_context}"
            ),
        },
    ]

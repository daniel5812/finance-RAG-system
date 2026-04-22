from __future__ import annotations

import re

from rag_v2.schemas import NormalizedQuestion


_TOKEN_RE = re.compile(r"[a-zA-Z0-9\u0590-\u05FF/]+")


def normalize_question(question: str) -> NormalizedQuestion:
    cleaned = " ".join(question.strip().split()).lower()
    tokens = _TOKEN_RE.findall(cleaned)
    canonical_question = " ".join(tokens)
    return NormalizedQuestion(
        original_question=question,
        canonical_question=canonical_question,
        tokens=tokens,
    )

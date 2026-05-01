"""
core/prompt_assembler.py — PromptAssembler (Phase 3A).

Active only when PROMPT_ASSEMBLY_V2=true. Sync path only.
Streaming path unchanged. Legacy prompt path fully preserved.

Phase 3A adds deterministic citation ID assignment:
- [S1], [S2], ... for structured SQL facts (separate counter)
- [D1], [D2], ... for document/vector chunks (separate counter)
Callers may pass raw sql_contexts / doc_contexts lists; PromptAssembler
assigns stable IDs internally. The legacy context_block param still works.
"""
from __future__ import annotations

from typing import Optional

from core.prompts import FACTUAL_HOLDINGS_PROMPT, NATURAL_ADVISORY_PROMPT

PROMPT_VERSION = "prompt_assembly_v2_phase3a"


class PromptAssembler:
    """
    Builds [system_msg, user_msg] for the sync chat path.

    Caller (chat_service) inserts profile messages and conversation
    history between system_msg and user_msg, unchanged from legacy.
    """

    PROMPT_VERSION = PROMPT_VERSION

    @staticmethod
    def _select_prompt(mode_hint: str) -> str:
        return FACTUAL_HOLDINGS_PROMPT if mode_hint == "factual" else NATURAL_ADVISORY_PROMPT

    @staticmethod
    def _context_flags(
        has_context: bool,
        has_any_docs: bool,
        has_portfolio: bool,
        is_new_session: bool,
    ) -> str:
        return (
            f"CONTEXT_FLAGS:\n"
            f"HAS_CONTEXT={has_context}\n"
            f"HAS_DOCUMENTS={has_any_docs}\n"
            f"HAS_PORTFOLIO={has_portfolio}\n"
            f"IS_NEW_SESSION={is_new_session}\n\n"
        )

    # ── Citation assignment helpers (Phase 3A) ────────────────────────────────

    @staticmethod
    def _assign_sql_citations(items: list[str]) -> list[tuple[str, str]]:
        """Return [(tag, text), ...] with independent [S1], [S2], ... counter."""
        return [(f"[S{i + 1}]", text) for i, text in enumerate(items)]

    @staticmethod
    def _assign_doc_citations(items: list[str]) -> list[tuple[str, str]]:
        """Return [(tag, text), ...] with independent [D1], [D2], ... counter."""
        return [(f"[D{i + 1}]", text) for i, text in enumerate(items)]

    @staticmethod
    def _render_cited_context(
        sql_contexts: list[str],
        doc_contexts: list[str],
    ) -> str:
        """
        Build a labelled context block from separate SQL and doc lists.

        SQL and document counters are independent: [S1],[S2]... and
        [D1],[D2]... never share a numbering sequence, so doc IDs do not
        depend on how many SQL facts precede them.  Empty sections are
        omitted.  Ordering is stable (SQL first, then docs).
        """
        parts: list[str] = []
        for tag, text in PromptAssembler._assign_sql_citations(sql_contexts):
            parts.append(f"Source {tag}: {text}")
        for tag, text in PromptAssembler._assign_doc_citations(doc_contexts):
            parts.append(f"Source {tag}: {text}")
        return "\n---\n".join(parts)

    # ── Context envelope ──────────────────────────────────────────────────────

    @staticmethod
    def _context_envelope(
        mode_hint: str,
        intelligence_block: str,
        conversation_context: str,
        context_block: str,
    ) -> str:
        parts = ["<context>", f"  <mode>{mode_hint}</mode>"]
        if intelligence_block:
            parts.append(
                f"  <intelligence_context>\n{intelligence_block}\n  </intelligence_context>"
            )
        if conversation_context:
            parts.append(
                f"  <conversation_context>\n{conversation_context}\n  </conversation_context>"
            )
        if context_block:
            parts.append(
                f"  <retrieved_context>\n{context_block}\n  </retrieved_context>"
            )
        parts.append("</context>")
        return "\n".join(parts)

    @classmethod
    def build(
        cls,
        *,
        mode_hint: str = "advisory",
        context_block: str = "",
        sql_contexts: Optional[list[str]] = None,
        doc_contexts: Optional[list[str]] = None,
        intelligence_block: str = "",
        conversation_context: str = "",
        question: str,
        intent: str,
        portfolio_ctx: Optional[str] = None,
        has_context: bool = False,
        has_any_docs: bool = False,
        has_portfolio: bool = False,
        is_new_session: bool = True,
    ) -> list[dict]:
        """
        Returns [system_msg, user_msg].

        Caller inserts profile messages and history between them.

        When sql_contexts or doc_contexts are provided, citation IDs are
        assigned inside PromptAssembler with independent [S#] / [D#]
        counters, overriding context_block.  Passing neither preserves
        existing behaviour (context_block used as-is).
        """
        if sql_contexts is not None or doc_contexts is not None:
            context_block = cls._render_cited_context(
                sql_contexts or [], doc_contexts or []
            )

        system_content = cls._context_flags(
            has_context, has_any_docs, has_portfolio, is_new_session
        ) + cls._select_prompt(mode_hint)

        envelope = cls._context_envelope(
            mode_hint, intelligence_block, conversation_context, context_block
        )
        user_parts: list[str] = [envelope]
        if portfolio_ctx:
            user_parts.append(portfolio_ctx)
        user_parts.append(f"[Intent: {intent}]")
        user_parts.append(f"<user_query>\n{question}\n</user_query>")
        user_content = "\n\n".join(user_parts)

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

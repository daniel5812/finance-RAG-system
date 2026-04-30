"""
core/prompt_assembler.py — Minimal PromptAssembler (Phase 1B).

Active only when PROMPT_ASSEMBLY_V2=true. Sync path only.
Streaming path unchanged. Legacy prompt path fully preserved.
"""
from __future__ import annotations

from typing import Optional

from core.prompts import FACTUAL_HOLDINGS_PROMPT, NATURAL_ADVISORY_PROMPT

PROMPT_VERSION = "prompt_assembly_v2_phase1b"


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
        """
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

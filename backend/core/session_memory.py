"""
core/session_memory.py — Conversation Memory Storage & Summarization

Redis-backed memory system:
- Storage: Redis key session_memory:{owner_id}:{session_id}, TTL 24h
- Summary: ~200 tokens max, sliding window, pure function builder
- Content: user intent, topics, thread (NOT numbers, portfolio values, citations)
"""

import json
from core import connections
from core.logger import get_logger

logger = get_logger(__name__)

# ── TTL for session memory (24 hours in seconds) ──
SESSION_MEMORY_TTL = 86400


class SessionMemoryStore:
    """Redis-backed conversation memory storage, scoped by owner_id + session_id."""

    @staticmethod
    async def get(owner_id: str | None, session_id: str | None) -> str | None:
        """Load stored summary from Redis. Returns string or None."""
        if not owner_id or not session_id:
            return None

        key = f"session_memory:{owner_id}:{session_id}"
        try:
            raw = await connections.redis_client.get(key)
            if raw is None:
                logger.debug(f"session_memory:get_miss key={key}")
                return None
            result = json.loads(raw)
            logger.debug(f"session_memory:get_hit key={key} has_result={bool(result)}")
            return result
        except Exception as e:
            logger.warning(f"Failed to load session memory from Redis (key={key}): {e}")
            return None

    @staticmethod
    async def set(owner_id: str | None, session_id: str | None, summary: str) -> None:
        """Persist summary to Redis, scoped by owner_id to prevent cross-tenant writes."""
        if not owner_id or not session_id:
            return

        key = f"session_memory:{owner_id}:{session_id}"
        try:
            await connections.redis_client.set(
                key,
                json.dumps(summary),
                ex=SESSION_MEMORY_TTL
            )
            logger.info(json.dumps({"event": "session_memory_stored", "session_id": session_id, "key": key, "has_summary": bool(summary)}))
        except Exception as e:
            logger.warning(f"Failed to store session memory in Redis (key={key}): {e}")


class SummaryBuilder:
    """Pure function to build conversation summaries with strict content constraints."""

    # Maximum tokens: ~200 = ~800 chars as rough approximation
    MAX_CHARS = 800

    @staticmethod
    def build(history: list, max_chars: int = MAX_CHARS) -> str | None:
        """
        Build a summary from conversation history.

        Enforces:
        - No numerical values, portfolio values, raw SQL/vector data
        - No citations, chunk text, or full LLM responses
        - Focus: user intent, topics discussed, thread

        Returns: summary string or None if history too short
        """
        if not history or len(history) < 3:
            return None

        # Extract intent patterns from user messages
        user_msgs = [m for m in history if m.role == "user"]
        if not user_msgs:
            return None

        # Collect topics from all user messages (keywords only, no values)
        topics = set()
        for msg in user_msgs:
            topics.update(SummaryBuilder._extract_topics(msg.content))

        # Infer thread: what's the conversation about?
        thread = SummaryBuilder._infer_thread(user_msgs)

        # Paraphrase user intent from latest questions
        intent = SummaryBuilder._extract_intent(user_msgs[-2:])

        # Build summary
        parts = []
        if intent:
            parts.append(f"User intent: {intent}")
        if topics:
            topics_str = ", ".join(sorted(topics)[:5])  # limit to top 5 topics
            parts.append(f"Topics: {topics_str}")
        if thread:
            parts.append(f"Thread: {thread}")

        summary = " | ".join(parts)

        # Enforce max length
        if len(summary) > max_chars:
            summary = summary[:max_chars].rsplit(" ", 1)[0] + "..."

        return summary if summary else None

    @staticmethod
    def _extract_topics(text: str) -> set:
        """Extract financial topics from text (case-insensitive keywords)."""
        topics_keywords = {
            # Asset types
            "stock": ("stocks", "stock", "equity", "equities", "ticker"),
            "bond": ("bond", "bonds", "fixed income", "credit"),
            "etf": ("etf", "etfs", "fund"),
            "crypto": ("crypto", "bitcoin", "ethereum", "digital asset"),
            "fx": ("currency", "fx", "foreign exchange", "usd", "eur", "gbp"),
            # Macro / strategy
            "macro": ("macro", "gdp", "inflation", "cpi", "fed", "rate", "recession"),
            "diversification": ("diversification", "allocation", "rebalance", "correlation"),
            "risk": ("risk", "volatility", "vix", "drawdown", "concentration"),
            "performance": ("performance", "return", "yield", "exposure"),
            # Portfolio concepts
            "portfolio": ("portfolio", "holdings", "positions", "account"),
            "sector": ("sector", "tech", "energy", "healthcare", "financials", "utilities"),
        }

        text_lower = text.lower()
        found = set()

        for topic, keywords in topics_keywords.items():
            for kw in keywords:
                if kw in text_lower:
                    found.add(topic)
                    break

        return found

    @staticmethod
    def _infer_thread(user_msgs: list) -> str | None:
        """Infer high-level conversation thread from user messages."""
        if not user_msgs:
            return None

        text = " ".join([m.content.lower() for m in user_msgs[-3:]])

        # Simple heuristics for thread type
        if any(kw in text for kw in ["should i", "should we", "advice", "recommend", "strategy"]):
            return "advisory/strategy discussion"
        elif any(kw in text for kw in ["why", "how", "explain", "analyze", "compare"]):
            return "analytical inquiry"
        elif any(kw in text for kw in ["what if", "assume", "scenario", "suppose"]):
            return "scenario analysis"
        elif any(kw in text for kw in ["price", "what's the", "what is", "tell me"]):
            return "factual lookup"

        return None

    @staticmethod
    def _extract_intent(user_msgs: list) -> str | None:
        """Paraphrase intent from recent user messages (no values)."""
        if not user_msgs:
            return None

        # Take last 1-2 messages to infer intent
        recent = " ".join([m.content for m in user_msgs[-2:]])

        # Simple length-based truncation to keep only intent, not full question
        if len(recent) > 150:
            return recent[:150].rsplit(" ", 1)[0] + "..."

        return recent if len(recent) > 20 else None

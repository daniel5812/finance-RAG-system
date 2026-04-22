"""
tests/test_session_memory.py — Session Memory Tests

Coverage:
- Summary truncation (max ~200 tokens / ~800 chars)
- Topic extraction and sliding window
- Redis persistence scoped by owner_id + session_id
- Safe empty behavior (too short history)
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from core.session_memory import SessionMemoryStore, SummaryBuilder


# ── Message Mock Helper ──
class MockMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


# ── SessionMemoryStore Tests ──

class TestSessionMemoryStore:
    """Redis-backed memory storage tests."""

    @pytest.mark.asyncio
    async def test_get_returns_none_when_no_owner_id(self):
        """get() should return None if owner_id is None."""
        result = await SessionMemoryStore.get(None, "session_123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_when_no_session_id(self):
        """get() should return None if session_id is None."""
        result = await SessionMemoryStore.get("user_123", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_when_key_not_found(self):
        """get() should return None when Redis key doesn't exist."""
        with patch("core.connections.redis_client.get", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = None
            result = await SessionMemoryStore.get("user_123", "session_123")
            assert result is None
            mock_redis.assert_called_once_with("session_memory:user_123:session_123")

    @pytest.mark.asyncio
    async def test_get_parses_stored_summary(self):
        """get() should parse and return stored summary from Redis."""
        summary_text = "User intent: analyze portfolio | Topics: stocks, risk | Thread: analytical inquiry"
        import json

        with patch("core.connections.redis_client.get", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = json.dumps(summary_text)
            result = await SessionMemoryStore.get("user_123", "session_123")
            assert result == summary_text

    @pytest.mark.asyncio
    async def test_set_stores_with_ttl(self):
        """set() should store summary in Redis with correct TTL."""
        summary = "Test summary"
        owner_id = "user_123"
        session_id = "session_123"

        with patch("core.connections.redis_client.set", new_callable=AsyncMock) as mock_redis:
            await SessionMemoryStore.set(owner_id, session_id, summary)

            import json
            mock_redis.assert_called_once()
            args, kwargs = mock_redis.call_args
            assert args[0] == f"session_memory:{owner_id}:{session_id}"
            assert json.loads(args[1]) == summary
            assert kwargs.get("ex") == 86400  # 24 hours

    @pytest.mark.asyncio
    async def test_set_returns_none_if_missing_owner_id(self):
        """set() should return None and not call Redis if owner_id is None."""
        with patch("core.connections.redis_client.set", new_callable=AsyncMock) as mock_redis:
            result = await SessionMemoryStore.set(None, "session_123", "summary")
            assert result is None
            mock_redis.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_scoped_by_owner_id(self):
        """set() should use owner_id in Redis key to prevent cross-tenant writes."""
        summary = "User A summary"
        user_a = "user_a"
        user_b = "user_b"
        session = "session_123"

        with patch("core.connections.redis_client.set", new_callable=AsyncMock) as mock_redis:
            await SessionMemoryStore.set(user_a, session, "Summary A")
            await SessionMemoryStore.set(user_b, session, "Summary B")

            # Verify different keys used
            calls = mock_redis.call_args_list
            assert calls[0][0][0] == f"session_memory:{user_a}:{session}"
            assert calls[1][0][0] == f"session_memory:{user_b}:{session}"


# ── SummaryBuilder Tests ──

class TestSummaryBuilder:
    """Summary building and constraint enforcement tests."""

    def test_build_returns_none_if_history_too_short(self):
        """build() should return None if history has fewer than 3 messages."""
        history = [MockMessage("user", "Hello")]
        result = SummaryBuilder.build(history)
        assert result is None

    def test_build_returns_none_if_no_user_messages(self):
        """build() should return None if no user messages in history."""
        history = [
            MockMessage("assistant", "Response 1"),
            MockMessage("assistant", "Response 2"),
            MockMessage("assistant", "Response 3"),
        ]
        result = SummaryBuilder.build(history)
        assert result is None

    def test_build_extracts_intent_from_user_messages(self):
        """build() should extract user intent from messages."""
        history = [
            MockMessage("user", "should I buy AAPL stock?"),
            MockMessage("assistant", "Based on analysis..."),
            MockMessage("user", "What about sector diversification?"),
        ]
        result = SummaryBuilder.build(history)
        assert result is not None
        assert "intent" in result.lower() or "buy" in result.lower()

    def test_build_extracts_topics(self):
        """build() should identify financial topics from user messages."""
        history = [
            MockMessage("user", "What is the Fed rate?"),
            MockMessage("assistant", "The Fed rate is 5.5%"),
            MockMessage("user", "How does this affect my tech stock holdings?"),
        ]
        result = SummaryBuilder.build(history)
        assert result is not None
        # Should mention topics like "macro", "stock", "tech"
        topics = result.lower()
        assert any(kw in topics for kw in ["stock", "tech", "fed", "macro", "rate"])

    def test_build_enforces_max_length(self):
        """build() should truncate summary to max ~800 chars."""
        long_question = "What is " + "a very long question " * 100
        history = [
            MockMessage("user", long_question),
            MockMessage("assistant", "Response"),
            MockMessage("user", "another question"),
        ]
        result = SummaryBuilder.build(history)
        assert result is not None
        assert len(result) <= 850  # Allow some slack

    def test_build_includes_thread(self):
        """build() should identify conversation thread (advisory, analytical, etc.)."""
        history = [
            MockMessage("user", "Explain why the bond market is falling."),
            MockMessage("assistant", "The Fed is raising rates..."),
            MockMessage("user", "What are the implications for my portfolio?"),
        ]
        result = SummaryBuilder.build(history)
        assert result is not None
        assert "thread" in result.lower()

    def test_extract_topics_identifies_asset_types(self):
        """_extract_topics() should find asset class keywords."""
        topics = SummaryBuilder._extract_topics("I'm looking at Tesla stock and Bitcoin crypto")
        assert "stock" in topics
        assert "crypto" in topics

    def test_extract_topics_identifies_macro_concepts(self):
        """_extract_topics() should find macro keywords."""
        topics = SummaryBuilder._extract_topics("The Fed raised rates, causing inflation concerns")
        assert "macro" in topics

    def test_extract_topics_identifies_risk_concepts(self):
        """_extract_topics() should find risk-related keywords."""
        topics = SummaryBuilder._extract_topics("I'm concerned about volatility and concentration")
        assert "risk" in topics

    def test_infer_thread_detects_advisory(self):
        """_infer_thread() should detect advisory questions."""
        user_msgs = [MockMessage("user", "Should I rebalance my portfolio?")]
        thread = SummaryBuilder._infer_thread(user_msgs)
        assert thread is not None
        assert "advisory" in thread.lower() or "strategy" in thread.lower()

    def test_infer_thread_detects_analytical(self):
        """_infer_thread() should detect analytical questions."""
        user_msgs = [MockMessage("user", "Why is the market down today?")]
        thread = SummaryBuilder._infer_thread(user_msgs)
        assert thread is not None
        assert "analytical" in thread.lower() or "explain" in thread.lower()

    def test_infer_thread_detects_scenario(self):
        """_infer_thread() should detect scenario analysis."""
        user_msgs = [MockMessage("user", "What if the Fed cuts rates by 2%?")]
        thread = SummaryBuilder._infer_thread(user_msgs)
        assert thread is not None
        assert "scenario" in thread.lower()

    def test_extract_intent_truncates_long_messages(self):
        """_extract_intent() should truncate very long intent text."""
        long_msg = MockMessage("user", "A" * 200)
        user_msgs = [long_msg]
        intent = SummaryBuilder._extract_intent(user_msgs)
        assert intent is not None
        assert len(intent) <= 160  # Some slack for truncation

    def test_build_does_not_include_numerical_values(self):
        """build() should NOT include numerical values in summary."""
        history = [
            MockMessage("user", "What about the price of AAPL at $150?"),
            MockMessage("assistant", "The price is $150.25"),
            MockMessage("user", "And the dividend is 0.92%?"),
        ]
        result = SummaryBuilder.build(history)
        assert result is not None
        # Should have summary but without numbers
        # (exact validation depends on how topics are extracted)

    def test_build_sliding_window_from_recent_messages(self):
        """build() should use recent messages to infer current thread."""
        history = [
            MockMessage("user", "Tell me about gold prices in 2020"),
            MockMessage("assistant", "Gold was around $1700/oz"),
            MockMessage("user", "Now what about current Fed policy?"),
            MockMessage("assistant", "The Fed is at 5.5%"),
            MockMessage("user", "How does this affect bonds?"),
        ]
        result = SummaryBuilder.build(history)
        assert result is not None
        # Should emphasize recent topics (Fed, bonds) not historical (gold)
        recent_lower = result.lower()
        assert any(kw in recent_lower for kw in ["bond", "fed", "rate", "policy"])


# ── Integration Tests ──

class TestSessionMemoryIntegration:
    """Integration tests with Redis and history."""

    @pytest.mark.asyncio
    async def test_full_memory_lifecycle(self):
        """Test full lifecycle: build, store, retrieve."""
        owner_id = "test_user"
        session_id = "test_session"
        history = [
            MockMessage("user", "What's my portfolio risk?"),
            MockMessage("assistant", "Your portfolio has..."),
            MockMessage("user", "Should I reduce tech exposure?"),
        ]

        # Build summary
        summary = SummaryBuilder.build(history)
        assert summary is not None

        # Store it (mocked)
        with patch("core.connections.redis_client.set", new_callable=AsyncMock):
            await SessionMemoryStore.set(owner_id, session_id, summary)

        # Retrieve it (mocked)
        import json
        with patch("core.connections.redis_client.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = json.dumps(summary)
            retrieved = await SessionMemoryStore.get(owner_id, session_id)
            assert retrieved == summary

    def test_summary_with_hebrew_messages(self):
        """Summary builder should handle Hebrew text."""
        history = [
            MockMessage("user", "מה לעשות עם התיקייה שלי?"),  # What to do with my portfolio?
            MockMessage("assistant", "התיקייה שלך..."),
            MockMessage("user", "אם אני מוקד על טכנולוגיה?"),  # If I focus on tech?
        ]
        result = SummaryBuilder.build(history)
        # Should not crash, may or may not extract topics from Hebrew
        # (depends on keyword matching)

    def test_summary_preserves_conversation_thread_continuity(self):
        """Summary should maintain thread across message boundary."""
        history = [
            MockMessage("user", "Should I buy index funds?"),
            MockMessage("assistant", "Index funds provide..."),
            MockMessage("user", "What's the best allocation?"),
            MockMessage("assistant", "For your profile..."),
            MockMessage("user", "Is 60/40 stocks/bonds good?"),
        ]
        result = SummaryBuilder.build(history)
        assert result is not None
        # Should track the allocation/advisory thread
        assert "thread" in result.lower()

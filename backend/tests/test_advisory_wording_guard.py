"""
Phase 4E — Advisory Wording Guard tests.

All tests are static string assertions on prompt constants.
No LLM calls. No mocks. No network. No DB.

Run:
    docker compose exec api pytest tests/test_advisory_wording_guard.py -v
"""
from __future__ import annotations

from core.prompts import (
    ADVISORY_WORDING_GUARD,
    NATURAL_ADVISORY_PROMPT,
    CHAT_BEHAVIOR_RULES,
)


def test_natural_advisory_prompt_contains_wording_constraint():
    """Guard is embedded in the active advisory prompt."""
    assert "WORDING CONSTRAINT" in NATURAL_ADVISORY_PROMPT, (
        "NATURAL_ADVISORY_PROMPT must contain the WORDING CONSTRAINT block"
    )


def test_natural_advisory_prompt_forbids_direct_recommend_phrases():
    """Guard names the exact forbidden patterns so the LLM has concrete examples."""
    for phrase in ("I recommend", "You should buy", "You should hold"):
        assert phrase in ADVISORY_WORDING_GUARD, (
            f"ADVISORY_WORDING_GUARD must explicitly forbid: {phrase!r}"
        )


def test_natural_advisory_prompt_allows_classification_framing():
    """Guard permits system-classification language (BUY/HOLD as labels, not commands)."""
    assert "scoring model classifies" in ADVISORY_WORDING_GUARD, (
        "Guard must allow 'The scoring model classifies X as [action]' framing"
    )


def test_natural_advisory_prompt_requires_uncertainty_qualifier():
    """Guard requires at least one uncertainty qualifier per advisory response."""
    uncertainty_phrases = (
        "based on available data",
        "subject to market conditions",
        "individual circumstances vary",
    )
    assert any(phrase in ADVISORY_WORDING_GUARD for phrase in uncertainty_phrases), (
        f"ADVISORY_WORDING_GUARD must contain at least one of: {uncertainty_phrases}"
    )


def test_natural_advisory_prompt_permits_strategy_level_direction():
    """Guard explicitly allows directional guidance at strategy/asset-class level."""
    assert "strategy" in ADVISORY_WORDING_GUARD or "asset-class" in ADVISORY_WORDING_GUARD, (
        "Guard must permit strategy/asset-class level direction (e.g. 'increase fixed income')"
    )


def test_legacy_chat_behavior_rules_carves_out_stock_picks():
    """Legacy YES/NO binary rule has an explicit exception for specific ticker questions."""
    assert "individual circumstances vary" in CHAT_BEHAVIOR_RULES, (
        "CHAT_BEHAVIOR_RULES must note 'individual circumstances vary' for stock-pick questions"
    )
    # At least one of these phrasings must be present to identify the exception scope.
    assert "specific ticker" in CHAT_BEHAVIOR_RULES or "specific stock" in CHAT_BEHAVIOR_RULES, (
        "CHAT_BEHAVIOR_RULES must carve out 'specific ticker' or 'specific stock' from bare YES/NO"
    )


# ── Phase 4.3: Recommendation Classification Rendering ───────────────────────

def test_advisory_wording_guard_forbids_action_ticker_opener():
    """Guard must explicitly prohibit opening a response with [Action] [Ticker] constructions."""
    assert any(phrase in ADVISORY_WORDING_GUARD for phrase in (
        "Never open",
        "[Action] [Ticker]",
        "Hold NVDA",
        "Buy AAPL",
    )), (
        "ADVISORY_WORDING_GUARD must prohibit '[Action] [Ticker]' response opener patterns "
        "such as 'Hold NVDA' or 'Buy AAPL' — add the new opener prohibition sentence"
    )


def test_chat_system_prompt_contains_wording_guard():
    """ADVISORY_WORDING_GUARD must be included in the main CHAT_SYSTEM_PROMPT assembly."""
    from core.prompts import CHAT_SYSTEM_PROMPT
    assert "WORDING CONSTRAINT" in CHAT_SYSTEM_PROMPT, (
        "CHAT_SYSTEM_PROMPT must include the ADVISORY_WORDING_GUARD block — "
        "add ADVISORY_WORDING_GUARD to the CHAT_SYSTEM_PROMPT assembly in prompts.py"
    )

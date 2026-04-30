"""
Unit tests for PromptAssembler (Phase 1B).
Run: cd backend && pytest tests/test_prompt_assembler.py -v
"""
from core.prompt_assembler import PromptAssembler, PROMPT_VERSION
from core.prompts import FACTUAL_HOLDINGS_PROMPT, NATURAL_ADVISORY_PROMPT


def _build(**kwargs) -> list[dict]:
    defaults = {"question": "test question", "intent": "factual"}
    defaults.update(kwargs)
    return PromptAssembler.build(**defaults)


# ── Prompt selection ──────────────────────────────────────────────────────────

def test_factual_mode_selects_factual_prompt():
    msgs = _build(mode_hint="factual")
    assert FACTUAL_HOLDINGS_PROMPT in msgs[0]["content"]


def test_advisory_mode_selects_advisory_prompt():
    msgs = _build(mode_hint="advisory")
    assert NATURAL_ADVISORY_PROMPT in msgs[0]["content"]


def test_missing_mode_hint_defaults_to_advisory():
    msgs = _build()  # no mode_hint → default "advisory"
    assert NATURAL_ADVISORY_PROMPT in msgs[0]["content"]


def test_unknown_mode_hint_defaults_to_advisory():
    msgs = _build(mode_hint="unknown_value")
    assert NATURAL_ADVISORY_PROMPT in msgs[0]["content"]


# ── Message structure ─────────────────────────────────────────────────────────

def test_returns_two_messages():
    msgs = _build(mode_hint="factual")
    assert len(msgs) == 2


def test_system_message_is_first():
    msgs = _build(mode_hint="advisory")
    assert msgs[0]["role"] == "system"


def test_user_message_is_last():
    msgs = _build(mode_hint="advisory")
    assert msgs[-1]["role"] == "user"


def test_user_message_wraps_question_in_tag():
    msgs = _build(question="What is SPY?", mode_hint="factual")
    assert "<user_query>" in msgs[1]["content"]
    assert "What is SPY?" in msgs[1]["content"]


def test_context_flags_in_system_message():
    msgs = _build(mode_hint="advisory", has_context=True, has_portfolio=True)
    system = msgs[0]["content"]
    assert "HAS_CONTEXT=True" in system
    assert "HAS_PORTFOLIO=True" in system


def test_context_flags_false_by_default():
    msgs = _build(mode_hint="factual")
    system = msgs[0]["content"]
    assert "HAS_CONTEXT=False" in system
    assert "HAS_PORTFOLIO=False" in system


def test_context_envelope_wraps_retrieved_context():
    msgs = _build(mode_hint="factual", context_block="SPY holds AAPL 7.2%")
    user = msgs[1]["content"]
    assert "<context>" in user
    assert "<retrieved_context>" in user
    assert "SPY holds AAPL 7.2%" in user


def test_intelligence_block_included_in_advisory():
    msgs = _build(mode_hint="advisory", intelligence_block="[INVESTMENT INTEL] signal=bullish")
    assert "<intelligence_context>" in msgs[1]["content"]
    assert "[INVESTMENT INTEL] signal=bullish" in msgs[1]["content"]


def test_intelligence_block_omitted_when_empty():
    msgs = _build(mode_hint="factual", intelligence_block="")
    assert "<intelligence_context>" not in msgs[1]["content"]


def test_conversation_context_included_when_present():
    msgs = _build(mode_hint="advisory", conversation_context="Prior: user asked about SPY")
    assert "<conversation_context>" in msgs[1]["content"]


def test_portfolio_ctx_included_when_present():
    msgs = _build(mode_hint="advisory", portfolio_ctx="[PORTFOLIO] AAPL: 10 units")
    assert "[PORTFOLIO] AAPL: 10 units" in msgs[1]["content"]


def test_mode_tag_present_in_envelope():
    msgs = _build(mode_hint="factual")
    assert "<mode>factual</mode>" in msgs[1]["content"]

    msgs2 = _build(mode_hint="advisory")
    assert "<mode>advisory</mode>" in msgs2[1]["content"]


# ── Prompt version ────────────────────────────────────────────────────────────

def test_prompt_version_exposed_on_class():
    assert PromptAssembler.PROMPT_VERSION == PROMPT_VERSION


def test_prompt_version_contains_phase1b():
    assert "phase1b" in PROMPT_VERSION


# ── Feature flag ──────────────────────────────────────────────────────────────

def test_prompt_assembly_v2_flag_exists_in_config():
    import core.config as cfg
    assert hasattr(cfg, "PROMPT_ASSEMBLY_V2")
    assert isinstance(cfg.PROMPT_ASSEMBLY_V2, bool)


def test_prompt_assembly_v2_default_is_false():
    """Default must be False so legacy path is active without explicit opt-in."""
    import os
    import importlib
    original = os.environ.pop("PROMPT_ASSEMBLY_V2", None)
    try:
        import core.config as cfg
        importlib.reload(cfg)
        assert cfg.PROMPT_ASSEMBLY_V2 is False
    finally:
        if original is not None:
            os.environ["PROMPT_ASSEMBLY_V2"] = original
        importlib.reload(cfg)

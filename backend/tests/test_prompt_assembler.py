"""
Unit tests for PromptAssembler (Phase 3A — citation ID assignment).
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


def test_prompt_version_contains_phase3a():
    assert "phase3a" in PROMPT_VERSION


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


# ── Phase 3A — Citation assignment helpers ────────────────────────────────────

def test_assign_sql_citations_labels_s1_s2():
    tagged = PromptAssembler._assign_sql_citations(["fact one", "fact two"])
    assert tagged[0] == ("[S1]", "fact one")
    assert tagged[1] == ("[S2]", "fact two")


def test_assign_doc_citations_labels_d1_d2():
    tagged = PromptAssembler._assign_doc_citations(["chunk one", "chunk two"])
    assert tagged[0] == ("[D1]", "chunk one")
    assert tagged[1] == ("[D2]", "chunk two")


def test_sql_and_doc_counters_are_independent():
    """D1 must follow S2, not S3 — separate counters, no shared offset."""
    sql = PromptAssembler._assign_sql_citations(["s1", "s2"])
    doc = PromptAssembler._assign_doc_citations(["d1", "d2"])
    sql_tags = [t for t, _ in sql]
    doc_tags = [t for t, _ in doc]
    assert sql_tags == ["[S1]", "[S2]"]
    assert doc_tags == ["[D1]", "[D2]"]
    # No overlap between tag sets
    assert set(sql_tags).isdisjoint(set(doc_tags))


def test_render_cited_context_sql_only():
    block = PromptAssembler._render_cited_context(["holdings data"], [])
    assert "[S1]" in block
    assert "[D" not in block


def test_render_cited_context_doc_only():
    block = PromptAssembler._render_cited_context([], ["doc text"])
    assert "[D1]" in block
    assert "[S" not in block


def test_render_cited_context_mixed_independent_counters():
    block = PromptAssembler._render_cited_context(["sql1", "sql2"], ["doc1", "doc2"])
    assert "[S1]" in block
    assert "[S2]" in block
    assert "[D1]" in block
    assert "[D2]" in block
    # Doc counter must NOT continue from SQL counter
    assert "[D3]" not in block
    assert "[D4]" not in block


def test_render_cited_context_empty_inputs_returns_empty_string():
    block = PromptAssembler._render_cited_context([], [])
    assert block == ""


def test_render_cited_context_sql_before_docs():
    block = PromptAssembler._render_cited_context(["sql_fact"], ["doc_chunk"])
    s_pos = block.index("[S1]")
    d_pos = block.index("[D1]")
    assert s_pos < d_pos


def test_build_with_sql_contexts_assigns_s_tags():
    msgs = _build(sql_contexts=["SQL fact A", "SQL fact B"])
    user = msgs[1]["content"]
    assert "[S1]" in user
    assert "[S2]" in user


def test_build_with_doc_contexts_assigns_d_tags():
    msgs = _build(doc_contexts=["Doc chunk A", "Doc chunk B"])
    user = msgs[1]["content"]
    assert "[D1]" in user
    assert "[D2]" in user


def test_build_mixed_citations_independent_counters():
    msgs = _build(
        sql_contexts=["SQL fact 1", "SQL fact 2"],
        doc_contexts=["Doc chunk 1", "Doc chunk 2"],
    )
    user = msgs[1]["content"]
    assert "[S1]" in user
    assert "[S2]" in user
    assert "[D1]" in user
    assert "[D2]" in user
    assert "[D3]" not in user


def test_build_no_citations_when_no_context():
    msgs = _build()
    user = msgs[1]["content"]
    assert "[S1]" not in user
    assert "[D1]" not in user


def test_build_sql_contexts_overrides_context_block():
    """When sql_contexts provided, it replaces context_block."""
    msgs = _build(
        sql_contexts=["fresh sql"],
        context_block="stale preformatted block",
    )
    user = msgs[1]["content"]
    assert "[S1]" in user
    assert "fresh sql" in user
    # stale block is discarded when sql_contexts takes precedence
    assert "stale preformatted block" not in user


def test_build_context_block_still_works_without_new_params():
    """Legacy context_block param unchanged when sql/doc contexts not provided."""
    msgs = _build(context_block="legacy block content")
    user = msgs[1]["content"]
    assert "legacy block content" in user


def test_factual_mode_with_sql_citations():
    msgs = _build(
        mode_hint="factual",
        sql_contexts=["holdings data row"],
    )
    assert FACTUAL_HOLDINGS_PROMPT in msgs[0]["content"]
    assert "[S1]" in msgs[1]["content"]
    assert "<intelligence_context>" not in msgs[1]["content"]


def test_advisory_mode_with_both_citation_types():
    msgs = _build(
        mode_hint="advisory",
        sql_contexts=["sql row"],
        doc_contexts=["doc chunk"],
        intelligence_block="[INVESTMENT INTEL] signal=bullish",
    )
    assert NATURAL_ADVISORY_PROMPT in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "[S1]" in user
    assert "[D1]" in user
    assert "<intelligence_context>" in user


def test_missing_mode_hint_defaults_to_advisory_with_citations():
    msgs = _build(sql_contexts=["some fact"])
    assert NATURAL_ADVISORY_PROMPT in msgs[0]["content"]
    assert "[S1]" in msgs[1]["content"]


def test_returns_two_messages_with_citations():
    msgs = _build(sql_contexts=["fact"], doc_contexts=["chunk"])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_citation_ordering_is_stable():
    """Same inputs always produce same tag assignments."""
    items = ["alpha", "beta", "gamma"]
    first = PromptAssembler._assign_sql_citations(items)
    second = PromptAssembler._assign_sql_citations(items)
    assert first == second

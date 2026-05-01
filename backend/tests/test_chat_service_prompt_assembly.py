"""
Phase 1C — Structural smoke tests for PROMPT_ASSEMBLY_V2 wiring.

Strategy: source-level verification (no import of chat_service) because
the service requires DB, Redis, Pinecone, OpenAI, and embed models that
are not available in the unit-test environment. Source scanning validates
the exact structural invariants that matter for Phase 1B/1C correctness.

Run: cd backend && pytest tests/test_chat_service_prompt_assembly.py -v
"""
import os
import importlib
import pathlib

_ROOT = pathlib.Path(__file__).parent.parent
_CHAT_SVC  = (_ROOT / "rag/services/chat_service.py").read_text(encoding="utf-8")
_CONFIG    = (_ROOT / "core/config.py").read_text(encoding="utf-8")
_PROMPTS   = (_ROOT / "core/prompts.py").read_text(encoding="utf-8")
_ASSEMBLER = (_ROOT / "core/prompt_assembler.py").read_text(encoding="utf-8")

# Split source at streaming boundary so checks can target sync vs stream separately
_STREAM_START = _CHAT_SVC.find("# ── Stream Stage 1")
assert _STREAM_START != -1, "Stream Stage 1 marker missing from chat_service.py"
_SYNC_SRC   = _CHAT_SVC[:_STREAM_START]
_STREAM_SRC = _CHAT_SVC[_STREAM_START:]


# ── Feature flag — config.py ──────────────────────────────────────────────────

def test_config_defines_prompt_assembly_v2():
    assert "PROMPT_ASSEMBLY_V2" in _CONFIG


def test_config_default_is_false():
    """Default must be 'false' so legacy path is safe without an env override."""
    assert '"false"' in _CONFIG or "'false'" in _CONFIG


def test_config_flag_is_bool_at_runtime():
    import core.config as cfg
    assert hasattr(cfg, "PROMPT_ASSEMBLY_V2")
    assert isinstance(cfg.PROMPT_ASSEMBLY_V2, bool)


def test_config_default_evaluates_to_false_when_env_unset():
    original = os.environ.pop("PROMPT_ASSEMBLY_V2", None)
    try:
        import core.config as cfg
        importlib.reload(cfg)
        assert cfg.PROMPT_ASSEMBLY_V2 is False
    finally:
        if original is not None:
            os.environ["PROMPT_ASSEMBLY_V2"] = original
        importlib.reload(cfg)


def test_config_evaluates_to_true_when_env_set():
    os.environ["PROMPT_ASSEMBLY_V2"] = "true"
    try:
        import core.config as cfg
        importlib.reload(cfg)
        assert cfg.PROMPT_ASSEMBLY_V2 is True
    finally:
        os.environ.pop("PROMPT_ASSEMBLY_V2", None)
        importlib.reload(cfg)


# ── chat_service imports ──────────────────────────────────────────────────────

def test_chat_service_imports_prompt_assembler():
    assert "from core.prompt_assembler import PromptAssembler" in _CHAT_SVC


def test_chat_service_has_prompt_assembly_v2_in_scope():
    """PROMPT_ASSEMBLY_V2 arrives via 'from core.config import *'."""
    assert "from core.config import *" in _CHAT_SVC
    assert "PROMPT_ASSEMBLY_V2" in _CHAT_SVC


# ── Sync path — flag=true branch ─────────────────────────────────────────────

def test_sync_path_calls_assembler_build():
    assert "PromptAssembler.build(" in _SYNC_SRC


def test_sync_path_passes_mode_hint_from_plan():
    assert "hybrid_plan.plan_meta.mode_hint" in _SYNC_SRC


def test_sync_path_appends_assembler_user_message():
    assert "_asm[1]" in _SYNC_SRC


def test_sync_path_logs_prompt_version():
    assert "prompt_assembly_v2_active" in _SYNC_SRC
    assert "PromptAssembler.PROMPT_VERSION" in _SYNC_SRC


# ── Sync path — flag=false legacy branch ─────────────────────────────────────

def test_sync_path_legacy_prompt_selection_preserved():
    assert "NATURAL_ADVISORY_PROMPT if not _skip_intelligence" in _SYNC_SRC


def test_sync_path_legacy_context_flags_format_preserved():
    assert "CONTEXT_FLAGS:" in _SYNC_SRC
    assert "HAS_CONTEXT=" in _SYNC_SRC


def test_sync_path_legacy_user_message_append_preserved():
    assert '"role": "user", "content": user_message' in _SYNC_SRC


# ── Streaming path — Phase 2B V2 branch ──────────────────────────────────────

def test_streaming_path_references_prompt_assembly_v2():
    assert "PROMPT_ASSEMBLY_V2" in _STREAM_SRC, (
        "Streaming path must gate V2 logic behind PROMPT_ASSEMBLY_V2"
    )


def test_streaming_path_references_prompt_assembler():
    assert "PromptAssembler" in _STREAM_SRC, (
        "Streaming path must import/use PromptAssembler in V2 branch"
    )


def test_streaming_v2_calls_assembler_build():
    assert "PromptAssembler.build(" in _STREAM_SRC


def test_streaming_v2_passes_mode_hint_from_plan():
    assert "hybrid_plan" in _STREAM_SRC
    assert "mode_hint" in _STREAM_SRC


def test_streaming_v2_logs_prompt_version_and_mode_hint():
    assert "prompt_assembly_v2_active" in _STREAM_SRC
    assert "PromptAssembler.PROMPT_VERSION" in _STREAM_SRC


def test_streaming_v2_appends_assembler_user_message():
    assert "_asm[1]" in _STREAM_SRC


def test_streaming_v2_uses_mode_hint_for_profile_suppression():
    assert '_inject_profile = (_mode_hint != "factual")' in _STREAM_SRC


# ── Streaming path — legacy branch preserved ──────────────────────────────────

def test_streaming_legacy_prompt_selection_preserved():
    assert "NATURAL_ADVISORY_PROMPT if not guidance.get('_skip_intelligence', False) else FACTUAL_HOLDINGS_PROMPT" in _STREAM_SRC


def test_streaming_legacy_context_flags_format_preserved():
    assert "CONTEXT_FLAGS:" in _STREAM_SRC
    assert "HAS_CONTEXT=" in _STREAM_SRC


def test_streaming_legacy_build_user_message_preserved():
    assert "build_user_message(" in _STREAM_SRC


def test_streaming_v2_branch_surrounds_build_user_message():
    """build_user_message in streaming must be inside the legacy else block."""
    v2_branch = _STREAM_SRC.find("if PROMPT_ASSEMBLY_V2:")
    else_pos = _STREAM_SRC.find("else:", v2_branch)
    bum_pos = _STREAM_SRC.find("user_message = build_user_message(", v2_branch)
    assert v2_branch != -1
    assert else_pos != -1
    assert bum_pos > else_pos, "build_user_message() must be inside the legacy else block in streaming"


# ── Legacy prompts still intact ───────────────────────────────────────────────

def test_factual_holdings_prompt_not_removed():
    assert "FACTUAL_HOLDINGS_PROMPT" in _PROMPTS


def test_natural_advisory_prompt_not_removed():
    assert "NATURAL_ADVISORY_PROMPT" in _PROMPTS


def test_chat_system_prompt_not_removed():
    assert "CHAT_SYSTEM_PROMPT" in _PROMPTS


# ── Assembler invariants (cross-check from phase 1B) ─────────────────────────

def test_assembler_defaults_mode_hint_to_advisory():
    assert 'mode_hint: str = "advisory"' in _ASSEMBLER


def test_assembler_factual_branch_uses_factual_prompt():
    assert 'mode_hint == "factual"' in _ASSEMBLER
    assert "FACTUAL_HOLDINGS_PROMPT" in _ASSEMBLER


def test_assembler_prompt_version_is_phase3a():
    assert "phase3a" in _ASSEMBLER


# ── Phase 2A — mode_hint consistency & build_user_message gating ─────────────

def test_v2_path_sets_inject_profile_from_mode_hint():
    """V2 branch must use mode_hint, not _skip_intelligence, for profile suppression."""
    assert '_inject_profile = (hybrid_plan.plan_meta.mode_hint != "factual")' in _SYNC_SRC


def test_legacy_path_sets_inject_profile_from_skip_intelligence():
    """Legacy branch must preserve original _skip_intelligence-based guard."""
    assert "_inject_profile = not _skip_intelligence" in _SYNC_SRC


def test_profile_injection_guard_uses_inject_profile():
    """The if-statement controlling profile injection must read _inject_profile."""
    assert "user_profile and _inject_profile" in _SYNC_SRC


def test_profile_injection_guard_does_not_directly_use_skip_intelligence():
    """Profile guard must NOT use 'not _skip_intelligence' directly (replaced by _inject_profile)."""
    assert "user_profile and not _skip_intelligence" not in _SYNC_SRC


def test_build_user_message_only_in_legacy_else_block():
    """build_user_message() must only be called inside the legacy else block, not before."""
    v2_branch_start = _SYNC_SRC.find("if PROMPT_ASSEMBLY_V2:")
    else_start = _SYNC_SRC.find("else:", v2_branch_start)
    build_um_pos = _SYNC_SRC.find("user_message = build_user_message(")
    assert v2_branch_start != -1, "PROMPT_ASSEMBLY_V2 branch not found"
    assert else_start != -1, "else block not found after PROMPT_ASSEMBLY_V2 branch"
    assert build_um_pos != -1, "build_user_message() call not found"
    assert build_um_pos > else_start, (
        "build_user_message() must be inside the legacy else block, not called unconditionally"
    )


def test_build_user_message_not_called_before_v2_branch():
    """build_user_message() must not appear before the PROMPT_ASSEMBLY_V2 branch."""
    v2_branch_start = _SYNC_SRC.find("if PROMPT_ASSEMBLY_V2:")
    build_um_pos = _SYNC_SRC.find("user_message = build_user_message(")
    assert build_um_pos > v2_branch_start, (
        "build_user_message() is called before the PROMPT_ASSEMBLY_V2 check — wastes work in V2 mode"
    )


def test_legacy_path_still_contains_build_user_message():
    """Legacy else block must still call build_user_message() for backward compatibility."""
    assert "build_user_message(" in _SYNC_SRC


# ── Phase 2C — sync V2 downstream user_message regression ────────────────────

def test_sync_v2_assigns_user_message_from_assembler():
    """V2 path must set user_message from _asm[1]['content'] so downstream metric
    logging (len(user_message)) does not raise UnboundLocalError at runtime."""
    assert 'user_message = _asm[1]["content"]' in _SYNC_SRC


def test_sync_v2_user_message_assignment_follows_asm_append():
    """user_message = _asm[1]['content'] must appear immediately after messages.append(_asm[1])
    in the same V2 block — not in the legacy else or unconditionally outside any branch.

    Uses the append call as the anchor rather than searching for an 'else:' boundary,
    because the sync path contains two PROMPT_ASSEMBLY_V2 blocks and find('else:') would
    land on the wrong one.
    """
    append_anchor = "messages.append(_asm[1])"
    assign_needle = 'user_message = _asm[1]["content"]'
    append_pos = _SYNC_SRC.find(append_anchor)
    assert append_pos != -1, "messages.append(_asm[1]) not found in sync path"
    # Assignment must follow the append within a tight window (≤ 120 chars covers one comment line)
    window = _SYNC_SRC[append_pos : append_pos + 120]
    assert assign_needle in window, (
        f"user_message = _asm[1]['content'] must immediately follow messages.append(_asm[1]); "
        f"window was: {window!r}"
    )


def test_sync_v2_does_not_call_build_user_message_in_v2_block():
    """build_user_message() must NOT appear inside the V2 if-block (only in legacy else)."""
    v2_start = _SYNC_SRC.find("if PROMPT_ASSEMBLY_V2:")
    else_start = _SYNC_SRC.find("else:", v2_start)
    bum_pos = _SYNC_SRC.find("user_message = build_user_message(", v2_start)
    assert bum_pos == -1 or bum_pos > else_start, (
        "build_user_message() must not be called inside the V2 if-block"
    )


# ── Phase 3B — sql_contexts / doc_contexts wiring ────────────────────────────

_CHAT_SVC_FULL = (_ROOT / "rag/services/chat_service.py").read_text(encoding="utf-8")


def test_extract_citation_lists_defined_in_chat_service():
    assert "def _extract_citation_lists(" in _CHAT_SVC_FULL


def test_extract_citation_lists_returns_sql_and_doc_lists():
    assert "sql_contexts" in _CHAT_SVC_FULL
    assert "doc_contexts" in _CHAT_SVC_FULL


def test_sync_v2_passes_sql_contexts_to_assembler():
    assert "sql_contexts=_sql_contexts" in _SYNC_SRC


def test_sync_v2_passes_doc_contexts_to_assembler():
    assert "doc_contexts=_doc_contexts" in _SYNC_SRC


def test_sync_v2_does_not_pass_context_block_to_assembler():
    """V2 sync path uses sql_contexts/doc_contexts instead of the pre-joined context_block."""
    v2_start = _SYNC_SRC.find("if PROMPT_ASSEMBLY_V2:")
    else_start = _SYNC_SRC.find("else:", v2_start)
    v2_block = _SYNC_SRC[v2_start:else_start]
    assert "context_block=context_block" not in v2_block


def test_streaming_v2_passes_sql_contexts_to_assembler():
    assert "sql_contexts=retrieval[" in _STREAM_SRC


def test_streaming_v2_passes_doc_contexts_to_assembler():
    assert "doc_contexts=retrieval[" in _STREAM_SRC


def test_streaming_v2_does_not_pass_context_block_to_assembler():
    """V2 streaming path uses sql_contexts/doc_contexts instead of context_block."""
    v2_start = _STREAM_SRC.find("if PROMPT_ASSEMBLY_V2:")
    else_start = _STREAM_SRC.find("else:", v2_start)
    v2_block = _STREAM_SRC[v2_start:else_start]
    assert 'context_block=retrieval["context_block"]' not in v2_block


def test_retrieval_dict_includes_sql_contexts_key():
    assert '"sql_contexts"' in _CHAT_SVC_FULL or "'sql_contexts'" in _CHAT_SVC_FULL


def test_retrieval_dict_includes_doc_contexts_key():
    assert '"doc_contexts"' in _CHAT_SVC_FULL or "'doc_contexts'" in _CHAT_SVC_FULL


def test_legacy_sync_path_context_block_in_build_user_message():
    """Legacy sync path must still pass context_block to build_user_message."""
    assert "build_user_message(context_block," in _SYNC_SRC


def test_legacy_streaming_path_context_block_unchanged():
    """Legacy streaming path must still pass retrieval['context_block'] to build_user_message."""
    assert 'retrieval["context_block"]' in _STREAM_SRC


def test_extract_citation_lists_called_after_fusion_to_context():
    """_extract_citation_lists must be called right after _fusion_to_context in both paths."""
    assert "_extract_citation_lists(fusion_result)" in _CHAT_SVC_FULL


def test_prompt_assembler_s1_d1_appear_in_cited_build():
    """Unit-style: PromptAssembler with sql_contexts/doc_contexts produces [S1] and [D1]."""
    from core.prompt_assembler import PromptAssembler
    msgs = PromptAssembler.build(
        mode_hint="advisory",
        sql_contexts=["Holdings: AAPL 7.2%"],
        doc_contexts=["Buffett favors long-term holdings."],
        question="What is SPY?",
        intent="advisory",
    )
    user = msgs[1]["content"]
    assert "[S1]" in user
    assert "[D1]" in user
    assert "Holdings: AAPL 7.2%" in user
    assert "Buffett favors long-term holdings." in user

"""
observability/analyzer.py — Deterministic LLM behavior analysis.

Zero LLM calls. Pure text + logic inspection of the LLM's response.

Answers:
  1. Did the LLM follow the system's recommendation action?
  2. Did it attempt arithmetic the system explicitly forbids?
  3. Did it invent a confidence level different from pipeline_confidence?
  4. Does the response contain unsupported claim markers?
  5. Overall classification: followed_system | deviated | added_unsupported_claims

Developer debugging guide:
  - "arithmetic_attempted" flag → LLM computed something it shouldn't have
  - "confidence_mismatch" flag  → LLM overrode deterministic confidence
  - "ignored_recommendation"    → LLM suggested BUY when system said AVOID (or vice versa)
  - "hallucination_risk"        → response contains language patterns associated with invention
"""

from __future__ import annotations

import re
from typing import Optional

from observability.schemas import (
    LLMBehaviorAnalysis,
    LLMBehaviorFlag,
    LLMConstraints,
    LLMInputBlocks,
    LLMOutputStructure,
    LLMTrace,
)


# ── Arithmetic detection ─────────────────────────────────────────────────────

# Patterns that suggest the LLM performed arithmetic in its response text.
# We look for:
#   - Explicit equals-sign computations: "100 + 200 = 300"
#   - "total of X" / "sum of X" computed inline
#   - "= $X" after a list of numbers (strong signal)
_ARITHMETIC_PATTERNS: list[re.Pattern] = [
    re.compile(r'\d[\d,\.]*\s*[\+\-\×\÷\*\/]\s*\d[\d,\.]*\s*=\s*\d', re.UNICODE),
    re.compile(r'=\s*\$?\d[\d,\.]+', re.IGNORECASE),
    re.compile(r'(total|sum|equals?)\s+(is|of|:)?\s*\$?\d[\d,\.]+', re.IGNORECASE),
    re.compile(r'\d+\s*\+\s*\d+', re.UNICODE),
    re.compile(r'(adding|subtracting|multiplying|dividing)\s+\$?\d', re.IGNORECASE),
]

# ── Hallucination risk markers ───────────────────────────────────────────────

# Phrases that suggest the LLM is inventing data not in the context.
# These are weak signals — logged as "hallucination_risk", never as definitive.
_HALLUCINATION_PHRASES: list[str] = [
    "typically yields",
    "usually returns",
    "historically generates",
    "generally provides",
    "estimated return",
    "approximate yield",
    "based on typical",
    "standard rate of",
    "average annual return of",
    "i estimate",
    "i calculate",
    "my calculation",
    "roughly",       # too vague for a financial advisory system
]

# ── Recommendation action detection ─────────────────────────────────────────

_ACTION_KEYWORDS: dict[str, list[str]] = {
    "BUY":    ["buy", "purchase", "invest", "acquire", "add to"],
    "HOLD":   ["hold", "maintain", "keep", "retain", "no change"],
    "REDUCE": ["reduce", "trim", "decrease", "scale back", "lower exposure"],
    "AVOID":  ["avoid", "stay away", "do not buy", "not recommended", "steer clear"],
}


def _detect_arithmetic(response: str) -> list[str]:
    """Return list of matched arithmetic snippet strings found in the response."""
    matches = []
    for pattern in _ARITHMETIC_PATTERNS:
        for m in pattern.finditer(response):
            snippet = m.group(0)[:60].strip()
            if snippet not in matches:
                matches.append(snippet)
    return matches


def _detect_hallucination_risk(response: str) -> bool:
    """Return True if the response contains hallucination-associated language."""
    lower = response.lower()
    return any(phrase in lower for phrase in _HALLUCINATION_PHRASES)


def _extract_action_from_response(response: str) -> Optional[str]:
    """
    Heuristic: detect which action word the LLM most prominently used.
    Returns "BUY" / "HOLD" / "REDUCE" / "AVOID" or None.
    """
    lower = response.lower()
    scores: dict[str, int] = {action: 0 for action in _ACTION_KEYWORDS}
    for action, keywords in _ACTION_KEYWORDS.items():
        for kw in keywords:
            scores[action] += lower.count(kw)
    best = max(scores, key=lambda a: scores[a])
    return best if scores[best] > 0 else None


def _check_confidence_mismatch(
    response: str,
    pipeline_confidence: Optional[str],
) -> bool:
    """
    Return True if the LLM appears to have stated a confidence that differs
    from the deterministic pipeline_confidence.

    Only meaningful when pipeline_confidence is set (intelligence layer ran).
    """
    if not pipeline_confidence:
        return False

    lower = response.lower()
    opposites = {
        "high":   ["low confidence", "medium confidence", "uncertain"],
        "medium": ["high confidence", "very confident", "low confidence"],
        "low":    ["high confidence", "very confident", "medium confidence"],
    }
    signals = opposites.get(pipeline_confidence.lower(), [])
    return any(s in lower for s in signals)


# ── Public API ───────────────────────────────────────────────────────────────


def _detect_shallow_reasoning(response: str) -> bool:
    """Return True if Analysis/Synthesis sections are suspiciously short."""
    # Look for common section headers
    sections = re.split(r'###?\s*\d?\.?\s*(Analysis|Synthesis|Insight)', response, flags=re.IGNORECASE)
    if len(sections) > 1:
        # The content after the header is what matters
        for i in range(2, len(sections), 2):
            content = sections[i].strip()
            if len(content) < 100:
                return True
    return False


def _detect_repeated_statements(response: str) -> bool:
    """Return True if sentences are repeated or highly redundant."""
    sentences = [s.strip().lower() for s in re.split(r'[.!?]', response) if len(s.strip()) > 20]
    seen = set()
    for s in sentences:
        # Check for exact or near-exact (90% similarity is hard without fuzzy, so just exact/prefix)
        if s in seen:
            return True
        seen.add(s)
    return False


def _detect_missing_signals(response: str, input_blocks: Optional[LLMInputBlocks]) -> bool:
    """Return True if important input signals are present in input but never mentioned."""
    if not input_blocks:
        return False
    
    lower = response.lower()
    checks = []
    if input_blocks.has_market_context:
        checks.append(("market", ["regime", "vix", "yield curve", "fed rate", "inflation"]))
    if input_blocks.has_normalized_portfolio:
        checks.append(("portfolio", ["allocation", "invested", "position"]))
    
    for category, keywords in checks:
        if not any(kw in lower for kw in keywords):
            return True
    return False


def _detect_lack_of_synthesis(response: str) -> bool:
    """Return True if 'dot-connecting' transition words are missing."""
    synthesis_words = [
        "compounded", "interacting", "sensitivity", "overlap", "impacted by",
        "sensitivity to", "correlation", "driven by", "because", "due to",
        "consequently", "resulting in", "therefore"
    ]
    lower = response.lower()
    return not any(w in lower for w in synthesis_words)


def analyze_llm_behavior(
    response: str,
    pipeline_confidence: Optional[str],
    system_action: Optional[str],
    validation_flags: Optional[list[str]] = None,
    input_blocks: Optional[LLMInputBlocks] = None,
) -> LLMBehaviorAnalysis:
    """
    Inspect the LLM's response text and return a deterministic behavior analysis.
    """
    flags: list[LLMBehaviorFlag] = []
    arithmetic_markers: list[str] = []
    notes_parts: list[str] = []

    # 1. Arithmetic check
    arithmetic_markers = _detect_arithmetic(response)
    if arithmetic_markers:
        flags.append(LLMBehaviorFlag.ARITHMETIC_ATTEMPTED)
        notes_parts.append(f"Arithmetic found: {'; '.join(arithmetic_markers[:2])}")

    # 2. Confidence mismatch
    if _check_confidence_mismatch(response, pipeline_confidence):
        flags.append(LLMBehaviorFlag.CONFIDENCE_MISMATCH)

    # 3. Recommendation action mismatch
    if system_action:
        llm_action = _extract_action_from_response(response)
        if llm_action and llm_action != system_action:
            contradictions = {"BUY": {"AVOID", "REDUCE"}, "AVOID": {"BUY"}, "REDUCE": {"BUY"}}
            if llm_action in contradictions.get(system_action, set()):
                flags.append(LLMBehaviorFlag.IGNORED_RECOMMENDATION)

    # 4. Hallucination risk
    if _detect_hallucination_risk(response):
        flags.append(LLMBehaviorFlag.HALLUCINATION_RISK)

    # 5. Reasoning Quality Detection (NEW Phase 3)
    is_shallow = _detect_shallow_reasoning(response)
    is_repeated = _detect_repeated_statements(response)
    is_missing_signals = _detect_missing_signals(response, input_blocks)
    is_unsynthesized = _detect_lack_of_synthesis(response)

    if is_shallow: flags.append(LLMBehaviorFlag.SHALLOW_REASONING)
    if is_repeated: flags.append(LLMBehaviorFlag.REPEATED_STATEMENTS)
    if is_missing_signals: flags.append(LLMBehaviorFlag.MISSING_SIGNALS)
    if is_unsynthesized: flags.append(LLMBehaviorFlag.LACK_OF_SYNTHESIS)

    # 6. Quality Classification
    if not any([is_shallow, is_repeated, is_missing_signals, is_unsynthesized]):
        reasoning_quality = "high_quality_reasoning"
    elif is_missing_signals:
        reasoning_quality = "incomplete_use_of_context"
    else:
        reasoning_quality = "surface_level"

    # 7. Overall Classification
    if LLMBehaviorFlag.IGNORED_RECOMMENDATION in flags or LLMBehaviorFlag.CONFIDENCE_MISMATCH in flags:
        classification = "deviated"
    elif LLMBehaviorFlag.HALLUCINATION_RISK in flags or LLMBehaviorFlag.ARITHMETIC_ATTEMPTED in flags:
        classification = "added_unsupported_claims"
    else:
        classification = "followed_system"

    return LLMBehaviorAnalysis(
        classification=classification,
        reasoning_quality=reasoning_quality,
        flags=flags,
        validation_flags=validation_flags or [],
        arithmetic_markers=arithmetic_markers,
        notes=" | ".join(notes_parts) if notes_parts else "Analysis complete",
    )


def build_llm_input_blocks(
    intelligence_block: str,
    context_block: str,
    portfolio_ctx: Optional[str],
) -> LLMInputBlocks:
    """
    Inspect the strings passed to the LLM and produce a structured inventory.
    Used to answer: "Which data blocks actually reached the model?"
    """
    ib = intelligence_block or ""
    cb = context_block or ""
    total_chars = len(ib) + len(cb) + len(portfolio_ctx or "")

    return LLMInputBlocks(
        has_normalized_portfolio = "[NORMALIZED PORTFOLIO" in ib,
        has_market_context       = "[MARKET CONTEXT" in ib or "MARKET REGIME" in ib,
        has_validation_block     = "[VALIDATION]" in ib,
        has_vector_context       = "[D" in cb,   # document citations
        has_sql_context          = "[S" in cb,   # SQL citations
        has_portfolio_context    = portfolio_ctx is not None and len(portfolio_ctx) > 10,
        intelligence_block_chars = len(ib),
        context_block_chars      = len(cb),
        # Rough token estimate: 1 token ≈ 4 chars for English/financial text
        estimated_prompt_tokens  = total_chars // 4,
    )


def build_llm_output_structure(
    answer: str,
    suggested_questions: list,
    pipeline_confidence: Optional[str],
    reasoning_summary: Optional[str],
    system_action: Optional[str],
) -> LLMOutputStructure:
    """Build the output structure record from parsed LLM response fields."""
    confidence_source = "none"
    if pipeline_confidence:
        confidence_source = "pipeline"
    elif reasoning_summary:
        confidence_source = "llm_fallback"

    return LLMOutputStructure(
        has_explainability_block  = reasoning_summary is not None,
        has_suggested_questions   = len(suggested_questions) > 0,
        recommendation_action     = system_action,
        confidence_source         = confidence_source,
        confidence_level          = pipeline_confidence,
        response_length_chars     = len(answer),
        suggested_questions_count = len(suggested_questions),
    )

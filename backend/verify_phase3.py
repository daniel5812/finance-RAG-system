import re
import json

# Mocking the enum and schemas since I can't import them easily without dependencies
class LLMBehaviorFlag:
    FOLLOWED_SYSTEM       = "followed_system"
    DEVIATED              = "deviated"
    ARITHMETIC_ATTEMPTED  = "arithmetic_attempted"
    HALLUCINATION_RISK    = "hallucination_risk"
    IGNORED_RECOMMENDATION = "ignored_recommendation"
    UNSUPPORTED_CLAIMS    = "unsupported_claims"
    CONFIDENCE_MISMATCH   = "confidence_mismatch"
    SHALLOW_REASONING     = "shallow_reasoning"
    REPEATED_STATEMENTS   = "repeated_statements"
    MISSING_SIGNALS       = "missing_signals"
    LACK_OF_SYNTHESIS     = "lack_of_synthesis"

class LLMInputBlocks:
    def __init__(self, has_market_context=False, has_normalized_portfolio=False):
        self.has_market_context = has_market_context
        self.has_normalized_portfolio = has_normalized_portfolio

# Copied detection logic from analyzer.py to verify it works as intended
def _detect_shallow_reasoning(response: str) -> bool:
    sections = re.split(r'###?\s*\d?\.?\s*(Analysis|Synthesis|Insight)', response, flags=re.IGNORECASE)
    if len(sections) > 1:
        for i in range(2, len(sections), 2):
            content = sections[i].strip()
            if len(content) < 100:
                return True
    return False

def _detect_repeated_statements(response: str) -> bool:
    sentences = [s.strip().lower() for s in re.split(r'[.!?]', response) if len(s.strip()) > 20]
    seen = set()
    for s in sentences:
        if s in seen: return True
        seen.add(s)
    return False

def _detect_missing_signals(response: str, input_blocks: LLMInputBlocks) -> bool:
    lower = response.lower()
    checks = []
    if input_blocks.has_market_context:
        checks.append(("market", ["regime", "vix", "yield curve", "fed rate", "inflation"]))
    if input_blocks.has_normalized_portfolio:
        checks.append(("portfolio", ["allocation", "invested", "position"]))
    for category, keywords in checks:
        if not any(kw in lower for kw in keywords): return True
    return False

def _detect_lack_of_synthesis(response: str) -> bool:
    synthesis_words = ["compounded", "interacting", "sensitivity", "overlap", "impacted by", "because", "due to"]
    lower = response.lower()
    return not any(w in lower for w in synthesis_words)

# Copied from orchestrator.py
_ADVISORY_KEYWORDS = {"recommend", "buy", "portfolio", "position"}
def _select_llm_mode(question: str, intent: str, tickers: list) -> str:
    q_lower = question.lower()
    is_analytical_or_advisory = intent in ("analytical", "advisory") or any(kw in q_lower for kw in _ADVISORY_KEYWORDS)
    if is_analytical_or_advisory:
        return "advisory" if not tickers else "synthesis"
    return "explanation"

def test():
    print("--- Testing Mode Selection ---")
    assert _select_llm_mode("Should I diversify?", "advisory", []) == "advisory"
    assert _select_llm_mode("Should I buy AAPL?", "advisory", ["AAPL"]) == "synthesis"
    print("Mode Selection OK")

    print("\n--- Testing Quality Detection ---")
    blocks = LLMInputBlocks(has_market_context=True, has_normalized_portfolio=True)
    
    good = "### Insight\nThe VIX is high and this is compounded by your position in tech, resulting in sensitivity to rates because of inflation."
    assert not _detect_shallow_reasoning(good)
    assert not _detect_missing_signals(good, blocks)
    assert not _detect_lack_of_synthesis(good)
    print("High Quality Detection OK")

    shallow = "### Insight\nShort."
    assert _detect_shallow_reasoning(shallow)
    print("Shallow Detection OK")

    missing = "### Insight\nEverything is fine."
    assert _detect_missing_signals(missing, blocks)
    assert _detect_lack_of_synthesis(missing)
    print("Missing/Unsynthesized Detection OK")

    repeat = "The market is up today. The market is up today."
    assert _detect_repeated_statements(repeat)
    print("Repeat Detection OK")

if __name__ == "__main__":
    test()

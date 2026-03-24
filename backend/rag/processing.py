"""
processing.py — Text processing utilities.
Chunking and retrieval filtering logic.
"""

from core.config import CHUNK_SIZE, CHUNK_OVERLAP, RELATIVE_THRESHOLD, DROP_OFF_GAP, MIN_ABSOLUTE_SCORE


# ── Text Chunking ──

def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks."""
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ── Dynamic Retrieval Filtering ──

def dynamic_filter(matches: list) -> list:
    """Apply dynamic top_k + relative threshold + drop-off filtering."""
    if not matches:
        return []
    max_score = matches[0]["score"]
    cutoff = max(max_score * RELATIVE_THRESHOLD, MIN_ABSOLUTE_SCORE)
    filtered = []
    for i, m in enumerate(matches):
        if m["score"] < cutoff:
            break
        if i > 0 and (matches[i-1]["score"] - m["score"]) > DROP_OFF_GAP:
            break
        filtered.append(m)
    return filtered

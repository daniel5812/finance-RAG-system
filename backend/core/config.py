"""
core/config.py — Single source of truth for all settings.
Every module imports from here. No magic numbers scattered in business logic.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── External Services ──
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FRED_API_KEY = os.getenv("FRED_API_KEY")
INDEX_NAME = "rag-384"

# ── Redis ──
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = 6379

# ── Authentication ──

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-super-secret-key-change-me")
ALGORITHM = "HS256"

# ── PostgreSQL ──
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rag:rag@localhost:5432/investdb")


# ── Cache TTLs ──
CACHE_TTL = 600           # Hard expiration (10 min) — enforced by Redis ex=
CACHE_SOFT_TTL = 240      # Soft expiration (4 min) — checked application-side
EMBED_CACHE_TTL = 3600    # Embedding cache (1 hour)

# ── Semantic Cache ──
SEMANTIC_CACHE_THRESHOLD = 0.88   # cosine similarity threshold
SEMANTIC_CACHE_MAX = 100          # max entries per role

# ── Dynamic Retrieval ──
DYNAMIC_TOP_K = 5              # fetch more, then filter down
RELATIVE_THRESHOLD = 0.6       # score >= max_score * this
DROP_OFF_GAP = 0.15            # cut off if gap between consecutive scores > this
MIN_ABSOLUTE_SCORE = 0.25      # hard floor — never accept below this

# ── Chunking ──
CHUNK_SIZE = 500        # characters per chunk
CHUNK_OVERLAP = 50      # overlap between chunks

# ── Stream Security ──
MAX_STREAM_DURATION = 30        # seconds per stream connection
MAX_CONCURRENT_STREAMS = 10     # max parallel streams

# ── LLM Backpressure ──
LLM_WAIT_TIMEOUT = 10          # seconds to wait for a free LLM slot
OPENAI_TIMEOUT = 30            # seconds — max wait for OpenAI response
PINECONE_TIMEOUT = 10          # seconds — max wait for Pinecone query

# ── Content Filter (Sliding Window) ──
BUFFER_LIMIT = 50               # chars before triggering a scan
OVERLAP_SIZE = 20               # chars to keep as overlap (≥ longest pattern)

# ── Access Control ──
ROLE_ACCESS = {
    "admin":    ["public", "admin"],
    "employee": ["public"],
}

# ── Rate Limiting ──
# Per-user sliding window: max requests allowed per 60-second window.
# An SPA fires ~6 requests per page load; 200 allows ~33 page loads/min
# before throttling, which is sufficient for normal use.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "200"))

# ── Document Pipeline ──
# DOCUMENT_UPLOAD_DIR: where uploaded PDFs are saved on disk.
#   → In Docker: mount a volume here (e.g. ./data/uploads:/app/uploads)
#   → In production: replace with S3 client — only this setting changes.
DOCUMENT_UPLOAD_DIR = os.getenv("DOCUMENT_UPLOAD_DIR", "./uploads")

# DOCUMENT_MAX_SIZE_MB: hard limit on upload size.
#   50 MB is generous for pension statements / broker reports; adjust as needed.
DOCUMENT_MAX_SIZE_MB = int(os.getenv("DOCUMENT_MAX_SIZE_MB", "50"))

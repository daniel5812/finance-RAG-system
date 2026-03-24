"""
core/connections.py — All external service clients in one place.
Any module that needs Redis, Pinecone, or OpenAI imports from here.
"""

import time
from typing import Any
import redis.asyncio as aioredis
from openai import AsyncOpenAI

from core.config import REDIS_HOST, REDIS_PORT, PINECONE_API_KEY, INDEX_NAME, OPENAI_API_KEY
from core.logger import get_logger

logger = get_logger(__name__)

# ── Redis ──
redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# ── Embedding & Reranking Models ──
embed_model: Any = None
rerank_model: Any = None

def load_ml_models():
    """
    Load ML models into global variables. 
    Called during FastAPI lifespan to avoid blocking imports and provide better logging.
    """
    global embed_model, rerank_model
    
    try:
        from sentence_transformers import SentenceTransformer, CrossEncoder
        
        logger.info("Loading Embedding model (all-MiniLM-L6-v2)...")
        t_load = time.time()
        embed_model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info(f"Embedding model loaded in {time.time() - t_load:.2f}s")
        
        logger.info("Loading Reranking model (cross-encoder/ms-marco-MiniLM-L-6-v2)...")
        t_load = time.time()
        rerank_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info(f"Reranking model loaded in {time.time() - t_load:.2f}s")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to load ML models: {e}")
        # Keep them as None so fallback logic in services triggers correctly
        embed_model = None
        rerank_model = None

# ── Pinecone ──
try:
    from pinecone import Pinecone
    if PINECONE_API_KEY:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        pinecone_index = pc.Index(INDEX_NAME)
        logger.info(f"Connected to Pinecone: {INDEX_NAME}")
    else:
        pinecone_index = None
        logger.warning("Pinecone key missing")
except Exception as e:
    pinecone_index = None
    logger.warning(f"Pinecone not available: {e}")

# ── OpenAI (Async) ──
if OPENAI_API_KEY:
    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    logger.info("Connected to OpenAI (Async)")
else:
    openai_client = None
    logger.warning("OpenAI key missing")

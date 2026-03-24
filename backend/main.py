from contextlib import asynccontextmanager
from fastapi import FastAPI

from core.routes.health import router as health_router
from rag.routes import ingest as rag_ingest
from rag.routes import chat as rag_chat
from rag.routes import sessions as rag_sessions
from financial.routes import router as financial_router
from documents.routes import router as doc_router
from core.routes.user import router as user_router
from core.logger import get_logger
from core.middleware import add_request_id
from fastapi.middleware.cors import CORSMiddleware
import core.db as db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app):
    """Startup/shutdown hooks — manage the DB connection pool and ML models."""
    logger.info("Initializing Investment Intelligence Engine...")
    
    # 1. Database
    await db.get_pool()
    logger.info("Database pool ready")
    
    # 2. ML Models (CPU/RAM intensive)
    from core.connections import load_ml_models
    load_ml_models()
    
    yield
    
    await db.close_pool()
    logger.info("Database pool closed")


app = FastAPI(lifespan=lifespan)

# ── CORS Middleware ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Tracing Middleware ──
app.middleware("http")(add_request_id)

# ── Include Routers ──
app.include_router(health_router)           # GET /health, GET /metrics
app.include_router(rag_ingest.router)       # POST /ingest
app.include_router(rag_chat.router)         # POST /chat, POST /chat/stream
app.include_router(rag_sessions.router)     # GET/POST /chat/sessions
app.include_router(financial_router)        # POST /financial/ingest/*
app.include_router(doc_router)              # POST /documents/upload
app.include_router(user_router)             # GET/POST /user/settings


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

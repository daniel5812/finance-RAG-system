import os
from contextlib import asynccontextmanager
from fastapi import FastAPI

from core.routes.health import router as health_router
from rag.routes import ingest as rag_ingest
from rag.routes import chat as rag_chat
from rag.routes import sessions as rag_sessions
from financial.routes import router as financial_router
from documents.routes import router as doc_router
from core.routes.user import router as user_router
from core.routes.auth import router as auth_router
from core.routes.admin import router as admin_router
from core.routes.portfolio import router as portfolio_router
from observability.routes import router as observability_router

from core.logger import get_logger, setup_logging
from core.middleware import add_request_id
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import core.db as db

# ── Unified Logging — MUST run before app initialization ──
setup_logging()
logger = get_logger(__name__)


async def _seed_holdings_if_empty(pool) -> None:
    """
    Non-blocking startup hook: ingest SPY and QQQ holdings if etf_holdings is empty.
    Runs as a background task — never blocks server startup.
    Subsequent startups are no-ops (hash-based skip inside HoldingsProvider).
    """
    try:
        count = await pool.fetchval("SELECT COUNT(*) FROM etf_holdings")
        if count == 0:
            logger.info("etf_holdings empty — seeding SPY and QQQ holdings on startup...")
            from financial.providers.holdings import HoldingsProvider
            result = await HoldingsProvider().ingest(pool, symbols=["SPY", "QQQ"])
            logger.info(
                f"Holdings seed: processed={result['processed']}, "
                f"updated={result['updated']}, "
                f"skipped={result['skipped']}, failed={result['failed']}"
            )
        else:
            logger.info(f"etf_holdings already populated ({count} rows) — seed skipped")
    except Exception as e:
        logger.warning(f"ETF holdings seed failed (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app):
    """Startup/shutdown hooks — manage the DB connection pool and ML models."""
    logger.info("Initializing Investment Intelligence Engine...")

    # 1. Database
    pool = await db.get_pool()
    logger.info("Database pool ready")

    # 2. Seed ETF holdings — gated behind AUTO_SEED_HOLDINGS_ON_STARTUP (default: true)
    auto_seed = os.getenv("AUTO_SEED_HOLDINGS_ON_STARTUP", "true").lower() == "true"
    if auto_seed:
        logger.info("AUTO_SEED_HOLDINGS_ON_STARTUP=true — scheduling background ETF holdings seed (first query may arrive before seed completes)")
        asyncio.create_task(_seed_holdings_if_empty(pool))
    else:
        logger.info("AUTO_SEED_HOLDINGS_ON_STARTUP=false — startup ETF holdings seed disabled; seed manually via /financial/ingest/holdings")

    # 3. ML Models (CPU/RAM intensive)
    from core.connections import load_ml_models
    load_ml_models()
    
    yield
    
    await db.close_pool()
    logger.info("Database pool closed")


app = FastAPI(lifespan=lifespan)

# ── Tracing Middleware ──
app.middleware("http")(add_request_id)

# ── CORS Middleware ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://localhost:5173",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Include Routers ──
app.include_router(health_router)           # GET /health, GET /metrics
app.include_router(rag_ingest.router)       # POST /ingest
app.include_router(rag_chat.router)         # POST /chat, POST /chat/stream
app.include_router(rag_sessions.router)     # GET/POST /chat/sessions
app.include_router(financial_router)        # POST /financial/ingest/*
app.include_router(doc_router)              # POST /documents/upload
app.include_router(user_router)             # GET/POST /user/settings
app.include_router(auth_router)             # POST /auth/login/google
app.include_router(admin_router)            # /admin/*
app.include_router(portfolio_router)        # /portfolio/*
app.include_router(observability_router)    # /admin/observability/*



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

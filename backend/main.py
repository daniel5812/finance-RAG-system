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
    Non-blocking startup hook: seed SPY and QQQ holdings if either is missing.
    Checks per-symbol so a partial prior run does not block the missing symbol.
    Subsequent startups skip symbols that already have rows.
    """
    try:
        missing = []
        for symbol in ["SPY", "QQQ"]:
            count = await pool.fetchval(
                "SELECT COUNT(*) FROM etf_holdings WHERE etf_symbol = $1", symbol
            )
            if count == 0:
                missing.append(symbol)

        if missing:
            logger.info(f"etf_holdings missing for {missing} — seeding on startup...")
            from financial.providers.holdings import HoldingsProvider
            result = await HoldingsProvider().ingest(pool, symbols=missing)
            logger.info(
                f"Holdings seed: processed={result['processed']}, "
                f"updated={result['updated']}, "
                f"skipped={result['skipped']}, failed={result['failed']}"
            )
        else:
            logger.info("etf_holdings already populated for SPY and QQQ — seed skipped")
    except Exception as e:
        logger.warning(f"ETF holdings seed failed (non-fatal): {e}")


async def _seed_prices_if_empty(pool) -> None:
    """
    Non-blocking startup hook: seed SPY and QQQ daily prices if missing.
    Uses YFinancePriceProvider (no API key required). Idempotent via ON CONFLICT DO NOTHING.
    """
    try:
        from financial.providers.price import YFinancePriceProvider
        for symbol in ["SPY", "QQQ"]:
            count = await pool.fetchval(
                "SELECT COUNT(*) FROM prices WHERE symbol = $1", symbol
            )
            if count == 0:
                logger.info(f"prices empty for {symbol} — seeding from Yahoo Finance...")
                result = await YFinancePriceProvider(symbol=symbol).ingest(pool)
                logger.info(f"Price seed {symbol}: {result.get('status')}, rows={result.get('rows_ingested', 0)}")
            else:
                logger.info(f"prices already populated for {symbol} ({count} rows) — skipped")
    except Exception as e:
        logger.warning(f"Price seed failed (non-fatal): {e}")


async def _seed_macro_if_empty(pool) -> None:
    """
    Non-blocking startup hook: seed core FRED macro series if macro_series table is empty.
    Requires a valid FRED_API_KEY in the environment.
    """
    try:
        count = await pool.fetchval("SELECT COUNT(*) FROM macro_series")
        if count == 0:
            logger.info("macro_series empty — seeding FRED series on startup...")
            from financial.providers.macro import FREDProvider
            for series_id in ["CPIAUCNS", "FEDFUNDS", "GDP", "UNRATE"]:
                result = await FREDProvider(series_id=series_id).ingest(pool)
                logger.info(f"Macro seed {series_id}: {result.get('status')}, rows={result.get('rows_ingested', 0)}")
        else:
            logger.info(f"macro_series already populated ({count} rows) — seed skipped")
    except Exception as e:
        logger.warning(f"Macro seed failed (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app):
    """Startup/shutdown hooks — manage the DB connection pool and ML models."""
    logger.info("Initializing Investment Intelligence Engine...")

    # 1. Database
    pool = await db.get_pool()
    logger.info("Database pool ready")

    # 2. Seed data — gated behind AUTO_SEED_HOLDINGS_ON_STARTUP (default: true)
    auto_seed = os.getenv("AUTO_SEED_HOLDINGS_ON_STARTUP", "true").lower() == "true"
    if auto_seed:
        logger.info("AUTO_SEED_HOLDINGS_ON_STARTUP=true — scheduling background seed tasks")
        asyncio.create_task(_seed_holdings_if_empty(pool))
        asyncio.create_task(_seed_prices_if_empty(pool))
        asyncio.create_task(_seed_macro_if_empty(pool))
    else:
        logger.info("AUTO_SEED_HOLDINGS_ON_STARTUP=false — startup seeds disabled; seed manually via /financial/ingest/*")

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

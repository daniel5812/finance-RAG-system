# financial/routes/ — Financial ingestion route handlers.
# Each file owns one data domain. They all share the /financial prefix.
#
# This init combines all sub-routers so main.py can import a single object:
#   from financial.routes import router

from fastapi import APIRouter

from financial.routes.prices import router as prices_router
from financial.routes.fx import router as fx_router
from financial.routes.macro import router as macro_router
from financial.routes.filings import router as filings_router
from financial.routes.holdings import router as holdings_router
from financial.routes.portfolio import router as portfolio_router

# One combined router for main.py to include
router = APIRouter()
router.include_router(prices_router)
router.include_router(fx_router)
router.include_router(macro_router)
router.include_router(filings_router)
router.include_router(holdings_router)
router.include_router(portfolio_router)

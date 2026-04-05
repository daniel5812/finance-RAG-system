"""
backend/core/routes/portfolio.py — Per-user portfolio CRUD API.

Endpoints:
  GET    /portfolio/positions             — list caller's positions
  POST   /portfolio/positions             — add / update one position
  DELETE /portfolio/positions/{symbol}    — remove a symbol
  POST   /portfolio/positions/import      — bulk import from CSV or PDF
"""

import io
import csv
import re
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
import asyncpg

from core import db
from core.dependencies import get_current_user
from core.logger import get_logger
from financial.crud import (
    upsert_portfolio_positions,
    get_portfolio_positions_for_user,
    delete_portfolio_position,
)
from financial.schemas import PortfolioPositionCreate, PortfolioPositionResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ── GET /portfolio/positions ──────────────────────────────────────────────────

@router.get("/positions")
async def list_positions(
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(db.get_pool),
):
    """Return all portfolio positions for the authenticated user."""
    try:
        positions = await get_portfolio_positions_for_user(pool, user_id)
        logger.info(f"portfolio_list user={user_id} count={len(positions)}")
        return positions
    except Exception as e:
        logger.error(f"portfolio_list_error user={user_id} err={e}")
        raise HTTPException(500, "Failed to fetch portfolio positions")


# ── POST /portfolio/positions ─────────────────────────────────────────────────

@router.post("/positions", status_code=201)
async def add_position(
    body: PortfolioPositionCreate,
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(db.get_pool),
):
    """Add or update a single portfolio position."""
    row = {
        "user_id": user_id,
        "symbol": body.symbol.upper().strip(),
        "quantity": body.quantity,
        "cost_basis": body.cost_basis,
        "currency": body.currency.upper(),
        "account": body.account,
        "date": body.date,
        "source": "manual",
    }
    try:
        await upsert_portfolio_positions(pool, [row])
        logger.info(f"portfolio_add user={user_id} symbol={row['symbol']}")
        return {"status": "success", "rows_ingested": 1}
    except Exception as e:
        logger.error(f"portfolio_add_error user={user_id} err={e}")
        raise HTTPException(500, "Failed to add portfolio position")


# ── DELETE /portfolio/positions/{symbol} ──────────────────────────────────────

@router.delete("/positions/{symbol}")
async def remove_position(
    symbol: str,
    account: str = Query(default="default"),
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(db.get_pool),
):
    """Delete all positions for a given symbol (and optionally account) for the caller."""
    try:
        deleted = await delete_portfolio_position(pool, user_id, symbol, account)
        if deleted == 0:
            raise HTTPException(404, f"No position found for symbol {symbol.upper()}")
        logger.info(f"portfolio_delete user={user_id} symbol={symbol.upper()} rows={deleted}")
        return {"status": "success", "rows_deleted": deleted}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"portfolio_delete_error user={user_id} err={e}")
        raise HTTPException(500, "Failed to delete portfolio position")


# ── POST /portfolio/positions/import ─────────────────────────────────────────

def _parse_date(s: str) -> date:
    """Try common date formats."""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {s!r}")


def _parse_csv_rows(content: str, user_id: str) -> tuple[list[dict], list[str]]:
    """Parse CSV text → list of position dicts + list of error strings."""
    reader = csv.DictReader(io.StringIO(content))
    # Normalise header names: lowercase + strip
    fieldnames = [f.lower().strip() for f in (reader.fieldnames or [])]
    if not fieldnames:
        return [], ["CSV has no headers"]

    rows: list[dict] = []
    errors: list[str] = []

    for i, raw_row in enumerate(reader, start=2):
        norm = {k.lower().strip(): v.strip() for k, v in raw_row.items()}
        try:
            symbol = norm.get("symbol") or norm.get("ticker") or ""
            if not symbol:
                raise ValueError("missing 'symbol' or 'ticker' column")
            qty_str = norm.get("quantity") or norm.get("qty") or norm.get("shares") or ""
            if not qty_str:
                raise ValueError("missing 'quantity' column")
            qty = float(qty_str.replace(",", ""))
            if qty <= 0:
                raise ValueError(f"quantity must be > 0, got {qty}")

            cost_str = norm.get("cost_basis") or norm.get("cost") or norm.get("avg_price") or ""
            cost = float(cost_str.replace(",", "")) if cost_str else None

            date_str = norm.get("date") or norm.get("as_of") or ""
            pos_date = _parse_date(date_str) if date_str else date.today()

            rows.append({
                "user_id": user_id,
                "symbol": symbol.upper(),
                "quantity": qty,
                "cost_basis": cost,
                "currency": (norm.get("currency") or "USD").upper()[:3],
                "account": norm.get("account") or "default",
                "date": pos_date,
                "source": "import_csv",
            })
        except Exception as e:
            errors.append(f"Row {i}: {e}")

    return rows, errors


def _parse_pdf_rows(pdf_bytes: bytes, user_id: str) -> tuple[list[dict], list[str]]:
    """Extract portfolio positions from a PDF using pypdf + regex heuristics."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], ["pypdf is not installed — PDF import unavailable"]

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # Heuristic: match lines like: AAPL  10  150.50  USD  default  2024-01-15
    pattern = re.compile(
        r"\b([A-Z]{1,5})\s+"          # symbol
        r"([\d,]+\.?\d*)\s+"          # quantity
        r"([\d,]+\.?\d*)?"            # optional cost
        r".*?(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})?",  # optional date
        re.MULTILINE
    )

    rows: list[dict] = []
    errors: list[str] = []

    for m in pattern.finditer(text):
        try:
            symbol = m.group(1).strip()
            if len(symbol) < 1 or len(symbol) > 6:
                continue
            qty = float(m.group(2).replace(",", ""))
            if qty <= 0 or qty > 1_000_000:  # sanity guard
                continue
            cost = float(m.group(3).replace(",", "")) if m.group(3) else None
            date_str = m.group(4)
            pos_date = _parse_date(date_str) if date_str else date.today()
            rows.append({
                "user_id": user_id,
                "symbol": symbol,
                "quantity": qty,
                "cost_basis": cost,
                "currency": "USD",
                "account": "import_pdf",
                "date": pos_date,
                "source": "import_pdf",
            })
        except Exception as e:
            errors.append(f"PDF parse row error: {e}")

    if not rows:
        errors.append("No positions extracted from PDF — check file format")

    return rows, errors


@router.post("/positions/import", status_code=201)
async def import_positions(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(db.get_pool),
):
    """
    Bulk-import portfolio positions from a CSV or PDF file.
    CSV expected columns: symbol (or ticker), quantity (or qty/shares), cost_basis?, currency?, account?, date?
    PDF: heuristic text extraction — works best with simple tabular layouts.
    """
    filename = file.filename or ""
    content = await file.read()

    if filename.lower().endswith(".pdf"):
        rows, errors = _parse_pdf_rows(content, user_id)
    elif filename.lower().endswith(".csv"):
        text = content.decode("utf-8", errors="replace")
        rows, errors = _parse_csv_rows(text, user_id)
    else:
        raise HTTPException(400, "Unsupported file type — upload a .csv or .pdf file")

    ingested = 0
    if rows:
        try:
            ingested = await upsert_portfolio_positions(pool, rows)
            logger.info(f"portfolio_import user={user_id} file={filename} ingested={ingested}")
        except Exception as e:
            logger.error(f"portfolio_import_db_error user={user_id} err={e}")
            raise HTTPException(500, "Failed to save imported positions")

    return {
        "status": "success" if ingested > 0 else "partial",
        "rows_ingested": ingested,
        "parse_errors": errors,
    }

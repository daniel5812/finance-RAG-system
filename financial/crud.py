"""
financial/crud.py — Data Access Object (DAO) for the financial domain.

Abstracts all direct asyncpg/SQL calls out of the provider classes.
"""

from datetime import date, datetime
import json
import asyncpg


# ── LOGGING ─────────────────────────────────────────────────────────────────

async def insert_raw_ingestion_log(
    pool: asyncpg.Pool,
    provider: str,
    request_params: str,
    raw_response: str | None,
    status: str,
    rows_ingested: int,
    error_message: str | None,
):
    await pool.execute(
        """
        INSERT INTO raw_ingestion_log
            (provider, request_params, raw_response, status, rows_ingested, error_message)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        provider,
        request_params,
        raw_response,
        status,
        rows_ingested,
        error_message,
    )


# ── PRICES ──────────────────────────────────────────────────────────────────

async def upsert_prices(pool: asyncpg.Pool, rows: list[dict]) -> int:
    query = """
        INSERT INTO prices (symbol, date, open, high, low, close, volume, currency, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (symbol, date, source) DO NOTHING
    """
    args = [
        (
            r["symbol"], r["date"], r["open"], r["high"],
            r["low"], r["close"], r["volume"], r["currency"], r["source"]
        )
        for r in rows
    ]
    await pool.executemany(query, args)
    return len(rows)


async def get_last_price_date(pool: asyncpg.Pool, symbol: str, source: str) -> date | None:
    row = await pool.fetchrow(
        "SELECT MAX(date) as last_date FROM prices WHERE symbol = $1 AND source = $2",
        symbol, source,
    )
    return row["last_date"] if row and row["last_date"] else None


# ── MACRO ───────────────────────────────────────────────────────────────────

async def upsert_macro_series(pool: asyncpg.Pool, rows: list[dict]) -> int:
    query = """
        INSERT INTO macro_series (series_id, date, value, source)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (series_id, date, source) DO NOTHING
    """
    args = [
        (r["series_id"], r["date"], r["value"], r["source"])
        for r in rows
    ]
    await pool.executemany(query, args)
    return len(rows)


async def get_last_macro_date(pool: asyncpg.Pool, series_id: str, source: str) -> date | None:
    row = await pool.fetchrow(
        "SELECT MAX(date) as last_date FROM macro_series "
        "WHERE series_id = $1 AND source = $2",
        series_id,
        source,
    )
    return row["last_date"] if row and row["last_date"] else None


# ── ETF HOLDINGS ────────────────────────────────────────────────────────────

async def get_active_etfs(pool: asyncpg.Pool, symbols: list[str] | None = None) -> list[dict]:
    if symbols:
        placeholders = ", ".join(f"${i+1}" for i in range(len(symbols)))
        query = f"""
            SELECT etf_symbol, last_hash, status
            FROM etf_sources
            WHERE etf_symbol IN ({placeholders})
        """
        rows = await pool.fetch(query, *[s.upper() for s in symbols])
    else:
        rows = await pool.fetch(
            "SELECT etf_symbol, last_hash, status "
            "FROM etf_sources WHERE status = 'active'"
        )
    return [dict(r) for r in rows]


async def upsert_etf_holdings(pool: asyncpg.Pool, rows: list[dict]) -> int:
    query = """
        INSERT INTO etf_holdings
            (etf_symbol, holding_symbol, holding_name,
             weight, sector, country, date, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (etf_symbol, holding_symbol, date) DO NOTHING
    """
    args = [
        (
            r["etf_symbol"], r["holding_symbol"], r["holding_name"],
            r["weight"], r["sector"], r["country"],
            r["date"], r["source"],
        )
        for r in rows
    ]
    await pool.executemany(query, args)
    return len(rows)


async def update_etf_tracker(pool: asyncpg.Pool, etf_symbol: str, new_hash: str):
    await pool.execute(
        """
        UPDATE etf_sources
        SET last_hash = $1, last_success = $2
        WHERE etf_symbol = $3
        """,
        new_hash,
        datetime.now(),
        etf_symbol,
    )


# ── FX RATES ────────────────────────────────────────────────────────────────

async def upsert_fx_rates(pool: asyncpg.Pool, rows: list[dict]) -> int:
    query = """
        INSERT INTO fx_rates (base_currency, quote_currency, date, rate, source)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (base_currency, quote_currency, date, source) DO NOTHING
    """
    args = [
        (r["base_currency"], r["quote_currency"], r["date"], r["rate"], r["source"])
        for r in rows
    ]
    await pool.executemany(query, args)
    return len(rows)


async def get_last_fx_date(pool: asyncpg.Pool, source: str) -> date | None:
    row = await pool.fetchrow(
        "SELECT MAX(date) as last_date FROM fx_rates WHERE source = $1",
        source,
    )
    return row["last_date"] if row and row["last_date"] else None


# ── SEC FILINGS ─────────────────────────────────────────────────────────────

async def upsert_filings(pool: asyncpg.Pool, rows: list[dict]) -> int:
    query = """
        INSERT INTO filings
            (cik, ticker, company_name, accession_number,
             filing_type, filing_date, extracted_metrics, raw_json, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (accession_number) DO NOTHING
    """
    args = [
        (
            r["cik"], r["ticker"], r["company_name"],
            r["accession_number"], r["filing_type"], r["filing_date"],
            json.dumps(r["extracted_metrics"]) if r["extracted_metrics"] else None,
            json.dumps(r["raw_json"]) if r["raw_json"] else None,
            r["source"],
        )
        for r in rows
    ]
    await pool.executemany(query, args)
    return len(rows)


# ── PORTFOLIO ───────────────────────────────────────────────────────────────

async def upsert_portfolio_positions(pool: asyncpg.Pool, rows: list[dict]) -> int:
    query = """
        INSERT INTO portfolio_positions
            (symbol, quantity, cost_basis, currency, account, date, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (account, symbol, date)
        DO UPDATE SET
            quantity = EXCLUDED.quantity,
            cost_basis = EXCLUDED.cost_basis
    """
    args = [
        (
            r["symbol"], r["quantity"], r["cost_basis"],
            r["currency"], r["account"], r["date"],
            r["source"],
        )
        for r in rows
    ]
    await pool.executemany(query, args)
    return len(rows)

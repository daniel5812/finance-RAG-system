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


async def fetch_benchmark_holdings(pool: asyncpg.Pool, etf_symbol: str) -> list[dict]:
    """
    Fetch the most recent holdings snapshot for a benchmark ETF (SPY, QQQ).

    Returns list of {holding_symbol, weight} dicts ordered by weight descending.
    Weight is stored as a percentage (0–100).
    Returns empty list when no rows exist — never raises.

    NOTE: etf_holdings.sector is not read here — it is NULL for all rows from
    the current Yahoo client. Sector mapping is done via _SECTOR_MAP in the agent.
    """
    try:
        rows = await pool.fetch(
            """
            SELECT holding_symbol, weight
            FROM etf_holdings
            WHERE etf_symbol = $1
              AND date = (
                  SELECT MAX(date) FROM etf_holdings WHERE etf_symbol = $1
              )
            ORDER BY weight DESC
            """,
            etf_symbol.upper(),
        )
        return [
            {"holding_symbol": r["holding_symbol"], "weight": float(r["weight"])}
            for r in rows
        ]
    except Exception:
        return []


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
    """
    Upsert portfolio positions.
    IMPORTANT: each row dict MUST include 'user_id' for multi-tenant isolation.
    ON CONFLICT key: (user_id, symbol, account, date)
    """
    query = """
        INSERT INTO portfolio_positions
            (user_id, symbol, quantity, cost_basis, currency, account, date, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (user_id, symbol, account, date)
        DO UPDATE SET
            quantity = EXCLUDED.quantity,
            cost_basis = EXCLUDED.cost_basis
    """
    args = [
        (
            r["user_id"], r["symbol"], r["quantity"], r["cost_basis"],
            r["currency"], r["account"], r["date"],
            r["source"],
        )
        for r in rows
    ]
    await pool.executemany(query, args)
    return len(rows)


async def get_portfolio_positions_for_user(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """Fetch all portfolio positions for a specific user (owner-scoped)."""
    rows = await pool.fetch(
        """
        SELECT id, user_id, symbol, quantity, cost_basis, currency, account, date, source, created_at
        FROM portfolio_positions
        WHERE user_id = $1
        ORDER BY date DESC, symbol ASC
        """,
        user_id,
    )
    return [dict(r) for r in rows]


async def delete_portfolio_position(pool: asyncpg.Pool, user_id: str, symbol: str, account: str = "default") -> int:
    """Delete a portfolio position by symbol+account for a specific user. Returns rows deleted."""
    result = await pool.execute(
        """
        DELETE FROM portfolio_positions
        WHERE user_id = $1 AND symbol = $2 AND account = $3
        """,
        user_id, symbol.upper(), account,
    )
    # asyncpg returns 'DELETE N' string
    return int(result.split()[-1])


# ── PROACTIVE INSIGHTS & PROFILES ──────────────────────────────────────────

async def get_portfolio_positions(pool: asyncpg.Pool, user_id: str | None = None) -> list[dict]:
    if user_id:
        rows = await pool.fetch(
            "SELECT symbol, quantity, cost_basis, currency, account "
            "FROM portfolio_positions WHERE user_id = $1 "
            "ORDER BY date DESC",
            user_id
        )
    else:
        rows = await pool.fetch(
            "SELECT symbol, quantity, cost_basis, currency, account "
            "FROM portfolio_positions "
            "ORDER BY date DESC"
        )
    return [dict(r) for r in rows]

async def get_latest_macro_indicators(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        "SELECT DISTINCT ON (series_id) series_id, date, value "
        "FROM macro_series "
        "ORDER BY series_id, date DESC"
    )
    return [dict(r) for r in rows]

async def get_recent_insights(pool: asyncpg.Pool, user_id: str, limit: int = 5) -> list[dict]:
    rows = await pool.fetch(
        "SELECT id, insight_text, relevance_score, timestamp "
        "FROM insights WHERE user_id = $1 "
        "ORDER BY timestamp DESC LIMIT $2",
        user_id, limit
    )
    return [dict(r) for r in rows]

async def insert_insight(pool: asyncpg.Pool, user_id: str, text: str, score: float):
    await pool.execute(
        "INSERT INTO insights (user_id, insight_text, relevance_score) VALUES ($1, $2, $3)",
        user_id, text, score
    )

async def get_user_profile(pool: asyncpg.Pool, user_id: str) -> dict | None:
    row = await pool.fetchrow(
        "SELECT * FROM user_profiles WHERE user_id = $1",
        user_id
    )
    return dict(row) if row else None

async def upsert_user_profile(pool: asyncpg.Pool, user_id: str, data: dict):
    await pool.execute(
        """
        INSERT INTO user_profiles (
            user_id, risk_tolerance, preferred_style, interests, past_queries, custom_persona, experience_level, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            risk_tolerance = EXCLUDED.risk_tolerance,
            preferred_style = EXCLUDED.preferred_style,
            interests = EXCLUDED.interests,
            past_queries = EXCLUDED.past_queries,
            custom_persona = EXCLUDED.custom_persona,
            experience_level = EXCLUDED.experience_level,
            updated_at = NOW()
        """,
        user_id,
        data.get("risk_tolerance", "medium"),
        data.get("preferred_style", "deep"),
        json.dumps(data.get("interests", [])),
        json.dumps(data.get("past_queries", [])),
        data.get("custom_persona"),
        data.get("experience_level", "intermediate")
    )

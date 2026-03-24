import re
import json
import asyncpg
from core.logger import get_logger, trace_latency

logger = get_logger(__name__)

ALLOWED_TABLES = {"prices", "fx_rates", "macro_series", "filings", "etf_holdings", "portfolio_positions"}
FORBIDDEN_KEYWORDS = {"drop", "delete", "insert", "update", "truncate", "alter", "grant", "revoke", "create"}

@trace_latency("sql_execution_latency")
async def run_sql_query(pool: asyncpg.Pool, query: str) -> list[dict]:
    """
    Executes a read-only SQL query with strict security guards.
    """
    # 1. Basic Cleaning (preserve original for execution)
    clean_query = query.strip()
    norm_query = clean_query.lower()
    
    # 2. Security Guard: Must be SELECT
    if not norm_query.startswith("select"):
        logger.warning(f"Security: Blocked non-SELECT query: {clean_query}")
        return [{"error": "Only SELECT queries are allowed."}]
    
    # 3. Security Guard: Forbidden Keywords
    for word in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{word}\b", norm_query):
            logger.warning(f"Security: Blocked query with forbidden keyword '{word}': {clean_query}")
            return [{"error": f"Keyword '{word}' is forbidden."}]
            
    # 4. Security Guard: Table Whitelist
    # Simple regex to find words after FROM or JOIN
    tables_found = re.findall(rf"\b(?:from|join)\s+([a-zA-Z0-9_]+)", norm_query)
    for table in tables_found:
        if table not in ALLOWED_TABLES:
            logger.warning(f"Security: Blocked query with unauthorized table '{table}': {clean_query}")
            return [{"error": f"Table '{table}' is not authorized."}]
            
    # 5. Execution
    try:
        async with pool.acquire() as conn:
            # Set a low statement timeout for safety
            await conn.execute("SET statement_timeout = '5s'")
            rows = await conn.fetch(clean_query)
            logger.info(json.dumps({"event": "sql_query_success", "row_count": len(rows), "query": clean_query}))
            # Convert to list of dicts
            return [dict(r) for r in rows[:100]] # Row limit for safety
            
    except Exception as e:
        logger.error(f"SQL execution failed: {e}")
        return [{"error": str(e)}]

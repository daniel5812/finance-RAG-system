import json
import re
from core.llm_client import RoutingAgentClient
from core.logger import get_logger, trace_latency
from rag.schemas import QueryPlan, MultiQueryPlan

logger = get_logger(__name__)

ROUTER_PROMPT = """
You are a financial query router. Break down the user question into ONE OR MORE sub-queries to retrieve all necessary information.
Output ONLY a JSON object: {"plans": [{"source": "...", "query": "..."}, ...]}

CRITICAL: Currency codes (USD, ILS, EUR) and ETF symbols (SPY, QQQ) MUST ALWAYS be UPPERCASE in SQL queries.

SOURCES:
1. "sql": Use for ALL structured data queries:
   - Currency exchange / FX rates (table: fx_rates). Query MUST include base_currency and quote_currency.
     Example: "SELECT rate FROM fx_rates WHERE base_currency='USD' AND quote_currency='ILS' ORDER BY date DESC LIMIT 1"
   - ETF Holdings / Portfolio components (table: etf_holdings).
     Example: "SELECT * FROM etf_holdings WHERE etf_symbol='SPY' ORDER BY weight DESC LIMIT 10"
   - Stock/ETF historical prices (table: prices).
   - Macro indicators like GDP/CPI (table: macro_series).
     Example: "SELECT value FROM macro_series WHERE series_id='CPIAUCNS' ORDER BY date DESC LIMIT 1"
   - SEC Filing metadata (table: filings).

   The "query" field MUST be a valid PostgreSQL SELECT statement.

2. "vector": Use for unstructured document search/analysis.
   CRITICAL: This is your "Notebook". If the user asks for "advice", "interpretation", "risks", "insights", or any analytical "why/how", ALWAYS include at least one "vector" sub-query. Combine SQL data with Vector context to provide a synthesized answer.

EXAMPLES:
- Question: "Compare SPY holdings with latest USD rate."
  Output: {"plans": [
    {"source": "sql", "query": "SELECT * FROM etf_holdings WHERE etf_symbol='SPY' ORDER BY weight DESC LIMIT 10"},
    {"source": "sql", "query": "SELECT rate FROM fx_rates WHERE base_currency='USD' AND quote_currency='ILS' ORDER BY date DESC LIMIT 1"}
  ]}
"""

class QueryPlanner:
    @staticmethod
    def sanitize_sql(sql: str) -> str:
        """Enforces uppercase for common financial identifiers in SQL."""
        # Regex to find 3-letter currency codes or common ETF symbols in single quotes
        def uppercase_match(m):
            return m.group(0).upper()
        
        # Match pattern like 'usd' or 'cpiaucns' inside single quotes
        return re.sub(r"'[a-z]+'", uppercase_match, sql, flags=re.IGNORECASE)

    @staticmethod
    @trace_latency("router_latency")
    async def plan(question: str) -> MultiQueryPlan:
        """Classifies the question to determine the optimal data sources."""
        try:
            response = await RoutingAgentClient.generate_json(
                messages=[
                    {"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": question}
                ]
            )
            
            plan_dict = json.loads(response)
            logger.info(f"DEBUG_ROUTER_V3: Original LLM response: {plan_dict}")
            for p in plan_dict.get("plans", []):
                if p.get("source") == "sql":
                    p["query"] = QueryPlanner.sanitize_sql(p["query"])
            
            logger.info(json.dumps({"event": "router_decision", "decision": plan_dict}))
            return MultiQueryPlan(**plan_dict)
            
        except Exception as e:
            logger.error(f"Routing failed: {e}. LLM Response: {response if 'response' in locals() else 'N/A'}")
            return MultiQueryPlan(plans=[QueryPlan(source="vector", query=question)])

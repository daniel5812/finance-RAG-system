import json
import asyncio
from datetime import datetime
import asyncpg
from core.logger import get_logger
from financial.crud import get_portfolio_positions, get_latest_macro_indicators, insert_insight
from core.llm_client import ChatAgentClient

logger = get_logger(__name__)

class ProactiveInsightEngine:
    """
    Service to generate proactive financial insights without user queries.
    Analyzes portfolio concentration, macro risks, and trends using LLM.
    """

    @staticmethod
    async def generate_insights(pool: asyncpg.Pool, user_id: str):
        logger.info(f"Generating proactive insights for user: {user_id}")
        
        # 1. Fetch Data
        portfolio = await get_portfolio_positions(pool, user_id)
        macro = await get_latest_macro_indicators(pool)
        
        if not portfolio:
            logger.info(f"No portfolio data for user {user_id}, skipping insight generation.")
            return

        # 2. Prepare LLM Prompt
        portfolio_str = "\n".join([f"- {p['symbol']}: {p['quantity']} units" for p in portfolio])
        macro_str = "\n".join([f"- {m['series_id']}: {m['value']} (as of {m['date']})" for m in macro])
        
        prompt = f"""
You are a Proactive Financial Advisor.
Your task is to analyze the following portfolio and macro data to identify ONE critical insight.

Data:
[PORTFOLIO]
{portfolio_str}

[MACRO INDICATORS]
{macro_str}

Analyze for:
1. Concentration: Is the user too exposed to a single asset or sector (if known)?
2. Macro Risk: How do current macro trends (inflation, interest rates, FX) impact this specific portfolio?
3. Anomalies/Trends: Are there sudden changes or clear directions?

Rules:
- Be specific and data-driven.
- Keep it concise (2-3 sentences).
- If no critical risk is found, suggest a strategic optimization.
- Include a relevance score (0.0 to 1.0) based on the importance of the insight.

Respond ONLY with a JSON object:
{{
    "insight_text": "...",
    "relevance_score": 0.XX
}}
"""

        try:
            response_str = await ChatAgentClient.generate(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            # Remove possible code blocks or extra text
            clean_response = response_str.strip()
            if "```json" in clean_response:
                clean_response = clean_response.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_response:
                clean_response = clean_response.split("```")[1].split("```")[0].strip()
                
            data = json.loads(clean_response)
            
            insight_text = data.get("insight_text")
            score = data.get("relevance_score", 0.5)
            
            if insight_text:
                await insert_insight(pool, user_id, insight_text, score)
                logger.info(f"Insight generated and stored for user {user_id}: {insight_text[:50]}...")
            
        except Exception as e:
            logger.error(f"Failed to generate proactive insight for user {user_id}: {e}")

    @staticmethod
    async def run_periodic_check(pool: asyncpg.Pool):
        """
        Mock for a periodic job that runs for all users.
        """
        try:
            async with pool.acquire() as conn:
                user_ids = await conn.fetch("SELECT DISTINCT user_id FROM portfolio_positions WHERE user_id IS NOT NULL")
                for row in user_ids:
                    await ProactiveInsightEngine.generate_insights(pool, row['user_id'])
        except Exception as e:
            logger.error(f"Periodic insight check failed: {e}")

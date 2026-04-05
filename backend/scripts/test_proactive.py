import asyncio
import asyncpg
import os
import json
from dotenv import load_dotenv
from financial.services.proactive_insights_service import ProactiveInsightEngine
from financial.services.user_profile_service import UserProfileService
from rag.services.chat_service import generate_chat_response
from rag.schemas import ChatQuery, Message
import core.db as db
from core.connections import load_ml_models

load_dotenv()

async def test_proactive_features():
    print("Testing Proactive Financial Advisor Features...")
    
    # 1. Setup DB
    pool = await db.get_pool()
    user_id = "test_proactive_user_1"
    
    # 2. Mock some portfolio data for the user
    print(f"Adding mock portfolio for {user_id}...")
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM portfolio_positions WHERE user_id = $1", user_id)
        await conn.execute("""
            INSERT INTO portfolio_positions (symbol, quantity, cost_basis, currency, account, date, user_id)
            VALUES 
            ('AAPL', 10, 150.0, 'USD', 'brokerage', CURRENT_DATE, $1),
            ('MSFT', 5, 300.0, 'USD', 'brokerage', CURRENT_DATE, $1),
            ('GLD', 20, 180.0, 'USD', 'brokerage', CURRENT_DATE, $1)
        """, user_id)
        
        # Ensure user profile exists
        await conn.execute("DELETE FROM user_profiles WHERE user_id = $1", user_id)
        await conn.execute("""
            INSERT INTO user_profiles (user_id, risk_tolerance, preferred_style, interests)
            VALUES ($1, 'medium', 'deep', '["tech", "gold"]')
        """, user_id)

    # 3. Test Insight Generation
    print("Generating proactive insights...")
    await ProactiveInsightEngine.generate_insights(pool, user_id)
    
    async with pool.acquire() as conn:
        insight = await conn.fetchrow("SELECT insight_text, relevance_score FROM insights WHERE user_id = $1 ORDER BY timestamp DESC LIMIT 1", user_id)
        if insight:
            print(f"Generated Insight: {insight['insight_text']} (Score: {insight['relevance_score']})")
        else:
            print("No insight generated.")

    # 4. Test User Profile Evolution (via Chat)
    print("Testing Profile Evolution via Chat...")
    load_ml_models() # Load models for embedding/rerank mockup if needed (might be slow)
    
    # We can't easily run full RAG without full setup, but we can test the update_profile_from_query directly
    question = "I am very worried about the upcoming inflation and how it affects my gold holdings."
    print(f"Simulating query: {question}")
    await UserProfileService.update_profile_from_query(pool, user_id, question)
    
    profile = await UserProfileService.get_profile(pool, user_id)
    print(f"Updated Profile Interests: {profile['interests']}")
    print(f"Updated Risk Tolerance: {profile['risk_tolerance']}")

    # 5. Verify Explainability Parsing logic (Unit test style)
    from rag.services.chat_service import is_simulation_query
    print(f"Is 'What if I sell my Apple stocks?' a simulation? {is_simulation_query('What if I sell my Apple stocks?')}")
    
    print("Test complete.")
    await db.close_pool()

if __name__ == "__main__":
    asyncio.run(test_proactive_features())

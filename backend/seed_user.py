import asyncio
import asyncpg
import os
from dotenv import load_dotenv
from core.auth import get_password_hash

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rag:rag@localhost:5432/investdb")

async def seed():
    print(f"Connecting to {DATABASE_URL}...")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        user_id = "test_advisor_user"
        password = "password123"
        hashed_pwd = get_password_hash(password)
        
        print(f"Seeding user {user_id}...")
        await conn.execute("""
            INSERT INTO users (id, email, hashed_password, full_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET hashed_password = EXCLUDED.hashed_password
        """, user_id, "test@example.com", hashed_pwd, "Test Advisor")
        
        # Ensure profile exists
        await conn.execute("INSERT INTO user_profiles (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
        
        print("Seed successful")
        await conn.close()
    except Exception as e:
        print(f"Seed failed: {e}")

if __name__ == "__main__":
    asyncio.run(seed())

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rag:rag@localhost:5432/investdb")

async def migrate():
    print(f"Connecting to {DATABASE_URL}...")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        print("Adding user_id to portfolio_positions...")
        await conn.execute("""
            ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS user_id TEXT;
        """)
        
        print("Migration successful")
        await conn.close()
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())

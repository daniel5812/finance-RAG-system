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
        
        print("Creating users table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              TEXT         PRIMARY KEY,
                email           TEXT         UNIQUE,
                hashed_password TEXT         NOT NULL,
                full_name       TEXT,
                is_active       BOOLEAN      DEFAULT TRUE,
                is_admin        BOOLEAN      DEFAULT FALSE,
                created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            );
        """)
        
        print("Updating portfolio_positions table...")
        # Check if user_id exists, if not add it
        cols = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'portfolio_positions'")
        col_names = [r['column_name'] for r in cols]
        
        if 'user_id' not in col_names:
            await conn.execute("ALTER TABLE portfolio_positions ADD COLUMN user_id TEXT")
            # Set a default user for existing rows to avoid null constraint violation if we add it later
            await conn.execute("UPDATE portfolio_positions SET user_id = 'test_advisor_user' WHERE user_id IS NULL")
            await conn.execute("ALTER TABLE portfolio_positions ALTER COLUMN user_id SET NOT NULL")
        
        # Update unique constraint
        print("Updating unique constraint on portfolio_positions...")
        try:
            # Drop old constraint if it exists (might be named portfolio_positions_symbol_account_date_key)
            await conn.execute("ALTER TABLE portfolio_positions DROP CONSTRAINT IF EXISTS portfolio_positions_symbol_account_date_key")
            await conn.execute("ALTER TABLE portfolio_positions ADD CONSTRAINT portfolio_positions_user_symbol_account_date_key UNIQUE (user_id, symbol, account, date)")
        except Exception as ce:
            print(f"Constraint update warning: {ce}")

        print("Migration successful")
        await conn.close()
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())

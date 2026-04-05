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
        
        print("Creating insights table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS insights (
                id              BIGSERIAL PRIMARY KEY,
                user_id         TEXT         NOT NULL,
                insight_text    TEXT         NOT NULL,
                relevance_score NUMERIC(3,2),
                timestamp       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_insights_user ON insights (user_id, timestamp);
        """)
        
        print("Creating user_profiles table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id         TEXT         PRIMARY KEY,
                risk_tolerance  VARCHAR(20)  DEFAULT 'medium',
                preferred_style VARCHAR(20)  DEFAULT 'deep',
                interests       JSONB        DEFAULT '[]',
                past_queries    JSONB        DEFAULT '[]',
                custom_persona  TEXT,
                created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            );
        """)
        
        # Migrating existing data from user_settings if it exists
        try:
            print("Checking for legacy user_settings table...")
            has_user_settings = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'user_settings'
                )
            """)
            if has_user_settings:
                print("Migrating from user_settings to user_profiles...")
                await conn.execute("""
                    INSERT INTO user_profiles (user_id, custom_persona, created_at, updated_at)
                    SELECT user_id, custom_persona, updated_at, updated_at FROM user_settings
                    ON CONFLICT (user_id) DO UPDATE SET 
                        custom_persona = EXCLUDED.custom_persona,
                        updated_at = EXCLUDED.updated_at
                """)
                print("Migration from user_settings complete.")
        except Exception as e:
            print(f"Failed to migrate from user_settings: {e}")

        print("Migration successful")
        await conn.close()
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())

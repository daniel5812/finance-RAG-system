import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

# Using the Docker database URL since we're running this from the host but pointing to the forwarded port
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rag:rag@localhost:5432/investdb")

async def migrate():
    print(f"Connecting to {DATABASE_URL}...")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        print("Restoring chat_sessions table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id          UUID          PRIMARY KEY,
                user_id     TEXT          NOT NULL,
                title       TEXT          NOT NULL DEFAULT 'New Conversation',
                created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions (user_id, updated_at);
        """)
        
        print("Restoring chat_messages table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id          BIGSERIAL     PRIMARY KEY,
                session_id  UUID          NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role        VARCHAR(20)   NOT NULL,
                content     TEXT          NOT NULL,
                citations   JSONB         DEFAULT '{}',
                latency     JSONB         DEFAULT '{}',
                created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages (session_id, created_at);
        """)
        
        print("Migration successful")
        await conn.close()
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())

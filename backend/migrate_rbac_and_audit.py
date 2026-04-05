import asyncio
import asyncpg
from core.config import DATABASE_URL

async def migrate():
    print(f"Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)
    
    try:
        async with conn.transaction():
            print("1. Updating 'users' table...")
            # Check if columns exist before adding
            cols = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
            col_names = [c['column_name'] for c in cols]
            
            if 'role' not in col_names:
                await conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
                print("   Added 'role' column.")
            
            if 'scopes' not in col_names:
                await conn.execute("ALTER TABLE users ADD COLUMN scopes TEXT[] DEFAULT '{}'")
                print("   Added 'scopes' column.")
                
            # Migrate isAdmin to roles if it exists
            if 'is_admin' in col_names:
                await conn.execute("""
                    UPDATE users SET role = 'admin', scopes = '{admin:read, admin:users, admin:logs, admin:metrics}'
                    WHERE is_admin = TRUE
                """)
                # Keep is_admin for backward compatibility temporarily or drop it
                # await conn.execute("ALTER TABLE users DROP COLUMN is_admin")
                print("   Migrated is_admin to roles/scopes.")

            print("2. Creating 'audit_events' table...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id              BIGSERIAL PRIMARY KEY,
                    event_type      TEXT NOT NULL,          -- login, chat, admin_action, error
                    user_id         TEXT,
                    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    resource_id     TEXT,                   -- optional (doc_id, session_id)
                    action          TEXT NOT NULL,          -- read, write, update, delete
                    status          TEXT NOT NULL,          -- success, failure
                    request_id      TEXT,
                    metadata        JSONB DEFAULT '{}',     -- extra info
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events (user_id, timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events (event_type, timestamp)")
            print("   'audit_events' table ready.")

    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        await conn.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(migrate())

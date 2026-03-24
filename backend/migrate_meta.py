import asyncio
import asyncpg

async def migrate():
    try:
        conn = await asyncpg.connect('postgresql://rag:rag@postgres:5432/investdb')
        await conn.execute("""
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS summary TEXT;
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS key_topics JSONB DEFAULT '[]';
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS suggested_questions JSONB DEFAULT '[]';
        """)
        print("Migration successful")
        await conn.close()
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())

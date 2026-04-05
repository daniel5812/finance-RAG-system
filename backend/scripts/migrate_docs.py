import asyncio
import asyncpg

async def migrate():
    conn = await asyncpg.connect("postgresql://rag:rag@localhost:5432/investdb")
    try:
        print("Migrating uploaded_documents table...")
        await conn.execute("""
            ALTER TABLE uploaded_documents 
            ADD COLUMN IF NOT EXISTS summary TEXT,
            ADD COLUMN IF NOT EXISTS key_topics JSONB DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS suggested_questions JSONB DEFAULT '[]';
        """)
        print("Migration complete.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())

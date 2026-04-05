"""
migrate_document_folders.py — Add document_folders table and folder_id to documents.

Run once against an existing database:
    cd backend
    python scripts/migrate_document_folders.py
"""

import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rag:rag@localhost:5432/investdb")


async def run():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS document_folders (
                id          BIGSERIAL    PRIMARY KEY,
                name        VARCHAR(255) NOT NULL,
                owner_id    TEXT         NOT NULL,
                created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                UNIQUE (owner_id, name)
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_folders_owner
            ON document_folders (owner_id);
        """)
        await conn.execute("""
            ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS folder_id BIGINT
                REFERENCES document_folders(id) ON DELETE SET NULL;
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_folder
            ON documents (folder_id);
        """)
        print("Migration complete: document_folders table created, folder_id added to documents.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())

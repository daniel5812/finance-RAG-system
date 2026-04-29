-- Migration 005: Document Classification (Step 5A)
--
-- Adds deterministic classification metadata to the documents table.
-- doc_type and classification_confidence are written by the indexing worker
-- after keyword-based analysis of the filename and extracted text snippet.
--
-- Defaults:
--   doc_type                 = 'unknown'  — safe fallback before classification runs
--   classification_confidence = 'low'     — conservative until signals are found

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS doc_type                 VARCHAR NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS classification_confidence VARCHAR NOT NULL DEFAULT 'low';

-- Index: speeds up future filtering by doc_type per owner (planner vector_filter)
CREATE INDEX IF NOT EXISTS idx_documents_doc_type
    ON documents (owner_id, doc_type);

-- Migration 006: Document Holdings (Step 5B)
--
-- Stores deterministically extracted holding candidates from broker and
-- portfolio statements. These are candidates only — they never auto-import
-- into portfolio_positions or influence RAG structured_data.
--
-- source_line is stored for internal audit and is never returned via API.
-- owner_id is denormalized for fast owner-scoped queries without a join.

CREATE TABLE IF NOT EXISTS document_holdings (
    id           BIGSERIAL    PRIMARY KEY,
    document_id  UUID         NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    owner_id     TEXT         NOT NULL,
    ticker       TEXT         NOT NULL,
    quantity     NUMERIC,
    source_line  TEXT,
    confidence   TEXT         NOT NULL DEFAULT 'low',   -- 'high' | 'low'
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Owner + ticker: fast lookup when a user asks "what tickers appear in my docs?"
CREATE INDEX IF NOT EXISTS idx_doc_holdings_owner_ticker
    ON document_holdings (owner_id, ticker);

-- Document-scoped fetch (status endpoint, future holdings viewer)
CREATE INDEX IF NOT EXISTS idx_doc_holdings_doc
    ON document_holdings (document_id);

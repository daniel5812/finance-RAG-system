-- Migration 007: document_financial_statements
-- Stores structured fields extracted from savings / pension / gemel / hishtalmut statements.
-- Completely separate from portfolio_positions — never modified by this table.

CREATE TABLE IF NOT EXISTS document_financial_statements (
    id                   SERIAL PRIMARY KEY,
    document_id          UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    owner_id             TEXT        NOT NULL,

    -- Extracted fields (all nullable — partial extraction is valid)
    provider             TEXT,
    account_type         TEXT,        -- 'gemel' | 'hishtalmut' | 'pension'
    account_number       TEXT,
    report_date          DATE,
    period_start         DATE,
    period_end           DATE,
    ending_balance       NUMERIC(18, 2),
    annual_deposits      NUMERIC(18, 2),
    investment_gains     NUMERIC(18, 2),
    management_fees      NUMERIC(18, 2),
    track_name           TEXT,
    equity_exposure_pct  NUMERIC(5, 2),
    fx_exposure_pct      NUMERIC(5, 2),

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT document_financial_statements_document_id_key UNIQUE (document_id)
);

CREATE INDEX IF NOT EXISTS idx_doc_fin_stmt_owner_id    ON document_financial_statements (owner_id);
CREATE INDEX IF NOT EXISTS idx_doc_fin_stmt_document_id ON document_financial_statements (document_id);

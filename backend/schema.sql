-- ============================================================
-- Investment Intelligence Engine — Database Schema
-- ============================================================
-- Auto-runs on first `docker compose up postgres` via
-- /docker-entrypoint-initdb.d/
--
-- Design rules:
--   • Every table has created_at for audit trail
--   • Every table has source for provenance
--   • Composite UNIQUE prevents duplicate ingestion
--   • Indexes on (symbol, date) for fast time-series queries
-- ============================================================

-- 0. Identity & Access Management
CREATE TABLE IF NOT EXISTS users (
    id              TEXT         PRIMARY KEY,   -- user_id / username
    email           TEXT         UNIQUE,
    hashed_password TEXT         NOT NULL,
    full_name       TEXT,
    is_active       BOOLEAN      DEFAULT TRUE,
    is_admin        BOOLEAN      DEFAULT FALSE,
    role            TEXT         NOT NULL DEFAULT 'user',
    scopes          TEXT[]       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 1. Daily OHLCV price data (stocks, ETFs, indices)
CREATE TABLE IF NOT EXISTS prices (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(20)  NOT NULL,
    date        DATE         NOT NULL,
    open        NUMERIC(14,4),
    high        NUMERIC(14,4),
    low         NUMERIC(14,4),
    close       NUMERIC(14,4) NOT NULL,
    volume      BIGINT,
    currency    VARCHAR(3)   NOT NULL DEFAULT 'USD',
    source      VARCHAR(50)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (symbol, date, source)
);
CREATE INDEX IF NOT EXISTS idx_prices_symbol_date ON prices (symbol, date);


-- 2. Currency exchange rates
CREATE TABLE IF NOT EXISTS fx_rates (
    id              BIGSERIAL PRIMARY KEY,
    base_currency   VARCHAR(3)   NOT NULL,
    quote_currency  VARCHAR(3)   NOT NULL,
    date            DATE         NOT NULL,
    rate            NUMERIC(14,6) NOT NULL,
    source          VARCHAR(50)  NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (base_currency, quote_currency, date, source)
);
CREATE INDEX IF NOT EXISTS idx_fx_date ON fx_rates (base_currency, quote_currency, date);


-- 3. Macro indicators (FRED, etc.)
CREATE TABLE IF NOT EXISTS macro_series (
    id          BIGSERIAL PRIMARY KEY,
    series_id   VARCHAR(50)  NOT NULL,   -- e.g. "FEDFUNDS", "CPIAUCSL"
    date        DATE         NOT NULL,
    value       NUMERIC(18,6) NOT NULL,
    source      VARCHAR(50)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (series_id, date, source)
);
CREATE INDEX IF NOT EXISTS idx_macro_series_date ON macro_series (series_id, date);


-- 4. SEC company filings (10-K, 10-Q)
CREATE TABLE IF NOT EXISTS filings (
    id                  BIGSERIAL PRIMARY KEY,
    cik                 VARCHAR(20)  NOT NULL,
    ticker              VARCHAR(10),
    company_name        VARCHAR(200),
    accession_number    VARCHAR(30)  NOT NULL UNIQUE,
    filing_type         VARCHAR(10)  NOT NULL,   -- "10-K", "10-Q"
    filing_date         DATE         NOT NULL,
    extracted_metrics   JSONB,                    -- parsed financial data
    raw_json            JSONB,                    -- original API response
    source              VARCHAR(50)  NOT NULL DEFAULT 'sec_edgar',
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_filings_cik ON filings (cik, filing_date);
CREATE INDEX IF NOT EXISTS idx_filings_ticker ON filings (ticker, filing_date);


-- 5. ETF holdings breakdown
CREATE TABLE IF NOT EXISTS etf_holdings (
    id              BIGSERIAL PRIMARY KEY,
    etf_symbol      VARCHAR(20)  NOT NULL,
    holding_symbol  VARCHAR(20),
    holding_name    VARCHAR(200),
    weight          NUMERIC(8,4),              -- percentage (e.g. 6.52)
    sector          VARCHAR(100),
    country         VARCHAR(100),
    date            DATE         NOT NULL,
    source          VARCHAR(50)  NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (etf_symbol, holding_symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_etf_holdings_etf ON etf_holdings (etf_symbol, date);


-- 5b. ETF source registry (tracks which ETFs to monitor)
CREATE TABLE IF NOT EXISTS etf_sources (
    etf_symbol      VARCHAR(20) PRIMARY KEY,
    last_hash       TEXT,                       -- SHA256 of last snapshot
    last_success    TIMESTAMPTZ,                -- last successful ingestion
    status          VARCHAR(20) DEFAULT 'active' -- active / disabled
);

-- Seed default ETFs
INSERT INTO etf_sources (etf_symbol) VALUES
    ('SPY'), ('QQQ'), ('IVV'), ('VTI'), ('VOO'),
    ('VEA'), ('VWO'), ('AGG'), ('BND'), ('GLD')
ON CONFLICT DO NOTHING;


-- 6. Portfolio positions (user holdings)
CREATE TABLE IF NOT EXISTS portfolio_positions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT         NOT NULL,
    symbol      VARCHAR(20)  NOT NULL,
    quantity    NUMERIC(14,4) NOT NULL,
    cost_basis  NUMERIC(14,4),                 -- avg price paid per unit
    currency    VARCHAR(3)   NOT NULL DEFAULT 'USD',
    account     VARCHAR(50)  DEFAULT 'default', -- broker/account name
    date        DATE         NOT NULL,          -- position as-of date
    source      VARCHAR(50)  NOT NULL DEFAULT 'manual',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (user_id, symbol, account, date)
);
CREATE INDEX IF NOT EXISTS idx_portfolio_symbol ON portfolio_positions (symbol, date);


-- 7. Raw ingestion log (provenance / traceability)
CREATE TABLE IF NOT EXISTS raw_ingestion_log (
    id              BIGSERIAL PRIMARY KEY,
    provider        VARCHAR(50)  NOT NULL,      -- "stooq", "fred", "boi", etc.
    request_params  JSONB,                      -- what was requested
    raw_response    TEXT,                        -- full raw response body
    status          VARCHAR(20)  NOT NULL DEFAULT 'success',   -- success / error
    rows_ingested   INTEGER      DEFAULT 0,
    error_message   TEXT,
    fetch_time      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    version         VARCHAR(20)  DEFAULT '1.0'
);
CREATE INDEX IF NOT EXISTS idx_ingestion_provider ON raw_ingestion_log (provider, fetch_time);


-- 8a. Document Folders (user-defined organization)
CREATE TABLE IF NOT EXISTS document_folders (
    id          BIGSERIAL    PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    owner_id    TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, name)
);
CREATE INDEX IF NOT EXISTS idx_document_folders_owner ON document_folders (owner_id);


-- 8b. Document pipeline — uploaded financial documents (PDF-first)
--
-- Design notes:
--   • UUID primary key: safe to expose to clients (non-sequential integers leak volume)
--   • storage_path: local disk path today → S3 key tomorrow (change config, not schema)
--   • status lifecycle: pending_processing → processing → completed | failed
--   • owner_id: placeholder for real user identity (auth system comes later)
--   • folder_id: optional, references document_folders; SET NULL on folder delete
CREATE TABLE IF NOT EXISTS documents (
    id                  UUID         PRIMARY KEY,
    owner_id            TEXT         NOT NULL,
    original_filename   TEXT         NOT NULL,
    content_type        TEXT         NOT NULL DEFAULT 'application/pdf',
    file_size_bytes     BIGINT,
    storage_path        TEXT,                          -- local path or future S3 key
    status              TEXT         NOT NULL DEFAULT 'pending_processing',
    summary             TEXT,                          -- AI-generated summary
    key_topics          JSONB,                         -- AI-extracted topics
    suggested_questions JSONB,                         -- AI-suggested follow-ups
    folder_id           BIGINT       REFERENCES document_folders(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents (owner_id, created_at);
CREATE INDEX IF NOT EXISTS idx_documents_folder ON documents (folder_id);


-- 9. Proactive Insights
CREATE TABLE IF NOT EXISTS insights (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT         NOT NULL,
    insight_text    TEXT         NOT NULL,
    relevance_score NUMERIC(3,2),               -- 0.0 to 1.0 (e.g., 0.85)
    timestamp       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_insights_user ON insights (user_id, timestamp);


-- 10. User Profiles (Evolutionary context)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id         TEXT         PRIMARY KEY,
    risk_tolerance  VARCHAR(20)  DEFAULT 'medium', -- low, medium, high
    preferred_style VARCHAR(20)  DEFAULT 'deep',   -- simple, deep
    interests       JSONB        DEFAULT '[]',     -- topics (e.g. ["inflation", "tech"])
    past_queries    JSONB        DEFAULT '[]',     -- track history for personalization
    custom_persona  TEXT,                          -- manual persona instructions
    experience_level VARCHAR(20) DEFAULT 'intermediate', -- beginner, intermediate, expert
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 11. Chat Sessions (Persistence)
CREATE TABLE IF NOT EXISTS chat_sessions (
    id                   UUID          PRIMARY KEY,
    user_id              TEXT          NOT NULL,
    title                TEXT          NOT NULL DEFAULT 'New Conversation',
    conversation_summary TEXT,                        -- rolling LLM-generated summary of older messages
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions (user_id, updated_at);

-- Migration: add conversation_summary to existing chat_sessions tables
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS conversation_summary TEXT;

-- 12. Chat Messages (Session History)
CREATE TABLE IF NOT EXISTS chat_messages (
    id                  BIGSERIAL     PRIMARY KEY,
    session_id          UUID          NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role                VARCHAR(20)   NOT NULL,         -- user / assistant / system
    content             TEXT          NOT NULL,
    citations           JSONB         DEFAULT '{}',
    latency             JSONB         DEFAULT '{}',
    suggested_questions JSONB         DEFAULT '[]',
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages (session_id, created_at);

-- Migration: add suggested_questions to existing chat_messages tables
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS suggested_questions JSONB DEFAULT '[]';


-- 13. Audit Events (RBAC audit trail)
CREATE TABLE IF NOT EXISTS audit_events (
    id              BIGSERIAL    PRIMARY KEY,
    event_type      TEXT         NOT NULL,          -- login, chat, admin_action, error
    user_id         TEXT,
    timestamp       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resource_id     TEXT,                            -- optional (doc_id, session_id)
    action          TEXT         NOT NULL,           -- read, write, update, delete
    status          TEXT         NOT NULL,           -- success, failure
    request_id      TEXT,
    metadata        JSONB        DEFAULT '{}',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events (user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events (event_type, timestamp);

-- schema.sql — reference schema. tracker/models.py (SQLAlchemy) mirrors this and is the source of truth.
-- Written for Postgres (Neon); SQLAlchemy handles the SQLite differences locally.
-- Licensing note: we store daily percent changes only, never price history. News search results are never stored.

-- Stocks users may follow: the 100 largest US companies. Top 20 flagged for the demo.
CREATE TABLE universe (
    ticker          TEXT PRIMARY KEY,
    cik             TEXT NOT NULL,              -- SEC company ID, zero-padded to 10 digits
    name            TEXT NOT NULL,
    industry        TEXT NOT NULL,              -- own labels or EDGAR SIC-based (not GICS); peer group for shared notes
    sic_code        TEXT,
    region          TEXT NOT NULL DEFAULT 'US', -- for later: ADRs and non-US stocks
    market_cap_rank INTEGER,
    is_demo         BOOLEAN NOT NULL DEFAULT FALSE,
    active          BOOLEAN NOT NULL DEFAULT TRUE,  -- FALSE = dropped out of the top 100: current followers keep it, nobody new can add it
    updated_at      TIMESTAMP NOT NULL
);

-- Every exchange-listed ticker seen in the SEC's company_tickers_exchange file. Used to spot new listings (IPOs).
-- is_candidate = a new US domestic filer; it joins the weekly market-cap ranking alongside config/candidates.csv.
CREATE TABLE listings_seen (
    ticker        TEXT PRIMARY KEY,
    cik           TEXT NOT NULL,
    name          TEXT NOT NULL,
    exchange      TEXT,
    sic_code      TEXT,
    is_candidate  BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen    TIMESTAMP NOT NULL
);

CREATE TABLE users (
    email       TEXT PRIMARY KEY,               -- from Google sign-in; no passwords stored
    created_at  TIMESTAMP NOT NULL,
    last_login  TIMESTAMP
);

CREATE TABLE user_watchlist (
    email     TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    ticker    TEXT NOT NULL REFERENCES universe(ticker),
    added_at  TIMESTAMP NOT NULL,
    PRIMARY KEY (email, ticker)
);

-- Outlets a user wants coverage links from (domains from config/outlets.yaml). No rows = all outlets.
CREATE TABLE user_outlets (
    email   TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    domain  TEXT NOT NULL,                      -- e.g. wsj.com
    PRIMARY KEY (email, domain)
);

-- Daily percent change per stock and for the S&P 500 (ticker 'SPY'). The only price-derived data we keep.
CREATE TABLE daily_returns (
    ticker      TEXT NOT NULL,                  -- no foreign key: includes 'SPY'
    date        DATE NOT NULL,
    return_pct  NUMERIC NOT NULL,
    PRIMARY KEY (ticker, date)
);

-- One row per trading day: did the S&P 500 move enough to raise a market alert?
CREATE TABLE market_days (
    date              DATE PRIMARY KEY,
    index_return_pct  NUMERIC NOT NULL,
    level             TEXT NOT NULL             -- none, alert, major
);

-- Figures from EDGAR XBRL (companyfacts), only the tags we use. Numbers for the AI come from here, never from the model.
-- One row per (tag, period end, duration): a 6-month and a 12-month figure can share an end date.
CREATE TABLE fundamentals (
    ticker          TEXT NOT NULL REFERENCES universe(ticker),
    metric          TEXT NOT NULL,              -- XBRL tag, e.g. Revenues, OperatingIncomeLoss
    period_end      DATE NOT NULL,
    duration_days   INTEGER NOT NULL,           -- 0 for balance-sheet (point in time) figures
    fiscal_period   TEXT NOT NULL,              -- Q1, Q2, Q3, FY (of the filing that reported it)
    form            TEXT NOT NULL,              -- 10-Q, 10-K
    value           NUMERIC NOT NULL,
    unit            TEXT NOT NULL,              -- USD, shares, USD/shares
    accession       TEXT NOT NULL,
    filed_at        DATE NOT NULL,              -- latest filing wins when a period is restated
    PRIMARY KEY (ticker, metric, period_end, duration_days)
);

CREATE TABLE filings (
    accession     TEXT PRIMARY KEY,
    ticker        TEXT NOT NULL REFERENCES universe(ticker),
    form          TEXT NOT NULL,                -- 10-Q, 10-K, 8-K
    items         TEXT,                         -- 8-K items, e.g. "2.02,9.01"
    filed_at      TIMESTAMP NOT NULL,
    period_end    DATE,
    url           TEXT NOT NULL,
    processed_at  TIMESTAMP                     -- NULL = profile update still queued
);

-- A detected large move and where the ladder placed it.
CREATE TABLE moves (
    id                   BIGSERIAL PRIMARY KEY,
    ticker               TEXT NOT NULL REFERENCES universe(ticker),
    date                 DATE NOT NULL,
    return_pct           NUMERIC NOT NULL,
    scope                TEXT NOT NULL,         -- market, industry, stock
    market_return_pct    NUMERIC,
    industry_return_pct  NUMERIC,               -- average of tracked peers
    note_id              BIGINT,                -- ai_outputs row shown for this move (shared for market / industry)
    status               TEXT NOT NULL,         -- pending, explained, no_catalyst, recheck
    recheck_after        TIMESTAMP,
    UNIQUE (ticker, date)
);

-- Every AI result we keep: profiles, market / industry / stock notes, Monday/Thursday summaries.
-- sources holds only what the note cites: id, url, outlet. No titles, snippets or article text.
CREATE TABLE ai_outputs (
    id           BIGSERIAL PRIMARY KEY,
    kind         TEXT NOT NULL,                 -- profile, stock_note, industry_note, market_note, summary
    scope_key    TEXT NOT NULL,                 -- ticker, 'industry:<name>', or 'market'
    model        TEXT NOT NULL,
    input_hash   TEXT NOT NULL,                 -- same inputs -> reuse, don't call again
    content      JSONB NOT NULL,                -- validated pydantic output
    sources      JSONB NOT NULL,                -- [{id, url, outlet}]
    confidence   TEXT,                          -- high, medium, low
    created_at   TIMESTAMP NOT NULL,
    valid_until  TIMESTAMP,
    UNIQUE (kind, scope_key, input_hash)
);

ALTER TABLE moves ADD CONSTRAINT fk_moves_note FOREIGN KEY (note_id) REFERENCES ai_outputs(id);

CREATE TABLE company_facts (
    ticker         TEXT PRIMARY KEY REFERENCES universe(ticker),
    qid            TEXT NOT NULL,               -- Wikidata item
    logo_url       TEXT,                        -- Wikimedia Commons file
    ceo            TEXT,
    ceo_since      DATE,
    headquarters   TEXT,
    country        TEXT,
    founded        INTEGER,
    employees      INTEGER,
    website        TEXT,
    wikipedia_url  TEXT,
    fetched_at     TIMESTAMP NOT NULL
);

CREATE TABLE refresh_requests (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    ticker        TEXT NOT NULL REFERENCES universe(ticker),
    kind          TEXT NOT NULL,                -- refresh, coverage_search
    requested_at  TIMESTAMP NOT NULL,
    status        TEXT NOT NULL                 -- served_from_cache, done, refused_cap, failed
);

CREATE TABLE usage_log (
    id             BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMP NOT NULL,
    job            TEXT NOT NULL,               -- daily, summary, profiles, refresh, coverage
    model          TEXT,                        -- NULL for search-only rows
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    search_calls   INTEGER NOT NULL DEFAULT 0,  -- summed per month for the search cap
    cost_usd       NUMERIC(10,4) NOT NULL       -- summed per month for the AI budget stop
);

CREATE INDEX idx_returns_date            ON daily_returns (date);
CREATE INDEX idx_universe_industry       ON universe (industry);
CREATE INDEX idx_filings_unprocessed     ON filings (processed_at) WHERE processed_at IS NULL;
CREATE INDEX idx_moves_date              ON moves (date DESC);
CREATE INDEX idx_ai_outputs_lookup       ON ai_outputs (kind, scope_key, created_at DESC);
CREATE INDEX idx_refresh_user_day        ON refresh_requests (email, requested_at);
CREATE INDEX idx_usage_month             ON usage_log (created_at);

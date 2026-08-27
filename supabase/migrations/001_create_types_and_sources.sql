-- 001: Shared enums + sources table.
--
-- NOTE: the PRD lists `entries` as migration 001 and `sources` as 002, but
-- `entries.source_id` has a FK to `sources(id)` and `sources.category` uses the
-- `entry_category` enum. Postgres needs both to exist first, so the enums and
-- `sources` are created here and `entries` moves to 002.

CREATE TYPE entry_category AS ENUM (
  'yojana', 'naukri', 'tender', 'rule', 'auction', 'notice'
);

CREATE TYPE entry_urgency AS ENUM (
  'low', 'medium', 'high', 'critical'
);

CREATE TYPE entry_status AS ENUM (
  'pending', 'approved', 'rejected', 'expired'
);

CREATE TABLE sources (
  id SERIAL PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  url TEXT NOT NULL,
  category entry_category,
  state VARCHAR(4) DEFAULT 'ALL',
  scraper_key VARCHAR(100) NOT NULL UNIQUE,  -- Maps to Python scraper class
  frequency_minutes INTEGER DEFAULT 60,

  -- Health tracking
  last_run_at TIMESTAMPTZ,
  last_success_at TIMESTAMPTZ,
  last_failure_at TIMESTAMPTZ,
  last_error TEXT,
  consecutive_failures INTEGER DEFAULT 0,
  total_entries_scraped INTEGER DEFAULT 0,

  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

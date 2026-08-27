-- 002: The core content table.

CREATE TABLE entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id INTEGER REFERENCES sources(id),

  -- Content
  title TEXT NOT NULL,
  summary_en TEXT NOT NULL DEFAULT '',
  summary_hi TEXT,
  original_text TEXT,            -- Raw scraped text (for debugging)

  -- Classification
  category entry_category NOT NULL,
  state VARCHAR(4) NOT NULL,     -- RJ, UP, MH, ALL, DL etc.
  district VARCHAR(100),
  department VARCHAR(200),

  -- Links
  original_url TEXT NOT NULL,
  pdf_url TEXT,                  -- If notification is a PDF
  snapshot_path TEXT,            -- Supabase Storage path to page screenshot

  -- Dates
  deadline DATE,
  published_date DATE,           -- When govt published it

  -- Structured data
  budget_amount BIGINT,          -- In paisa (Rs 1 = 100 paisa)
  salary_range JSONB,            -- {"min": 25000, "max": 80000}
  eligibility JSONB,             -- {"age_min": 18, "age_max": 32, "education": "graduate"}
  key_details JSONB,             -- Flexible extra data

  -- AI metadata
  ai_confidence FLOAT DEFAULT 0,
  urgency entry_urgency DEFAULT 'low',
  ai_input_tokens INTEGER DEFAULT 0,
  ai_output_tokens INTEGER DEFAULT 0,
  ai_processed_at TIMESTAMPTZ,
  ai_attempts INTEGER DEFAULT 0,

  -- Deduplication
  content_hash VARCHAR(64) NOT NULL,  -- SHA256 of title+url+date

  -- Status
  status entry_status DEFAULT 'pending',
  reviewed_by UUID REFERENCES auth.users(id),
  reviewed_at TIMESTAMPTZ,

  -- Timestamps
  published_at TIMESTAMPTZ,      -- When we published it on our feed
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(content_hash)
);

-- NOTE: summary_en is NOT NULL in the PRD, but scrapers insert rows before the
-- AI has written a summary. A '' default keeps the constraint honest while
-- letting the two-phase (scrape -> summarize) pipeline work.

CREATE INDEX idx_entries_category ON entries(category);
CREATE INDEX idx_entries_state ON entries(state);
CREATE INDEX idx_entries_status ON entries(status);
CREATE INDEX idx_entries_deadline ON entries(deadline) WHERE deadline IS NOT NULL;
CREATE INDEX idx_entries_published_at ON entries(published_at DESC);
CREATE INDEX idx_entries_category_state ON entries(category, state);

-- Full-text search index
ALTER TABLE entries ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(summary_en, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(department, '')), 'C')
  ) STORED;

CREATE INDEX idx_entries_search ON entries USING gin(search_vector);

-- Trigram index for fuzzy search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_entries_title_trgm ON entries USING gin(title gin_trgm_ops);

-- Keep updated_at fresh
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER entries_set_updated_at
  BEFORE UPDATE ON entries
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

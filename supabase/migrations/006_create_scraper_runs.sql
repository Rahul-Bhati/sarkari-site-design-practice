-- 006: scraper_runs (observability)

CREATE TABLE scraper_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id INTEGER REFERENCES sources(id),

  started_at TIMESTAMPTZ DEFAULT NOW(),
  finished_at TIMESTAMPTZ,

  status VARCHAR(20) DEFAULT 'running',  -- running, success, failed
  entries_found INTEGER DEFAULT 0,
  entries_new INTEGER DEFAULT 0,
  entries_duplicate INTEGER DEFAULT 0,
  error TEXT,

  duration_seconds FLOAT
);

CREATE INDEX idx_scraper_runs_source ON scraper_runs(source_id, started_at DESC);

-- Daily AI spend tracking (Milestone 3, Step 3.4)
CREATE TABLE ai_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_id UUID REFERENCES entries(id) ON DELETE SET NULL,
  model VARCHAR(100) NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_inr NUMERIC(10, 4) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ai_usage_created ON ai_usage(created_at DESC);

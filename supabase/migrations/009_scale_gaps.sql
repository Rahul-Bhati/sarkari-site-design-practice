-- 009: tables for the scale-gaps spec.
-- Do not apply this file until it is explicitly confirmed. Nothing in the
-- running app reads these tables yet.

-- A deadline change on a notice we already stored.
CREATE TABLE entry_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_id UUID NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_entry_events_entry ON entry_events(entry_id, created_at DESC);

-- Cron enqueues. A worker claims a row with FOR UPDATE SKIP LOCKED.
CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  payload JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',
  run_after TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  locked_at TIMESTAMPTZ,
  locked_by TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_jobs_claim ON jobs(status, run_after);

-- One row per subscriber per channel per digest day. The sender drains this.
CREATE TABLE notification_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id UUID NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
  channel TEXT NOT NULL,
  digest_date DATE NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (subscriber_id, channel, digest_date)
);

-- Hindi summaries are searchable without an English stemmer.
ALTER TABLE entries ADD COLUMN search_vector_hi tsvector
  GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(summary_hi, ''))
  ) STORED;

CREATE INDEX idx_entries_search_hi ON entries USING gin(search_vector_hi);

ALTER TABLE entry_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_outbox ENABLE ROW LEVEL SECURITY;

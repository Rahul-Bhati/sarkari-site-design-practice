-- 010: one follow per signed-in user and notice.
-- Do not apply this file until it is explicitly confirmed.

CREATE TABLE notice_follows (
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  entry_id UUID NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  email VARCHAR(255),
  remind_days INTEGER NOT NULL DEFAULT 3,
  last_deadline DATE,
  reminded_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, entry_id)
);

CREATE INDEX idx_notice_follows_entry ON notice_follows(entry_id);

ALTER TABLE notice_follows ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own follows"
  ON notice_follows FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

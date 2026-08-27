-- 008: Admin flagging + search/stats RPCs used by the API layer.

CREATE TABLE admin_users (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email VARCHAR(255),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE admin_users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can check own admin row"
  ON admin_users FOR SELECT
  USING (user_id = auth.uid());

-- Full-text search with a trigram fallback when tsquery finds nothing.
-- Milestone 4, Step 4.4.
CREATE OR REPLACE FUNCTION search_entries(
  q TEXT,
  categories TEXT[] DEFAULT NULL,
  states TEXT[] DEFAULT NULL,
  lim INTEGER DEFAULT 20,
  off INTEGER DEFAULT 0
)
RETURNS TABLE (LIKE entries, rank REAL, total_count BIGINT)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  fts_hits BIGINT;
BEGIN
  SELECT count(*) INTO fts_hits
  FROM entries e
  WHERE e.status = 'approved'
    AND e.search_vector @@ plainto_tsquery('english', q)
    AND (categories IS NULL OR e.category::text = ANY(categories))
    AND (states IS NULL OR e.state = ANY(states));

  IF fts_hits > 0 THEN
    RETURN QUERY
      SELECT e.*,
             ts_rank(e.search_vector, plainto_tsquery('english', q)) AS rank,
             fts_hits AS total_count
      FROM entries e
      WHERE e.status = 'approved'
        AND e.search_vector @@ plainto_tsquery('english', q)
        AND (categories IS NULL OR e.category::text = ANY(categories))
        AND (states IS NULL OR e.state = ANY(states))
      ORDER BY rank DESC, e.published_at DESC NULLS LAST
      LIMIT lim OFFSET off;
  ELSE
    -- Fuzzy fallback: trigram similarity on the title.
    RETURN QUERY
      SELECT e.*,
             similarity(e.title, q) AS rank,
             count(*) OVER () AS total_count
      FROM entries e
      WHERE e.status = 'approved'
        AND e.title % q
        AND (categories IS NULL OR e.category::text = ANY(categories))
        AND (states IS NULL OR e.state = ANY(states))
      ORDER BY rank DESC
      LIMIT lim OFFSET off;
  END IF;
END;
$$;

-- Landing page stats. Milestone 4, Step 4.3.
CREATE OR REPLACE FUNCTION feed_stats()
RETURNS JSON
LANGUAGE sql
STABLE
AS $$
  SELECT json_build_object(
    'total_entries', (SELECT count(*) FROM entries WHERE status = 'approved'),
    'entries_today', (
      SELECT count(*) FROM entries
      WHERE status = 'approved'
        AND published_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata')
    ),
    'states_covered', (SELECT count(DISTINCT state) FROM entries WHERE status = 'approved'),
    'sources_active', (SELECT count(*) FROM sources WHERE is_active),
    'categories', COALESCE((
      SELECT json_object_agg(category, n)
      FROM (
        SELECT category, count(*) AS n
        FROM entries WHERE status = 'approved'
        GROUP BY category
      ) c
    ), '{}'::json)
  );
$$;

-- Expire entries whose deadline has passed. Called nightly by the scheduler.
CREATE OR REPLACE FUNCTION expire_stale_entries()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
  n INTEGER;
BEGIN
  UPDATE entries
  SET status = 'expired'
  WHERE status = 'approved'
    AND deadline IS NOT NULL
    AND deadline < current_date;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

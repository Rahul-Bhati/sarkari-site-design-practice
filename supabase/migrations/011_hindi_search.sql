-- 011: make search find Hindi, and fix the return type that made it raise.
--
-- Two separate faults, both in search_entries:
--
-- 1. `RETURNS TABLE (LIKE entries, rank REAL, total_count BIGINT)` does not
--    copy the columns of `entries`. Postgres reads `LIKE` as an identifier, so
--    the function declared one column literally named "like" of the composite
--    type `entries`. The body returns `e.*` expanded to one column per field,
--    so every call raised:
--        structure of query does not match function result type
--    Search has never returned a row through this RPC.
--
-- 2. Only `search_vector` was consulted, and that vector is built from title,
--    summary_en, and department. `summary_hi` was never indexed, so a query in
--    Devanagari matched nothing — and the trigram fallback runs on `title`,
--    which is usually English, so it matched nothing either.
--
-- The entry now comes back as jsonb. A composite return type silently breaks
-- the moment a column is added to `entries` — which 009 did — and this version
-- cannot break that way. It also means `original_text` and `content_hash` are
-- dropped in the database rather than trusted to be stripped in the API.

-- The Hindi summary joins the fuzzy fallback, so it needs the same trigram
-- index the title already has.
CREATE INDEX IF NOT EXISTS idx_entries_summary_hi_trgm
  ON entries USING gin(summary_hi gin_trgm_ops);

-- One place that decides what a search result may expose.
CREATE OR REPLACE FUNCTION entry_public(e entries)
RETURNS JSONB
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT to_jsonb(e)
       - 'search_vector'
       - 'search_vector_hi'
       - 'original_text'
       - 'content_hash';
$$;

CREATE OR REPLACE FUNCTION search_entries(
  q TEXT,
  categories TEXT[] DEFAULT NULL,
  states TEXT[] DEFAULT NULL,
  lim INTEGER DEFAULT 20,
  off INTEGER DEFAULT 0
)
RETURNS TABLE (entry JSONB, rank REAL, total_count BIGINT)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  -- English stems the query; Hindi has no stock stemmer, so 'simple' only
  -- lowercases and splits. That matches how search_vector_hi is built.
  en_query tsquery := plainto_tsquery('english', q);
  hi_query tsquery := plainto_tsquery('simple', q);
  fts_hits BIGINT;
BEGIN
  SELECT count(*) INTO fts_hits
  FROM entries e
  WHERE e.status = 'approved'
    AND (e.search_vector @@ en_query OR e.search_vector_hi @@ hi_query)
    AND (categories IS NULL OR e.category::text = ANY(categories))
    AND (states IS NULL OR e.state = ANY(states));

  IF fts_hits > 0 THEN
    RETURN QUERY
      SELECT entry_public(e),
             -- A row matching in either language ranks on its better match,
             -- so an English hit is not diluted by a zero Hindi score.
             GREATEST(
               ts_rank(e.search_vector, en_query),
               ts_rank(e.search_vector_hi, hi_query)
             ) AS rank,
             fts_hits AS total_count
      FROM entries e
      WHERE e.status = 'approved'
        AND (e.search_vector @@ en_query OR e.search_vector_hi @@ hi_query)
        AND (categories IS NULL OR e.category::text = ANY(categories))
        AND (states IS NULL OR e.state = ANY(states))
      ORDER BY rank DESC, e.published_at DESC NULLS LAST
      LIMIT lim OFFSET off;
  ELSE
    -- Fuzzy fallback for a typo or a partial word. Hindi is compared against
    -- the Hindi summary, because the title is usually English.
    RETURN QUERY
      SELECT entry_public(e),
             GREATEST(
               similarity(e.title, q),
               similarity(coalesce(e.summary_hi, ''), q)
             ) AS rank,
             count(*) OVER () AS total_count
      FROM entries e
      WHERE e.status = 'approved'
        AND (e.title % q OR coalesce(e.summary_hi, '') % q)
        AND (categories IS NULL OR e.category::text = ANY(categories))
        AND (states IS NULL OR e.state = ANY(states))
      ORDER BY rank DESC
      LIMIT lim OFFSET off;
  END IF;
END;
$$;

COMMENT ON FUNCTION search_entries IS
  'Full-text search over English and Hindi summaries, with a trigram fallback. '
  'Returns the entry as jsonb so adding a column to entries cannot break it.';

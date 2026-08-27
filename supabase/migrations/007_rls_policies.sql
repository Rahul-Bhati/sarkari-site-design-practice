-- 007: Row Level Security
--
-- The backend uses the service role key, which bypasses RLS entirely. These
-- policies govern what the frontend's anon key can see.

-- Entries: everyone can read approved entries, only admins can write
ALTER TABLE entries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read approved entries"
  ON entries FOR SELECT
  USING (status = 'approved');

CREATE POLICY "Service role has full access"
  ON entries FOR ALL
  USING (auth.role() = 'service_role');

-- Sources: public read (used by the "source" label on feed cards)
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read sources"
  ON sources FOR SELECT
  USING (true);

CREATE POLICY "Service role has full access to sources"
  ON sources FOR ALL
  USING (auth.role() = 'service_role');

-- Subscribers: users can only see their own
ALTER TABLE subscribers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own subscriptions"
  ON subscribers FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "Users can update own subscriptions"
  ON subscribers FOR UPDATE
  USING (user_id = auth.uid());

CREATE POLICY "Service role has full access to subscribers"
  ON subscribers FOR ALL
  USING (auth.role() = 'service_role');

-- NOTE: two PRD policies are deliberately NOT included.
--
-- 1. "Users can read own subscriptions ... OR user_id IS NULL" would let any
--    anon visitor read every anonymous subscriber's email and phone number.
-- 2. "Anyone can insert subscription WITH CHECK (true)" would let anyone write
--    arbitrary rows, including plan='thekedar'.
--
-- Anonymous subscribe goes through POST /api/subscribe on the backend instead,
-- which validates input, rate limits, and uses the service role key.

-- Bookmarks
ALTER TABLE bookmarks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own bookmarks"
  ON bookmarks FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- Internal tables: service role only, no public policies at all.
ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraper_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY;

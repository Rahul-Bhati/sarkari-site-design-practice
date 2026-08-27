-- SarkariSaar — full schema + seed, generated 2026-08-27.
-- Paste into the Supabase SQL editor and Run, on a fresh project.

-- ============================================================
-- supabase/migrations/001_create_types_and_sources.sql
-- ============================================================
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

-- ============================================================
-- supabase/migrations/002_create_entries.sql
-- ============================================================
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

-- ============================================================
-- supabase/migrations/003_create_subscribers.sql
-- ============================================================
-- 003: subscribers

CREATE TYPE sub_channel AS ENUM ('email', 'whatsapp', 'both');
CREATE TYPE sub_frequency AS ENUM ('instant', 'daily', 'weekly');
CREATE TYPE user_plan AS ENUM ('free', 'pro', 'thekedar');

CREATE TABLE subscribers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id),  -- NULL for anonymous subscribers

  email VARCHAR(255),
  phone VARCHAR(15),                        -- With country code: +919876543210

  channel sub_channel DEFAULT 'email',
  frequency sub_frequency DEFAULT 'weekly',

  -- Filter preferences
  categories entry_category[] DEFAULT '{}',  -- Empty = all categories
  states VARCHAR(4)[] DEFAULT '{}',          -- Empty = all states
  keywords TEXT[] DEFAULT '{}',

  -- Thekedar-specific filters
  min_budget BIGINT,
  max_budget BIGINT,
  departments TEXT[] DEFAULT '{}',

  plan user_plan DEFAULT 'free',

  -- Status
  is_active BOOLEAN DEFAULT true,
  is_verified BOOLEAN DEFAULT false,
  phone_verified BOOLEAN DEFAULT false,
  verification_token VARCHAR(64),
  unsubscribe_token VARCHAR(64) DEFAULT encode(gen_random_bytes(32), 'hex'),
  last_digest_at TIMESTAMPTZ,

  -- Razorpay
  razorpay_customer_id VARCHAR(100),
  razorpay_subscription_id VARCHAR(100),
  plan_expires_at TIMESTAMPTZ,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  CONSTRAINT email_or_phone CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE UNIQUE INDEX idx_subscribers_email ON subscribers(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX idx_subscribers_phone ON subscribers(phone) WHERE phone IS NOT NULL;
CREATE INDEX idx_subscribers_active ON subscribers(is_active) WHERE is_active = true;
CREATE INDEX idx_subscribers_unsub_token ON subscribers(unsubscribe_token);
CREATE INDEX idx_subscribers_verif_token ON subscribers(verification_token);

-- NOTE: the PRD's email/phone indexes are plain; they are UNIQUE here so the
-- "duplicate subscription updates the existing row" acceptance test is enforced
-- by the database rather than only by application code.

CREATE TRIGGER subscribers_set_updated_at
  BEFORE UPDATE ON subscribers
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- supabase/migrations/004_create_bookmarks.sql
-- ============================================================
-- 004: bookmarks

CREATE TABLE bookmarks (
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  entry_id UUID REFERENCES entries(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, entry_id)
);

CREATE INDEX idx_bookmarks_user ON bookmarks(user_id, created_at DESC);

-- ============================================================
-- supabase/migrations/005_create_notification_log.sql
-- ============================================================
-- 005: notification_log

CREATE TYPE notification_status AS ENUM ('queued', 'sent', 'delivered', 'failed');

CREATE TABLE notification_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id UUID REFERENCES subscribers(id) ON DELETE CASCADE,
  entry_ids UUID[] NOT NULL,                     -- Can be a digest of multiple entries
  channel VARCHAR(20) NOT NULL,
  status notification_status DEFAULT 'queued',

  -- Tracking
  sent_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ,
  error TEXT,
  retry_count INTEGER DEFAULT 0,

  -- WhatsApp/Email specifics
  external_message_id VARCHAR(200),              -- Gupshup/Resend message ID

  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notif_log_subscriber ON notification_log(subscriber_id);
CREATE INDEX idx_notif_log_status ON notification_log(status);
CREATE INDEX idx_notif_log_external ON notification_log(external_message_id);

-- ============================================================
-- supabase/migrations/006_create_scraper_runs.sql
-- ============================================================
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

-- ============================================================
-- supabase/migrations/007_rls_policies.sql
-- ============================================================
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

-- ============================================================
-- supabase/migrations/008_admin_and_rpc.sql
-- ============================================================
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

-- ============================================================
-- supabase/seed.sql
-- ============================================================
-- Test data for local development. Safe to re-run (idempotent on scraper_key /
-- content_hash).
--
-- The entries below are illustrative fixtures modelled on the shape of real
-- portal listings. They are NOT scraped records -- run the scrapers for those.

-- is_active drives which scrapers the runner picks up.
--   pib, ssc  -> verified working against the live portals
--   raj_eproc -> inactive: every tender listing on the portal is CAPTCHA-gated
--                (see app/scrapers/sources/raj_eproc.py for the evidence and
--                the alternatives). Flip to true once a CAPTCHA-free route exists.
--   cppp, gem -> inactive: no scraper implemented yet (Milestone 11)
INSERT INTO sources (name, url, category, state, scraper_key, frequency_minutes, is_active) VALUES
  ('Press Information Bureau',         'https://pib.gov.in/allRel.aspx?reg=3&lang=1', 'notice', 'ALL', 'pib',        60,  true),
  ('Staff Selection Commission',       'https://ssc.gov.in',                          'naukri', 'ALL', 'ssc',       120,  true),
  ('Rajasthan eProcurement',           'https://eproc.rajasthan.gov.in',              'tender', 'RJ',  'raj_eproc',  60,  false),
  ('Central Public Procurement Portal','https://eprocure.gov.in/epublish/app',        'tender', 'ALL', 'cppp',       60,  false),
  ('Government e-Marketplace',         'https://gem.gov.in',                          'tender', 'ALL', 'gem',       120,  false)
ON CONFLICT (scraper_key) DO NOTHING;

INSERT INTO entries (
  source_id, title, summary_en, summary_hi, category, state, department,
  original_url, deadline, published_date, budget_amount, urgency, ai_confidence,
  content_hash, status, published_at, key_details
) VALUES
  ((SELECT id FROM sources WHERE scraper_key='raj_eproc'),
   'Road widening work on Jaipur-Sikar highway, 12 km stretch',
   'The Rajasthan PWD has invited bids to widen a 12 km stretch of the Jaipur-Sikar highway. Estimated cost is Rs 8.4 crore and the EMD is Rs 16.8 lakh. Contractors with Class A registration can apply until the closing date.',
   'राजस्थान PWD ने जयपुर-सीकर हाईवे के 12 किमी हिस्से को चौड़ा करने के लिए टेंडर निकाला है। अनुमानित लागत 8.4 करोड़ रुपये है और EMD 16.8 लाख रुपये है। क्लास A ठेकेदार अंतिम तिथि तक आवेदन कर सकते हैं।',
   'tender', 'RJ', 'Public Works Department',
   'https://eproc.rajasthan.gov.in/nicgep/app?tender=RJ-PWD-2026-0412',
   CURRENT_DATE + 5, CURRENT_DATE - 2, 840000000, 'critical', 0.94,
   'seed_hash_0001', 'approved', NOW() - INTERVAL '2 days',
   '{"emd_amount": 1680000, "tender_id": "RJ-PWD-2026-0412", "helpline": "0141-2385791"}'),

  ((SELECT id FROM sources WHERE scraper_key='ssc'),
   'SSC CGL 2026: 8,326 vacancies announced for graduates',
   'The Staff Selection Commission has announced 8,326 vacancies in the Combined Graduate Level examination 2026. Any graduate aged 18 to 32 can apply. Pay ranges from Rs 25,500 to Rs 81,100 per month depending on the post.',
   'कर्मचारी चयन आयोग ने CGL परीक्षा 2026 में 8,326 पदों की घोषणा की है। 18 से 32 वर्ष का कोई भी स्नातक आवेदन कर सकता है। पद के अनुसार वेतन 25,500 से 81,100 रुपये प्रति माह है।',
   'naukri', 'ALL', 'Staff Selection Commission',
   'https://ssc.gov.in/notice/cgl-2026-notification',
   CURRENT_DATE + 21, CURRENT_DATE - 4, NULL, 'high', 0.97,
   'seed_hash_0002', 'approved', NOW() - INTERVAL '4 days',
   '{"vacancies": 8326, "application_link": "https://ssc.gov.in/apply"}'),

  ((SELECT id FROM sources WHERE scraper_key='pib'),
   'PM Kisan 19th instalment released to 9.8 crore farmers',
   'The government has released the 19th instalment of PM Kisan Samman Nidhi. Rs 2,000 has been credited directly to the bank accounts of 9.8 crore farmers. Farmers who have not received it should complete their eKYC at the nearest CSC.',
   'सरकार ने PM किसान सम्मान निधि की 19वीं किस्त जारी कर दी है। 9.8 करोड़ किसानों के बैंक खाते में सीधे 2,000 रुपये भेजे गए हैं। जिन किसानों को नहीं मिला है वे नजदीकी CSC पर eKYC पूरा करें।',
   'yojana', 'ALL', 'Ministry of Agriculture and Farmers Welfare',
   'https://pib.gov.in/PressReleasePage.aspx?PRID=2099431',
   NULL, CURRENT_DATE - 1, 2000000000000, 'medium', 0.96,
   'seed_hash_0003', 'approved', NOW() - INTERVAL '1 day',
   '{"helpline": "155261", "application_link": "https://pmkisan.gov.in"}'),

  ((SELECT id FROM sources WHERE scraper_key='gem'),
   'Supply of 4,200 desktop computers to Uttar Pradesh schools',
   'The UP education department needs 4,200 desktop computers for government schools. The contract is worth about Rs 21 crore. Bids must be submitted on the GeM portal before the closing date.',
   'यूपी शिक्षा विभाग को सरकारी स्कूलों के लिए 4,200 डेस्कटॉप कंप्यूटर चाहिए। यह अनुबंध लगभग 21 करोड़ रुपये का है। बोली अंतिम तिथि से पहले GeM पोर्टल पर जमा करनी होगी।',
   'tender', 'UP', 'Department of Basic Education',
   'https://gem.gov.in/bid/GEM-2026-B-4412907',
   CURRENT_DATE + 12, CURRENT_DATE - 3, 210000000000, 'high', 0.91,
   'seed_hash_0004', 'approved', NOW() - INTERVAL '3 days',
   '{"tender_id": "GEM-2026-B-4412907", "emd_amount": 4200000}'),

  ((SELECT id FROM sources WHERE scraper_key='pib'),
   'New income tax rules for salaried employees from April',
   'Standard deduction for salaried taxpayers rises to Rs 75,000 under the new tax regime from 1 April. Employees do not need to file anything extra; employers will apply the change automatically in TDS calculations.',
   'नई कर व्यवस्था में वेतनभोगी करदाताओं के लिए स्टैंडर्ड डिडक्शन 1 अप्रैल से बढ़कर 75,000 रुपये हो गया है। कर्मचारियों को अलग से कुछ नहीं भरना है, नियोक्ता TDS में यह बदलाव अपने आप लागू करेंगे।',
   'rule', 'ALL', 'Central Board of Direct Taxes',
   'https://pib.gov.in/PressReleasePage.aspx?PRID=2099102',
   NULL, CURRENT_DATE - 6, NULL, 'medium', 0.93,
   'seed_hash_0005', 'approved', NOW() - INTERVAL '6 days', '{}'),

  ((SELECT id FROM sources WHERE scraper_key='cppp'),
   'Construction of 60-bed community health centre in Nagpur',
   'The Maharashtra health department has floated a tender for a 60-bed community health centre in Nagpur district. Estimated cost is Rs 14.7 crore with an EMD of Rs 29.4 lakh. Completion period is 18 months.',
   'महाराष्ट्र स्वास्थ्य विभाग ने नागपुर जिले में 60 बेड के सामुदायिक स्वास्थ्य केंद्र के लिए टेंडर निकाला है। अनुमानित लागत 14.7 करोड़ रुपये और EMD 29.4 लाख रुपये है। काम 18 महीने में पूरा करना है।',
   'tender', 'MH', 'Public Health Department',
   'https://eprocure.gov.in/epublish/app?tender=MH-PHD-2026-1180',
   CURRENT_DATE + 18, CURRENT_DATE - 5, 1470000000, 'high', 0.92,
   'seed_hash_0006', 'approved', NOW() - INTERVAL '5 days',
   '{"emd_amount": 2940000, "tender_id": "MH-PHD-2026-1180"}'),

  ((SELECT id FROM sources WHERE scraper_key='ssc'),
   'SSC MTS 2026: 4,887 posts for 10th pass candidates',
   'The Staff Selection Commission is hiring 4,887 Multi-Tasking Staff. Candidates who have passed class 10 and are aged 18 to 25 can apply. Salary is Rs 18,000 to Rs 22,000 per month.',
   'कर्मचारी चयन आयोग 4,887 मल्टी-टास्किंग स्टाफ की भर्ती कर रहा है। 10वीं पास और 18 से 25 वर्ष के उम्मीदवार आवेदन कर सकते हैं। वेतन 18,000 से 22,000 रुपये प्रति माह है।',
   'naukri', 'ALL', 'Staff Selection Commission',
   'https://ssc.gov.in/notice/mts-2026-notification',
   CURRENT_DATE + 3, CURRENT_DATE - 8, NULL, 'critical', 0.95,
   'seed_hash_0007', 'approved', NOW() - INTERVAL '8 days',
   '{"vacancies": 4887}'),

  ((SELECT id FROM sources WHERE scraper_key='pib'),
   'Free coaching scheme for SC and OBC students opens',
   'The social justice ministry is offering free coaching for competitive exams to SC and OBC students whose family income is under Rs 8 lakh a year. Around 3,500 seats are available across empanelled institutes.',
   'सामाजिक न्याय मंत्रालय SC और OBC छात्रों को प्रतियोगी परीक्षाओं की मुफ्त कोचिंग दे रहा है, जिनकी पारिवारिक आय 8 लाख रुपये सालाना से कम है। सूचीबद्ध संस्थानों में लगभग 3,500 सीटें हैं।',
   'yojana', 'ALL', 'Ministry of Social Justice and Empowerment',
   'https://pib.gov.in/PressReleasePage.aspx?PRID=2098877',
   CURRENT_DATE + 40, CURRENT_DATE - 7, NULL, 'low', 0.89,
   'seed_hash_0008', 'approved', NOW() - INTERVAL '7 days',
   '{"application_link": "https://coaching.dosje.gov.in", "vacancies": 3500}'),

  ((SELECT id FROM sources WHERE scraper_key='raj_eproc'),
   'Solar pump subsidy for farmers in Jodhpur division',
   'Rajasthan is offering a 60 percent subsidy on solar water pumps for farmers in Jodhpur division. A 5 HP pump costs about Rs 1.2 lakh after subsidy. Farmers need a Jan Aadhaar card and land records to apply.',
   'राजस्थान जोधपुर संभाग के किसानों को सोलर पंप पर 60 प्रतिशत सब्सिडी दे रहा है। सब्सिडी के बाद 5 HP पंप की कीमत लगभग 1.2 लाख रुपये है। आवेदन के लिए जन आधार कार्ड और जमीन के कागज चाहिए।',
   'yojana', 'RJ', 'Department of Agriculture',
   'https://rajkisan.rajasthan.gov.in/scheme/solar-pump-2026',
   CURRENT_DATE + 25, CURRENT_DATE - 3, NULL, 'medium', 0.90,
   'seed_hash_0009', 'approved', NOW() - INTERVAL '3 days',
   '{"helpline": "0141-2227849"}'),

  ((SELECT id FROM sources WHERE scraper_key='cppp'),
   'Auction of 14 abandoned vehicles by Delhi Police',
   'Delhi Police is auctioning 14 unclaimed vehicles seized over the past two years. The auction is open to the public and the base price for two-wheelers starts at Rs 8,000. Inspection is allowed two days before the auction.',
   'दिल्ली पुलिस पिछले दो साल में जब्त 14 लावारिस वाहनों की नीलामी कर रही है। नीलामी सभी के लिए खुली है और दोपहिया वाहनों की बेस कीमत 8,000 रुपये से शुरू है। नीलामी से दो दिन पहले वाहन देखे जा सकते हैं।',
   'auction', 'DL', 'Delhi Police',
   'https://eprocure.gov.in/epublish/app?auction=DL-POL-2026-0071',
   CURRENT_DATE + 9, CURRENT_DATE - 2, NULL, 'high', 0.88,
   'seed_hash_0010', 'approved', NOW() - INTERVAL '2 days', '{}'),

  ((SELECT id FROM sources WHERE scraper_key='pib'),
   'Aadhaar update deadline extended for free online changes',
   'Free online Aadhaar document updates have been extended by six months. Residents can update proof of identity and address at no cost on the myAadhaar portal. Updates at enrolment centres still cost Rs 50.',
   'मुफ्त ऑनलाइन आधार दस्तावेज अपडेट की सुविधा छह महीने बढ़ा दी गई है। myAadhaar पोर्टल पर पहचान और पते का प्रमाण मुफ्त में अपडेट किया जा सकता है। नामांकन केंद्र पर अपडेट के लिए 50 रुपये लगेंगे।',
   'notice', 'ALL', 'Unique Identification Authority of India',
   'https://pib.gov.in/PressReleasePage.aspx?PRID=2098120',
   CURRENT_DATE + 170, CURRENT_DATE - 9, NULL, 'low', 0.94,
   'seed_hash_0011', 'approved', NOW() - INTERVAL '9 days',
   '{"application_link": "https://myaadhaar.uidai.gov.in", "helpline": "1947"}'),

  ((SELECT id FROM sources WHERE scraper_key='gem'),
   'Annual maintenance contract for street lights in Indore',
   'Indore Municipal Corporation needs an agency to maintain 42,000 LED street lights for one year. The contract value is around Rs 3.6 crore. Firms with at least three years of experience are eligible.',
   'इंदौर नगर निगम को एक साल तक 42,000 LED स्ट्रीट लाइट के रखरखाव के लिए एजेंसी चाहिए। अनुबंध की राशि लगभग 3.6 करोड़ रुपये है। कम से कम तीन साल का अनुभव रखने वाली फर्में पात्र हैं।',
   'tender', 'MP', 'Indore Municipal Corporation',
   'https://gem.gov.in/bid/GEM-2026-B-4390122',
   CURRENT_DATE + 6, CURRENT_DATE - 4, 36000000000, 'critical', 0.90,
   'seed_hash_0012', 'approved', NOW() - INTERVAL '4 days',
   '{"emd_amount": 720000, "tender_id": "GEM-2026-B-4390122"}'),

  ((SELECT id FROM sources WHERE scraper_key='ssc'),
   'Railway Recruitment Board: 11,558 technician posts',
   'The Railway Recruitment Board has opened applications for 11,558 technician posts across zones. ITI holders aged 18 to 30 are eligible. Starting pay is Rs 19,900 per month plus allowances.',
   'रेलवे भर्ती बोर्ड ने सभी जोन में 11,558 तकनीशियन पदों के लिए आवेदन शुरू किए हैं। 18 से 30 वर्ष के ITI धारक पात्र हैं। शुरुआती वेतन 19,900 रुपये प्रति माह और भत्ते हैं।',
   'naukri', 'ALL', 'Railway Recruitment Board',
   'https://rrbcdg.gov.in/technician-2026',
   CURRENT_DATE + 15, CURRENT_DATE - 5, NULL, 'high', 0.96,
   'seed_hash_0013', 'approved', NOW() - INTERVAL '5 days',
   '{"vacancies": 11558}'),

  ((SELECT id FROM sources WHERE scraper_key='pib'),
   'Ayushman Bharat now covers all citizens above 70',
   'Everyone aged 70 and above is now covered under Ayushman Bharat regardless of income. The scheme gives Rs 5 lakh of free hospital treatment per family per year. Eligible seniors should register on the PMJAY portal.',
   '70 वर्ष और उससे अधिक आयु के सभी लोग अब आय की परवाह किए बिना आयुष्मान भारत में शामिल हैं। इस योजना में हर परिवार को साल में 5 लाख रुपये तक मुफ्त इलाज मिलता है। पात्र बुजुर्ग PMJAY पोर्टल पर पंजीकरण करें।',
   'yojana', 'ALL', 'Ministry of Health and Family Welfare',
   'https://pib.gov.in/PressReleasePage.aspx?PRID=2097655',
   NULL, CURRENT_DATE - 11, NULL, 'medium', 0.95,
   'seed_hash_0014', 'approved', NOW() - INTERVAL '11 days',
   '{"application_link": "https://beneficiary.nha.gov.in", "helpline": "14555"}'),

  ((SELECT id FROM sources WHERE scraper_key='raj_eproc'),
   'Drinking water pipeline for 38 villages in Barmer',
   'The Rajasthan water department has invited tenders to lay a drinking water pipeline serving 38 villages in Barmer district. Estimated cost is Rs 22.5 crore and work must be completed in 24 months.',
   'राजस्थान जल विभाग ने बाड़मेर जिले के 38 गांवों में पेयजल पाइपलाइन बिछाने के लिए टेंडर निकाला है। अनुमानित लागत 22.5 करोड़ रुपये है और काम 24 महीने में पूरा करना है।',
   'tender', 'RJ', 'Public Health Engineering Department',
   'https://eproc.rajasthan.gov.in/nicgep/app?tender=RJ-PHED-2026-0908',
   CURRENT_DATE + 30, CURRENT_DATE - 1, 2250000000, 'medium', 0.93,
   'seed_hash_0015', 'approved', NOW() - INTERVAL '1 day',
   '{"emd_amount": 4500000, "tender_id": "RJ-PHED-2026-0908"}'),

  ((SELECT id FROM sources WHERE scraper_key='pib'),
   'New traffic fine rates take effect across Karnataka',
   'Karnataka has revised traffic penalty amounts. Riding without a helmet now costs Rs 1,000 and driving without insurance costs Rs 2,000. Repeat offences within a year attract double the fine.',
   'कर्नाटक ने ट्रैफिक जुर्माने की राशि बदल दी है। बिना हेलमेट चलाने पर अब 1,000 रुपये और बिना बीमा गाड़ी चलाने पर 2,000 रुपये जुर्माना है। एक साल में दोबारा गलती करने पर जुर्माना दोगुना होगा।',
   'rule', 'KA', 'Transport Department',
   'https://pib.gov.in/PressReleasePage.aspx?PRID=2097201',
   NULL, CURRENT_DATE - 13, NULL, 'low', 0.91,
   'seed_hash_0016', 'approved', NOW() - INTERVAL '13 days', '{}'),

  ((SELECT id FROM sources WHERE scraper_key='cppp'),
   'Bihar to hire 2,100 contractual health workers',
   'The Bihar health society is recruiting 2,100 ANMs and lab technicians on contract. Diploma holders aged 21 to 42 can apply. The monthly honorarium is Rs 24,000.',
   'बिहार स्वास्थ्य समिति 2,100 ANM और लैब टेक्नीशियन की संविदा पर भर्ती कर रही है। 21 से 42 वर्ष के डिप्लोमा धारक आवेदन कर सकते हैं। मासिक मानदेय 24,000 रुपये है।',
   'naukri', 'BR', 'State Health Society Bihar',
   'https://statehealthsocietybihar.org/recruitment-2026',
   CURRENT_DATE + 11, CURRENT_DATE - 2, NULL, 'high', 0.87,
   'seed_hash_0017', 'approved', NOW() - INTERVAL '2 days',
   '{"vacancies": 2100}'),

  -- Two low-confidence rows so the admin review queue has something to show.
  ((SELECT id FROM sources WHERE scraper_key='pib'),
   'Corrigendum regarding notification dated 14.03.2026',
   'A correction has been issued to an earlier notification. The details of what changed are unclear from the source text.',
   'पहले जारी अधिसूचना में सुधार किया गया है। स्रोत से यह स्पष्ट नहीं है कि क्या बदला है।',
   'notice', 'ALL', 'Ministry of Finance',
   'https://pib.gov.in/PressReleasePage.aspx?PRID=2099998',
   NULL, CURRENT_DATE, NULL, 'low', 0.42,
   'seed_hash_0018', 'pending', NULL, '{}'),

  ((SELECT id FROM sources WHERE scraper_key='gem'),
   'Bid document for miscellaneous office supplies',
   'A tender has been floated for assorted office supplies. Quantity and estimated value were not stated in the listing.',
   'विविध कार्यालय सामग्री के लिए टेंडर निकाला गया है। सूची में मात्रा और अनुमानित मूल्य नहीं दिया गया है।',
   'tender', 'ALL', 'Government e-Marketplace',
   'https://gem.gov.in/bid/GEM-2026-B-4400018',
   CURRENT_DATE + 14, CURRENT_DATE, NULL, 'low', 0.55,
   'seed_hash_0019', 'pending', NULL, '{}')
ON CONFLICT (content_hash) DO NOTHING;


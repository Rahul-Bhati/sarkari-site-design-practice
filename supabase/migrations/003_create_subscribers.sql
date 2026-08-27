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

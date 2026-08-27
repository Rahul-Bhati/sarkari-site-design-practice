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

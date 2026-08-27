"""Plan gating and webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services.payment import (
    PLAN_PRICES_INR,
    effective_plan,
    has_feature,
    verify_webhook_signature,
)


class TestPlanGating:
    def test_free_plan_has_only_the_basics(self):
        free = {"plan": "free"}
        assert has_feature(free, "web_feed")
        assert has_feature(free, "weekly_email")
        assert not has_feature(free, "instant_alerts")
        assert not has_feature(free, "daily_email")

    def test_pro_unlocks_daily_and_whatsapp(self):
        pro = {"plan": "pro"}
        assert has_feature(pro, "daily_email")
        assert has_feature(pro, "whatsapp_digest")
        assert has_feature(pro, "bookmarks")
        assert not has_feature(pro, "instant_alerts")

    def test_thekedar_unlocks_everything_pro_has_plus_alerts(self):
        thekedar = {"plan": "thekedar"}
        assert has_feature(thekedar, "instant_alerts")
        assert has_feature(thekedar, "tender_comparison")
        assert has_feature(thekedar, "daily_email")

    def test_expired_paid_plan_reads_as_free(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        subscriber = {"plan": "thekedar", "plan_expires_at": yesterday}
        assert effective_plan(subscriber) == "free"
        assert not has_feature(subscriber, "instant_alerts")

    def test_unexpired_paid_plan_stays_active(self):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        subscriber = {"plan": "pro", "plan_expires_at": tomorrow}
        assert effective_plan(subscriber) == "pro"

    def test_missing_expiry_does_not_downgrade(self):
        assert effective_plan({"plan": "pro", "plan_expires_at": None}) == "pro"

    def test_unparsable_expiry_does_not_downgrade(self):
        assert effective_plan({"plan": "pro", "plan_expires_at": "soon"}) == "pro"


class TestPricing:
    def test_prd_prices(self):
        assert PLAN_PRICES_INR[("pro", "monthly")] == 199
        assert PLAN_PRICES_INR[("thekedar", "monthly")] == 499

    def test_yearly_beats_twelve_months(self):
        for plan in ("pro", "thekedar"):
            assert PLAN_PRICES_INR[(plan, "yearly")] < PLAN_PRICES_INR[(plan, "monthly")] * 12


class TestWebhookSignature:
    SECRET = "test-webhook-secret"
    BODY = b'{"event":"subscription.activated"}'

    def _sign(self, body: bytes) -> str:
        return hmac.new(self.SECRET.encode(), body, hashlib.sha256).hexdigest()

    def test_accepts_a_correct_signature(self):
        settings.razorpay_webhook_secret = self.SECRET
        assert verify_webhook_signature(self.BODY, self._sign(self.BODY)) is True

    def test_rejects_a_tampered_body(self):
        settings.razorpay_webhook_secret = self.SECRET
        assert verify_webhook_signature(b'{"event":"hacked"}', self._sign(self.BODY)) is False

    def test_rejects_empty_signature(self):
        settings.razorpay_webhook_secret = self.SECRET
        assert verify_webhook_signature(self.BODY, "") is False

    def test_fails_closed_when_secret_is_unset(self):
        settings.razorpay_webhook_secret = ""
        assert verify_webhook_signature(self.BODY, self._sign(self.BODY)) is False

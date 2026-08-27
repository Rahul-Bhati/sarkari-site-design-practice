"""Razorpay subscriptions — Milestone 10."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from app.config import settings
from app.database import db

log = logging.getLogger(__name__)

Plan = Literal["pro", "thekedar"]
Period = Literal["monthly", "yearly"]

PLAN_PRICES_INR = {
    ("pro", "monthly"): 199,
    ("pro", "yearly"): 1999,
    ("thekedar", "monthly"): 499,
    ("thekedar", "yearly"): 4999,
}
TOTAL_COUNT = {"monthly": 12, "yearly": 5}

PLAN_FEATURES = {
    "free": {"web_feed", "weekly_email"},
    "pro": {
        "web_feed", "weekly_email", "daily_email", "whatsapp_digest",
        "custom_filters", "bookmarks", "deadline_reminders",
    },
    "thekedar": {
        "web_feed", "weekly_email", "daily_email", "whatsapp_digest",
        "custom_filters", "bookmarks", "deadline_reminders",
        "instant_alerts", "tender_filters", "tender_comparison",
    },
}


def _client():
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set")
    import razorpay

    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def _plan_id(plan: Plan, period: Period) -> str:
    mapping = {
        ("pro", "monthly"): settings.razorpay_plan_pro_monthly,
        ("pro", "yearly"): settings.razorpay_plan_pro_yearly,
        ("thekedar", "monthly"): settings.razorpay_plan_thekedar_monthly,
        ("thekedar", "yearly"): settings.razorpay_plan_thekedar_yearly,
    }
    plan_id = mapping.get((plan, period))
    if not plan_id:
        raise RuntimeError(f"No Razorpay plan id configured for {plan}/{period}")
    return plan_id


def create_subscription(subscriber_id: str, plan: Plan, period: Period) -> dict[str, Any]:
    subscription = _client().subscription.create(
        {
            "plan_id": _plan_id(plan, period),
            "total_count": TOTAL_COUNT[period],
            "customer_notify": 1,
            "notes": {"subscriber_id": subscriber_id, "plan": plan, "period": period},
        }
    )

    db().table("subscribers").update(
        {"razorpay_subscription_id": subscription["id"]}
    ).eq("id", subscriber_id).execute()

    return {
        "subscription_id": subscription["id"],
        "short_url": subscription.get("short_url"),
        "amount_inr": PLAN_PRICES_INR[(plan, period)],
        "key_id": settings.razorpay_key_id,
    }


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Razorpay signs webhooks with HMAC-SHA256 over the raw body."""
    if not settings.razorpay_webhook_secret:
        log.error("RAZORPAY_WEBHOOK_SECRET is not set — rejecting webhook")
        return False
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def handle_event(event: dict[str, Any]) -> dict[str, Any]:
    """Apply a Razorpay subscription event to the subscriber row."""
    kind = event.get("event", "")
    entity = (
        event.get("payload", {}).get("subscription", {}).get("entity")
        or event.get("payload", {}).get("payment", {}).get("entity")
        or {}
    )
    subscription_id = entity.get("id") if kind.startswith("subscription") else entity.get(
        "subscription_id"
    )
    notes = entity.get("notes") or {}
    subscriber_id = notes.get("subscriber_id")

    subscriber = _find_subscriber(subscription_id, subscriber_id)
    if subscriber is None:
        log.warning("razorpay event %s for unknown subscription %s", kind, subscription_id)
        return {"handled": False, "reason": "subscriber not found"}

    updates: dict[str, Any] = {}
    if kind in ("subscription.activated", "subscription.charged", "subscription.resumed"):
        updates["plan"] = notes.get("plan") or subscriber.get("plan") or "pro"
        updates["razorpay_subscription_id"] = subscription_id
        if end := entity.get("current_end") or entity.get("end_at"):
            updates["plan_expires_at"] = datetime.fromtimestamp(end, timezone.utc).isoformat()
    elif kind in ("subscription.cancelled", "subscription.completed", "subscription.halted"):
        updates["plan"] = "free"
        updates["plan_expires_at"] = None
    elif kind == "payment.failed":
        log.warning("payment failed for subscriber %s", subscriber["id"])
        return {"handled": True, "action": "payment_failed", "subscriber_id": subscriber["id"]}

    if updates:
        db().table("subscribers").update(updates).eq("id", subscriber["id"]).execute()

    return {"handled": True, "event": kind, "subscriber_id": subscriber["id"], "updates": updates}


def _find_subscriber(subscription_id: str | None, subscriber_id: str | None) -> dict | None:
    if subscriber_id:
        res = db().table("subscribers").select("*").eq("id", subscriber_id).limit(1).execute()
        if res.data:
            return res.data[0]
    if subscription_id:
        res = (
            db()
            .table("subscribers")
            .select("*")
            .eq("razorpay_subscription_id", subscription_id)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
    return None


def effective_plan(subscriber: dict[str, Any]) -> str:
    """Plan after expiry is applied — an expired paid plan reads as free."""
    plan = subscriber.get("plan") or "free"
    expires = subscriber.get("plan_expires_at")
    if plan != "free" and expires:
        try:
            if datetime.fromisoformat(expires.replace("Z", "+00:00")) < datetime.now(timezone.utc):
                return "free"
        except ValueError:
            pass
    return plan


def has_feature(subscriber: dict[str, Any], feature: str) -> bool:
    return feature in PLAN_FEATURES.get(effective_plan(subscriber), set())


def expire_lapsed_plans() -> int:
    """Nightly downgrade of plans whose expiry has passed."""
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db()
        .table("subscribers")
        .update({"plan": "free", "plan_expires_at": None})
        .neq("plan", "free")
        .not_.is_("plan_expires_at", "null")
        .lt("plan_expires_at", now)
        .execute()
    )
    return len(res.data or [])

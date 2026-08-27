"""Inbound webhooks: Razorpay payments, Gupshup WhatsApp."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.database import db
from app.models.user import Plan
from app.services import payment, whatsapp
from app.services.auth import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["payments"])


class CreateSubscription(BaseModel):
    plan: Plan = Field(description="pro | thekedar")
    period: str = Field(default="monthly", pattern="^(monthly|yearly)$")


@router.post("/payments/create-subscription")
async def create_subscription(body: CreateSubscription, user: dict = Depends(current_user)):
    if body.plan == Plan.free:
        raise HTTPException(status_code=400, detail="Free plan needs no subscription")

    subscriber = _subscriber_for_user(user)
    try:
        return payment.create_subscription(subscriber["id"], body.plan.value, body.period)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/payments/plan")
async def my_plan(user: dict = Depends(current_user)):
    subscriber = _subscriber_for_user(user)
    plan = payment.effective_plan(subscriber)
    return {
        "plan": plan,
        "expires_at": subscriber.get("plan_expires_at"),
        "features": sorted(payment.PLAN_FEATURES.get(plan, set())),
    }


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request, x_razorpay_signature: str | None = Header(default=None)
):
    raw = await request.body()
    if not payment.verify_webhook_signature(raw, x_razorpay_signature or ""):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = await request.json()
    log.info("razorpay webhook: %s", event.get("event"))
    return payment.handle_event(event)


@router.post("/webhooks/gupshup")
async def gupshup_webhook(request: Request):
    """Gupshup posts both delivery receipts and inbound messages here."""
    body: dict[str, Any] = await request.json()
    kind = body.get("type")

    if kind == "message":
        payload = body.get("payload", {})
        phone = payload.get("source") or payload.get("sender", {}).get("phone", "")
        text = (payload.get("payload") or {}).get("text", "")
        result = whatsapp.handle_incoming(phone, text)
        log.info("gupshup inbound from %s -> %s", phone, result["action"])
        return {"success": True, **result}

    if kind in ("message-event", "billing-event"):
        payload = body.get("payload", {})
        message_id = payload.get("gsId") or payload.get("id") or ""
        status = payload.get("type") or ""
        if message_id and status:
            whatsapp.handle_delivery_status(message_id, status)
        return {"success": True, "recorded": status}

    return {"success": True, "ignored": kind}


def _subscriber_for_user(user: dict) -> dict:
    res = db().table("subscribers").select("*").eq("user_id", user["id"]).limit(1).execute()
    if res.data:
        return res.data[0]

    if not user.get("email"):
        raise HTTPException(status_code=400, detail="Account has no email address")

    # A logged-in user who never subscribed still needs a subscriber row to
    # hang a plan off.
    existing = db().table("subscribers").select("*").eq("email", user["email"]).limit(1).execute()
    if existing.data:
        db().table("subscribers").update({"user_id": user["id"]}).eq(
            "id", existing.data[0]["id"]
        ).execute()
        return {**existing.data[0], "user_id": user["id"]}

    created = (
        db()
        .table("subscribers")
        .insert(
            {
                "user_id": user["id"],
                "email": user["email"],
                "is_verified": True,
                "channel": "email",
                "frequency": "weekly",
            }
        )
        .execute()
    )
    return created.data[0]

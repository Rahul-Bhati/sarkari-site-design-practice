"""Subscription management — Milestone 7.

Anonymous subscribe goes through here rather than straight to Supabase, so the
input is validated, rate limited, and written with the service key.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.config import settings
from app.database import db
from app.models.user import SubscribeRequest, SubscribeResponse
from app.services import notifier

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["subscribe"])

# PRD: max 3 subscribe attempts per email per hour. In-process is fine for a
# single Railway instance; move to Redis when we run more than one.
RATE_LIMIT = 3
RATE_WINDOW_SECONDS = 3600
_attempts: dict[str, deque[float]] = defaultdict(deque)


def _rate_limited(key: str) -> bool:
    now = time.time()
    bucket = _attempts[key]
    while bucket and bucket[0] < now - RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT:
        return True
    bucket.append(now)
    return False


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(body: SubscribeRequest, request: Request, background: BackgroundTasks):
    identity = (body.email or body.phone or request.client.host or "anon").lower()
    if _rate_limited(identity):
        raise HTTPException(
            status_code=429, detail="Too many subscribe attempts. Try again in an hour."
        )

    existing = _find_existing(body.email, body.phone)
    token = notifier.new_token()

    payload = {
        "email": body.email,
        "phone": body.phone,
        "channel": body.channel.value,
        "frequency": body.frequency.value,
        "categories": [c.value for c in body.categories],
        "states": body.states,
        "is_active": True,
    }

    if existing:
        # PRD acceptance test: a duplicate subscription updates, never duplicates.
        if not existing.get("is_verified"):
            payload["verification_token"] = token
        db().table("subscribers").update(payload).eq("id", existing["id"]).execute()
        already_verified = bool(existing.get("is_verified"))
    else:
        payload["verification_token"] = token
        payload["unsubscribe_token"] = notifier.new_token()
        db().table("subscribers").insert(payload).execute()
        already_verified = False

    if already_verified:
        return SubscribeResponse(success=True, message="Preferences updated")

    if body.email:
        background.add_task(_send_verification, body.email, token)
        return SubscribeResponse(success=True, message="Verification email sent")

    return SubscribeResponse(
        success=True, message="Subscription created. Confirm your number on WhatsApp."
    )


def _send_verification(email: str, token: str) -> None:
    try:
        notifier.send_verification_email(email, token)
    except Exception as exc:
        log.error("verification email failed for %s: %s", email, exc)


def _find_existing(email: str | None, phone: str | None) -> dict | None:
    for column, value in (("email", email), ("phone", phone)):
        if not value:
            continue
        res = db().table("subscribers").select("*").eq(column, value).limit(1).execute()
        if res.data:
            return res.data[0]
    return None


@router.get("/verify")
async def verify(token: str = Query(min_length=16, max_length=64)):
    res = db().table("subscribers").select("id").eq("verification_token", token).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Invalid or already-used verification link")

    db().table("subscribers").update(
        {"is_verified": True, "verification_token": None, "is_active": True}
    ).eq("id", res.data[0]["id"]).execute()

    return RedirectResponse(f"{settings.frontend_url}/?verified=1", status_code=303)


@router.get("/unsubscribe")
async def unsubscribe(token: str = Query(min_length=16, max_length=64)):
    res = db().table("subscribers").select("id").eq("unsubscribe_token", token).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Invalid unsubscribe link")

    db().table("subscribers").update({"is_active": False}).eq("id", res.data[0]["id"]).execute()
    return RedirectResponse(f"{settings.frontend_url}/?unsubscribed=1", status_code=303)


@router.get("/subscribers/preview-digest")
async def preview_digest(token: str = Query(min_length=16, max_length=64)):
    """Render what this subscriber's next digest would look like. Used for QA."""
    res = db().table("subscribers").select("*").eq("unsubscribe_token", token).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Unknown subscriber")

    digest = notifier.generate_digest(res.data[0])
    return {
        "total": digest.total,
        "states": sorted(digest.states),
        "groups": [{"category": g.category, "count": len(g.entries)} for g in digest.groups],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

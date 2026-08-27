"""WhatsApp delivery via Gupshup — Milestone 9.

Gupshup requires pre-approved templates; the three the PRD specifies are defined
below. Template *content* is registered in the Gupshup console — here we only
send the parameter list that fills each {{n}} placeholder.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.database import db
from app.models.notification import Digest
from app.services import notifier

log = logging.getLogger(__name__)

GUPSHUP_URL = "https://api.gupshup.io/wa/api/v1/template/msg"
TEMPLATES = {
    "daily_digest": "sarkarisaar_daily_digest",
    "tender_alert": "sarkarisaar_tender_alert",
    "deadline_reminder": "sarkarisaar_deadline_reminder",
}
MAX_DIGEST_LINES = 5
RETRY_AFTER_MINUTES = 5


class WhatsAppError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sent_today() -> int:
    midnight = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    res = (
        db()
        .table("notification_log")
        .select("id", count="exact")
        .eq("channel", "whatsapp")
        .in_("status", ["sent", "delivered"])
        .gte("created_at", midnight.isoformat())
        .execute()
    )
    return res.count or 0


def _check_quota() -> None:
    used = sent_today()
    if used >= settings.gupshup_daily_limit:
        raise WhatsAppError(
            f"Gupshup daily limit reached ({used}/{settings.gupshup_daily_limit})"
        )


async def send_template_message(
    phone: str, template_name: str, params: list[str]
) -> str:
    """Send one pre-approved template. Returns Gupshup's message id."""
    if not settings.gupshup_api_key or not settings.gupshup_source_number:
        raise WhatsAppError("GUPSHUP_API_KEY / GUPSHUP_SOURCE_NUMBER are not configured")
    _check_quota()

    payload = {
        "channel": "whatsapp",
        "source": settings.gupshup_source_number,
        "destination": phone.lstrip("+"),
        "src.name": settings.gupshup_app_name,
        "template": _json({"id": template_name, "params": params}),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GUPSHUP_URL,
            headers={
                "apikey": settings.gupshup_api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=payload,
        )
    if resp.status_code >= 400:
        raise WhatsAppError(f"Gupshup {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    if body.get("status") not in ("submitted", "success"):
        raise WhatsAppError(f"Gupshup rejected message: {body}")
    return body.get("messageId", "")


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj)


async def send_digest(subscriber: dict[str, Any]) -> str | None:
    """Daily digest template. Returns the message id, or None when there's nothing to send."""
    digest = notifier.generate_digest(subscriber)
    if digest.total == 0:
        return None

    lines = []
    for group in digest.groups:
        for entry in group.entries[:MAX_DIGEST_LINES]:
            lines.append(f"• {entry['title'][:70]}")
        if len(lines) >= MAX_DIGEST_LINES:
            break

    message_id = await send_template_message(
        subscriber["phone"],
        TEMPLATES["daily_digest"],
        [str(digest.total), "\n".join(lines[:MAX_DIGEST_LINES])],
    )
    _log(digest.subscriber_id, digest.entry_ids, "sent", message_id)
    db().table("subscribers").update({"last_digest_at": _now().isoformat()}).eq(
        "id", subscriber["id"]
    ).execute()
    return message_id


async def send_instant_alert(subscriber: dict[str, Any], entry: dict[str, Any]) -> str:
    """Thekedar-plan instant tender alert."""
    cost = entry.get("budget_amount")
    cost_text = f"{cost // 100:,}" if cost else "Not stated"
    message_id = await send_template_message(
        subscriber["phone"],
        TEMPLATES["tender_alert"],
        [
            entry["title"][:120],
            cost_text,
            entry.get("state", "ALL"),
            entry.get("deadline") or "Not stated",
            f"{settings.frontend_url}/entry/{entry['id']}",
        ],
    )
    _log(subscriber["id"], [entry["id"]], "sent", message_id)
    return message_id


async def send_deadline_reminder(
    subscriber: dict[str, Any], entry: dict[str, Any], days_left: int
) -> str:
    message_id = await send_template_message(
        subscriber["phone"],
        TEMPLATES["deadline_reminder"],
        [
            entry["title"][:120],
            str(days_left),
            entry.get("deadline") or "",
            f"{settings.frontend_url}/entry/{entry['id']}",
        ],
    )
    _log(subscriber["id"], [entry["id"]], "sent", message_id)
    return message_id


def _log(subscriber_id: str, entry_ids: list[str], status: str, message_id: str | None) -> None:
    db().table("notification_log").insert(
        {
            "subscriber_id": subscriber_id,
            "entry_ids": entry_ids,
            "channel": "whatsapp",
            "status": status,
            "sent_at": _now().isoformat() if status == "sent" else None,
            "external_message_id": message_id,
        }
    ).execute()


# --- incoming ---------------------------------------------------------------


def handle_incoming(phone: str, text: str) -> dict[str, Any]:
    """Interpret a subscriber's reply. Returns what the webhook should answer with."""
    normalized = (text or "").strip().upper()
    phone_e164 = phone if phone.startswith("+") else f"+{phone}"

    if normalized in ("STOP", "UNSUBSCRIBE", "BAND KARO"):
        db().table("subscribers").update({"is_active": False}).eq("phone", phone_e164).execute()
        return {"action": "unsubscribed"}

    if normalized == "1":
        return {"action": "send_details", "phone": phone_e164}

    return {"action": "menu", "phone": phone_e164}


def handle_delivery_status(message_id: str, status: str) -> None:
    mapped = {
        "delivered": "delivered",
        "read": "delivered",
        "sent": "sent",
        "failed": "failed",
        "enqueued": "queued",
    }.get(status.lower())
    if not mapped:
        return

    update: dict[str, Any] = {"status": mapped}
    if mapped == "delivered":
        update["delivered_at"] = _now().isoformat()
    db().table("notification_log").update(update).eq("external_message_id", message_id).execute()


async def retry_failed() -> int:
    """Retry WhatsApp messages that failed more than RETRY_AFTER_MINUTES ago, once."""
    cutoff = (_now() - timedelta(minutes=RETRY_AFTER_MINUTES)).isoformat()
    rows = (
        db()
        .table("notification_log")
        .select("*, subscribers(phone, plan)")
        .eq("channel", "whatsapp")
        .eq("status", "failed")
        .eq("retry_count", 0)
        .lte("created_at", cutoff)
        .limit(50)
        .execute()
        .data
        or []
    )

    retried = 0
    for row in rows:
        subscriber = row.get("subscribers") or {}
        if not subscriber.get("phone"):
            continue
        try:
            entries = (
                db()
                .table("entries")
                .select("id, title, state, deadline, budget_amount")
                .in_("id", row["entry_ids"][:1])
                .execute()
                .data
                or []
            )
            if entries:
                await send_instant_alert({"id": row["subscriber_id"], **subscriber}, entries[0])
                retried += 1
        except Exception as exc:
            log.warning("whatsapp retry failed for %s: %s", row["id"], exc)
        finally:
            db().table("notification_log").update({"retry_count": 1}).eq("id", row["id"]).execute()
    return retried

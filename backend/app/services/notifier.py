"""Email digests — Milestone 7.

generate_digest() builds the payload for one subscriber; render_digest_html()
turns it into an inline-CSS email. Which entries belong in a digest is decided
in `outbox`, so a preview, a WhatsApp digest, and the queued email all apply
the same filters in the same order.
"""

from __future__ import annotations

import html
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.database import db
from app.models.notification import Digest, DigestGroup
from app.services.outbox import ENTRY_FIELDS, entries_for, subscriber_cutoff

log = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "yojana": "Yojana / Schemes",
    "naukri": "Naukri / Jobs",
    "tender": "Tenders",
    "rule": "Rule Changes",
    "auction": "Auctions",
    "notice": "Notices",
}
CATEGORY_ORDER = ["tender", "naukri", "yojana", "rule", "auction", "notice"]

#: One subscriber's window, read in full so keywords can be applied before the
#: cap. Wide enough for a weekly digest at today's publishing volume.
POOL_LIMIT_ONE = 500



#: Every deadline we publish is an Indian government date, and every reader is
#: in India. Counting "days left" in UTC is wrong for the 5h30m each day when
#: the UTC date trails IST: a notice closing today reads "1 day left", and one
#: that closed today still shows a badge instead of none.
IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> date:
    return datetime.now(IST).date()


def new_token() -> str:
    return secrets.token_hex(32)


# --- digest building -------------------------------------------------------


def generate_digest(subscriber: dict[str, Any]) -> Digest:
    """Entries published since this subscriber's last digest, matching their filters.

    One subscriber, one query. The scheduled email path pools that read across
    every subscriber instead — see `outbox.enqueue_digests`.
    """
    now = _now()
    rows = (
        db()
        .table("entries")
        .select(ENTRY_FIELDS)
        .eq("status", "approved")
        .gte("published_at", subscriber_cutoff(subscriber, now).isoformat())
        .order("published_at", desc=True)
        .limit(POOL_LIMIT_ONE)
        .execute()
        .data
        or []
    )
    return build_digest(subscriber, entries_for(subscriber, rows, now))


def build_digest(subscriber: dict[str, Any], entries: list[dict[str, Any]]) -> Digest:
    """Group already-chosen entries into the payload the templates render."""
    grouped: dict[str, list[dict]] = {}
    for row in entries:
        grouped.setdefault(row["category"], []).append(row)

    return Digest(
        subscriber_id=subscriber["id"],
        email=subscriber.get("email"),
        phone=subscriber.get("phone"),
        frequency=subscriber.get("frequency") or "weekly",
        groups=[DigestGroup(category=c, entries=grouped[c]) for c in CATEGORY_ORDER if c in grouped],
        unsubscribe_token=subscriber.get("unsubscribe_token") or "",
    )


# --- rendering -------------------------------------------------------------


def _esc(text: Any) -> str:
    return html.escape(str(text or ""))


def _deadline_badge(deadline: str | None) -> str:
    if not deadline:
        return ""
    try:
        days = (datetime.fromisoformat(deadline).date() - _today_ist()).days
    except ValueError:
        return ""
    if days < 0:
        return ""
    color = "#EF4444" if days <= 7 else "#F59E0B" if days <= 30 else "#10B981"
    label = "Today" if days == 0 else f"{days} day{'s' if days != 1 else ''} left"
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;font-size:11px;'
        f'font-weight:600;padding:2px 8px;border-radius:10px;margin-left:6px;">{label}</span>'
    )


def render_digest_html(digest: Digest) -> str:
    period = "Daily" if digest.frequency == "daily" else "Weekly"
    unsubscribe_url = f"{settings.api_base_url}/api/unsubscribe?token={digest.unsubscribe_token}"

    blocks = []
    for group in digest.groups:
        label = CATEGORY_LABELS.get(group.category, group.category.title())
        items = []
        for entry in group.entries:
            items.append(
                f"""
      <tr><td style="padding:12px 0;border-bottom:1px solid #eceae6;">
        <div style="font-size:15px;font-weight:600;color:#111;line-height:1.4;">
          {_esc(entry['title'])}{_deadline_badge(entry.get('deadline'))}
        </div>
        <div style="font-size:13px;color:#555;line-height:1.6;margin-top:6px;">
          {_esc((entry.get('summary_en') or '')[:220])}
        </div>
        <div style="font-size:12px;color:#888;margin-top:8px;">
          {_esc(entry.get('department') or '')} &middot; {_esc(entry.get('state'))}
          &nbsp;<a href="{settings.frontend_url}/entry/{_esc(entry['id'])}"
             style="color:#FF6B35;text-decoration:none;font-weight:600;">Read more &rarr;</a>
        </div>
      </td></tr>"""
            )
        blocks.append(
            f"""
  <tr><td style="padding-top:24px;">
    <div style="font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                color:#FF6B35;">{_esc(label)}</div>
    <table width="100%" cellpadding="0" cellspacing="0">{''.join(items)}</table>
  </td></tr>"""
        )

    states = len(digest.states)
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f5f3;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f6f5f3;padding:24px 12px;">
<tr><td align="center">
<table width="100%" style="max-width:600px;background:#fff;border-radius:12px;padding:28px;">
  <tr><td>
    <div style="font-size:20px;font-weight:800;color:#111;">Sarkari<span style="color:#FF6B35;">Saar</span></div>
    <div style="font-size:16px;font-weight:600;color:#111;margin-top:16px;">
      Your {period} Government Update
    </div>
    <div style="font-size:13px;color:#666;margin-top:4px;">
      {digest.total} new update{'s' if digest.total != 1 else ''} across {states} state{'s' if states != 1 else ''}
    </div>
  </td></tr>
  {''.join(blocks)}
  <tr><td style="padding-top:28px;border-top:1px solid #eceae6;margin-top:20px;">
    <div style="font-size:11px;color:#999;line-height:1.7;">
      SarkariSaar summarises publicly available government notifications. Summaries are
      AI-generated — always confirm details on the official source before acting.
      <br><a href="{unsubscribe_url}" style="color:#999;">Unsubscribe</a>
      &middot; <a href="{settings.frontend_url}/dashboard" style="color:#999;">Manage preferences</a>
    </div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def render_digest_text(digest: Digest) -> str:
    lines = [f"SarkariSaar — {digest.total} new government updates", ""]
    for group in digest.groups:
        lines.append(CATEGORY_LABELS.get(group.category, group.category).upper())
        for entry in group.entries:
            lines.append(f"  - {entry['title']}")
            lines.append(f"    {(entry.get('summary_en') or '')[:180]}")
            lines.append(f"    {settings.frontend_url}/entry/{entry['id']}")
        lines.append("")
    lines.append(
        f"Unsubscribe: {settings.api_base_url}/api/unsubscribe?token={digest.unsubscribe_token}"
    )
    return "\n".join(lines)


# --- sending ---------------------------------------------------------------


def _resend():
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is not set")
    import resend

    resend.api_key = settings.resend_api_key
    return resend


def send_email(to: str, subject: str, html_body: str, text_body: str = "") -> str:
    client = _resend()
    result = client.Emails.send(
        {
            "from": settings.resend_from,
            "to": [to],
            "subject": subject,
            "html": html_body,
            "text": text_body or "",
        }
    )
    return result.get("id", "")


def send_verification_email(email: str, token: str) -> str:
    link = f"{settings.api_base_url}/api/verify?token={token}"
    body = f"""<!doctype html><html><body style="font-family:sans-serif;padding:24px;">
<h2 style="color:#111;">Confirm your SarkariSaar subscription</h2>
<p style="color:#555;line-height:1.6;">Click below to start receiving government updates
in plain language.</p>
<p><a href="{link}" style="background:#FF6B35;color:#fff;padding:12px 22px;border-radius:8px;
text-decoration:none;font-weight:600;">Confirm subscription</a></p>
<p style="color:#999;font-size:12px;">If you didn't sign up, ignore this email.</p>
</body></html>"""
    return send_email(email, "Confirm your SarkariSaar subscription", body, f"Confirm: {link}")


def log_notification(
    digest: Digest, channel: str, status: str, message_id: str | None, error: str | None = None
) -> None:
    db().table("notification_log").insert(
        {
            "subscriber_id": digest.subscriber_id,
            "entry_ids": digest.entry_ids,
            "channel": channel,
            "status": status,
            "sent_at": _now().isoformat() if status == "sent" else None,
            "external_message_id": message_id,
            "error": error,
        }
    ).execute()

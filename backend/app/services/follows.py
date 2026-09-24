"""When a followed notice should email the person who asked.

The clock is passed in. Three days means the IST calendar day that is three
days before the deadline, and a moved date starts that count again.
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta, timezone

from app.database import db
from app.services.notifier import send_email

log = logging.getLogger(__name__)


def reminder_due(deadline: date | None, today: date, already_sent: bool) -> bool:
    """True on the day three days before `deadline`, once."""
    if deadline is None or already_sent:
        return False
    return today == deadline - timedelta(days=3)


def deadline_moved(previous: date | None, current: date | None) -> bool:
    """A follow stores the deadline it last knew. A different one is a change."""
    return previous is not None and current is not None and previous != current


IST = timezone(timedelta(hours=5, minutes=30))


def _as_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def send_follow_reminders(today: date | None = None) -> dict:
    """Email follows that are due. A failed send is not marked sent.

    Returns counts. If the follows table is not there yet, the caller sees
    an exception and can leave the rest of maintenance alone.
    """
    today = today or datetime.now(IST).date()
    rows = (
        db()
        .table("notice_follows")
        .select("user_id, entry_id, email, last_deadline, reminded_at, entries(title, deadline)")
        .execute()
        .data
        or []
    )

    reminded = moved = skipped = 0
    for row in rows:
        entry = row.get("entries") or {}
        email = row.get("email")
        current = _as_date(entry.get("deadline"))
        previous = _as_date(row.get("last_deadline"))
        title = entry.get("title") or "A notice you follow"
        safe = html.escape(title)

        if deadline_moved(previous, current) and current is not None:
            if not email:
                skipped += 1
            else:
                send_email(
                    email,
                    f"Deadline moved: {title}",
                    f"<p>The last date for <strong>{safe}</strong> is now {current.isoformat()}.</p>",
                    f"The last date for {title} is now {current.isoformat()}.",
                )
                db().table("notice_follows").update(
                    {"last_deadline": current.isoformat(), "reminded_at": None}
                ).eq("user_id", row["user_id"]).eq("entry_id", row["entry_id"]).execute()
                moved += 1
                row["reminded_at"] = None

        already = row.get("reminded_at") is not None
        if reminder_due(current, today, already_sent=already):
            if not email:
                skipped += 1
            else:
                send_email(
                    email,
                    f"3 days left: {title}",
                    f"<p><strong>{safe}</strong> closes on {current.isoformat() if current else ''}.</p>",
                    f"{title} closes on {current.isoformat() if current else ''}.",
                )
                db().table("notice_follows").update(
                    {"reminded_at": datetime.now(timezone.utc).isoformat()}
                ).eq("user_id", row["user_id"]).eq("entry_id", row["entry_id"]).execute()
                reminded += 1

    return {"reminded": reminded, "moved": moved, "skipped": skipped}

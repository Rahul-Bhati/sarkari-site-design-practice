"""Plan every digest from one pool of entries, then store the decision.

The old path ran one `entries` select per subscriber and applied the keyword
filter in Python *after* the database had already cut the list to 25. A
subscriber tracking "railway" got an empty digest on a day when a railway
notice ranked thirtieth. Here the pool is read once, every subscriber is
matched against it in memory with keywords applied before the cut, and the
result is written to `notification_outbox`.

The unique key `(subscriber_id, channel, digest_date)` is what makes a
half-finished run resumable: enqueue decides who gets what, drain sends it,
and a crash between the two costs nothing but a retry.

The decisions are pure functions over rows and a clock, so the rules can be
pinned in a test without a database.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from app.database import db

log = logging.getLogger(__name__)

MAX_ENTRIES_PER_DIGEST = 25
LOOKBACK = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "instant": timedelta(hours=1)}

#: A subscriber who stopped reading a year ago must not widen the shared pool
#: to the whole table. Their first digest back covers a month.
MAX_POOL_DAYS = 30

#: Hard ceiling on one pooled select. At roughly 50 entries a day a 30-day
#: window is ~1,500 rows, so this only bites if publishing volume triples.
POOL_LIMIT = 2000

#: Postgres orders an enum by declaration order, not alphabetically. Sorting
#: these as plain strings would rank "medium" above "critical".
URGENCY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

DRAIN_LIMIT = 200
ID_CHUNK = 500

#: Resend rate-limits bursts, so the drain pauses between blocks of sends.
SEND_BATCH = 50
SEND_DELAY_SECONDS = 1.0

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class PlannedDigest:
    """One subscriber's digest for one day, before it is sent."""

    subscriber_id: str
    channel: str
    digest_date: date
    entry_ids: list[str]
    frequency: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.subscriber_id, self.channel, self.digest_date.isoformat())

    def row(self) -> dict:
        return {
            "subscriber_id": self.subscriber_id,
            "channel": self.channel,
            "digest_date": self.digest_date.isoformat(),
            "status": "pending",
            "payload": {"entry_ids": list(self.entry_ids), "frequency": self.frequency},
        }


# --- the decisions ---------------------------------------------------------


def pool_cutoff(subscribers: list[dict], now: datetime) -> datetime:
    """The oldest moment any of these subscribers still needs, floored at MAX_POOL_DAYS."""
    floor = now - timedelta(days=MAX_POOL_DAYS)
    cutoffs = [subscriber_cutoff(s, now) for s in subscribers]
    widest = min(cutoffs) if cutoffs else now - LOOKBACK["daily"]
    return max(widest, floor)


def subscriber_cutoff(subscriber: dict, now: datetime) -> datetime:
    """Where this subscriber's digest starts: their last one, or one period back."""
    if parsed := _parse(subscriber.get("last_digest_at")):
        return parsed
    frequency = subscriber.get("frequency") or "weekly"
    return now - LOOKBACK.get(frequency, timedelta(days=7))


def entries_for(subscriber: dict, entries: list[dict], now: datetime) -> list[dict]:
    """This subscriber's slice of the shared pool, ranked and capped.

    Every filter — including keywords — runs before the cap, so the 25 a
    reader receives are the top 25 of what they actually asked for.
    """
    cutoff = subscriber_cutoff(subscriber, now)
    matched = [e for e in entries if _wanted(subscriber, e, cutoff)]
    matched.sort(key=_rank, reverse=True)
    return matched[:MAX_ENTRIES_PER_DIGEST]


def plan_digests(
    subscribers: list[dict],
    entries: list[dict],
    digest_date: date,
    now: datetime,
    channel: str = "email",
) -> list[PlannedDigest]:
    """One row per subscriber who has something to read. Empty digests are dropped."""
    planned: list[PlannedDigest] = []
    for subscriber in subscribers:
        picked = entries_for(subscriber, entries, now)
        if not picked:
            continue
        planned.append(
            PlannedDigest(
                subscriber_id=subscriber["id"],
                channel=channel,
                digest_date=digest_date,
                entry_ids=[e["id"] for e in picked],
                frequency=subscriber.get("frequency") or "weekly",
            )
        )
    return planned


def _wanted(subscriber: dict, entry: dict, cutoff: datetime) -> bool:
    published = _parse(entry.get("published_at"))
    if published is None or published < cutoff:
        return False

    if (categories := subscriber.get("categories")) and entry.get("category") not in categories:
        return False

    # 'ALL' entries are central-government and relevant to every state.
    if (states := subscriber.get("states")) and entry.get("state") not in {*states, "ALL"}:
        return False

    if (departments := subscriber.get("departments")) and entry.get("department") not in departments:
        return False

    # Postgres `budget_amount >= n` never matches NULL, and the feed leans on
    # that: an unpriced notice is not a tender a Thekedar subscriber bid on.
    budget = entry.get("budget_amount")
    low, high = subscriber.get("min_budget"), subscriber.get("max_budget")
    if (low is not None or high is not None) and budget is None:
        return False
    if low is not None and budget < low:
        return False
    if high is not None and budget > high:
        return False

    if keywords := subscriber.get("keywords"):
        haystack = f"{entry.get('title') or ''} {entry.get('summary_en') or ''}".lower()
        if not any(k.lower() in haystack for k in keywords):
            return False

    return True


def _rank(entry: dict) -> tuple[int, str]:
    return (URGENCY_RANK.get(entry.get("urgency") or "low", 0), entry.get("published_at") or "")


# --- the database side -----------------------------------------------------


ENTRY_FIELDS = (
    "id, title, summary_en, summary_hi, category, state, deadline, "
    "department, original_url, urgency, budget_amount, published_at"
)


def eligible_subscribers(frequency: str, channel: str = "email") -> list[dict]:
    channels = ["email", "both"] if channel == "email" else [channel, "both"]
    return (
        db()
        .table("subscribers")
        .select("*")
        .eq("is_active", True)
        .eq("is_verified", True)
        .eq("frequency", frequency)
        .in_("channel", channels)
        .not_.is_("email", "null")
        .execute()
        .data
        or []
    )


def fetch_pool(cutoff: datetime) -> list[dict]:
    """Every approved entry published since `cutoff` — one select for the whole run."""
    rows = (
        db()
        .table("entries")
        .select(ENTRY_FIELDS)
        .eq("status", "approved")
        .gte("published_at", cutoff.isoformat())
        .order("published_at", desc=True)
        .limit(POOL_LIMIT)
        .execute()
        .data
        or []
    )
    if len(rows) == POOL_LIMIT:
        log.warning("digest pool hit the %d row ceiling; the oldest entries were dropped", POOL_LIMIT)
    return rows


def enqueue_digests(frequency: str, channel: str = "email") -> dict[str, Any]:
    """Decide today's digests and reserve one outbox row each.

    Safe to run twice: the unique key means a second run is a no-op rather
    than a second email.
    """
    now = _now()
    subscribers = eligible_subscribers(frequency, channel)
    report = {"frequency": frequency, "subscribers": len(subscribers), "queued": 0, "skipped": 0}
    if not subscribers:
        return report

    pool = fetch_pool(pool_cutoff(subscribers, now))
    planned = plan_digests(subscribers, pool, _today_ist(), now, channel)
    report["skipped"] = len(subscribers) - len(planned)
    if not planned:
        return report

    db().table("notification_outbox").upsert(
        [p.row() for p in planned],
        on_conflict="subscriber_id,channel,digest_date",
        ignore_duplicates=True,
    ).execute()
    report["queued"] = len(planned)
    return report


async def drain_outbox(limit: int = DRAIN_LIMIT) -> dict[str, Any]:
    """Send what is queued. Entries and subscribers are read once for the batch."""
    from app.services import notifier

    pending = (
        db()
        .table("notification_outbox")
        .select("*")
        .eq("status", "pending")
        .eq("channel", "email")
        .order("created_at")
        .limit(limit)
        .execute()
        .data
        or []
    )
    report = {"pending": len(pending), "sent": 0, "failed": 0}
    if not pending:
        return report

    entries = _by_id("entries", ENTRY_FIELDS, {i for r in pending for i in _entry_ids(r)})
    subscribers = _by_id("subscribers", "*", {r["subscriber_id"] for r in pending})

    for position, row in enumerate(pending):
        if position and position % SEND_BATCH == 0:
            await asyncio.sleep(SEND_DELAY_SECONDS)
        subscriber = subscribers.get(row["subscriber_id"])
        if subscriber is None:
            _mark(row["id"], "failed")
            report["failed"] += 1
            continue

        picked = [entries[i] for i in _entry_ids(row) if i in entries]
        if not picked:
            # Every entry was expired or deleted between planning and sending.
            _mark(row["id"], "sent")
            continue

        digest = notifier.build_digest(subscriber, picked)
        try:
            message_id = notifier.send_email(
                digest.email,
                f"{digest.total} new government updates for you",
                notifier.render_digest_html(digest),
                notifier.render_digest_text(digest),
            )
            notifier.log_notification(digest, "email", "sent", message_id)
            _mark(row["id"], "sent")
            db().table("subscribers").update({"last_digest_at": _now().isoformat()}).eq(
                "id", subscriber["id"]
            ).execute()
            report["sent"] += 1
        except Exception as exc:
            log.error("digest send failed for %s: %s", subscriber["id"], exc)
            notifier.log_notification(digest, "email", "failed", None, str(exc)[:500])
            _mark(row["id"], "failed")
            report["failed"] += 1

    return report


async def run_digests(frequency: str, channel: str = "email") -> dict[str, Any]:
    """Plan, then send. What the scheduler calls."""
    queued = enqueue_digests(frequency, channel)
    sent = await drain_outbox()
    return {**queued, **sent}


def _entry_ids(row: dict) -> list[str]:
    return list((row.get("payload") or {}).get("entry_ids") or [])


def _by_id(table: str, fields: str, ids: set[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for chunk in _chunks(sorted(ids), ID_CHUNK):
        rows = db().table(table).select(fields).in_("id", chunk).execute().data or []
        found.update({r["id"]: r for r in rows})
    return found


def _mark(outbox_id: str, status: str) -> None:
    db().table("notification_outbox").update({"status": status}).eq("id", outbox_id).execute()


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> date:
    return datetime.now(IST).date()


def _parse(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

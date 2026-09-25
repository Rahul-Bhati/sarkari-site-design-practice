"""Plan today's digests against the real database and write nothing.

Run this before the first live send. It answers three questions:

  1. Does `notification_outbox` exist and is it empty?
  2. How many subscribers would be queued, and how many entries each?
  3. How many of those digests the old keyword-after-the-cap path would have
     lost — the bug this queue was built to fix.

Nothing here inserts, updates, or emails. The only writes in the digest path
live in `outbox.enqueue_digests` and `outbox.drain_outbox`, and neither is
called.

    cd backend && .venv/bin/python ../scripts/dry-enqueue.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from app.database import db
from app.services.outbox import (
    MAX_ENTRIES_PER_DIGEST,
    URGENCY_RANK,
    _rank,
    _today_ist,
    _wanted,
    eligible_subscribers,
    entries_for,
    fetch_pool,
    plan_digests,
    pool_cutoff,
    subscriber_cutoff,
)

FREQUENCIES = ("daily", "weekly")


def old_path_count(subscriber: dict, pool: list[dict], now: datetime) -> int:
    """What the pre-outbox code would have delivered: cap first, keywords after."""
    cutoff = subscriber_cutoff(subscriber, now)
    without_keywords = {**subscriber, "keywords": []}
    matched = [e for e in pool if _wanted(without_keywords, e, cutoff)]
    matched.sort(key=_rank, reverse=True)
    capped = matched[:MAX_ENTRIES_PER_DIGEST]

    if not (keywords := subscriber.get("keywords")):
        return len(capped)
    lowered = [k.lower() for k in keywords]
    return sum(
        1
        for e in capped
        if any(k in f"{e.get('title') or ''} {e.get('summary_en') or ''}".lower() for k in lowered)
    )


def _n(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def check_table() -> bool:
    try:
        rows = db().table("notification_outbox").select("status").limit(500).execute().data or []
    except Exception as exc:
        print(f"  notification_outbox is NOT reachable: {str(exc)[:160]}")
        return False
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"  notification_outbox exists — {len(rows)} rows {counts or '(empty)'}")
    return True


def report(frequency: str, now: datetime) -> None:
    print(f"\n{frequency.upper()}")
    subscribers = eligible_subscribers(frequency)
    print(f"  eligible subscribers : {len(subscribers)}")
    if not subscribers:
        return

    cutoff = pool_cutoff(subscribers, now)
    pool = fetch_pool(cutoff)
    print(f"  pool window          : since {cutoff.isoformat(timespec='minutes')}")
    print(f"  pool rows (1 select) : {len(pool)}  [old path: {len(subscribers)} selects]")

    planned = plan_digests(subscribers, pool, _today_ist(), now)
    entry_refs = sum(len(p.entry_ids) for p in planned)
    print(f"  would queue          : {len(planned)}")
    print(f"  would skip (empty)   : {len(subscribers) - len(planned)}")
    if planned:
        sizes = sorted(len(p.entry_ids) for p in planned)
        print(f"  entries per digest   : min {sizes[0]}, median {sizes[len(sizes) // 2]}, max {sizes[-1]}")
        print(f"  total entry refs     : {entry_refs}")

    by_id = {s["id"]: s for s in subscribers}
    recovered = []
    for plan in planned:
        subscriber = by_id[plan.subscriber_id]
        before = old_path_count(subscriber, pool, now)
        if before < len(plan.entry_ids):
            recovered.append((plan.subscriber_id, before, len(plan.entry_ids)))

    keyword_users = sum(1 for s in subscribers if s.get("keywords"))
    print(f"  keyword subscribers  : {keyword_users}")
    if recovered:
        gained = sum(after - before for _, before, after in recovered)
        blanks = sum(1 for _, before, _ in recovered if before == 0)
        print(
            f"  FIXED: {_n(len(recovered), 'digest')} recovering "
            f"{_n(gained, 'entry', 'entries')} the old path dropped"
        )
        print(f"         {blanks} of them would have been sent empty or not at all")
    else:
        print("  no digest changes size under the fix (expected with few keyword subscribers)")


def main() -> int:
    now = datetime.now(timezone.utc)
    print(f"Dry enqueue at {now.isoformat(timespec='seconds')} — nothing is written.")
    if not check_table():
        return 1
    for frequency in FREQUENCIES:
        report(frequency, now)
    print("\nNo rows inserted. No email sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

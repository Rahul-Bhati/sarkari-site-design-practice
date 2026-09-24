"""Which sources have gone quiet.

The decision is pure so a test can pin the rule without a database. Callers
pass the source row and the clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

FAILURE_LIMIT = 3
MISSED_INTERVALS = 3


def source_staleness(source: dict, now: datetime) -> str | None:
    """A short reason the source needs a human, or None when it does not.

    Inactive sources are quiet on purpose. A row that has never been run is
    not an alarm yet.
    """
    if source.get("is_active") is False:
        return None

    failures = source.get("consecutive_failures") or 0
    if failures >= FAILURE_LIMIT:
        return f"{failures} consecutive failures"

    last_success = _parse(source.get("last_success_at"))
    if last_success is None:
        if _parse(source.get("last_run_at")) is None:
            return None
        return "no successful run"

    minutes = source.get("frequency_minutes") or 60
    limit = timedelta(minutes=int(minutes) * MISSED_INTERVALS)
    if _aware(now) - last_success > limit:
        return "last success is older than 3 intervals"
    return None


def stale_sources(sources: list[dict], now: datetime) -> list[dict]:
    stale = []
    for source in sources:
        reason = source_staleness(source, now)
        if reason is None:
            continue
        stale.append({"scraper_key": source.get("scraper_key"), "reason": reason})
    return stale


def _parse(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _aware(value)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

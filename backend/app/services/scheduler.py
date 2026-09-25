"""APScheduler jobs, started from FastAPI's lifespan.

All times are IST. Jobs are wrapped so a failure logs and returns rather than
killing the scheduler thread.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import db
from app.scrapers.runner import SCRAPERS, run_scraper
from app.services import cache, outbox, payment, whatsapp
from app.services.summarizer import DailyCapReached, process_pending_entries

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
_scheduler: AsyncIOScheduler | None = None

#: scraper_key -> interval in minutes (PRD Step 2.7)
SCRAPE_INTERVALS = {"pib": 60, "ssc": 120, "raj_eproc": 60}


async def _safe(name: str, coro_fn, *args) -> None:
    try:
        result = await coro_fn(*args)
        log.info("job %s finished: %s", name, result)
    except DailyCapReached as exc:
        log.warning("job %s skipped: %s", name, exc)
    except Exception as exc:
        log.error("job %s failed: %s", name, exc, exc_info=True)


async def _scrape(source_key: str) -> dict:
    result = await run_scraper(source_key)
    return {"source": source_key, "new": result.entries_new, "status": result.status}


async def _process_pending() -> dict:
    return await process_pending_entries()


async def _email_digest(frequency: str) -> dict:
    return await outbox.run_digests(frequency)


async def _whatsapp_digest(frequency: str) -> dict:
    subscribers = (
        db()
        .table("subscribers")
        .select("*")
        .eq("is_active", True)
        .eq("phone_verified", True)
        .eq("frequency", frequency)
        .in_("channel", ["whatsapp", "both"])
        .in_("plan", ["pro", "thekedar"])
        .not_.is_("phone", "null")
        .execute()
        .data
        or []
    )

    sent = failed = 0
    for subscriber in subscribers:
        try:
            if await whatsapp.send_digest(subscriber):
                sent += 1
        except whatsapp.WhatsAppError as exc:
            log.warning("whatsapp digest stopped: %s", exc)
            break
        except Exception as exc:
            log.error("whatsapp digest failed for %s: %s", subscriber["id"], exc)
            failed += 1
    return {"sent": sent, "failed": failed, "eligible": len(subscribers)}


async def _instant_alerts() -> dict:
    """Thekedar plan: tenders approved in the last 5 minutes, pushed immediately."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    entries = (
        db()
        .table("entries")
        .select("id, title, state, category, deadline, budget_amount, department")
        .eq("status", "approved")
        .eq("category", "tender")
        .gte("published_at", cutoff)
        .limit(20)
        .execute()
        .data
        or []
    )
    if not entries:
        return {"entries": 0, "sent": 0}

    subscribers = (
        db()
        .table("subscribers")
        .select("*")
        .eq("is_active", True)
        .eq("phone_verified", True)
        .eq("plan", "thekedar")
        .in_("channel", ["whatsapp", "both"])
        .execute()
        .data
        or []
    )

    sent = 0
    for subscriber in subscribers:
        for entry in entries:
            if not _matches(subscriber, entry):
                continue
            try:
                await whatsapp.send_instant_alert(subscriber, entry)
                sent += 1
            except whatsapp.WhatsAppError as exc:
                log.warning("instant alerts stopped: %s", exc)
                return {"entries": len(entries), "sent": sent}
            except Exception as exc:
                log.error("instant alert failed: %s", exc)
    return {"entries": len(entries), "sent": sent}


def _matches(subscriber: dict, entry: dict) -> bool:
    states = subscriber.get("states") or []
    if states and entry["state"] not in states and entry["state"] != "ALL":
        return False
    if (lo := subscriber.get("min_budget")) is not None and (entry.get("budget_amount") or 0) < lo:
        return False
    if (hi := subscriber.get("max_budget")) is not None and (entry.get("budget_amount") or 0) > hi:
        return False
    departments = subscriber.get("departments") or []
    if departments and entry.get("department") not in departments:
        return False
    return True


async def _follow_reminders() -> dict:
    from app.services.follows import send_follow_reminders

    return send_follow_reminders()


async def _nightly_housekeeping() -> dict:
    expired = db().rpc("expire_stale_entries", {}).execute().data
    downgraded = payment.expire_lapsed_plans()
    cache.invalidate_feed()
    return {"entries_expired": expired, "plans_downgraded": downgraded}


async def _retry_whatsapp() -> dict:
    return {"retried": await whatsapp.retry_failed()}


def jobs_for_sources(sources: list[dict], registered: set[str]) -> list[tuple[str, int]]:
    """One (scraper_key, minutes) pair per active source that has a class."""
    jobs: list[tuple[str, int]] = []
    for row in sources:
        key = row.get("scraper_key")
        if not row.get("is_active", True) or key not in registered:
            continue
        minutes = row.get("frequency_minutes") or 60
        jobs.append((key, int(minutes)))
    return jobs


def _scrape_intervals() -> dict[str, int]:
    """Intervals from `sources`, or every registered scraper when the read fails."""
    try:
        rows = (
            db()
            .table("sources")
            .select("scraper_key, frequency_minutes, is_active")
            .execute()
            .data
            or []
        )
    except Exception as exc:
        log.warning("scheduler could not read sources, using defaults: %s", exc)
        return {key: SCRAPE_INTERVALS.get(key, 60) for key in SCRAPERS}
    return dict(jobs_for_sources(rows, set(SCRAPERS)))


def start() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.scheduler_enabled:
        log.info("scheduler disabled via SCHEDULER_ENABLED=false")
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone=IST)

    for source_key, minutes in _scrape_intervals().items():
        scheduler.add_job(
            _safe,
            IntervalTrigger(minutes=minutes, jitter=120),
            args=[f"scrape:{source_key}", _scrape, source_key],
            id=f"scrape_{source_key}",
            max_instances=1,
            coalesce=True,
        )

    scheduler.add_job(
        _safe,
        IntervalTrigger(minutes=5),
        args=["ai_process", _process_pending],
        id="ai_process",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _safe,
        CronTrigger(hour=7, minute=0, timezone=IST),
        args=["email_digest_daily", _email_digest, "daily"],
        id="email_digest_daily",
    )
    scheduler.add_job(
        _safe,
        CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=IST),
        args=["email_digest_weekly", _email_digest, "weekly"],
        id="email_digest_weekly",
    )
    scheduler.add_job(
        _safe,
        CronTrigger(hour=7, minute=30, timezone=IST),
        args=["whatsapp_digest_daily", _whatsapp_digest, "daily"],
        id="whatsapp_digest_daily",
    )
    scheduler.add_job(
        _safe,
        IntervalTrigger(minutes=5),
        args=["instant_alerts", _instant_alerts],
        id="instant_alerts",
        max_instances=1,
    )
    scheduler.add_job(
        _safe,
        IntervalTrigger(minutes=5),
        args=["retry_whatsapp", _retry_whatsapp],
        id="retry_whatsapp",
        max_instances=1,
    )
    scheduler.add_job(
        _safe,
        CronTrigger(hour=8, minute=0, timezone=IST),
        args=["follow_reminders", _follow_reminders],
        id="follow_reminders",
        max_instances=1,
    )
    scheduler.add_job(
        _safe,
        CronTrigger(hour=1, minute=0, timezone=IST),
        args=["nightly_housekeeping", _nightly_housekeeping],
        id="nightly_housekeeping",
    )

    scheduler.start()
    _scheduler = scheduler
    log.info("scheduler started with %d jobs", len(scheduler.get_jobs()))
    return scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def jobs() -> list[dict]:
    if _scheduler is None:
        return []
    return [
        {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
        for j in _scheduler.get_jobs()
    ]

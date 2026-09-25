"""Admin endpoints — review queue, scraper control, AI processing.

Every route here requires an admin identity (see app/services/auth.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import db
from app.models.entry import Category, Urgency
from app.scrapers.runner import SCRAPERS, results_as_dicts, run_all, run_scraper
from app.services import cache
from app.services.auth import AdminIdentity, require_admin
from app.services.freshness import source_staleness, stale_sources
from app.config import settings
from app.services.summarizer import (
    DailyCapReached,
    awaiting_summary_count,
    pending_count,
    process_pending_entries,
    requests_today,
    spend_today_inr,
    tokens_today,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

SELECT = "*, sources(id, name, url, scraper_key)"


class EntryEdit(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    summary_en: Optional[str] = None
    summary_hi: Optional[str] = None
    category: Optional[Category] = None
    state: Optional[str] = Field(default=None, max_length=4)
    department: Optional[str] = Field(default=None, max_length=200)
    deadline: Optional[str] = None
    urgency: Optional[Urgency] = None
    key_details: Optional[dict[str, Any]] = None


class BulkApprove(BaseModel):
    entry_ids: list[str] = Field(min_length=1, max_length=100)


class BulkApproveByConfidence(BaseModel):
    min_confidence: float = Field(default=0.95, ge=0, le=1)
    limit: int = Field(default=50, ge=1, le=200)


# --- review queue ----------------------------------------------------------


@router.get("/entries/pending")
async def pending_entries(
    limit: int = Query(25, ge=1, le=100),
    page: int = Query(1, ge=1),
    min_confidence: float = Query(0.0, ge=0, le=1),
):
    offset = (page - 1) * limit
    res = (
        db()
        .table("entries")
        .select(SELECT, count="exact")
        .eq("status", "pending")
        .neq("summary_en", "")
        .gte("ai_confidence", min_confidence)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {
        "entries": res.data or [],
        "total": res.count or 0,
        "page": page,
        "limit": limit,
        "has_more": offset + limit < (res.count or 0),
    }


@router.patch("/entries/{entry_id}/approve")
async def approve_entry(entry_id: str, admin: AdminIdentity = Depends(require_admin)):
    entry = _require_entry(entry_id)
    if not (entry.get("summary_en") or "").strip():
        raise HTTPException(status_code=400, detail="Entry has no summary yet — run AI processing first")

    _update(entry_id, {"status": "approved", "published_at": _now()}, admin)
    cache.invalidate_feed()
    return {"success": True, "id": entry_id, "status": "approved"}


@router.patch("/entries/{entry_id}/reject")
async def reject_entry(entry_id: str, admin: AdminIdentity = Depends(require_admin)):
    _require_entry(entry_id)
    _update(entry_id, {"status": "rejected", "published_at": None}, admin)
    cache.invalidate_feed()
    return {"success": True, "id": entry_id, "status": "rejected"}


@router.patch("/entries/{entry_id}")
async def edit_entry(
    entry_id: str, edit: EntryEdit, admin: AdminIdentity = Depends(require_admin)
):
    _require_entry(entry_id)
    changes = {k: v for k, v in edit.model_dump(exclude_unset=True).items() if v is not None}
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "state" in changes:
        changes["state"] = changes["state"].upper()

    _update(entry_id, changes, admin)
    cache.invalidate_feed()
    return {"success": True, "id": entry_id, "updated": sorted(changes)}


@router.post("/entries/bulk-approve")
async def bulk_approve(body: BulkApprove, admin: AdminIdentity = Depends(require_admin)):
    res = (
        db()
        .table("entries")
        .update({"status": "approved", "published_at": _now(), **_reviewer(admin)})
        .in_("id", body.entry_ids)
        .eq("status", "pending")
        .neq("summary_en", "")
        .execute()
    )
    cache.invalidate_feed()
    return {"success": True, "approved": len(res.data or [])}


@router.post("/entries/bulk-approve-confident")
async def bulk_approve_confident(
    body: BulkApproveByConfidence, admin: AdminIdentity = Depends(require_admin)
):
    candidates = (
        db()
        .table("entries")
        .select("id")
        .eq("status", "pending")
        .neq("summary_en", "")
        .gte("ai_confidence", body.min_confidence)
        .limit(body.limit)
        .execute()
    )
    ids = [row["id"] for row in (candidates.data or [])]
    if not ids:
        return {"success": True, "approved": 0}

    res = (
        db()
        .table("entries")
        .update({"status": "approved", "published_at": _now(), **_reviewer(admin)})
        .in_("id", ids)
        .execute()
    )
    cache.invalidate_feed()
    return {"success": True, "approved": len(res.data or [])}


# --- scrapers --------------------------------------------------------------


@router.post("/scrape")
async def trigger_scrape(
    background: BackgroundTasks,
    source: Optional[str] = Query(None, description="scraper_key; omit to run all"),
    wait: bool = Query(True, description="Run inline and return counts, or queue in background"),
):
    if source and source not in SCRAPERS:
        raise HTTPException(status_code=404, detail=f"Unknown scraper '{source}'")

    if not wait:
        background.add_task(_scrape_task, source)
        return {"success": True, "queued": source or "all"}

    results = [await run_scraper(source)] if source else await run_all()
    return {"success": True, "results": results_as_dicts(results)}


async def _scrape_task(source: Optional[str]) -> None:
    try:
        await (run_scraper(source) if source else run_all())
    except Exception as exc:  # background tasks must never bubble
        log.error("background scrape failed: %s", exc)


@router.get("/scraper-status")
async def scraper_status():
    sources = db().table("sources").select("*").order("name").execute().data or []
    runs = (
        db()
        .table("scraper_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(100)
        .execute()
        .data
        or []
    )

    latest: dict[int, dict] = {}
    for run in runs:
        latest.setdefault(run["source_id"], run)

    now = datetime.now(timezone.utc)
    out = []
    for src in sources:
        failures = src.get("consecutive_failures") or 0
        reason = source_staleness(src, now)
        if reason or failures >= 3:
            health = "red"
        elif failures:
            health = "yellow"
        else:
            health = "green"
        out.append(
            {
                **src,
                "registered": src["scraper_key"] in SCRAPERS,
                "health": health,
                "stale": reason is not None,
                "stale_reason": reason,
                "last_run": latest.get(src["id"]),
            }
        )
    return {"sources": out, "registered_scrapers": sorted(SCRAPERS)}


@router.get("/scraper-dashboard")
async def scraper_dashboard():
    """Alias kept for the PRD's endpoint list."""
    return await scraper_status()


# --- AI processing ---------------------------------------------------------


@router.post("/process")
async def trigger_processing(batch_size: int = Query(10, ge=1, le=50)):
    try:
        return await process_pending_entries(batch_size=batch_size)
    except DailyCapReached as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


# --- jobs that the in-process scheduler also runs -------------------------
#
# Exposed so an external scheduler can drive them when SCHEDULER_ENABLED=false
# — which is the setup on free hosts that sleep when idle. See
# .github/workflows/cron.yml.


@router.post("/send-digests")
async def send_digests(
    frequency: str = Query("weekly", pattern="^(daily|weekly)$"),
):
    """Queue today's digests and send what is queued.

    Safe to call twice: a subscriber already queued for today is not queued
    again, and one already sent is not resent.
    """
    from app.services import outbox

    try:
        return await outbox.run_digests(frequency)
    except RuntimeError as exc:
        # Missing RESEND_API_KEY, typically.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/drain-outbox")
async def drain_outbox():
    """Send digests left pending by an interrupted run."""
    from app.services import outbox

    try:
        return await outbox.drain_outbox()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/maintenance")
async def maintenance():
    """Expire entries past their deadline and downgrade lapsed plans."""
    from app.services import payment

    expired = db().rpc("expire_stale_entries", {}).execute().data
    downgraded = payment.expire_lapsed_plans()
    cache.invalidate_feed()
    rows = (
        db()
        .table("sources")
        .select(
            "scraper_key, is_active, consecutive_failures, frequency_minutes, "
            "last_success_at, last_run_at"
        )
        .execute()
        .data
        or []
    )
    stale = stale_sources(rows, datetime.now(timezone.utc))
    if stale:
        log.warning("stale sources: %s", [row["scraper_key"] for row in stale])
    reminders: dict = {"reminded": 0, "moved": 0, "skipped": 0}
    try:
        from app.services.follows import send_follow_reminders

        reminders = send_follow_reminders()
    except Exception as exc:
        log.warning("follow reminders skipped: %s", exc)
    return {
        "entries_expired": expired,
        "plans_downgraded": downgraded,
        "stale_sources": stale,
        "follow_reminders": reminders,
    }


@router.get("/pending-count")
async def pending():
    tokens = tokens_today()
    return {
        "pending": pending_count(),
        # Published entries from trusted sources count here too: they are live
        # in the feed with the portal's own wording and still owed a summary.
        "awaiting_ai": awaiting_summary_count(),
        "awaiting_review": _count(lambda q: q.eq("status", "pending").neq("summary_en", "")),
        "ai_spend_today_inr": spend_today_inr(),
        "ai_requests_today": requests_today(),
        "ai_tokens_today": tokens,
        "ai_token_cap": settings.ai_daily_token_cap,
        # The quota that runs out first on a free tier. Surfaced so the
        # dashboard can say "paused until midnight IST" instead of the queue
        # appearing to stall for no reason.
        "ai_tokens_remaining": max(settings.ai_daily_token_cap - tokens, 0)
        if settings.ai_daily_token_cap
        else None,
    }


# --- helpers ---------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reviewer(admin: AdminIdentity) -> dict:
    return {"reviewed_by": admin.user_id, "reviewed_at": _now()}


def _require_entry(entry_id: str) -> dict:
    res = db().table("entries").select("*").eq("id", entry_id).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found")
    return rows[0]


def _update(entry_id: str, changes: dict, admin: AdminIdentity) -> None:
    db().table("entries").update({**changes, **_reviewer(admin)}).eq("id", entry_id).execute()


def _count(apply) -> int:
    query = db().table("entries").select("id", count="exact")
    return apply(query).execute().count or 0

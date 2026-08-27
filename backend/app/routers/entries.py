"""Public feed API — Milestone 4.

Only ever returns entries with status='approved'. Responses are cached per
unique filter combination for FEED_CACHE_TTL_SECONDS.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.database import db
from app.models.entry import EntriesResponse, Entry, StatsResponse
from app.services import cache

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["entries"])

VALID_CATEGORIES = {"yojana", "naukri", "tender", "rule", "auction", "notice"}
VALID_URGENCY = {"low", "medium", "high", "critical"}
SORTS = {
    "published_at": ("published_at", True),
    "deadline": ("deadline", False),
    "created_at": ("created_at", True),
}
SELECT = "*, sources(id, name, url)"


def _csv(value: Optional[str], allowed: set[str] | None = None) -> list[str]:
    if not value:
        return []
    items = [v.strip().lower() for v in value.split(",") if v.strip()]
    if allowed is not None:
        items = [v for v in items if v in allowed]
    return items


def _shape(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["source"] = row.pop("sources", None)
    row.pop("original_text", None)  # debugging field, never public
    row.pop("content_hash", None)
    row.pop("search_vector", None)
    return row


@router.get("/entries", response_model=EntriesResponse)
async def list_entries(
    category: Optional[str] = Query(None, description='Comma-separated, e.g. "tender,naukri"'),
    state: Optional[str] = Query(None, description='Comma-separated, e.g. "RJ,UP"'),
    search: Optional[str] = Query(None, min_length=2, max_length=120),
    urgency: Optional[str] = Query(None, description='Comma-separated, e.g. "high,critical"'),
    deadline_before: Optional[date] = None,
    sort: str = Query("published_at"),
    page: int = Query(1, ge=1, le=500),
    limit: int = Query(20, ge=1, le=50),
):
    categories = _csv(category, VALID_CATEGORIES)
    states = [s.upper() for s in _csv(state)]
    urgencies = _csv(urgency, VALID_URGENCY)
    sort = sort if sort in SORTS else "published_at"
    offset = (page - 1) * limit

    key = cache.feed_key(
        c=",".join(categories),
        s=",".join(states),
        q=search or "",
        u=",".join(urgencies),
        d=deadline_before.isoformat() if deadline_before else "",
        sort=sort,
        page=page,
        limit=limit,
    )
    if (cached := cache.get(key)) is not None:
        return cached

    if search:
        payload = _search(search, categories, states, page, limit)
    else:
        payload = _filter(categories, states, urgencies, deadline_before, sort, offset, limit, page)

    cache.set(key, payload)
    return payload


def _filter(
    categories: list[str],
    states: list[str],
    urgencies: list[str],
    deadline_before: Optional[date],
    sort: str,
    offset: int,
    limit: int,
    page: int,
) -> dict:
    column, descending = SORTS[sort]
    query = db().table("entries").select(SELECT, count="exact").eq("status", "approved")

    if categories:
        query = query.in_("category", categories)
    if states:
        query = query.in_("state", states)
    if urgencies:
        query = query.in_("urgency", urgencies)
    if deadline_before:
        query = query.lte("deadline", deadline_before.isoformat())
    if sort == "deadline":
        query = query.not_.is_("deadline", "null")

    res = (
        query.order(column, desc=descending, nullsfirst=False)
        .range(offset, offset + limit - 1)
        .execute()
    )
    total = res.count or 0
    return {
        "entries": [_shape(r) for r in (res.data or [])],
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": offset + limit < total,
    }


def _search(query_text: str, categories: list[str], states: list[str], page: int, limit: int) -> dict:
    """Full-text search with a trigram fallback, via the search_entries RPC."""
    offset = (page - 1) * limit
    res = db().rpc(
        "search_entries",
        {
            "q": query_text,
            "categories": categories or None,
            "states": states or None,
            "lim": limit,
            "off": offset,
        },
    ).execute()

    rows = res.data or []
    total = rows[0]["total_count"] if rows else 0

    # The RPC returns a flat row; re-attach the source for response parity.
    source_ids = {r["source_id"] for r in rows if r.get("source_id")}
    sources = {}
    if source_ids:
        s = db().table("sources").select("id, name, url").in_("id", list(source_ids)).execute()
        sources = {row["id"]: row for row in (s.data or [])}

    entries = []
    for row in rows:
        row = dict(row)
        row.pop("rank", None)
        row.pop("total_count", None)
        row["sources"] = sources.get(row.get("source_id"))
        entries.append(_shape(row))

    return {
        "entries": entries,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/entries/{entry_id}", response_model=Entry)
async def get_entry(entry_id: str):
    key = f"entry:{entry_id}"
    if (cached := cache.get(key)) is not None:
        return cached

    res = (
        db()
        .table("entries")
        .select(SELECT)
        .eq("id", entry_id)
        .eq("status", "approved")
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found")

    entry = _shape(rows[0])
    cache.set(key, entry)
    return entry


@router.get("/entries/{entry_id}/related", response_model=list[Entry])
async def related_entries(entry_id: str, limit: int = Query(4, ge=1, le=10)):
    res = db().table("entries").select("category, state").eq("id", entry_id).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found")

    related = (
        db()
        .table("entries")
        .select(SELECT)
        .eq("status", "approved")
        .eq("category", rows[0]["category"])
        .eq("state", rows[0]["state"])
        .neq("id", entry_id)
        .order("published_at", desc=True, nullsfirst=False)
        .limit(limit)
        .execute()
    )
    return [_shape(r) for r in (related.data or [])]


@router.get("/stats", response_model=StatsResponse)
async def stats():
    if (cached := cache.get("stats")) is not None:
        return cached

    res = db().rpc("feed_stats", {}).execute()
    payload = res.data or {}
    payload.setdefault("categories", {})
    cache.set("stats", payload)
    return payload

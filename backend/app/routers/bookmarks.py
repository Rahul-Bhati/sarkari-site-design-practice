"""Bookmarks and per-user preferences — Milestone 8."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import db
from app.models.entry import Category
from app.models.user import Channel, Frequency
from app.services.auth import current_user
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["user"])


class PreferenceUpdate(BaseModel):
    channel: Channel | None = None
    frequency: Frequency | None = None
    categories: list[Category] | None = None
    states: list[str] | None = Field(default=None, max_length=40)
    keywords: list[str] | None = Field(default=None, max_length=20)
    min_budget: int | None = Field(default=None, ge=0)
    max_budget: int | None = Field(default=None, ge=0)


@router.post("/bookmarks/{entry_id}")
async def toggle_bookmark(entry_id: str, user: dict = Depends(current_user)):
    exists = (
        db()
        .table("entries")
        .select("id")
        .eq("id", entry_id)
        .eq("status", "approved")
        .limit(1)
        .execute()
    )
    if not exists.data:
        raise HTTPException(status_code=404, detail="Entry not found")

    current = (
        db()
        .table("bookmarks")
        .select("entry_id")
        .eq("user_id", user["id"])
        .eq("entry_id", entry_id)
        .limit(1)
        .execute()
    )
    if current.data:
        db().table("bookmarks").delete().eq("user_id", user["id"]).eq(
            "entry_id", entry_id
        ).execute()
        return {"bookmarked": False}

    db().table("bookmarks").insert({"user_id": user["id"], "entry_id": entry_id}).execute()
    return {"bookmarked": True}


@router.post("/follows/{entry_id}")
async def toggle_follow(entry_id: str, user: dict = Depends(current_user)):
    """Follow one notice so we can mail the reader before it closes."""
    entry = (
        db()
        .table("entries")
        .select("id, deadline, status")
        .eq("id", entry_id)
        .eq("status", "approved")
        .limit(1)
        .execute()
    )
    if not entry.data:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not entry.data[0].get("deadline"):
        raise HTTPException(status_code=400, detail="This notice has no deadline to follow")

    current = (
        db()
        .table("notice_follows")
        .select("entry_id")
        .eq("user_id", user["id"])
        .eq("entry_id", entry_id)
        .limit(1)
        .execute()
    )
    if current.data:
        db().table("notice_follows").delete().eq("user_id", user["id"]).eq(
            "entry_id", entry_id
        ).execute()
        return {"following": False}

    db().table("notice_follows").insert(
        {
            "user_id": user["id"],
            "entry_id": entry_id,
            "email": user.get("email"),
            "last_deadline": entry.data[0]["deadline"],
        }
    ).execute()
    return {"following": True}


@router.get("/follows/{entry_id}")
async def follow_state(entry_id: str, user: dict = Depends(current_user)):
    current = (
        db()
        .table("notice_follows")
        .select("entry_id")
        .eq("user_id", user["id"])
        .eq("entry_id", entry_id)
        .limit(1)
        .execute()
    )
    return {"following": bool(current.data)}


@router.get("/bookmarks")
async def list_bookmarks(
    user: dict = Depends(current_user),
    limit: int = Query(50, ge=1, le=100),
):
    rows = (
        db()
        .table("bookmarks")
        .select("created_at, entries(*, sources(id, name, url))")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )

    entries = []
    for row in rows:
        entry = row.get("entries")
        if not entry:
            continue
        entry = dict(entry)
        entry["source"] = entry.pop("sources", None)
        entry.pop("original_text", None)
        entry["bookmarked_at"] = row["created_at"]
        entries.append(entry)
    return {"entries": entries, "total": len(entries)}


@router.get("/preferences")
async def get_preferences(user: dict = Depends(current_user)):
    res = db().table("subscribers").select("*").eq("user_id", user["id"]).limit(1).execute()
    if not res.data:
        return {"subscribed": False}
    row = res.data[0]
    return {
        "subscribed": True,
        "channel": row["channel"],
        "frequency": row["frequency"],
        "categories": row["categories"],
        "states": row["states"],
        "keywords": row["keywords"],
        "min_budget": row["min_budget"],
        "max_budget": row["max_budget"],
        "plan": row["plan"],
        "is_active": row["is_active"],
    }


@router.patch("/preferences")
async def update_preferences(body: PreferenceUpdate, user: dict = Depends(current_user)):
    res = db().table("subscribers").select("id").eq("user_id", user["id"]).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="No subscription found for this account")

    changes = body.model_dump(exclude_unset=True)
    if "categories" in changes and changes["categories"] is not None:
        changes["categories"] = [c.value if hasattr(c, "value") else c for c in changes["categories"]]
    if "channel" in changes and changes["channel"] is not None:
        changes["channel"] = changes["channel"].value
    if "frequency" in changes and changes["frequency"] is not None:
        changes["frequency"] = changes["frequency"].value
    if "states" in changes and changes["states"] is not None:
        changes["states"] = [s.upper() for s in changes["states"]]

    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")

    db().table("subscribers").update(changes).eq("id", res.data[0]["id"]).execute()
    return {"success": True, "updated": sorted(changes)}

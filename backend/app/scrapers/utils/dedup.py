"""Deduplication helpers.

The database enforces uniqueness on `content_hash`; these helpers let the runner
skip known hashes before it ever issues an insert, which keeps the scraper_runs
counters honest (`entries_duplicate` vs `entries_new`).
"""

from __future__ import annotations

from app.database import db
from app.scrapers.identity import StoredNotice, normalize_url

CHUNK = 200


def existing_hashes(hashes: list[str]) -> set[str]:
    """Return the subset of `hashes` already present in `entries`."""
    if not hashes:
        return set()

    found: set[str] = set()
    for i in range(0, len(hashes), CHUNK):
        chunk = hashes[i : i + CHUNK]
        res = db().table("entries").select("content_hash").in_("content_hash", chunk).execute()
        found.update(row["content_hash"] for row in (res.data or []))
    return found


def _url_variants(url: str) -> set[str]:
    """Forms a stored row might use for the same permalink."""
    raw = url.strip()
    normal = normalize_url(url)
    return {raw, normal, f"{normal}/", normal.rstrip("/")}


def existing_notices(source_id: int, urls: list[str]) -> list[StoredNotice]:
    """Rows for this source whose permalink matches any of `urls`."""
    if not urls:
        return []

    wanted: list[str] = []
    seen: set[str] = set()
    for url in urls:
        for variant in _url_variants(url):
            if variant and variant not in seen:
                seen.add(variant)
                wanted.append(variant)

    found: dict[str, StoredNotice] = {}
    for i in range(0, len(wanted), CHUNK):
        chunk = wanted[i : i + CHUNK]
        res = (
            db()
            .table("entries")
            .select("id, original_url, title, deadline, published_date, pdf_url")
            .eq("source_id", source_id)
            .in_("original_url", chunk)
            .execute()
        )
        for row in res.data or []:
            found[row["id"]] = StoredNotice(
                id=row["id"],
                original_url=row["original_url"],
                title=row.get("title") or "",
                deadline=row.get("deadline"),
                published_date=row.get("published_date"),
                pdf_url=row.get("pdf_url"),
            )
    return list(found.values())


def existing_urls(urls: list[str]) -> set[str]:
    """Permalinks from `urls` that already have an entries row."""
    if not urls:
        return set()

    found: set[str] = set()
    for i in range(0, len(urls), CHUNK):
        chunk = urls[i : i + CHUNK]
        res = (
            db()
            .table("entries")
            .select("original_url")
            .in_("original_url", chunk)
            .execute()
        )
        found.update(row["original_url"] for row in (res.data or []) if row.get("original_url"))
    return found

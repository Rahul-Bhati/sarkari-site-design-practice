"""Deduplication helpers.

The database enforces uniqueness on `content_hash`; these helpers let the runner
skip known hashes before it ever issues an insert, which keeps the scraper_runs
counters honest (`entries_duplicate` vs `entries_new`).
"""

from __future__ import annotations

from app.database import db

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

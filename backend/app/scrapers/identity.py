"""Decide whether a scraped notice is new, a duplicate, or a revision.

The content hash stays the insert key so rows already stored are not
re-inserted. A notice we have seen before is recognized by its normalized
URL: a changed deadline or title patches that row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.scrapers.base import RawEntry

_FACT_FIELDS = ("title", "deadline", "published_date", "pdf_url")


@dataclass
class StoredNotice:
    id: str
    original_url: str
    title: str
    deadline: str | None = None
    published_date: str | None = None
    pdf_url: str | None = None


@dataclass
class PersistPlan:
    inserts: list[tuple[str, RawEntry]] = field(default_factory=list)
    updates: list[dict] = field(default_factory=list)
    duplicates: int = 0


def normalize_url(url: str) -> str:
    """Lowercase the host, drop fragments and utm params, strip a trailing slash."""
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            urlencode(query),
            "",
        )
    )


def plan_persist(
    incoming: list[tuple[str, RawEntry]],
    stored: list[StoredNotice],
) -> PersistPlan:
    """Split a scrape into inserts, revisions, and duplicates.

    `incoming` is (content_hash, entry). The last copy of a URL in the batch
    wins, so a corrigendum listed twice does not insert two rows.
    """
    by_url: dict[str, StoredNotice] = {}
    for row in stored:
        by_url[normalize_url(row.original_url)] = row

    plan = PersistPlan()
    seen_in_batch: dict[str, tuple[str, RawEntry]] = {}
    for content_hash, entry in incoming:
        key = normalize_url(entry.original_url)
        if key in seen_in_batch:
            plan.duplicates += 1
        seen_in_batch[key] = (content_hash, entry)

    for key, (content_hash, entry) in seen_in_batch.items():
        existing = by_url.get(key)
        if existing is None:
            plan.inserts.append((content_hash, entry))
            continue
        changed = _changes(existing, entry)
        if not changed:
            plan.duplicates += 1
            continue
        plan.updates.append({"id": existing.id, **changed})

    return plan


def _changes(existing: StoredNotice, entry: RawEntry) -> dict:
    changed: dict = {}
    for name in _FACT_FIELDS:
        new = _blank(getattr(entry, name))
        old = _blank(getattr(existing, name))
        if new != old:
            changed[name] = getattr(entry, name)
    return changed


def _blank(value: str | None) -> str:
    return (value or "").strip()

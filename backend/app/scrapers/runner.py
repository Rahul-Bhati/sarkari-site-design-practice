"""Scraper orchestration.

For each registered scraper:
  1. open a `scraper_runs` row
  2. call `scrape()`
  3. drop entries whose content_hash already exists
  4. insert the rest with status='pending'
  5. close the run row with counts, and update source health

One scraper failing never stops the others — each is wrapped individually and
its failure is recorded on both the run row and the source row.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.database import db
from app.scrapers.base import BaseScraper, RawEntry
from app.scrapers.sources.gem import GeMScraper
from app.scrapers.sources.nta import NTAScraper
from app.scrapers.sources.pib import PIBScraper
from app.scrapers.sources.raj_eproc import RajasthanEProcScraper
from app.scrapers.sources.sbi import SBIScraper
from app.scrapers.sources.ssc import SSCScraper
from app.scrapers.utils.dedup import existing_hashes

log = logging.getLogger(__name__)

#: scraper_key -> scraper class. Adding a source means adding a row here plus a
#: matching row in the `sources` table.
SCRAPERS: dict[str, type[BaseScraper]] = {
    "pib": PIBScraper,
    "ssc": SSCScraper,
    "gem": GeMScraper,
    "nta": NTAScraper,
    "sbi": SBIScraper,
    "raj_eproc": RajasthanEProcScraper,
}

# Guard against a single scraper hanging the whole run.
SCRAPER_TIMEOUT_SECONDS = 300


@dataclass
class RunResult:
    source_key: str
    status: str  # success | failed
    entries_found: int = 0
    entries_new: int = 0
    entries_duplicate: int = 0
    error: str | None = None
    duration_seconds: float = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _source_row(source_key: str) -> dict | None:
    res = db().table("sources").select("*").eq("scraper_key", source_key).limit(1).execute()
    return (res.data or [None])[0]


async def run_scraper(source_key: str) -> RunResult:
    """Run one scraper end to end. Never raises."""
    started = _now()
    scraper_cls = SCRAPERS.get(source_key)
    if scraper_cls is None:
        return RunResult(source_key, "failed", error=f"no scraper registered for '{source_key}'")

    source = _source_row(source_key)
    if source is None:
        return RunResult(
            source_key, "failed", error=f"no row in `sources` with scraper_key='{source_key}'"
        )
    source_id = source["id"]

    run = (
        db()
        .table("scraper_runs")
        .insert({"source_id": source_id, "started_at": started.isoformat(), "status": "running"})
        .execute()
    )
    run_id = run.data[0]["id"]
    db().table("sources").update({"last_run_at": started.isoformat()}).eq("id", source_id).execute()

    result = RunResult(source_key, "success")
    try:
        raw = await asyncio.wait_for(scraper_cls().scrape(), timeout=SCRAPER_TIMEOUT_SECONDS)
        result.entries_found = len(raw)
        new, dupes = _persist(scraper_cls(), source_id, raw)
        result.entries_new, result.entries_duplicate = new, dupes
        _mark_source_success(source, new)
    except Exception as exc:
        result.status = "failed"
        result.error = f"{type(exc).__name__}: {exc}"
        log.error("scraper %s failed: %s\n%s", source_key, exc, traceback.format_exc())
        _mark_source_failure(source, result.error)

    result.duration_seconds = (_now() - started).total_seconds()
    db().table("scraper_runs").update(
        {
            "finished_at": _now().isoformat(),
            "status": result.status,
            "entries_found": result.entries_found,
            "entries_new": result.entries_new,
            "entries_duplicate": result.entries_duplicate,
            "error": result.error,
            "duration_seconds": result.duration_seconds,
        }
    ).eq("id", run_id).execute()

    return result


def _persist(scraper: BaseScraper, source_id: int, raw: list[RawEntry]) -> tuple[int, int]:
    """Insert new entries, skipping ones we already have. Returns (new, duplicate)."""
    if not raw:
        return 0, 0

    # De-dupe within this batch first — portals often list the same notice twice.
    by_hash: dict[str, RawEntry] = {}
    in_batch_dupes = 0
    for entry in raw:
        h = scraper.content_hash(entry)
        if h in by_hash:
            in_batch_dupes += 1
            continue
        by_hash[h] = entry

    known = existing_hashes(list(by_hash))
    fresh = {h: e for h, e in by_hash.items() if h not in known}
    duplicates = in_batch_dupes + len(known)

    if not fresh:
        return 0, duplicates

    rows = [_to_row(source_id, h, e) for h, e in fresh.items()]
    # ignore_duplicates guards the race where two runs overlap.
    res = db().table("entries").upsert(rows, on_conflict="content_hash", ignore_duplicates=True).execute()
    inserted = len(res.data or [])
    duplicates += len(rows) - inserted
    return inserted, duplicates


def _to_row(source_id: int, content_hash: str, entry: RawEntry) -> dict:
    extra = {k: v for k, v in (entry.extra or {}).items() if v is not None}
    return {
        "source_id": source_id,
        "title": entry.title,
        "summary_en": "",  # filled in by the summarizer
        "original_text": entry.raw_text,
        "category": entry.category,
        "state": entry.state,
        "department": entry.department or None,
        "original_url": entry.original_url,
        "pdf_url": entry.pdf_url,
        "published_date": entry.published_date,
        "deadline": entry.deadline,
        "budget_amount": entry.budget_amount,
        "key_details": extra,
        "content_hash": content_hash,
        "status": "pending",
    }


def _mark_source_success(source: dict, new_count: int) -> None:
    now = _now().isoformat()
    db().table("sources").update(
        {
            "last_success_at": now,
            "consecutive_failures": 0,
            "last_error": None,
            "total_entries_scraped": (source.get("total_entries_scraped") or 0) + new_count,
        }
    ).eq("id", source["id"]).execute()


def _mark_source_failure(source: dict, error: str) -> None:
    db().table("sources").update(
        {
            "last_failure_at": _now().isoformat(),
            "last_error": error[:2000],
            "consecutive_failures": (source.get("consecutive_failures") or 0) + 1,
        }
    ).eq("id", source["id"]).execute()


async def run_all(source_keys: list[str] | None = None) -> list[RunResult]:
    """Run every active scraper concurrently. Failures are isolated per source."""
    keys = source_keys or _active_source_keys()
    results = await asyncio.gather(
        *(run_scraper(k) for k in keys), return_exceptions=True
    )

    out: list[RunResult] = []
    for key, res in zip(keys, results):
        if isinstance(res, BaseException):
            # run_scraper swallows its own errors; this only catches a crash in
            # the wrapper itself.
            log.error("runner crashed for %s: %s", key, res)
            out.append(RunResult(key, "failed", error=str(res)))
        else:
            out.append(res)
    return out


def _active_source_keys() -> list[str]:
    res = db().table("sources").select("scraper_key").eq("is_active", True).execute()
    known = {row["scraper_key"] for row in (res.data or [])}
    return [k for k in SCRAPERS if k in known]


def results_as_dicts(results: list[RunResult]) -> list[dict]:
    return [asdict(r) for r in results]

"""Summarization pipeline.

Raw scraped entries (status='pending', empty summary_en) go to whichever model
AI_PROVIDER selects, which returns a schema-validated `Summary` — the JSON is
checked against the schema by the provider, not parsed hopefully here.

Two guards, because the free and paid providers fail in different ways:
  * a daily spend cap in rupees  — for paid providers
  * a daily request cap          — for free tiers, where spend is always Rs 0
    and the real limit is requests per day
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.database import db
from app.models.entry import Summary
from app.scrapers.utils.pdf_extractor import extract_pdf_text, needs_ocr
from app.services.ai_provider import (
    PermanentAIError,
    SummaryProvider,
    TransientAIError,
    Usage,
    get_provider,
)
from app.services.notice_facts import keep_supported_facts, quote_in_text

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a government notification summarizer for Indian citizens.
Your job is to make complex government notifications understandable
to ordinary people — a farmer, a student, a small contractor.

IMPORTANT RULES:
- If you're unsure about a field, set it to null rather than guessing.
- The summary must be understandable by someone with a 10th-grade education.
- Always mention the deadline prominently in the summary if one exists.
- For tenders: always mention estimated cost and EMD if available.
- For jobs: always mention number of vacancies and eligibility.
- For yojanas: always mention who is eligible and how to apply.
- Write summary_hi in everyday spoken Hindi (Devanagari), not Shudh Hindi. \
Keep common English terms (tender, online, portal) as-is where people use them.
- Set confidence honestly. Below 0.9 means a human should review this before it \
goes public.
"""

USER_TEMPLATE = """\
Summarize this government notification.

Source: {source_name}
Scraped title: {title}
State: {state}
URL: {url}
Today's date: {today}

--- RAW TEXT ---
{raw_text}
--- END RAW TEXT ---
"""

MAX_RAW_CHARS = 24_000
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2

_last_call_at = 0.0


class DailyCapReached(RuntimeError):
    pass


def _ist_midnight_utc() -> datetime:
    """Start of the current IST day, as a UTC timestamp."""
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    return ist_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        hours=5, minutes=30
    )


def spend_today_inr() -> float:
    res = (
        db()
        .table("ai_usage")
        .select("cost_inr")
        .gte("created_at", _ist_midnight_utc().isoformat())
        .execute()
    )
    return round(sum(float(r["cost_inr"]) for r in (res.data or [])), 4)


def requests_today() -> int:
    res = (
        db()
        .table("ai_usage")
        .select("id", count="exact")
        .gte("created_at", _ist_midnight_utc().isoformat())
        .execute()
    )
    return res.count or 0


def tokens_today() -> int:
    """Input plus output tokens billed today.

    Providers meter the free tier on tokens per day, not requests, so this is
    the number that runs out first.
    """
    res = (
        db()
        .table("ai_usage")
        .select("input_tokens, output_tokens")
        .gte("created_at", _ist_midnight_utc().isoformat())
        .execute()
    )
    return sum(
        (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
        for r in (res.data or [])
    )


def estimate_cost_inr(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost for a hypothetical call. Looks the model up across both providers."""
    from app.services.ai_provider import (  # noqa: PLC0415
        ANTHROPIC_DEFAULT_RATE,
        ANTHROPIC_RATES_INR_PER_MTOK,
        GEMINI_RATES_INR_PER_MTOK,
    )

    if model in GEMINI_RATES_INR_PER_MTOK:
        rate_in, rate_out = GEMINI_RATES_INR_PER_MTOK[model]
    else:
        rate_in, rate_out = ANTHROPIC_RATES_INR_PER_MTOK.get(model, ANTHROPIC_DEFAULT_RATE)
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000


async def _respect_rate_limit(provider: SummaryProvider) -> None:
    """Free tiers cap requests per minute; space calls out to stay under it."""
    global _last_call_at
    if provider.min_interval_seconds <= 0:
        return
    elapsed = time.monotonic() - _last_call_at
    if (wait := provider.min_interval_seconds - elapsed) > 0:
        await asyncio.sleep(wait)
    _last_call_at = time.monotonic()


async def _attach_pdf_text(entry: dict[str, Any]) -> None:
    """Download a job or scheme PDF once, and keep its text for the summary.

    A scan that yields almost no text is marked unread so we do not fetch it
    on every later batch, and we do not invent facts from an empty file.
    A failed download is left unmarked so the next batch can try again.
    """
    if entry.get("category") not in {"naukri", "yojana"}:
        return
    details = dict(entry.get("key_details") or {})
    if details.get("pdf_extracted"):
        return
    url = entry.get("pdf_url")
    if not url:
        return

    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": settings.scraper_user_agent},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
        text = extract_pdf_text(response.content)
    except Exception as exc:
        log.warning("pdf fetch failed for %s: %s", entry.get("id"), exc)
        return

    details["pdf_extracted"] = True
    update: dict[str, Any] = {"key_details": details}
    if text and not needs_ocr(text):
        update["original_text"] = text[:50_000]
        entry["original_text"] = update["original_text"]
    else:
        details["pdf_unreadable"] = True
        update["key_details"] = details
    entry["key_details"] = details
    db().table("entries").update(update).eq("id", entry["id"]).execute()


def _user_message(entry: dict[str, Any]) -> str:
    raw_text = (entry.get("original_text") or entry.get("title") or "")[:MAX_RAW_CHARS]
    return USER_TEMPLATE.format(
        source_name=entry.get("_source_name") or "Government portal",
        title=entry.get("title", ""),
        state=entry.get("state", "ALL"),
        url=entry.get("original_url", ""),
        today=datetime.now().date().isoformat(),
        raw_text=raw_text,
    )


def _entries_per_call(provider: SummaryProvider) -> int:
    """How many notices go into one call. Config overrides the provider."""
    configured = settings.ai_batch_entries
    if configured > 0:
        return configured
    return max(getattr(provider, "batch_size", 1), 1)


async def summarize_group(
    entries: list[dict[str, Any]]
) -> tuple[list[Summary | None], Usage]:
    """Summarize several entries in one call, falling back to one at a time.

    A batch is worth attempting because the schema and system prompt dominate a
    single-entry request. It is worth *abandoning* cleanly because a bad reply
    costs every entry in the batch, not one — so any failure here retries the
    entries individually rather than writing them all off.

    Returns a summary per entry, with None where that entry could not be
    summarised, so the caller can still record a failure against the right row.
    """
    provider = get_provider()
    if not entries:
        return [], Usage(0, 0)

    if len(entries) > 1:
        await _respect_rate_limit(provider)
        try:
            summaries, usage = await provider.summarize_batch(
                SYSTEM_PROMPT, [_user_message(e) for e in entries]
            )
            return list(summaries), usage
        except PermanentAIError:
            raise
        except TransientAIError as exc:
            log.warning(
                "batch of %d failed (%s); retrying them one at a time",
                len(entries), exc,
            )

    results: list[Summary | None] = []
    total_in = total_out = 0
    for entry in entries:
        try:
            summary, usage = await summarize(entry)
        except TransientAIError as exc:
            log.warning("entry %s failed: %s", entry.get("id"), exc)
            results.append(None)
            continue
        results.append(summary)
        total_in += usage.input_tokens
        total_out += usage.output_tokens
    return results, Usage(total_in, total_out)


async def summarize(entry: dict[str, Any]) -> tuple[Summary, Usage]:
    """Summarize one entry, retrying transient failures with backoff."""
    provider = get_provider()
    user_message = _user_message(entry)

    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        await _respect_rate_limit(provider)
        try:
            return await provider.summarize(SYSTEM_PROMPT, user_message)
        except PermanentAIError:
            raise  # a bad key or a refusal will not fix itself
        except TransientAIError as exc:
            last_error = exc
            wait = BACKOFF_BASE_SECONDS ** (attempt + 1)
            log.warning(
                "summarize retry %d/%d in %ds: %s", attempt + 1, MAX_ATTEMPTS, wait, exc
            )
            await asyncio.sleep(wait)

    raise TransientAIError(f"summarize failed after {MAX_ATTEMPTS} attempts: {last_error}")


#: Sources whose parsing is reliable enough to publish without a human reading
#: every entry. Anything not named here is held for review no matter how
#: confident the model was, so **adding a scraper means adding it here too** —
#: forgetting sent 331 NTA entries to the review queue at confidence 0.95.
#: `test_trusted_sources_are_real_scrapers` guards the typo case.
TRUSTED_SOURCES = {
    "pib", "ssc", "gem", "nta", "sbi",
    "ibps_crp", "ibps_recruitment", "rrb_secunderabad",
}


def _check_caps() -> tuple[float, int, int]:
    """Raise if any daily cap is spent. Returns (spend, requests, tokens).

    Three caps because the providers fail in three different ways: a paid tier
    runs out of money, a free tier runs out of requests, and a free tier with
    generous request limits runs out of *tokens* first. Groq is the third case
    and it is the one that caught us out.
    """
    spend = spend_today_inr()
    if spend >= settings.ai_daily_cap_inr:
        raise DailyCapReached(
            f"daily AI spend cap reached: Rs {spend:.2f} of Rs {settings.ai_daily_cap_inr:.2f}"
        )

    used = requests_today()
    if used >= settings.ai_daily_request_cap:
        raise DailyCapReached(
            f"daily AI request cap reached: {used} of {settings.ai_daily_request_cap}"
        )

    tokens = tokens_today() if settings.ai_daily_token_cap else 0
    if settings.ai_daily_token_cap and tokens >= settings.ai_daily_token_cap:
        raise DailyCapReached(
            f"daily AI token cap reached: {tokens:,} of "
            f"{settings.ai_daily_token_cap:,}. The queue resumes after midnight IST."
        )

    if spend >= settings.ai_daily_cap_inr * 0.8:
        log.warning("AI spend at %.0f%% of the daily cap", spend / settings.ai_daily_cap_inr * 100)
    if used >= settings.ai_daily_request_cap * 0.8:
        log.warning("AI requests at %d of %d today", used, settings.ai_daily_request_cap)
    if settings.ai_daily_token_cap and tokens >= settings.ai_daily_token_cap * 0.8:
        log.warning("AI tokens at %d of %d today", tokens, settings.ai_daily_token_cap)

    return spend, used, tokens


async def process_pending_entries(batch_size: int | None = None) -> dict[str, Any]:
    """Summarize a batch of pending entries. Returns a run report."""
    batch_size = batch_size or settings.ai_batch_size
    spend, used, tokens = _check_caps()
    provider = get_provider()

    # Keyed on "has no summary", not on status. Entries from trusted sources are
    # published the moment they are scraped, showing the portal's own title and
    # dates, and the summary arrives later as an enrichment — so status no
    # longer tells us whether the AI still has work to do.
    res = (
        db()
        .table("entries")
        .select("*, sources(name, scraper_key)")
        .eq("summary_en", "")
        .neq("status", "rejected")
        .lt("ai_attempts", MAX_ATTEMPTS)
        .order("created_at", desc=False)
        .limit(batch_size)
        .execute()
    )
    entries = res.data or []

    report: dict[str, Any] = {
        "provider": provider.name,
        "model": provider.model,
        "processed": 0,
        "approved": 0,
        "held_for_review": 0,
        "failed": 0,
        "cost_inr": 0.0,
        "spend_today_inr": spend,
        "requests_today": used,
        "tokens_today": tokens,
        "token_cap": settings.ai_daily_token_cap,
        "errors": [],
    }

    for entry in entries:
        entry["_source_name"] = (entry.get("sources") or {}).get("name")
        await _attach_pdf_text(entry)

    per_call = _entries_per_call(provider)
    report["entries_per_call"] = per_call

    for group in _chunks(entries, per_call):
        try:
            summaries, usage = await summarize_group(group)
        except PermanentAIError as exc:
            # A misconfigured key fails identically for every entry; stop
            # rather than burning every remaining retry on it.
            report["failed"] += len(group)
            report["errors"].append({"error": f"stopping run: {exc}"[:300]})
            _bump_attempts(group, report)
            break

        # One call's tokens cover the whole group, so charge it once and split
        # the usage across the rows it produced. Otherwise a batch of five
        # would be recorded as five full-price calls and the daily token
        # accounting — which is what the caps read — would be five times wrong.
        written = [s for s in summaries if s is not None]
        share = _split_usage(usage, len(written))
        cost = provider.cost_inr(usage)
        report["cost_inr"] += cost

        for entry, summary in zip(group, summaries):
            if summary is None:
                report["failed"] += 1
                report["errors"].append(
                    {"entry_id": entry["id"], "error": "no summary returned"}
                )
                _bump_attempts([entry], report)
                continue

            report["processed"] += 1
            trusted = (entry.get("sources") or {}).get("scraper_key") in TRUSTED_SOURCES
            approve = summary.confidence > settings.ai_auto_approve_confidence and trusted
            report["approved" if approve else "held_for_review"] += 1
            _apply_summary(
                entry, summary, share, cost / max(len(written), 1), approve, provider
            )

        try:
            _check_caps()
        except DailyCapReached as exc:
            report["errors"].append({"error": f"stopping run: {exc}"})
            break

    report["cost_inr"] = round(report["cost_inr"], 4)
    return report


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _split_usage(usage: Usage, count: int) -> Usage:
    """Spread one call's tokens evenly across the entries it summarised."""
    if count <= 1:
        return usage
    return Usage(
        input_tokens=usage.input_tokens // count,
        output_tokens=usage.output_tokens // count,
    )


def _bump_attempts(entries: list[dict], report: dict[str, Any]) -> None:
    """Record a failed attempt so a poisonous entry stops being retried."""
    for entry in entries:
        try:
            db().table("entries").update(
                {"ai_attempts": (entry.get("ai_attempts") or 0) + 1}
            ).eq("id", entry["id"]).execute()
        except Exception as exc:
            # Losing the counter costs one wasted retry later. Letting it
            # propagate would abandon the run and lose summaries already
            # written, so it is only worth logging.
            log.warning("could not record failed attempt for %s: %s", entry["id"], exc)


def deadline_to_write(existing: str | None, suggested: str | None) -> str | None:
    """The deadline to store, or None to leave the column alone.

    A date the scraper already took from the portal is the one we show.
    The model may fill a deadline only when the portal did not.
    """
    if (existing or "").strip():
        return None
    suggested = (suggested or "").strip()
    return suggested or None


def _apply_summary(
    entry: dict,
    summary: Summary,
    usage: Usage,
    cost: float,
    approve: bool,
    provider: SummaryProvider,
) -> None:
    key_details = dict(entry.get("key_details") or {})
    supported = keep_supported_facts(summary.key_details.model_dump(), entry.get("original_text") or "")
    key_details.update(supported)

    update: dict[str, Any] = {
        "title": summary.title[:500],
        "summary_en": summary.summary_en,
        "summary_hi": summary.summary_hi,
        "category": summary.category,
        "urgency": summary.urgency,
        "department": summary.department or entry.get("department"),
        "key_details": key_details,
        "ai_confidence": round(summary.confidence, 4),
        "ai_input_tokens": usage.input_tokens,
        "ai_output_tokens": usage.output_tokens,
        "ai_processed_at": datetime.now(timezone.utc).isoformat(),
        "ai_attempts": (entry.get("ai_attempts") or 0) + 1,
    }
    written_deadline = deadline_to_write(entry.get("deadline"), summary.deadline)
    if written_deadline:
        update["deadline"] = written_deadline
    if summary.eligibility and quote_in_text(summary.eligibility, entry.get("original_text") or ""):
        update["eligibility"] = {"text": summary.eligibility}
    if summary.budget_or_salary and not entry.get("budget_amount"):
        update["budget_amount"] = int(summary.budget_or_salary) * 100  # INR -> paisa
    if approve:
        update["status"] = "approved"
        # A trusted entry was already published when it was scraped; keep that
        # timestamp so it does not jump to the top of the feed days later just
        # because the summary finally arrived.
        if not entry.get("published_at"):
            update["published_at"] = datetime.now(timezone.utc).isoformat()

    db().table("entries").update(update).eq("id", entry["id"]).execute()
    db().table("ai_usage").insert(
        {
            "entry_id": entry["id"],
            "model": provider.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_inr": round(cost, 4),
        }
    ).execute()


def awaiting_summary_count() -> int:
    """Entries the AI still owes a summary, whatever their publication status."""
    res = (
        db()
        .table("entries")
        .select("id", count="exact")
        .eq("summary_en", "")
        .neq("status", "rejected")
        .execute()
    )
    return res.count or 0


def pending_count() -> int:
    """Entries waiting on a human in the review queue."""
    res = db().table("entries").select("id", count="exact").eq("status", "pending").execute()
    return res.count or 0

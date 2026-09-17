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
from app.services.ai_provider import (
    PermanentAIError,
    SummaryProvider,
    TransientAIError,
    Usage,
    get_provider,
)

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


async def summarize(entry: dict[str, Any]) -> tuple[Summary, Usage]:
    """Summarize one entry, retrying transient failures with backoff."""
    provider = get_provider()
    raw_text = (entry.get("original_text") or entry.get("title") or "")[:MAX_RAW_CHARS]

    user_message = USER_TEMPLATE.format(
        source_name=entry.get("_source_name") or "Government portal",
        title=entry.get("title", ""),
        state=entry.get("state", "ALL"),
        url=entry.get("original_url", ""),
        today=datetime.now().date().isoformat(),
        raw_text=raw_text,
    )

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
TRUSTED_SOURCES = {"pib", "ssc", "gem", "nta", "sbi"}


def _check_caps() -> tuple[float, int]:
    """Raise if either daily cap is already spent. Returns (spend, requests)."""
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

    if spend >= settings.ai_daily_cap_inr * 0.8:
        log.warning("AI spend at %.0f%% of the daily cap", spend / settings.ai_daily_cap_inr * 100)
    if used >= settings.ai_daily_request_cap * 0.8:
        log.warning("AI requests at %d of %d today", used, settings.ai_daily_request_cap)

    return spend, used


async def process_pending_entries(batch_size: int | None = None) -> dict[str, Any]:
    """Summarize a batch of pending entries. Returns a run report."""
    batch_size = batch_size or settings.ai_batch_size
    spend, used = _check_caps()
    provider = get_provider()

    res = (
        db()
        .table("entries")
        .select("*, sources(name, scraper_key)")
        .eq("status", "pending")
        .eq("summary_en", "")
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
        "errors": [],
    }

    for entry in entries:
        source = entry.get("sources") or {}
        entry["_source_name"] = source.get("name")
        try:
            summary, usage = await summarize(entry)
        except Exception as exc:
            report["failed"] += 1
            report["errors"].append({"entry_id": entry["id"], "error": str(exc)[:300]})
            try:
                db().table("entries").update(
                    {"ai_attempts": (entry.get("ai_attempts") or 0) + 1}
                ).eq("id", entry["id"]).execute()
            except Exception as bump_exc:
                # Losing the attempt counter costs one wasted retry later.
                # Letting it propagate would abandon the whole batch and lose
                # the summaries already written, so it is only worth logging.
                log.warning(
                    "could not record failed attempt for %s: %s", entry["id"], bump_exc
                )
            if isinstance(exc, PermanentAIError):
                # A misconfigured key fails identically for every entry; stop
                # rather than burning the whole batch's retries on it.
                report["errors"].append({"error": "stopping batch: provider misconfigured"})
                break
            continue

        cost = provider.cost_inr(usage)
        report["cost_inr"] += cost
        report["processed"] += 1

        trusted = source.get("scraper_key") in TRUSTED_SOURCES
        approve = summary.confidence > settings.ai_auto_approve_confidence and trusted
        report["approved" if approve else "held_for_review"] += 1

        _apply_summary(entry, summary, usage, cost, approve, provider)

        try:
            _check_caps()
        except DailyCapReached as exc:
            report["errors"].append({"error": f"stopping batch: {exc}"})
            break

    report["cost_inr"] = round(report["cost_inr"], 4)
    return report


def _apply_summary(
    entry: dict,
    summary: Summary,
    usage: Usage,
    cost: float,
    approve: bool,
    provider: SummaryProvider,
) -> None:
    key_details = dict(entry.get("key_details") or {})
    key_details.update({k: v for k, v in summary.key_details.model_dump().items() if v is not None})

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
    if summary.deadline:
        update["deadline"] = summary.deadline
    if summary.eligibility:
        update["eligibility"] = {"text": summary.eligibility}
    if summary.budget_or_salary and not entry.get("budget_amount"):
        update["budget_amount"] = int(summary.budget_or_salary) * 100  # INR -> paisa
    if approve:
        update["status"] = "approved"
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


def pending_count() -> int:
    res = db().table("entries").select("id", count="exact").eq("status", "pending").execute()
    return res.count or 0

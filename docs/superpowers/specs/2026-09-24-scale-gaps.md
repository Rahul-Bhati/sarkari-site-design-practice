# Spec: Scale gaps — coverage, revisions, jobs, delivery, search, alarms

**Date:** 2026-09-24
**Status:** Approved to implement by the request that asked for this spec and then the code.
**Supersedes nothing.** `docs/PRD.md` stays the product definition. This spec is the fix for six gaps that show up once the feed has real notices and real subscribers.

## Assumptions

1. The product stays a web app (Next.js) plus a FastAPI scraper/API. No mobile client in this work.
2. Postgres stays Supabase. New tables ship as SQL migration files. They are not applied to a live database until you say so in the same message.
3. Publish-then-enrich stays. A trusted source is visible before the summary exists.
4. The content hash formula (title + URL + date) stays, so today's rows are not re-inserted. A repeat of the same notice is recognized by normalized URL within a source, and the hash is only the insert key.
5. No CAPTCHA-solving vendor, no Meilisearch, no new paid queue service. The queue is a Postgres table claimed with `FOR UPDATE SKIP LOCKED`.
6. Portal-extracted deadline, title, and dates win over the model when the portal already supplied them.
7. `tasks/plan.md` and `tasks/todo.md` are the finished jobs-coverage milestone. This work lives in `tasks/scale-gaps-plan.md` and `tasks/scale-gaps-todo.md`.

## Objective

A person tracking a job or a tender needs the notice while the closing date is still ahead, including when the department changes that date. Success for this spec:

- A second scrape of the same document URL updates the deadline on the existing row instead of dropping the change or inserting a twin.
- The model does not replace a deadline the scraper already stored.
- GeM keeps fetching newest-first pages until a page is entirely already stored, and never past 30 pages in one run.
- When the in-process scheduler is on, every active registered source is scheduled from `sources.frequency_minutes`, not from a three-key dict.
- The remaining three gaps (durable queue, digest outbox, Hindi search plus freshness alarm) are specified here and implemented only after the slices above are green. Their schema is in the migration file and is not executed automatically.

### Who it is for

Readers of the public feed, email subscribers, and Thekedar users who act on tender deadlines.

## Tech stack

- Backend: Python 3.12/3.13, FastAPI, pytest, Supabase client
- Frontend: Next.js 16, unchanged in the first slices
- Database: Supabase Postgres, migrations in `supabase/migrations/`

## Commands

```bash
cd backend && .venv/bin/python -m pytest
cd backend && .venv/bin/python -m pytest tests/test_identity.py tests/test_scheduler_plan.py -q
cd frontend && npm run build
```

Dev servers stay as in the README: uvicorn on port 8000, `npm run dev` on port 3000.

## Project structure

```
docs/superpowers/specs/2026-09-24-scale-gaps.md   → this spec
tasks/scale-gaps-plan.md                          → implementation order
tasks/scale-gaps-todo.md                          → task checklist
backend/app/scrapers/identity.py                  → URL identity and revision plan
backend/app/scrapers/runner.py                    → applies the plan on scrape
backend/app/scrapers/utils/dedup.py               → hash and URL lookups
backend/app/scrapers/sources/gem.py               → stop when a page is already stored
backend/app/services/summarizer.py                → portal deadline wins
backend/app/services/scheduler.py                 → one job per active source
backend/tests/                                    → pytest
supabase/migrations/009_scale_gaps.sql            → queue, outbox, events, search (not applied)
```

## Code style

Match the modules around the change. One pure function for the decision, the database call outside it.

```python
def plan_persist(
    incoming: list[tuple[str, RawEntry]],
    stored: list[StoredNotice],
) -> PersistPlan:
    """Split a scrape into inserts, revisions, and duplicates.

    `incoming` is (content_hash, entry). Match on normalized URL.
    A changed deadline updates the stored row. It does not insert another.
    """
```

Names are verbs for actions (`plan_persist`, `jobs_for_sources`) and nouns for data (`StoredNotice`). No new abstraction for a single call site.

## Testing strategy

- pytest in `backend/tests/`. New behavior gets a failing test first.
- Pure decisions (identity, page-stop, which deadline to write, which sources to schedule) are unit-tested with no network and no Supabase.
- Do not weaken existing scraper tests. The hash tests that expect a different date to change the hash stay true.
- Frontend is not part of these slices, so `npm run build` is not a gate until a later slice touches it.

## Boundaries

- Always: run the targeted pytest before calling a slice done. Keep certificate verification on. Leave the original source URL on the entry.
- Ask first: applying a migration, adding a dependency, changing CI, deploying, pushing.
- Never: disable TLS verification, solve CAPTCHAs with a paid bypass, commit secrets, overwrite `tasks/plan.md` or `tasks/todo.md`, delete stored summaries because a deadline changed.

## The six gaps and the solution we are building

### 1. Tender coverage

NIC eProc (CPPP, UP, Maharashtra, MP, Rajasthan) stays unbuilt while it is CAPTCHA-gated. One shared feed or a licensed dump is the way through, and it is a separate decision. This spec does not pretend a scraper can skip that gate.

GeM is the tender source we already parse. It stops at 5 pages (~50 bids) of ~47,000. **Solution:** newest-first pages continue until every URL on a page is already in `entries`, with a hard stop at 30 pages so a first run cannot walk the whole archive. The lookup is by `original_url`.

### 2. Deadlines never update

**Solution:** normalized URL within the source is the identity of a notice we have already stored. Tracking query params (`utm_*`) and a trailing slash do not make a new notice. If the title, deadline, published date, or PDF URL changed, patch that row. Do not insert a second row. Do not rewrite `content_hash`, `summary_en`, `summary_hi`, `status`, or `published_at`.

If the portal left the deadline empty, the model may fill it. If the portal set it, `_apply_summary` leaves it.

A later migration adds `entry_events` so a digest can say the date moved. The first slice updates the row without that table, so a digest still sees the new deadline on the entry itself.

### 3. Jobs die with the web process

**This slice:** `sources.frequency_minutes` drives the in-process scheduler for every active scraper that is registered in code. The old dict that only named PIB, SSC, and Rajasthan is the fallback when the database cannot be read.

**Next slice, not in the first code change:** a `jobs` table, cron only enqueues, workers claim with `FOR UPDATE SKIP LOCKED`, idempotency key `(source, window)`. The migration file contains the table. Nothing reads it until that task starts.

### 4. One query per subscriber

**Next slice:** one select of the day's new and changed entries, insert into `notification_outbox` unique on `(subscriber_id, channel, digest_date)`, keywords applied in SQL before the limit of 25. A sender drains the outbox. The current per-subscriber query stays until that task.

### 5. Feed and search shape

**Next slice:** keyset pagination on `(published_at, id)`, a second `tsvector` over `summary_hi` using the `simple` config, raw text moved toward object storage only when a row is larger than the excerpt we keep. Offset pagination stays until that task so the feed API does not change in the same breath as dedup.

### 6. No freshness alarm

`consecutive_failures` is already incremented. **Next slice:** a maintenance check that returns sources whose `consecutive_failures` is at least 3, or whose `last_success_at` is older than `frequency_minutes` times 3. The admin endpoint is how a human or the cron sees it. Emailing that list waits on Resend already being configured, and the check itself must not send mail in tests.

Subscribe rate limits move to Redis only when `UPSTASH_REDIS_URL` is set. Until then the in-process limit stays, and the spec does not claim it survives a second instance.

## Success criteria

- [ ] Same normalized URL and a new deadline produces an update plan, not an insert.
- [ ] Same normalized URL and the same facts produces a duplicate, not an update.
- [ ] A URL that differs only by `utm_source` or a trailing slash matches the stored row.
- [ ] `content_hash` still changes when the title, URL, or date string changes.
- [ ] GeM's page walker stops on the first fully-known page and stops at page 30 even if every page is new.
- [ ] A summary whose deadline differs from a stored portal deadline does not put `deadline` in the update.
- [ ] A summary may set `deadline` when the stored entry has none.
- [ ] An active source row for `nta` with `frequency_minutes = 120` is a scheduled job. An inactive row is not. A scraper key with no class is not.
- [ ] `cd backend && .venv/bin/python -m pytest` passes.
- [ ] Migration `009` is in the repo and has not been applied by the agent.

## Open questions

- Whether to license an NIC eProc feed or wait for an official dump. No scraper will be written for that family in this spec.
- Whether a deadline revision should clear the summary so the model rewrites it. This spec keeps the old summary and updates the date, so the card is not blank.

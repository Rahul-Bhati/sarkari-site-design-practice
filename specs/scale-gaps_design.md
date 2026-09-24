# Feature: Source freshness alarm

Guardian pass on the scale-gaps work that is still open. Tasks 1–6 are already on `scale-gaps-notice-revisions`. This document is the three-layer design for the next slice, and the security checkpoint for it. The queue, the digest outbox, and Hindi search stay designed here and are not built in this slice, because migration `009` is not applied.

## Requirements (EARS)

- While a source row is active, when it has 3 or more consecutive failures, the system shall mark it stale.
- While a source row is active and has succeeded at least once, when that success is older than three times `frequency_minutes`, the system shall mark it stale.
- While a source has been run and has never succeeded, the system shall mark it stale.
- While a source is inactive, or has never been run, the system shall not mark it stale.
- While an admin is signed in, when they open Scraper health, the system shall show which sources are stale and why.
- While the maintenance job runs, the system shall include the stale list in its result and write a warning log. It shall not send email.
- While the caller is not an admin, when they request scraper status or maintenance, the system shall respond 401 and shall not read `sources`.

## Architecture

### [Frontend]

- `ScraperHealth` in `frontend/src/components/admin/AdminConsole.tsx` already loads `/api/admin/scraper-status` behind a Supabase session.
- Add `stale` and `stale_reason` on `ScraperSource`. When `stale` is true, show the reason under the source name and include it in the health dot's accessible name.
- Loading stays the skeleton. A failed load stays the existing toast and an empty table. No new page, no public feed change.
- The admin screen does not send the shared `X-Admin-Key`. It sends the user's bearer token. The browser never decides who is an admin.

### [Backend]

- `source_staleness(row, now)` is a pure function. It returns a reason string or `None`.
- `GET /api/admin/scraper-status` adds `stale` and `stale_reason` on each source. A stale source is `health: "red"`.
- `POST /api/admin/maintenance` adds `stale_sources`: `{scraper_key, reason}[]`, and logs a warning. No Resend call.
- Both routes stay on the admin router. No new public route.
- Response fields are the existing source columns plus the two flags. No subscriber email, phone, or API key.

### [Security]

Checkpoint, completed before the code below:

| Check | Result |
|---|---|
| Auth | Both routes use `require_admin`. A missing or wrong `X-Admin-Key` is compared with `hmac.compare_digest` and returns 401. A bearer token must match `admin_users`. |
| Authz | Source health is operator data. It is not readable with the anon key. RLS already has no public policy on `scraper_runs`. |
| Input | This slice takes no new caller input. `now` is the server clock. Source rows are read, not trusted as commands. |
| Output | Stale payload is `scraper_key` and a fixed reason. `last_error` was already visible to admins and is not added to the maintenance list. |
| Rate limit | Unchanged. These routes are not on the public subscribe limiter. The cron caller is the admin key, already required. |
| Logging | A stale set writes one warning with scraper keys. Auth failures stay in `require_admin`. This slice does not log the admin key. |

Not in this slice, so they cannot be called against tables that do not exist yet:

- Job queue (`jobs`). Claiming rows before migration 009 is applied would 500 the cron.
- Notification outbox. Same reason. When it is built, the sender must keep the admin key off the public subscribe route, and the outbox unique key must be `(subscriber_id, channel, digest_date)` so a retry cannot double-send.
- Hindi search. A new `tsvector` is in migration 009. The feed query stays as it is until that migration is confirmed and applied.

## Implementation plan

- [x] Step 1: Pure staleness decision and tests
- [x] Step 2: Attach it to scraper status and maintenance
- [x] Step 3: Show the reason on Scraper health
- [ ] Step 4: Queue, outbox, Hindi search — after you confirm migration 009

## Hand-off

- QA: `cd backend && .venv/bin/python -m pytest tests/test_freshness.py -q` then the full suite.
- The admin page needs a signed-in admin to see the label. The decision itself is covered without a browser session.
- Do not apply `supabase/migrations/009_scale_gaps.sql` as part of this slice.

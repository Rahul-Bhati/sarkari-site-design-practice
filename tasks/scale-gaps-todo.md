# TODO: Scale gaps

Spec: `docs/superpowers/specs/2026-09-24-scale-gaps.md`
Plan: `tasks/scale-gaps-plan.md`

## Checkpoint A — identity, GeM stop, portal deadline, scheduler

- [x] **Task 1 — `plan_persist`**
  - Acceptance: new URL inserts; same URL and same facts is a duplicate; a new deadline is an update and not an insert; `utm_*` and a trailing slash match
  - Verify: `cd backend && .venv/bin/python -m pytest tests/test_identity.py -q`
  - Files: `backend/app/scrapers/identity.py`, `backend/tests/test_identity.py`

- [x] **Task 2 — runner applies the plan**
  - Acceptance: revisions call `entries` update and are not upserted; summaries and status are untouched
  - Verify: `tests/test_identity.py` plus the full suite
  - Files: `backend/app/scrapers/runner.py`, `backend/app/scrapers/utils/dedup.py`

- [x] **Task 3 — portal deadline wins**
  - Acceptance: a stored deadline is omitted from the summary update; an empty one may be filled
  - Verify: `cd backend && .venv/bin/python -m pytest tests/test_summarizer.py -q -k deadline_to_write`
  - Files: `backend/app/services/summarizer.py`, `backend/tests/test_summarizer.py`

- [x] **Task 4 — GeM stops on a known page**
  - Acceptance: walker stops on the first fully-known page and at page 30
  - Verify: `cd backend && .venv/bin/python -m pytest tests/test_scrapers.py -q -k pages_to_take`
  - Files: `backend/app/scrapers/sources/gem.py`, `backend/tests/test_scrapers.py`

- [x] **Task 5 — schedule every active source**
  - Acceptance: active registered sources use `frequency_minutes`; inactive and unknown keys are dropped
  - Verify: `cd backend && .venv/bin/python -m pytest tests/test_scheduler_plan.py -q`
  - Files: `backend/app/services/scheduler.py`, `backend/tests/test_scheduler_plan.py`

## Later — do not start until Checkpoint A is green

- [x] **Task 6 — `supabase/migrations/009_scale_gaps.sql`** (file only, not applied)
- [x] **Task 7 — freshness check**
- [ ] **Task 8 — durable job queue**
- [x] **Task 9 — notification outbox**
  - Acceptance: one pooled select instead of one per subscriber; keywords filter before the 25 cap; a planned digest is reserved on `(subscriber_id, channel, digest_date)` so a crashed run resumes instead of resending
  - Verify: `cd backend && .venv/bin/python -m pytest tests/test_outbox.py -q`
  - Files: `backend/app/services/outbox.py`, `backend/app/services/notifier.py`, `backend/app/services/scheduler.py`, `backend/app/routers/admin.py`, `backend/tests/test_outbox.py`
  - **Needs `009_scale_gaps.sql` applied before it runs live** — `notification_outbox` does not exist yet
- [ ] **Task 10 — keyset pagination and Hindi search vector**

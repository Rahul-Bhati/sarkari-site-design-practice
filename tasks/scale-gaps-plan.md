# Plan: Scale gaps

Spec: `docs/superpowers/specs/2026-09-24-scale-gaps.md`

## Order

Identity and the portal deadline come first, because a wrong or frozen closing date is the failure subscribers feel. GeM's page stop is the same idea applied to tenders. The scheduler fix is independent and lands in the same checkpoint because it is a pure function over rows we already store.

The queue, the outbox, Hindi search, and the freshness alarm wait until that checkpoint is green. Their tables are written in `009_scale_gaps.sql` and not applied.

```
Task 1  plan_persist (URL identity)
            │
            ├──► Task 2  runner applies updates
            │
Task 3  portal deadline wins ──────────────┐
                                            ├──► Checkpoint A
Task 4  GeM stops on a known page ──────────┤
                                            │
Task 5  schedule every active source ───────┘

Task 6  migration file only (jobs, outbox, events, Hindi vector)
Task 7  freshness check (read-only)
Task 8  durable queue worker
Task 9  notification outbox
Task 10 keyset feed + Hindi search
```

Tasks 1–5 are this implementation. Tasks 6–10 stay specified until checkpoint A is green and you ask for the next one. Task 6 is a file, not a live migration.

## Risks

- Matching on URL collapses two notices that share a permalink. GeM's bid document URL is unique per bid. Notice boards that use one "Read more" URL for many rows must keep the hash path: `plan_persist` inserts when the URL is new, and only updates when the URL matches a stored row.
- Patching a row must not clear `summary_en`. The update dict lists only the changed facts.
- Raising GeM from 5 pages toward 30 only happens until a page is fully known. A first run on an empty table stops at 30.

## Checkpoint A

- `cd backend && .venv/bin/python -m pytest` is green
- No migration has been applied

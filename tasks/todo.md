# TODO: Jobs source coverage (Milestone 11, batch 1)

Plan: `tasks/plan.md` · Spec: `docs/superpowers/specs/2026-09-18-jobs-source-coverage-design.md`

## Blockers

- [x] **`SUPABASE_SERVICE_KEY` holds the anon key** — resolved; the key now carries
      the `service_role` claim and scrapers insert.
- [x] **Decide NTA backlog depth** — capped at 12 months (Rahul, 2026-09-18).

## Phase 1: Ship the verified source

- [x] **Task 1 — NTA scraper** (M)
  - [x] `sources/nta.py`: parse `table tr`, title from row minus link text and index
  - [x] Date from `Notice_(\d{14})\.pdf` — *and* the bare pre-2020 `(\d{14})\.pdf`
  - [x] Age cap — positional, `_within_age_cap`, not per-row
  - [x] `ScraperError` on zero rows
  - [x] Register in `runner.py`; add `sources` row
  - [x] Tests — live run: 1,890 rows parsed, **331** within the cap
  - [x] Add to `TRUSTED_SOURCES` (missed first time; all 331 were held for review)

- [x] **Checkpoint A** — suite green; live scrape inserts; NTA notices in feed.

## Phase 2: Discovery, then the second example

- [x] **Task 2 — Discovery pass** (S)
  - [x] TNPSC — reachable, 291 rows, but **zero open recruitments**; deprioritised
  - [x] UPSC — returns 102,812 bytes for *every* URL incl. nonsense paths; no 404s.
        A JS shell with no server-rendered list. Blocked.
  - [x] SBI careers — viable, `div.card`, live windows
  - [x] RRB Secunderabad — viable, deferred to Task 7
  - [x] Recorded in `docs/SCRAPER_GUIDE.md` ("Source survey — September 2026")

- [x] **Task 3 — Second source, bespoke** (M) — **SBI**, not TNPSC: the plan
      picked TNPSC on row count, but freshness beat volume. Live: **76** entries,
      5 open application windows.

- [x] **Task 4 — Extract `NoticeBoardScraper`** (M)
  - [x] `base_notice.py` with the frozen `NoticeBoard` config
  - [x] Refactor Tasks 1 and 3 to configs (NTA 203 → 102 lines)
  - [x] Generic row-extraction tests, site-independent (20 tests, no real portal)
  - [x] Existing tests pass unedited — one import line changed, nothing else

- [x] **Checkpoint B** — two sources on one base; 210 tests green; all 407 live
      entries hash to rows already in the DB, so behaviour is provably unchanged.

## Phase 3: TLS and IBPS

- [x] **Task 5 — AIA TLS helper** (S)
  - [x] `utils/tls.py`: `ssl_context_for(host)`, cached per host, chases up to 4 levels
  - [x] `None` when no AIA extension; `TLSChainError` when the repair fails
  - [x] Wire `fetch="aia_tls"` into `base.py` (`client_aia`) and `base_notice.py`;
        an unknown mode raises at import time, not at scrape time
  - [x] Tests with stubbed I/O and real in-process certificates — no live handshake
  - [x] `grep -rn "verify=False" backend/app/` returns nothing, and a guard test
        keeps it that way
  - [x] Live: `ibps.in` 200 (221 KB), `egazette.gov.in` 200 (68 KB), verification on
  - [x] Removed the unnecessary `verify=False` in `raj_eproc.py` — that host
        verifies cleanly — and Playwright's `ignore_https_errors`

- [x] **Task 6 — IBPS source** (S)
  - [x] Found **two** listing pages, kept as two sources because they answer
        different questions: `ibps_crp` (`/crp-updates/`, IBPS's own exam
        notices) and `ibps_recruitment` (`/recruitment/`, live hiring IBPS runs
        for other bodies, every row with a closing date)
  - [x] Both `fetch="aia_tls"`; TLS path exercised end to end
  - [x] Live through the runner: `ibps_crp` 20 new, `ibps_recruitment` 10 new
  - [x] Registered, added to `TRUSTED_SOURCES`, `sources` rows inserted and active
  - [x] Base generalised on the evidence: the anchor may *be* the row, `_extra`
        may supply `published`/`deadline`, and row identity is title + URL
        (NTA 331 and SBI 76 verified unchanged)

## Phase 4: Fill out and verify

- [ ] **Task 7 — Remaining viable sources as configs** (S each)
- [ ] **Task 8 — Activate and verify end to end**
  - [ ] `UPDATE sources SET is_active = true` — editing `seed.sql` is not enough
        (`ON CONFLICT DO NOTHING`); this is how the GeM row was missed
  - [ ] `./scripts/real-data.sh` completes with entries from every new source
  - [ ] Browser pass over `/feed?category=naukri`
  - [ ] README source table updated, including what stayed blocked

- [ ] **Checkpoint C** — all criteria met; real job notifications live.

## Known blocked (do not attempt)

- NIC eProcurement family (CPPP, UP, Maharashtra, MP, Rajasthan) — CAPTCHA gate
- ~~RRB Chandigarh — certificate invalid for its own hostname~~ **Wrong.** Only
  `www.rrbcdg.gov.in` is mismatched; the apex `rrbcdg.gov.in` verifies and
  redirects to `rrb.indianrailways.gov.in/chandigarh`. Candidate for Task 7.
- SEBI (CAPTCHA); NCS, `rrbapply`, CBIC, joinindianarmy, RBI careers (JS-rendered)

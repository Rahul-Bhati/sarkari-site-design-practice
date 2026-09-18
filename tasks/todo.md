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

- [x] **Task 7 — Remaining viable sources as configs** (S each)
  - [x] **RRB Secunderabad** — 112 dated entries live. Task 2's recommended page
        (`/archive_type/employment-notices/`) turned out stale (newest
        2025-03-03); the boards are migrating onto one common portal,
        `rrb.indianrailways.gov.in/<board>`, which is live and dated. Secunderabad,
        Chandigarh and Mumbai serve identical markup, so `board_config()` makes
        any of the 21 boards a one-liner. Only Secunderabad registered — CENs are
        national, so all 21 would be 21 copies of every notice.
  - [x] **TNPSC** — re-checked, still zero open and zero recently-closed. Not built.
  - [x] **eGazette** — out of scope: it is the `rule` category, which the spec
        defers to a later batch. The AIA fix reaches it when that batch happens.
  - [x] URL spaces escaped in the base (RRB writes `category=Application (Special
        Notice)` raw); NTA, SBI and both IBPS sources verified unchanged.
- [x] **Task 8 — Activate and verify end to end**
  - [x] All five new sources have `sources` rows and `is_active = true`, inserted
        deliberately rather than via `seed.sql`'s `ON CONFLICT DO NOTHING`
  - [x] Full `run_all`: **8/8 scrapers succeeded**, 50 new entries, and the
        already-imported sources correctly returned 0 new / all duplicate
  - [x] Browser pass over `/feed?category=naukri` — real entry rendering with a
        working deadline badge and source attribution
  - [x] README source table rewritten: 6 working, 1 thin, 1 degraded, 4 blocked
  - [x] Fixed `real-data.sh --purge`, which matched 3 of 19 seed rows and could
        not have matched the rest safely (fake PIB URLs are shaped exactly like
        real ones). Now keys on `content_hash LIKE 'seed_hash_%'`, which no real
        scraper can produce.

- [ ] **Checkpoint C** — partially met, blocked on a provider quota, not on code.
  - [x] Scrapers: all 8 green, 691 entries collected
  - [x] Pipeline proven for the new sources — an IBPS recruitment entry
        summarised at 0.95 confidence, auto-approved, and is live in the feed
  - [ ] **Blocked: Groq free tier is 200,000 tokens/day and it is spent.**
        ~490 entries stay pending until the window resets. The app's guards are
        requests/day (900, only ~180 used) and rupees — neither models tokens,
        so it thought it had headroom while the real budget was gone. At ~1,800
        tokens a summary the true ceiling is ~110/day.
  - [ ] Decide whether to purge the 19 fabricated seed entries (see below)

## Publish-then-enrich (Rahul's call, 2026-09-18)

The AI quota used to gate *visibility*: nothing appeared until it was
summarised, so 490 real notices sat invisible behind an exhausted token budget.
That is now split in two:

- **Visibility** is decided by source trust, at scrape time. A `TRUSTED_SOURCES`
  entry is published immediately with the portal's own title, department and
  dates. The card says the summary is still being written and links the notice.
- **Summarisation** is decided by "has no summary yet", not by status, so the
  queue is unaffected by an entry already being live.

Result: the naukri feed went from 5 entries (4 of them fabricated seed rows) to
**219 real ones**, plus 312 notices and 98 tenders — 630 live, 446 of them
showing scraped facts while they wait their turn.

Consequence worth remembering: an unsummarised entry is filed under the
*scraper's* guessed category, so those guesses now have to be right. NTA's was
`naukri` and the AI had been reclassifying 128 of 130 to `notice` — the hint is
corrected and the 178 unsummarised NTA rows were moved.

- [x] **Token-per-day guard** — `ai_daily_token_cap`, default 195,000, checked
      alongside spend and requests, and surfaced in `/api/admin/pending-count`.

## Follow-ups this milestone surfaced
- [x] **PIB fixed.** My first diagnosis was wrong: the list page is fine — it
      yields correct English titles and ministries. The breakage was one link
      behind it. `allRel.aspx` points at `PressReleaseDetail.aspx`, a JavaScript
      shell whose only heading is the "Other Press Releases" menu, and the AI
      dutifully summarised that menu 24 times over. All 24 stored PIB entries
      were the same nav page under different PRIDs; four were live in the feed.
      The release is at `PressReleasePage.aspx` with the same PRID, so the URL is
      rebuilt and the body read from `#PdfDiv`. A minimum body length now stops
      a shell page ever being published as news. Artefacts deleted, re-scraped
      clean with real titles, ministries and dates.
      Note: `allRel.aspx` serves the current day only — its date dropdowns are a
      dead ASP.NET postback, verified by posting a valid `__VIEWSTATE` for
      several past dates and getting identical results.
- [x] **SSC widened: 1 entry → 124.** It was never broken, just pointed at the
      smallest of three feeds. The other two are not in the JS bundle at all —
      the main bundle names 53 `admin/5.1/*` paths and none is the notice board,
      and the whole `general-website` namespace is absent from it. Loading the
      homepage in a browser and reading the network tab found both in one go.
      - `general-website/portal/notice-boards` — 695 records, newest first,
        every one with a PDF. 120 kept inside a 180-day window.
      - `admin/5.1/liveExams` — the only feed with a deadline anyone can still
        act on. Three exams open now: CAPF (30 Sep), CHSL (7 Oct), JE (22 Sep).
      - The old advertisements feed stays; it is the only place the Selection
        Post phases appear.
      Two traps: `limit` is capped at 10 server-side (asking for 200 returns a
      response with no `data` key at all), and attachment paths arrive with
      Windows separators and must go through `/api/attachment/` — the bare
      `/uploads/...` path answers **200 with the SPA shell**, so a naive URL
      silently stores an 80 KB HTML page as the notice PDF.

## Known blocked (do not attempt)

- NIC eProcurement family (CPPP, UP, Maharashtra, MP, Rajasthan) — CAPTCHA gate
- ~~RRB Chandigarh — certificate invalid for its own hostname~~ **Wrong.** Only
  `www.rrbcdg.gov.in` is mismatched; the apex `rrbcdg.gov.in` verifies and
  redirects to `rrb.indianrailways.gov.in/chandigarh`. Candidate for Task 7.
- SEBI (CAPTCHA); NCS, `rrbapply`, CBIC, joinindianarmy, RBI careers (JS-rendered)

# Implementation Plan: Jobs source coverage (Milestone 11, batch 1)

Spec: `docs/superpowers/specs/2026-09-18-jobs-source-coverage-design.md`

## Overview

Add job (`naukri`) sources to a feed that currently has three working scrapers,
and build the shared machinery later batches can reuse. The verified prize is
NTA's notice archive — 1,891 rows carrying real titles and dates. A per-host TLS
helper brings back IBPS and eGazette, whose servers omit an intermediate
certificate. Four further sources are candidates only; their listing pages have
not been found yet, so the plan schedules discovery rather than assuming them.

## Architecture decisions

- **Row-based extraction, not anchor-based.** NTA's anchor text is the useless
  string "Read More" while the containing `<tr>` holds the real title. Any
  anchor-driven design fails on the source we most want.
- **The abstraction is extracted, not designed.** `NoticeBoardScraper` is pulled
  out of NTA *plus one further working source*. With one example there is no
  evidence about which parts generalise.
- **Certificate verification is never disabled.** The TLS helper supplies the
  intermediate the server should have sent, then verifies normally against
  certifi's roots. Sources that cannot be reached this way stay unreached.
- **Dates come from URLs when available.** NTA encodes the publish timestamp in
  the filename (`Notice_20260917191931.pdf`), which is more reliable than
  parsing display text.
- **`RawEntry` needs no change.** The runner already maps `raw_text` to the
  `original_text` column in `_to_row`.

## Dependency graph

```
Task 1  NTA scraper (bespoke)  ──┐
                                 ├──► Task 4  Extract NoticeBoardScraper
Task 2  Discovery pass ──► Task 3  Second source (bespoke) ──┘
                                                    │
                        Task 5  TLS helper ──► Task 6  IBPS config
                                                    │
                                          Task 7  Remaining configs
                                                    │
                                          Task 8  Activate + verify
```

## Task list

### Phase 1: Ship the verified source

**Task 1: NTA scraper**

*Description:* A bespoke scraper for `nta.ac.in/NoticeBoardArchive`. Parses
`table tr` rows, takes the title from the row text minus the link text and
leading index, and derives `published_date` from the PDF filename timestamp.
Written plainly, without abstraction — it is the first of two examples the base
class will later be extracted from.

*Acceptance criteria:*
- [ ] Returns ≥ 500 entries against saved fixture HTML
- [ ] Titles exclude "Read More" and the leading row index
- [ ] `published_date` parsed from `Notice_(\d{14})\.pdf`; absent rather than wrong when the pattern does not match
- [ ] Raises `ScraperError` when zero rows parse

*Verification:*
- [ ] `cd backend && .venv/bin/python -m pytest tests/test_scrapers.py -k NTA`
- [ ] Full suite green
- [ ] Live run inserts real rows: `POST /api/admin/scrape?source=nta`

*Dependencies:* None
*Files:* `backend/app/scrapers/sources/nta.py`, `backend/app/scrapers/runner.py`,
`backend/tests/test_scrapers.py`, `backend/tests/fixtures/nta_archive.html`,
`supabase/seed.sql`
*Scope:* M

---

### Checkpoint A — after Task 1
- [ ] Full test suite passes
- [ ] A live scrape inserts NTA entries and `scraper_runs` records success
- [ ] Summarised NTA notices render in the feed under `naukri`
- [ ] **Stop and review with Rahul before building the abstraction**

---

### Phase 2: Discovery, then the second example

**Task 2: Discovery pass for four candidate sources**

*Description:* Find the real listing page for TNPSC, UPSC, SBI careers and RRB
Secunderabad. Each is reachable, but the URLs tried returned navigation menus or
nothing. For each, record the listing URL, row selector, where the title and
date live, and whether plain fetching works. This is research; its output is
documentation, not code. Deliberately early — if all four fail, the next batch
should be the already-verified `rule`/`yojana` sources instead.

*Acceptance criteria:*
- [ ] Each of the four is marked viable (with selector and URL) or blocked (with the reason)
- [ ] At least one viable source identified, or an explicit recommendation to switch to the `rule`/`yojana` batch
- [ ] Findings appended to `docs/SCRAPER_GUIDE.md`

*Verification:*
- [ ] For each viable source, a throwaway script extracts ≥ 10 rows with titles
- [ ] No production code changed

*Dependencies:* None (can run alongside Task 1)
*Files:* `docs/SCRAPER_GUIDE.md`
*Scope:* S

---

**Task 3: Second source, bespoke**

*Description:* Implement the strongest source from Task 2, again without
abstraction. Two independent implementations are what make the extraction in
Task 4 evidence-based. If Task 2 found nothing viable, this task is replaced by
RBI notifications (698 anchors, already verified reachable) so the extraction
still has a second example.

*Acceptance criteria:*
- [ ] Returns ≥ 10 entries from fixture HTML
- [ ] Titles, links and dates correct for that source
- [ ] Raises `ScraperError` on zero rows

*Verification:*
- [ ] Targeted tests pass; full suite green
- [ ] Live scrape inserts rows

*Dependencies:* Task 2
*Files:* `backend/app/scrapers/sources/<key>.py`, `runner.py`, tests, fixture, `seed.sql`
*Scope:* M

---

**Task 4: Extract `NoticeBoardScraper`**

*Description:* Pull the shared shape out of Tasks 1 and 3 into
`base_notice.py` — the frozen `NoticeBoard` config and a generic `scrape()` —
then refactor both scrapers to configs. Only fields both sources actually need
get into the config; anything used by one source stays in that source.

*Acceptance criteria:*
- [ ] Both scrapers reduced to configuration plus any genuinely site-specific override
- [ ] Their existing tests pass unchanged — behaviour is identical
- [ ] Generic row extraction covered by its own tests, independent of any site
- [ ] `min_title_len` demonstrably excludes navigation rows

*Verification:*
- [ ] Full suite green with no test edits beyond imports
- [ ] Live scrape of both sources returns the same entry counts as before

*Dependencies:* Tasks 1, 3
*Files:* `backend/app/scrapers/base_notice.py`, both source files, `backend/tests/test_scrapers.py`
*Scope:* M

---

### Checkpoint B — after Tasks 2-4
- [ ] Two sources working through one shared base class
- [ ] No behaviour change from the refactor (entry counts identical)
- [ ] Full suite green

---

### Phase 3: TLS and IBPS

**Task 5: AIA TLS helper**

*Description:* `ssl_context_for(host)` reads the leaf certificate's Authority
Information Access "CA Issuers" URI, downloads the intermediate, and returns an
`SSLContext` built from certifi's roots plus that intermediate, cached per host.
Proven working against `ibps.in` and `egazette.gov.in` during design.

*Acceptance criteria:*
- [ ] Returns `None` when the certificate carries no AIA extension — callers fail loudly, never silently downgrade
- [ ] Contexts cached per host
- [ ] `verify=False` and `CERT_NONE` appear nowhere outside the throwaway probe that reads the leaf
- [ ] A fetch failure raises rather than falling back to unverified TLS

*Verification:*
- [ ] Unit tests with a stubbed AIA fetch; no live handshake in tests
- [ ] Manual: `ibps.in` returns HTTP 200 with verification on
- [ ] `grep -rn "verify=False" backend/app/` returns nothing

*Dependencies:* None
*Files:* `backend/app/scrapers/utils/tls.py`, `backend/app/scrapers/base.py`,
`backend/tests/test_scrapers.py`
*Scope:* S

---

**Task 6: IBPS source**

*Description:* Add IBPS as a `NoticeBoard` config with `fetch="aia_tls"`,
including finding its listing page — design only established that the host
becomes reachable, not where its notices live.

*Acceptance criteria:*
- [ ] Listing page identified, or IBPS documented as blocked with the reason
- [ ] If viable: entries parsed from fixture, with dates
- [ ] TLS path exercised end to end against the live host

*Verification:*
- [ ] Tests pass; live scrape inserts rows
- [ ] Certificate verification confirmed active

*Dependencies:* Tasks 4, 5
*Files:* `backend/app/scrapers/sources/ibps.py`, `runner.py`, tests, fixture, `seed.sql`
*Scope:* S

---

### Phase 4: Fill out and verify

**Task 7: Remaining viable sources as configs**

*Description:* Add whichever Task 2 sources remain viable, one config each. Each
is independent and individually revertible.

*Acceptance criteria:*
- [ ] Each source parses its fixture and yields dated entries
- [ ] Each has a `sources` row and a registry entry

*Verification:*
- [ ] Tests pass per source; full suite green
- [ ] Live scrape per source inserts rows

*Dependencies:* Task 4
*Files:* one source file, fixture and test per source; `runner.py`; `seed.sql`
*Scope:* S per source

---

**Task 8: Activate sources and verify end to end**

*Description:* Flip the new sources to `is_active = true` and run the full
pipeline. Note that `seed.sql` uses `ON CONFLICT DO NOTHING`, so editing it does
**not** update an already-seeded database — activation must be a deliberate
`UPDATE`, which is exactly how the GeM row was missed before.

*Acceptance criteria:*
- [ ] Every new source has `is_active = true` in the database, not only in `seed.sql`
- [ ] `./scripts/real-data.sh` completes with entries from every new source
- [ ] `naukri` feed shows real notifications with working "View original" links
- [ ] Scraper health dashboard shows each source succeeding

*Verification:*
- [ ] `GET /api/stats` shows the raised `sources_active` count
- [ ] Manual browser pass over `/feed?category=naukri`
- [ ] README source table updated

*Dependencies:* Tasks 1, 3, 6, 7
*Files:* `README.md`, `supabase/seed.sql`
*Scope:* S

---

### Checkpoint C — complete
- [ ] All acceptance criteria met
- [ ] Full suite green
- [ ] Real job notifications visible in the feed
- [ ] README reflects actual source status, including what stayed blocked

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Discovery finds nothing viable | Medium | Task 2 runs early; fallback is RBI, already verified. Batch still ships NTA. |
| Over-abstraction | Medium | Base class extracted from two working sources, never designed up front. |
| Markup changes break selectors | Medium | Zero rows raises `ScraperError`, surfaced on the health dashboard. |
| NTA archive is heavy (2.2 MB, 1,891 rows) | Low | One request per run; first run inserts many entries, later runs dedupe on `content_hash`. |
| Groq token pacing makes the first run slow | Low | Expected — `real-data.sh` loops until the queue drains. |

## Open questions

- **Backlog depth.** NTA's archive holds 1,891 notices going back years. Import
  all of them, or cap by age the way SSC's `MAX_AGE_DAYS` does? A full import
  costs roughly 1,891 Groq calls and would swamp the feed with expired notices.
  Recommendation: cap at 12 months. **Needs Rahul's decision before Task 1.**
- **Blocking issue:** `SUPABASE_SERVICE_KEY` in `backend/.env` currently holds
  the anon key. Reads work; writes fail with `new row violates row-level
  security policy`, so no scraper can insert. Must be the `service_role` key
  before any live verification step.

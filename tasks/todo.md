# TODO: Jobs source coverage (Milestone 11, batch 1)

Plan: `tasks/plan.md` · Spec: `docs/superpowers/specs/2026-09-18-jobs-source-coverage-design.md`

## Blockers

- [ ] **`SUPABASE_SERVICE_KEY` holds the anon key** — reads work, writes fail with
      `new row violates row-level security policy`. No scraper can insert until
      this is the `service_role` key. Blocks every live verification step.
- [ ] **Decide NTA backlog depth** — 1,891 notices in the archive. Import all, or
      cap at 12 months? Recommendation: cap. Blocks Task 1.

## Phase 1: Ship the verified source

- [ ] **Task 1 — NTA scraper** (M)
  - [ ] `sources/nta.py`: parse `table tr`, title from row minus link text and index
  - [ ] Date from `Notice_(\d{14})\.pdf`
  - [ ] Age cap per the decision above
  - [ ] `ScraperError` on zero rows
  - [ ] Register in `runner.py`; add `sources` row
  - [ ] Fixture + tests (≥ 500 entries parsed)

- [ ] **Checkpoint A** — suite green; live scrape inserts; NTA notices in feed.
      **Review with Rahul before abstracting.**

## Phase 2: Discovery, then the second example

- [ ] **Task 2 — Discovery pass** (S) *(can run alongside Task 1)*
  - [ ] TNPSC — find real listing page
  - [ ] UPSC — `active-exams` yielded zero rows; find the actual notice list
  - [ ] SBI careers
  - [ ] RRB Secunderabad
  - [ ] Record each as viable (URL + selector) or blocked (reason) in `docs/SCRAPER_GUIDE.md`

- [ ] **Task 3 — Second source, bespoke** (M) — strongest from Task 2;
      falls back to RBI notifications if none are viable

- [ ] **Task 4 — Extract `NoticeBoardScraper`** (M)
  - [ ] `base_notice.py` with the frozen `NoticeBoard` config
  - [ ] Refactor Tasks 1 and 3 to configs
  - [ ] Generic row-extraction tests, site-independent
  - [ ] Existing tests pass unedited

- [ ] **Checkpoint B** — two sources on one base; entry counts unchanged.

## Phase 3: TLS and IBPS

- [ ] **Task 5 — AIA TLS helper** (S)
  - [ ] `utils/tls.py`: `ssl_context_for(host)`, cached per host
  - [ ] `None` when no AIA extension; never a silent downgrade
  - [ ] Wire `fetch="aia_tls"` into `base.py`
  - [ ] Tests with stubbed AIA fetch
  - [ ] `grep -rn "verify=False" backend/app/` returns nothing

- [ ] **Task 6 — IBPS source** (S) — find listing page; config with `fetch="aia_tls"`

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
- RRB Chandigarh — certificate invalid for its own hostname; unreachable without
  disabling verification
- SEBI (CAPTCHA); NCS, `rrbapply`, CBIC, joinindianarmy, RBI careers (JS-rendered)

# Jobs source coverage — design

**Date:** 2026-09-18
**Milestone:** 11 (expand scrapers)
**Decisions made up front:** breadth before depth; jobs (`naukri`) first; store PDF
links without fetching them.

## Problem

Three sources work today — PIB (`notice`), SSC (`naukri`), GeM (`tender`). Once
the invented seed rows are purged, three of the six category filters in the UI
return an empty feed. The PRD asks for thirty sources; reconnaissance says that
number is not reachable, so this spec covers a first jobs batch and the shared
machinery the rest can be built on.

## What reconnaissance established

Everything below was probed live on 2026-09-17/18, not assumed.

### Blocked, and why it matters

**The NIC eProcurement family is one blocker, not five.** CPPP, UP, Maharashtra,
MP and Rajasthan all run the same `nicgep` software and all answer *"Provide
Captcha and click on Search button to list all active tenders."* Solving one
solves all of them; until then none is worth writing. This accounts for most of
the PRD's Batch 1 and Batch 4.

**The RRB boards are not uniform.** The hypothesis was one scraper for all
twenty-one regional boards. They are independently built: Bhubaneswar returns
166 anchors, Secunderabad 1,826, Patna 523, with different markup. There is no
cheap multiplier here.

**RRB Chandigarh cannot be fixed safely.** Its certificate is not valid for its
own hostname — a genuine mismatch, not a missing intermediate. Reaching it means
disabling hostname verification, which this spec declines to do.

Also blocked: SEBI (CAPTCHA), NCS and `rrbapply` (single-page apps), CBIC,
`joinindianarmy` and RBI careers (JavaScript-rendered).

### Verified working

| Source | Evidence |
|---|---|
| NTA `/NoticeBoardArchive` | **1,891 rows with usable titles**, publish date encoded in each PDF filename |
| IBPS | HTTP 200, 221 KB, once the missing intermediate is supplied |
| eGazette | HTTP 200, 68 KB, same fix |

### Needs a discovery step

TNPSC, UPSC, SBI careers and RRB Secunderabad are all reachable, but the URLs
tried were wrong ones — TNPSC's root yields only navigation menus, UPSC's
`active-exams` page yields no notice rows at all. Each needs its real listing
page found before a config can be written. **This spec does not assume those
URLs exist.**

## Architecture

Two pieces of shared infrastructure, then thin per-source configuration.

### 1. `app/scrapers/utils/tls.py`

Several portals omit the intermediate certificate from their TLS chain. Their
roots (GlobalSign, Let's Encrypt) are legitimate and already trusted; the
servers are simply misconfigured. Browsers recover by following the leaf
certificate's Authority Information Access "CA Issuers" URI; Python does not.

```
ssl_context_for(host) -> ssl.SSLContext | None
```

Reads the leaf's AIA extension, downloads the named intermediate, and returns a
context built from certifi's roots *plus* that intermediate. Cached per host.
Returns `None` when there is no AIA extension, so callers fail loudly rather
than silently downgrading.

Certificate verification stays fully enabled. The intermediate is fetched over
plain HTTP, which is safe because it is validated by chaining to a trusted root
rather than by the transport. **`verify=False` appears nowhere.**

Unlocks IBPS and eGazette. Does *not* unlock RRB Chandigarh, whose problem is a
hostname mismatch.

### 2. `app/scrapers/base_notice.py`

Most of these sites differ in markup but share a shape: a list of rows, each
holding a title and a link to a PDF. Extraction must be **row-based, not
anchor-based** — NTA's anchor text is the useless string "Read More", while the
row carries the real title.

```python
@dataclass(frozen=True)
class NoticeBoard:
    source_key: str
    list_url: str
    department: str
    row_selector: str                   # "table tr" — the row, not the anchor
    link_pattern: str = r"\.pdf$"       # which href in the row is the notice
    date_from_url: str | None = None    # NTA: r"Notice_(\d{14})\.pdf"
    title_strip: tuple[str, ...] = ("Read More",)
    state: str = "ALL"
    category: str = "naukri"            # best guess; the AI re-classifies
    fetch: str = "plain"                # plain | impersonate | aia_tls
    min_title_len: int = 15
```

`NoticeBoardScraper(BaseScraper)` implements `scrape()` once against this
config. Per row: find the first href matching `link_pattern`; take the row's
text, subtract the link's own text, strip `title_strip` entries and any leading
list index; derive the date from the URL if `date_from_url` is set, else parse
the row text. Rows whose title is shorter than `min_title_len` are dropped —
that is what keeps navigation menus out.

A new source becomes roughly ten lines of configuration instead of a hundred and
fifty of parsing.

### Sequencing

NTA is written first as a plain scraper. The base class is then **extracted from
NTA plus one further source**, rather than designed up front — with only one
real example there is not enough evidence to know which parts generalise.

## Scope

**In:** the TLS helper; `NoticeBoardScraper`; an NTA scraper; a discovery pass
for TNPSC, UPSC, SBI and RRB Secunderabad, converting whichever prove viable;
IBPS via the TLS helper; `sources` rows; parsing tests.

**Out:** fetching or parsing PDF bodies (the deferred depth project); the NIC
CAPTCHA wall; anything needing Playwright; the `yojana` and `rule` categories
(RBI, Income Tax, india.gov.in — all verified reachable, but a later batch);
`auction`, which has no identified source at all.

## Data flow

Unchanged. `NoticeBoardScraper.scrape()` returns `list[RawEntry]`; the runner
deduplicates on content hash, inserts as `status='pending'`, and records the run
in `scraper_runs`; the summariser sends each entry to Groq; anything scoring
below 0.90 confidence waits in `/admin`.

`category` on `RawEntry` is a hint only. NTA's board carries hotel-empanelment
quotations and translation-reviewer EoIs alongside exam notices, so the AI's
classification is what reaches the feed.

## Error handling

- Zero rows raises `ScraperError` — the existing signal for "the layout
  changed", surfaced through the scraper health dashboard.
- One source failing must not affect the others; the runner already isolates
  per-source failures and applies `SCRAPER_TIMEOUT_SECONDS`.
- A failed AIA fetch raises. It never falls back to unverified TLS.
- New sources are added to `sources` with `is_active = false` until their first
  successful run. Note that `seed.sql` uses `ON CONFLICT DO NOTHING`, so editing
  it does **not** update an already-seeded database; activation is a deliberate
  `UPDATE`.

## Testing

Existing rule holds: parsing tests use saved HTML and never touch the network.

- The generic row extractor is tested independently of any single site:
  title/link/date extraction, index stripping, `title_strip`, the
  `min_title_len` cut, and rows carrying no matching link.
- Each source config gets a fixture cut from its real page, asserting the fields
  that matter and that navigation rows are excluded.
- The TLS helper is tested with a stubbed AIA fetch — no live handshake — plus
  an assertion that a missing AIA extension returns `None` rather than an
  unverified context.

## Risks

**Over-abstraction.** Only NTA is verified in detail. Mitigated by extracting
the base class from two real sources instead of designing it speculatively.

**Discovery may fail.** TNPSC, UPSC, SBI and RRB may have no scrapable listing.
If all four fail, this batch delivers NTA (1,891 notices) plus IBPS, and the
next batch should be the verified `rule`/`yojana` sources instead.

**Brittleness.** Selector-driven scrapers break when markup changes. The
zero-rows error is the detector; there is no attempt to be clever about it.

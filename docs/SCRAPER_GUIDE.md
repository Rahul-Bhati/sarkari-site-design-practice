# Adding a scraper

## The short version

1. Add a class in `backend/app/scrapers/sources/<key>.py` extending `BaseScraper`.
2. Register it in `SCRAPERS` in `backend/app/scrapers/runner.py`.
3. Add a row to the `sources` table with a matching `scraper_key`.
4. Add parsing tests to `backend/tests/test_scrapers.py` using saved HTML — never
   hit the network from a test.

```python
from app.scrapers.base import BaseScraper, RawEntry, ScraperError

class MyPortalScraper(BaseScraper):
    source_key = "my_portal"

    async def scrape(self) -> list[RawEntry]:
        async with self.client() as client:
            html = (await self.fetch(client, LIST_URL)).text
        rows = self._parse(html)
        if not rows:
            raise ScraperError("my_portal: no rows — layout may have changed")
        return [self._to_entry(r) for r in rows]
```

The runner handles deduplication, insertion, run records and source health. Your
job is `scrape()`.

## The real work is access, not parsing

Every source so far has been an access problem first. Diagnose in this order.

### 1. Does a plain request work?

```bash
curl -s -o /dev/null -w "%{http_code}\n" -A "Mozilla/5.0 ..." "$URL"
```

If curl gets 200 and `httpx` gets 403 with identical headers, the WAF is
fingerprinting the TLS handshake, not reading your headers.

**Fix:** `await self.fetch_impersonated(url)` — replays a browser's TLS
handshake via `curl_cffi`. This is what makes PIB work; headless Chromium is
*also* blocked there, so don't reach for Playwright first.

### 2. Does the HTML contain the data?

```python
soup = BeautifulSoup(html, "lxml")
print(len(soup.find_all("a")))   # zero anchors => SPA
```

If it's a single-page app, **look for the JSON API before reaching for a
browser.** Fetch the main JS bundle and grep it:

```python
re.findall(r'["\']((?:api|admin)/[0-9.]*/[A-Za-z0-9_\-/]{3,45})["\']', bundle)
```

That is how the SSC scraper was built: `/api/admin/5.1/getAllCandiateAdvertisements`
returns clean JSON with real dates. An API beats HTML parsing on every axis —
it's faster, it doesn't break on a redesign, and the fields are already typed.

**Fix:** call the API directly. Only fall back to
`await self.fetch_rendered(url, wait_for="...")` (headless Chromium) when the
data genuinely exists only after JavaScript runs.

### 3. Is it CAPTCHA-gated?

Search the page for `captcha`. If the listing needs one, **stop** — per the PRD,
skip the source rather than fight it. Make `scrape()` raise a `ScraperError` that
says so, and set `is_active = false` on the source row.

Do not settle for whatever else parses on the page. Rajasthan's portal has an
announcements banner and a search form that both parse cleanly and yield rows
like `"« Due Date Extended for tenders closing on 12-08-2026"` and
`"Enter Captcha"`. Junk entries are worse than none: the AI layer will summarise
them, they cost money, and a human has to reject each one by hand.

Guard against it by validating row *shape*, not just the table header — a real
tender row has an identifier containing digits or a parseable date
(`RajasthanEProcScraper._is_tender_row`).

## Rules

- **Never invent data.** If a field isn't in the source, leave it `None`. The AI
  layer is instructed to do the same.
- **Fail loudly.** Zero rows should raise, not return `[]`. A silent empty run
  looks identical to a healthy one in the dashboard.
- **Respect the portals.** `BaseScraper.fetch()` sleeps 2–5s between requests.
  Don't bypass it or parallelise within a single source.
- **Cap your reach.** Take the first ~25 items per run. The scheduler runs
  hourly; you don't need the full archive every time.
- **Amounts in paisa.** `parse_amount_to_paisa()` handles "Rs. 8.40 Crore",
  "₹16,80,000" and "29.4 Lakh". EMD in `extra` stays in rupees.
- **Dates as ISO strings.** `parse_date()` covers the formats Indian portals
  use, including uppercase months like `13 AUG 2026`.

## Testing

Save a real page to a fixture and parse it offline:

```python
def test_parses_the_listing():
    rows = MyPortalScraper()._parse(FIXTURE_HTML)
    assert len(rows) == 3
    assert rows[0]["tender_id"] == "..."
```

Then check it against the live site once, by hand:

```bash
.venv/bin/python -c "
import asyncio
from app.scrapers.sources.my_portal import MyPortalScraper
print(asyncio.run(MyPortalScraper().scrape())[:3])
"
```

## When a working scraper goes quiet

`consecutive_failures >= 3` turns the source red on the admin dashboard. A
scraper returning 0 entries for three runs usually means the portal was
redesigned — re-run the diagnosis above from step 1, since blocks get added far
more often than layouts change.

## Source survey — September 2026

Probed live rather than assumed. Two patterns recur and are worth recognising
before spending an afternoon on a portal.

### Pattern 1: one blocker can hide behind many domains

CPPP, UP, Maharashtra, MP and Rajasthan eProcurement look like five sources.
They run the same NIC `nicgep` software and all answer *"Provide Captcha and
click on Search button to list all active tenders."* Solving one solves all of
them; until then none is worth writing.

The inverse also holds: the twenty-one RRB regional boards look like one source
and are not. Bhubaneswar returns 166 anchors, Secunderabad 1,826, Patna 523,
with different markup each. There is no shared adapter to write. RRB
Secunderabad's own notice board says the boards are migrating to a "new unified
common website" — worth re-checking later, since that would create the
multiplier that does not exist today.

### Pattern 2: a 200 does not mean a page

**Check what a deliberately wrong URL returns.** Every `upsc.gov.in` path
serves HTTP 200 with exactly 102,812 bytes — including
`/this-path-does-not-exist-12345`. UPSC never 404s and renders its content
client-side, so a scraper cannot tell a real listing from a typo. Without this
check you get a scraper that silently returns nothing and a source that looks
merely empty rather than broken.

```bash
# Run this before writing any selector.
for p in "" "/real-looking-path" "/definitely-not-a-page-99999"; do
  curl -s -o /dev/null -w "%{http_code} %{size_download} $p\n" "https://site.gov.in$p"
done
```

Identical sizes across all three means the content is not in the HTML.

### Missing TLS intermediates

IBPS and eGazette fail certificate verification, but their roots (GlobalSign,
Let's Encrypt) are legitimate — the servers simply omit the intermediate.
Browsers recover by following the leaf certificate's Authority Information
Access "CA Issuers" URI. Fetch that intermediate, add it to certifi's roots, and
verification passes normally.

**Implemented** as `app/scrapers/utils/tls.py`. Set `fetch="aia_tls"` on a
`NoticeBoard` config, or call `self.client_aia(url)` directly. Verified live:
`ibps.in` returns HTTP 200 (221 KB) and `egazette.gov.in` HTTP 200 (68 KB), both
with hostname checking and full chain verification on.

**Never turn verification off.** It is not a shortcut, it is a different
guarantee, and it hides the diagnosis. `tests/test_tls.py` fails the build if
`verify` is set to False anywhere under `app/`, and confines `CERT_NONE` to the
one throwaway probe that reads the leaf certificate to find its issuer.

Before assuming a chain is broken, check. Two of the three hosts we had written
off did not have the problem we recorded:

- `eproc.rajasthan.gov.in` verified cleanly on 2026-09-18. Its scraper had been
  skipping verification for nothing; the flag is gone.
- RRB Chandigarh's mismatch is on **`www.rrbcdg.gov.in`** only. The apex
  `rrbcdg.gov.in` verifies and redirects to `rrb.indianrailways.gov.in`, which
  also verifies. It was the hostname that was wrong, not the certificate.

### Findings

| Source | Status | Listing page and selector |
|---|---|---|
| TNPSC | **stale, not built** | `/English/Notification.aspx`, `table tr` parses cleanly — 293 rows — but re-checked on 2026-09-18: **zero open and zero closed-within-90-days**, and only one row carries a 2026 date. Structurally viable, editorially dead. Revisit when TNPSC posts a new notification. |
| SBI | **viable** | `/web/careers/current-openings`, `div.card` — 42 rows of recruitment titles; apply windows appear as "APPLY ONLINE (16.09.2026 to 06.10.2026)" and filenames carry `DDMMYYYY`. |
| RRB (all 21 boards) | **working** | `rrb.indianrailways.gov.in/<board>`, `li:has(span.pub_date)` — see `sources/rrb.py`. 112 dated notices for Secunderabad. The per-board sites are being retired onto this one common portal, and Secunderabad, Chandigarh and Mumbai serve identical markup, so any board is one line of config. Only Secunderabad is registered: CENs are national, so 21 boards would mean 21 copies of every notice. |
| ~~RRB Secunderabad archive~~ | **stale** | `/archive_type/employment-notices/` looked strong on row count (35 cards, 468 PDFs) but its newest notice is 2025-03-03. The old site froze when the migration notice went up on 2026-08-18. Check dates, not rows. |
| UPSC | **blocked** | Catch-all JS shell, never 404s. Needs Playwright. |
| NTA | **working** | `/NoticeBoardArchive`, `table tr` — see `sources/nta.py`. |
| IBPS | **working** | Two pages, both `a:has(.detail-section)` with `fetch="aia_tls"` — see `sources/ibps.py`. `/index.php/crp-updates/` (20 exam notices, dated) and `/index.php/recruitment/` (10 live recruitments with open/close dates). |
| eGazette | reachable | AIA fix works; listing page not yet found. |
| RRB Chandigarh | **viable** | Not blocked after all — use `rrbcdg.gov.in`, which redirects to `rrb.indianrailways.gov.in/chandigarh`. Only the `www.` host has the bad certificate. |
| SEBI, NCS, rrbapply, CBIC, joinindianarmy, RBI careers | **blocked** | CAPTCHA or client-rendered. |

Verified reachable but not yet built, for a later batch: RBI notifications (698
anchors) and RBI press releases (804) for `rule`, Income Tax communications
(needs `fetch_impersonated`), and india.gov.in schemes for `yojana`.

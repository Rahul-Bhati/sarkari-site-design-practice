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

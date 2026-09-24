"""Government e-Marketplace bids — https://bidplus.gem.gov.in

GeM's /all-bids page is a shell: the listing itself is drawn by JavaScript from
a JSON endpoint, so there is nothing useful in the served HTML. We call that
endpoint directly, which is both faster and gives us real timestamps instead of
parsed-out display strings.

Endpoint (verified live): POST /all-bids-data
  form fields: payload=<json>, csrf_bd_gem_nk=<token>
  -> {"status":1,"code":200,"response":{"response":{"numFound":N,"docs":[...]}}}

Two things make this awkward and are worth stating plainly:

  * **CSRF.** The token is handed out as the `csrf_gem_cookie` cookie by GET
    /all-bids, and must be echoed back in a form field named `csrf_bd_gem_nk`
    — the names do not match, and posting without it is a bare 403. So every
    run starts with a GET to pick the cookie up.
  * **Solr shapes.** The docs come straight out of Solr, so nearly every value
    arrives wrapped in a single-element list. `_one()` unwraps that rather than
    indexing [0] at thirty call sites.

Sorted newest-first: `Bid-End-Date-Oldest` would keep re-reading the same
closing-soon bids every run, which the dedup hash would then throw away.
There are ~47,000 live bids. A run keeps fetching newest-first pages
until one page is entirely already stored, and never past SAFETY_MAX_PAGES.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.scrapers.base import BaseScraper, RawEntry, ScraperError
from app.scrapers.utils.dedup import existing_urls

log = logging.getLogger(__name__)

BASE = "https://bidplus.gem.gov.in"
LISTING_URL = f"{BASE}/all-bids"
DATA_URL = f"{BASE}/all-bids-data"

#: The cookie the token arrives in, and the form field it must be echoed in.
CSRF_COOKIE = "csrf_gem_cookie"
CSRF_FIELD = "csrf_bd_gem_nk"

#: 10 bids per page. Walk newest-first until a page is already stored.
#: 30 pages is the hard stop so a first run cannot crawl the whole archive.
SAFETY_MAX_PAGES = 30


def pages_to_take(
    pages: list[list[str]], known: set[str], safety_max: int = SAFETY_MAX_PAGES
) -> int:
    """How many newest-first pages to keep.

    Stops after the first page whose URLs are all already stored, and never
    returns more than `safety_max` even when every page is new.
    """
    kept = 0
    for urls in pages:
        if kept >= safety_max:
            break
        kept += 1
        if urls and set(urls) <= known:
            break
    return kept


class GeMScraper(BaseScraper):
    source_key = "gem"

    async def scrape(self) -> list[RawEntry]:
        entries: list[RawEntry] = []
        seen: set[str] = set()

        async with self.client(headers={"Accept": "application/json, text/plain, */*"}) as client:
            # Establishes the session and hands us the CSRF token.
            landing = await self.fetch(client, LISTING_URL)
            token = landing.cookies.get(CSRF_COOKIE) or client.cookies.get(CSRF_COOKIE)
            if not token:
                raise ScraperError(
                    f"gem: no {CSRF_COOKIE} cookie on {LISTING_URL}; "
                    "the CSRF scheme has probably changed"
                )

            for page in range(1, SAFETY_MAX_PAGES + 1):
                docs = await self._fetch_page(client, token, page)
                if not docs:
                    break
                page_urls: list[str] = []
                for doc in docs:
                    entry = self._to_entry(doc)
                    if entry and entry.original_url not in seen:
                        seen.add(entry.original_url)
                        entries.append(entry)
                        page_urls.append(entry.original_url)
                if page_urls and set(page_urls) <= existing_urls(page_urls):
                    break

        log.info("gem: %d bids kept", len(entries))
        return entries

    # ------------------------------------------------------------------

    async def _fetch_page(self, client, token: str, page: int) -> list[dict[str, Any]]:
        payload = {
            "page": page,
            "param": {"searchBid": "", "searchType": "fullText"},
            "filter": {
                "bidStatusType": "ongoing_bids",
                "byType": "all",
                "highBidValue": "",
                "byEndDate": {"from": "", "to": ""},
                "sort": "Bid-Start-Date-Latest",
            },
        }
        resp = await client.post(
            DATA_URL,
            data={"payload": json.dumps(payload), CSRF_FIELD: token},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": LISTING_URL},
            timeout=self.request_timeout,
        )
        if resp.status_code == 403:
            raise ScraperError("gem: 403 on /all-bids-data — CSRF token rejected")
        resp.raise_for_status()

        try:
            body = resp.json()
        except ValueError as exc:
            raise ScraperError("gem: /all-bids-data did not return JSON") from exc

        try:
            return body["response"]["response"]["docs"]
        except (KeyError, TypeError) as exc:
            raise ScraperError(f"gem: unexpected payload shape: {list(body)[:5]}") from exc

    def _to_entry(self, doc: dict[str, Any]) -> RawEntry | None:
        bid_no = self._one(doc.get("b_bid_number"))
        bid_id = self._one(doc.get("b_id"))
        if not bid_no or not bid_id:
            return None

        # b_category_name is the item list and is truncated to ~100 chars by
        # Solr; bd_category_name is the fuller classification. Prefer whichever
        # we actually got.
        category_name = (
            self._one(doc.get("bd_category_name"))
            or self._one(doc.get("b_category_name"))
            or "Bid"
        )
        ministry = self._one(doc.get("ba_official_details_minName")) or ""
        dept = self._one(doc.get("ba_official_details_deptName")) or ""
        # The API writes a literal "NA" rather than omitting the field.
        dept = "" if dept.upper() == "NA" else dept
        department = " — ".join(p for p in (ministry, dept) if p) or "Government e-Marketplace"

        quantity = self._one(doc.get("b_total_quantity"))
        published = self.parse_date(self._one(doc.get("final_start_date_sort")))
        deadline = self.parse_date(self._one(doc.get("final_end_date_sort")))

        title = f"{category_name} — {bid_no}"

        raw_text = "\n".join(
            filter(
                None,
                [
                    f"Government e-Marketplace bid {bid_no}.",
                    f"Items / category: {category_name}",
                    f"Buying ministry: {ministry}" if ministry else None,
                    f"Buying department: {dept}" if dept else None,
                    f"Total quantity: {quantity}" if quantity else None,
                    f"Bid published: {published}" if published else None,
                    f"Bid closes: {deadline}" if deadline else None,
                    "High value bid." if doc.get("is_high_value") else None,
                    f"Bid document: {BASE}/showbidDocument/{bid_id}",
                ],
            )
        )

        return RawEntry(
            title=title[:500],
            raw_text=self.clean_text(raw_text),
            # GeM has no public HTML page per bid — the bid document itself is
            # the only stable public permalink, so that is what we link to.
            original_url=f"{BASE}/showbidDocument/{bid_id}",
            category="tender",
            # GeM is a central marketplace; the buying office's state is not in
            # the listing payload, so the AI layer infers it from the text.
            state="ALL",
            department=department[:300],
            published_date=published,
            deadline=deadline,
            pdf_url=f"{BASE}/showbidDocument/{bid_id}",
            extra={
                "bid_number": bid_no,
                "bid_id": bid_id,
                "quantity": quantity,
                "high_value": bool(doc.get("is_high_value")),
            },
        )

    @staticmethod
    def _one(value: Any) -> Any:
        """Unwrap Solr's single-element lists; pass anything else through."""
        if isinstance(value, list):
            return value[0] if value else None
        return value

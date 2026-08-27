"""Staff Selection Commission — https://ssc.gov.in

ssc.gov.in is an Angular SPA: the served HTML contains **zero** anchors, so the
HTML-scraping approach the PRD assumed cannot work here. The site's own frontend
reads a public JSON API instead, and so do we — it is faster, stable, and gives
us real dates without any parsing guesswork.

Endpoint (verified live): GET /api/admin/5.1/getAllCandiateAdvertisements
  -> {"statusCode": "200", "data": [{id, advertisementName, startDate,
      endDate, year}, ...]}

Note the "Candiate" typo — it is theirs, and load-bearing.

Not yet covered: the homepage notice board (results, admit cards, corrigenda)
is rendered from a lazily-loaded JS chunk whose endpoint isn't in the main
bundle. Adding it means either finding that chunk's endpoint or rendering the
page with Playwright; see docs/SCRAPER_GUIDE.md.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.scrapers.base import BaseScraper, RawEntry, ScraperError

log = logging.getLogger(__name__)

BASE = "https://ssc.gov.in"
ADVERTISEMENTS_URL = f"{BASE}/api/admin/5.1/getAllCandiateAdvertisements"
#: Ignore advertisements that closed more than this long ago.
MAX_AGE_DAYS = 400


class SSCScraper(BaseScraper):
    source_key = "ssc"

    async def scrape(self) -> list[RawEntry]:
        async with self.client(headers={"Accept": "application/json"}) as client:
            resp = await self.fetch(client, ADVERTISEMENTS_URL)
            try:
                payload = resp.json()
            except ValueError as exc:
                raise ScraperError("ssc: advertisements endpoint did not return JSON") from exc

        records = payload.get("data")
        if not isinstance(records, list):
            raise ScraperError(f"ssc: unexpected payload shape: {list(payload)[:5]}")

        entries = [
            entry
            for record in records
            if (entry := self._to_entry(record)) is not None
        ]
        log.info("ssc: %d advertisements, %d recent enough to keep", len(records), len(entries))
        return entries

    # ------------------------------------------------------------------

    def _to_entry(self, record: dict[str, Any]) -> RawEntry | None:
        name = (record.get("advertisementName") or "").strip()
        record_id = (record.get("id") or "").strip()
        if not name or not record_id:
            return None

        start = self._iso(record.get("startDate"))
        end = self._iso(record.get("endDate"))
        if self._too_old(end or start):
            return None

        year = record.get("year") or ""
        title = f"SSC {name}".replace("SSC SSC", "SSC").strip()

        raw_text = "\n".join(
            filter(
                None,
                [
                    f"Staff Selection Commission advertisement: {name}",
                    f"Advertisement year: {year}" if year else None,
                    f"Application window opens: {start}" if start else None,
                    f"Last date to apply: {end}" if end else None,
                    "Recruitment is conducted by the Staff Selection Commission "
                    "for posts across central government departments. "
                    f"Full details: {BASE}",
                ],
            )
        )

        return RawEntry(
            title=title[:500],
            raw_text=self.clean_text(raw_text),
            # The portal has no stable per-advertisement permalink, so the
            # canonical link is the notice board plus the advertisement id.
            original_url=f"{BASE}/candidate-portal/notice-board#{record_id}",
            category="naukri",
            state="ALL",
            department="Staff Selection Commission",
            published_date=start,
            deadline=end,
            extra={"advertisement_id": record_id, "year": year or None},
        )

    @staticmethod
    def _iso(value: Any) -> str | None:
        """The API already returns YYYY-MM-DD; validate rather than trust it."""
        if not value or not isinstance(value, str):
            return None
        return BaseScraper.parse_date(value)

    @staticmethod
    def _too_old(iso: str | None) -> bool:
        if not iso:
            return False
        try:
            return (date.today() - date.fromisoformat(iso)).days > MAX_AGE_DAYS
        except ValueError:
            return False

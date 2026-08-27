"""Rajasthan eProcurement — https://eproc.rajasthan.gov.in

**Currently blocked, and inactive by default.**

This portal runs the NIC eProcurement stack. Every listing route that actually
returns tenders is CAPTCHA-gated — verified against `FrontEndLatestActiveTenders`
and `WebTenderStatusLists` (both render an "Enter Captcha ... click on Search"
form instead of rows), while `FrontEndTendersByDate` and
`FrontEndTendersbyOrganisation` return no tender table at all. Rendering the
page with Playwright does not help: the CAPTCHA is the gate, not JavaScript.

The PRD's own guidance for this case is to skip the source rather than fight it
(Milestone 11, "Common Challenges"), so `scrape()` raises instead of returning
data, and the seed marks this source `is_active = false`.

The parsing code below is kept and unit-tested because it is correct for a real
NIC tender table — it is what we'll need the moment we have a CAPTCHA-free
route. Do not "fix" this scraper by pointing it at the page's announcements
banner: that table parses cleanly and yields rows like "« Due Date Extended for
tenders closing on 12-08-2026", which are not tenders. Junk entries are worse
than no entries, because the AI layer will summarise them and a reviewer has to
throw each one out by hand.

Ways forward, best first:
  1. Rajasthan's SPPP portal (sppp.rajasthan.gov.in) publishes tender notices
     without a CAPTCHA — a different parser, but real data.
  2. Ask RISL/NIC for API or bulk-feed access; state procurement data is public
     and this is the durable answer.
  3. Central CPPP (eprocure.gov.in) carries many Rajasthan tenders and is worth
     checking for a CAPTCHA-free listing first.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, RawEntry, ScraperError

log = logging.getLogger(__name__)

BASE = "https://eproc.rajasthan.gov.in"
LIST_URL = f"{BASE}/nicgep/app?page=FrontEndLatestActiveTenders&service=page"
MAX_ITEMS = 25

#: Rows must come from a table whose header names these; the announcements
#: banner does not, which is what keeps its text out of the feed.
REQUIRED_HEADERS = ("tender id", "title")


class RajasthanEProcScraper(BaseScraper):
    source_key = "raj_eproc"
    request_timeout = 45.0

    async def scrape(self) -> list[RawEntry]:
        html = await self._fetch_list()
        rows = self._parse_table(html)

        if not rows:
            if self._is_captcha_gated(html):
                raise ScraperError(
                    "raj_eproc: tender listing is CAPTCHA-gated — no CAPTCHA-free "
                    "route found on this portal. See the module docstring for "
                    "alternatives (SPPP portal, NIC feed access, CPPP)."
                )
            raise ScraperError(
                "raj_eproc: no tender table found — the portal layout may have changed"
            )

        log.info("raj_eproc: %d tender rows found", len(rows))
        return [self._to_entry(r) for r in rows[:MAX_ITEMS]]

    # ------------------------------------------------------------------

    async def _fetch_list(self) -> str:
        # NIC portals often ship an incomplete cert chain; this is a public,
        # read-only listing, so verify=False is an acceptable trade here.
        async with self.client(verify=False) as client:
            html = (await self.fetch(client, LIST_URL)).text

        if self._has_tender_table(html):
            return html

        log.info("raj_eproc: static fetch had no tender table, trying Playwright")
        return await self.fetch_rendered(LIST_URL) or html

    @staticmethod
    def _is_captcha_gated(html: str) -> bool:
        lowered = html.lower()
        return "captcha" in lowered

    @classmethod
    def _has_tender_table(cls, html: str) -> bool:
        return bool(cls._parse_table(html))

    @classmethod
    def _parse_table(cls, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        rows: list[dict] = []

        for table in soup.find_all("table"):
            header = table.find("tr")
            if not header:
                continue

            columns = [
                th.get_text(" ", strip=True).lower()
                for th in header.find_all(["th", "td"])
            ]
            joined = " ".join(columns)
            # Require a real tender header, not merely the word "tender"
            # somewhere — that is what let the announcements banner through.
            if not all(needle in joined for needle in REQUIRED_HEADERS):
                continue

            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all("td")
                if len(cells) < 3:
                    continue
                values = [c.get_text(" ", strip=True) for c in cells]
                record = dict(zip(columns, values))

                title = cls._pick(record, "title", "work")
                if not title or len(title) < 10:
                    continue

                link = tr.find("a", href=True)
                candidate = {
                        "title": title,
                        "url": urljoin(BASE, link["href"]) if link else LIST_URL,
                        "tender_id": cls._pick(record, "tender id", "reference"),
                        "department": cls._pick(
                            record, "department", "organisation", "organization"
                        ),
                        "value": cls._pick(record, "value", "cost", "amount"),
                        "emd": cls._pick(record, "emd"),
                        "published": cls._pick(record, "publish", "published date"),
                    "closing": cls._pick(record, "closing", "bid submission", "due date"),
                    "row_text": tr.get_text(" | ", strip=True),
                }
                if cls._is_tender_row(candidate):
                    rows.append(candidate)
        return rows

    @classmethod
    def _is_tender_row(cls, row: dict) -> bool:
        """Reject rows that merely sit in a tender-shaped table.

        The portal's search form has a header row reading "Tender ID | Tender
        Title", so a header check alone lets its own controls through as rows
        titled "Enter Captcha" or "Active Tenders Back". A real tender always
        carries either an identifier containing a digit or a parseable date.
        """
        tender_id = row.get("tender_id") or ""
        if any(ch.isdigit() for ch in tender_id) and len(tender_id) >= 4:
            return True
        return bool(
            cls.parse_date(row.get("published")) or cls.parse_date(row.get("closing"))
        )

    @staticmethod
    def _pick(record: dict[str, str], *needles: str) -> str:
        for key, value in record.items():
            if any(n in key for n in needles) and value:
                return value
        return ""

    def _to_entry(self, row: dict) -> RawEntry:
        return RawEntry(
            title=row["title"][:500],
            raw_text=self.clean_text(row["row_text"]),
            original_url=row["url"],
            category="tender",
            state="RJ",
            department=(row["department"] or "Government of Rajasthan")[:200],
            published_date=self.parse_date(row["published"]),
            deadline=self.parse_date(row["closing"]),
            budget_amount=self.parse_amount_to_paisa(row["value"]),
            extra={
                "tender_id": row["tender_id"] or None,
                "emd_raw": row["emd"] or None,
                "emd_amount": self._emd_inr(row["emd"]),
            },
        )

    def _emd_inr(self, text: str) -> int | None:
        paisa = self.parse_amount_to_paisa(text)
        return paisa // 100 if paisa else None


# The sources table maps scraper_key -> class; keep the old name importable.
RajEprocScraper = RajasthanEProcScraper

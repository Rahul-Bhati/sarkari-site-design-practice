"""National Testing Agency — https://www.nta.ac.in

NTA runs JEE, NEET, UGC-NET, CUET and CMAT, so its notice board is the widest
single source of exam news we have. `/NoticeBoardArchive` carries the full
history — around 1,900 rows — as a plain table, no WAF and no JavaScript.

**Extraction is row-based, not anchor-based, and that is the whole trick here.**
Every link on the page reads "Read More"; the title lives in the containing
`<tr>` alongside a row index:

    <tr> <td>4</td>
         <td>Publication of the Examination Calendar ... - reg.</td>
         <td><a href="/Download/Notice/Notice_20260916195948.pdf">Read More</a></td>
    </tr>

So the title is the row's text minus the link's own text minus the leading
index. An anchor-driven scraper gets 1,891 entries all titled "Read More".

Dates are taken from the filename rather than the page: NTA stamps every notice
`Notice_YYYYMMDDHHMMSS.pdf`, which is exact, whereas the table shows no date at
all.

The board mixes exam notices with procurement and hiring of its own ("NOTICE
INVITING QUOTATION FOR EMPANELMENT OF HOTELS", "EoI for Translation
Reviewers"), so `category` here is only a hint — the AI layer classifies for
real.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, RawEntry, ScraperError

log = logging.getLogger(__name__)

BASE = "https://www.nta.ac.in"
LIST_URL = f"{BASE}/NoticeBoardArchive"

#: Notice PDFs are stamped with a timestamp. Current files are
#: `Notice_YYYYMMDDHHMMSS.pdf`; everything before roughly 2020 is a bare
#: `YYYYMMDDHHMMSS.pdf`. Both must be matched — treating the old form as
#: undated let 64 notices from 2019 straight past the age cap.
DATE_IN_URL = re.compile(r"(?:Notice_)?(\d{14})\.pdf", re.I)

#: The archive goes back years. Older notices are almost all expired, and
#: summarising the lot would cost ~1,900 AI calls to bury the feed in dead
#: entries.
MAX_AGE_DAYS = 365

#: Link text carries no information and must come out of the title.
TITLE_NOISE = ("Read More",)

#: Below this a "title" is a stray table cell, not a notice.
MIN_TITLE_LEN = 15


class NTAScraper(BaseScraper):
    source_key = "nta"

    async def scrape(self) -> list[RawEntry]:
        async with self.client() as client:
            html = (await self.fetch(client, LIST_URL)).text

        rows = self._parse(html)
        if not rows:
            raise ScraperError(
                "nta: no notice rows parsed — the archive layout may have changed"
            )

        entries = [self._to_entry(r) for r in self._within_age_cap(rows)]
        log.info("nta: %d rows parsed, %d within %d days", len(rows), len(entries), MAX_AGE_DAYS)
        return entries

    @staticmethod
    def _within_age_cap(rows: list[dict]) -> list[dict]:
        """Take rows until the archive is reliably past the age cap.

        The archive is strictly newest-first, so position tells us more than
        any individual row does. That matters because a row's date can be
        missing: the oldest notices predate the timestamped filename convention
        entirely (`PressReleaseCMAT.pdf`), and judging those one at a time means
        either dropping anything NTA renames in future or — as happened here —
        letting 2019 notices past the cap because they parsed as undated.

        Cutting the list instead keeps undated rows near the top, where a new
        naming convention would show up, and discards undated rows in the tail,
        where the pre-2020 files live.

        CONSECUTIVE_OLD guards against one mis-stamped filename truncating the
        whole run.
        """
        CONSECUTIVE_OLD = 3
        run = 0
        for i, row in enumerate(rows):
            published = NTAScraper._date_from_url(row["url"])
            if published and NTAScraper._too_old(published):
                run += 1
                if run >= CONSECUTIVE_OLD:
                    return rows[: i - CONSECUTIVE_OLD + 1]
            else:
                run = 0
        return rows

    # ------------------------------------------------------------------

    @staticmethod
    def _parse(html: str) -> list[dict]:
        """Pull (title, url) out of each archive row."""
        soup = BeautifulSoup(html, "lxml")
        out: list[dict] = []
        seen: set[str] = set()

        for row in soup.select("table tr"):
            link = next(
                (a for a in row.find_all("a", href=True)
                 if a["href"].lower().endswith(".pdf")),
                None,
            )
            if link is None:
                continue

            url = urljoin(BASE, link["href"])
            if url in seen:
                continue

            title = NTAScraper._title_from_row(row, link)
            if len(title) < MIN_TITLE_LEN:
                continue

            seen.add(url)
            out.append({"title": title, "url": url})

        return out

    @staticmethod
    def _title_from_row(row, link) -> str:
        """Row text, minus the link's own text and the leading row number."""
        row_text = " ".join(row.get_text(" ", strip=True).split())
        link_text = " ".join(link.get_text(" ", strip=True).split())
        if link_text:
            row_text = row_text.replace(link_text, " ")
        for noise in TITLE_NOISE:
            row_text = row_text.replace(noise, " ")
        # Leading "4" / "4." / "4)" is the archive's own row counter.
        row_text = re.sub(r"^\s*\d+\s*[.)]?\s*", "", " ".join(row_text.split()))
        return row_text.strip()

    def _to_entry(self, row: dict) -> RawEntry:
        published = self._date_from_url(row["url"])

        raw_text = "\n".join(
            filter(
                None,
                [
                    f"National Testing Agency notice: {row['title']}",
                    f"Published: {published}" if published else None,
                    "The National Testing Agency conducts entrance examinations "
                    "including JEE (Main), NEET, UGC-NET, CUET and CMAT.",
                    f"Full notice (PDF): {row['url']}",
                ],
            )
        )

        return RawEntry(
            title=row["title"][:500],
            raw_text=self.clean_text(raw_text),
            original_url=row["url"],
            # A hint only — the board also carries NTA's own tenders and EoIs,
            # and the AI layer reclassifies.
            category="naukri",
            state="ALL",
            department="National Testing Agency",
            published_date=published,
            pdf_url=row["url"],
        )

    @staticmethod
    def _date_from_url(url: str) -> str | None:
        m = DATE_IN_URL.search(url)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").date().isoformat()
        except ValueError:
            # A stamp that isn't a real date tells us nothing; better absent
            # than wrong, since deadline urgency is computed from these.
            return None

    @staticmethod
    def _too_old(iso: str | None) -> bool:
        if not iso:
            return False
        try:
            return (date.today() - date.fromisoformat(iso)).days > MAX_AGE_DAYS
        except ValueError:
            return False

"""A configurable scraper for government notice boards.

Most of the portals surveyed for this milestone differ in markup but share one
shape: a list of rows, each holding a title and a link to a PDF. This module
holds that shape once, so a new board is a dozen lines of configuration rather
than a hundred and fifty of parsing.

**Extraction is row-based, not anchor-based.** That is the part worth keeping.
NTA's every anchor reads "Read More" and SBI's first anchor reads "English
(1 MB)" — in both cases the anchor supplies the href and nothing else, and the
title comes from the row around it.

This class was extracted from the NTA and SBI scrapers after both were working,
not designed ahead of them, and the two disagree in instructive ways:

  * NTA's title is the row's own text; SBI's is a specific paragraph with a
    blinking span cut out of it. So the title is a **hook**, not a config field.
  * NTA keeps a run of rows by position in the archive; SBI keeps a row if
    people can still apply. So relevance is a **hook** too.

Only what both sources genuinely share lives in `NoticeBoard`. A field that one
source needs stays in that source's module.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, RawEntry, ScraperError

log = logging.getLogger(__name__)

#: Connection modes a config may ask for. Neither disables verification.
FETCH_MODES = frozenset({"plain", "aia_tls"})


@dataclass(frozen=True)
class NoticeBoard:
    """Everything a plain notice board needs to be scraped."""

    source_key: str
    list_url: str
    department: str

    #: The row, never the anchor — see the module docstring.
    row_selector: str

    #: Which href inside a row is the notice itself. Matched with `re.search`,
    #: so `\.pdf` catches SBI's `.../file.pdf/72f2` while `\.pdf$` restricts NTA
    #: to links that really end there.
    link_pattern: str = r"\.pdf$"

    #: Group 1 must be the date stamp. Portals name uploads far more reliably
    #: than they date their own listing pages.
    date_in_url: str | None = None
    date_format: str = "%Y%m%d%H%M%S"

    #: Boilerplate link text to remove from a row-derived title.
    title_strip: tuple[str, ...] = ()

    #: Below this length a "title" is a navigation label or a stray cell, not a
    #: notice. This is what keeps sidebars and menus out of the feed.
    min_title_len: int = 15

    #: How to open the connection. "aia_tls" is for portals that omit an
    #: intermediate certificate; see `utils/tls.py`. Verification is never
    #: disabled in either mode.
    fetch: str = "plain"

    state: str = "ALL"
    #: A hint only. The AI layer reclassifies, which matters because most of
    #: these boards mix recruitment with the department's own tenders.
    category: str = "naukri"

    #: One sentence telling the AI layer what this body does, prepended to every
    #: entry's raw text. Titles alone are often too terse to summarise well.
    context: str = ""

    def __post_init__(self) -> None:
        # Catch a typo here rather than at scrape time, where `fetch="aia-tls"`
        # would quietly fall through to a plain connection — exactly the silent
        # downgrade the TLS helper exists to prevent.
        if self.fetch not in FETCH_MODES:
            raise ValueError(
                f"{self.source_key}: unknown fetch mode {self.fetch!r}; "
                f"expected one of {', '.join(sorted(FETCH_MODES))}"
            )


class NoticeBoardScraper(BaseScraper):
    """Scrapes any source that fits `NoticeBoard`.

    Subclasses set `config`. They may additionally override:

    * `_title(row, link)` — when the row's own text is not the title
    * `_extra(row, link)` — to pull site-specific fields into the parsed row
    * `_select(rows)`     — to drop rows in bulk, by position or by age
    * `_to_entry(row)`    — to build a richer `RawEntry`, or `None` to skip

    The parsing helpers are classmethods so they can be exercised against saved
    HTML without constructing a scraper or touching the network.
    """

    config: ClassVar[NoticeBoard]

    @property
    def source_key(self) -> str:
        return self.config.source_key

    async def scrape(self) -> list[RawEntry]:
        html = await self._fetch_list()

        rows = self._parse(html)
        if not rows:
            raise ScraperError(
                f"{self.source_key}: no rows parsed from {self.config.list_url} — "
                "the page layout may have changed"
            )

        kept = self._select(rows)
        entries = [e for r in kept if (e := self._to_entry(r)) is not None]
        log.info("%s: %d rows parsed, %d kept", self.source_key, len(rows), len(entries))
        return entries

    async def _fetch_list(self) -> str:
        url = self.config.list_url
        if self.config.fetch == "aia_tls":
            client = await self.client_aia(url)
        else:
            client = self.client()
        async with client:
            return (await self.fetch(client, url)).text

    # --- row extraction ---------------------------------------------------

    @classmethod
    def _parse(cls, html: str) -> list[dict]:
        """Pull one dict per notice row out of a saved or fetched page."""
        cfg = cls.config
        link_re = re.compile(cfg.link_pattern, re.I)
        soup = BeautifulSoup(html, "lxml")

        out: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for row in soup.select(cfg.row_selector):
            link = cls._link(row, link_re)
            if link is None:
                continue

            # Resolving against the listing URL rather than a configured base
            # handles relative and absolute hrefs alike. Spaces are escaped
            # because portals do write them raw — RRB's query string carries
            # `category=Application (Special Notice)` — and a URL with a space
            # in it is not a URL, however forgiving a browser chooses to be.
            url = urljoin(cfg.list_url, link["href"]).replace(" ", "%20")
            title = cls._title(row, link)
            if len(title) < cfg.min_title_len:
                continue

            # Keyed on both, because one landing page can legitimately carry two
            # notices: IBPS lists "Notification for CRP-RRB-XV" and "Apply
            # Online for CRP-RRBs-XV" pointing at the same page. Keying on the
            # URL alone silently dropped the second. This matches how the runner
            # identifies an entry, which is title, URL and date together.
            key = (url, title)
            if key in seen:
                continue

            seen.add(key)
            out.append({"title": title, "url": url, **cls._extra(row, link)})

        return out

    @staticmethod
    def _link(row, link_re: re.Pattern) -> object | None:
        """The notice link in this row — which may be the row itself.

        Most boards put an anchor inside the row. IBPS wraps the whole row in
        one, so `find_all` on it returns the cells and never the link.
        """
        candidates = row.find_all("a", href=True)
        if row.name == "a" and row.get("href"):
            candidates = [row, *candidates]
        return next((a for a in candidates if link_re.search(a["href"])), None)

    @classmethod
    def _title(cls, row, link) -> str:
        """The row's text, minus the link's own text and any leading index."""
        row_text = " ".join(row.get_text(" ", strip=True).split())
        link_text = " ".join(link.get_text(" ", strip=True).split())
        if link_text:
            row_text = row_text.replace(link_text, " ")
        for noise in cls.config.title_strip:
            row_text = row_text.replace(noise, " ")
        # A leading "4" / "4." / "4)" is the board's own row counter.
        row_text = re.sub(r"^\s*\d+\s*[.)]?\s*", "", " ".join(row_text.split()))
        return row_text.strip()

    @classmethod
    def _extra(cls, row, link) -> dict:
        """Site-specific fields to carry alongside the title and URL."""
        return {}

    @classmethod
    def _select(cls, rows: list[dict]) -> list[dict]:
        """Bulk filter applied after parsing. Keeps everything by default."""
        return rows

    # --- dates ------------------------------------------------------------

    @classmethod
    def _date_from_url(cls, url: str) -> str | None:
        cfg = cls.config
        if not cfg.date_in_url:
            return None
        m = re.search(cfg.date_in_url, url, re.I)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1), cfg.date_format).date().isoformat()
        except ValueError:
            # A stamp that isn't a real date tells us nothing, and absent beats
            # wrong here because urgency is computed from these.
            return None

    # --- entry construction -----------------------------------------------

    def _to_entry(self, row: dict) -> RawEntry | None:
        cfg = self.config
        # A board that prints a date column is telling us more than a filename
        # can, so `_extra` supplying one wins over the URL pattern.
        published = row.get("published") or self._date_from_url(row["url"])
        deadline = row.get("deadline")

        raw_text = "\n".join(
            filter(
                None,
                [
                    f"{cfg.department} notice: {row['title']}",
                    f"Published: {published}" if published else None,
                    f"Last date: {deadline}" if deadline else None,
                    cfg.context or None,
                    f"Full notice (PDF): {row['url']}",
                ],
            )
        )

        return RawEntry(
            title=row["title"][:500],
            raw_text=self.clean_text(raw_text),
            original_url=row["url"],
            category=cfg.category,
            state=cfg.state,
            department=cfg.department,
            published_date=published,
            deadline=deadline,
            pdf_url=row["url"],
        )

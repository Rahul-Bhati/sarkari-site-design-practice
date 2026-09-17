"""State Bank of India recruitment — https://sbi.co.in/web/careers/current-openings

SBI is the largest recruiter in Indian banking and, unlike most sources probed
for this milestone, its listings are genuinely live: the page carries open
application windows rather than an archive of expired ones.

Each opening is a `div.card` with a fixed shape:

    div.card
      div.col-md-8 .text-uppercase
        <p> ENGAGEMENT OF SPECIALIST CADRE OFFICERS ...      <- title
            <span class="text_blink"> (Apply Online from 16.09.2026 to 06.10.2026)
        <p> ADVERTISEMENT NO: CRPD/SCO/2026-27/20
      div.col-md-4
        <button> LAST DATE TO APPLY : 06-10-2026             <- deadline
      div.accordion-content
        ul.text-link > li > a   DOWNLOAD ADVERTISEMENT / APPLY ONLINE / BIODATA

SBI is where `NoticeBoardScraper`'s hooks earn their keep: the rows, links,
deduplication and filename dates are shared, but all three of the overrides
below are needed, for two traps and one judgement call.

The traps both produce plausible-looking rubbish rather than an error:

  * The title `<p>` contains a nested `text_blink` span repeating the apply
    window. Left in, every title ends with "(Apply Online from ... to ...)".
  * The obvious "first anchor in the card" is the advertisement *download*
    link, whose text is the file's language and size — "English (1 MB)". Taking
    it as the title gives a feed full of entries called "Hindi".

The judgement call is relevance: SBI lists a recruitment through its whole
lifecycle, so a card with no "LAST DATE TO APPLY" has usually moved on to call
letters or results. That absence is real signal, not a parsing miss.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import RawEntry
from app.scrapers.base_notice import NoticeBoard, NoticeBoardScraper

BASE = "https://sbi.co.in"
LIST_URL = f"{BASE}/web/careers/current-openings"

LAST_DATE = re.compile(r"LAST DATE TO APPLY\s*:?\s*(\d{2}[-/.]\d{2}[-/.]\d{4})", re.I)
WINDOW = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s*to\s*(\d{2}\.\d{2}\.\d{4})", re.I)
ADVT_NO = re.compile(r"ADVERTISEMENT\s*NO\s*:?\s*([A-Z0-9/\-]+)", re.I)

#: Keep openings that are still open, plus a month's grace so something that
#: closed last week does not vanish from the feed the day it expires.
CLOSED_GRACE_DAYS = 30
#: Fallback when a card carries no deadline at all.
MAX_AGE_DAYS = 365


class SBIScraper(NoticeBoardScraper):
    config = NoticeBoard(
        source_key="sbi",
        list_url=LIST_URL,
        department="State Bank of India",
        row_selector="div.card",
        # Advertisement URLs look like
        # /documents/77530/57941334/16092026_ADV_CRPD_SCO.pdf/72f2 — the `.pdf`
        # is mid-path, so anchoring the pattern to the end would match nothing.
        link_pattern=r"\.pdf|/documents/",
        #: SBI names uploads 16092026_ADV_CRPD_SCO_2026-27_20.pdf — DDMMYYYY.
        date_in_url=r"/(\d{8})_",
        date_format="%d%m%Y",
        min_title_len=20,
        category="naukri",
    )

    # --- overrides --------------------------------------------------------

    @classmethod
    def _title(cls, row, link) -> str:
        """First paragraph, minus the blinking apply-window span inside it.

        The row's own text would pull in the advertisement number, the deadline
        button and every link label, so the generic row-text title does not
        work here. `link` is unused: its text is the file size.
        """
        p = row.find("p")
        if p is None:
            return ""
        # Work on a copy: the span sits *inside* the title paragraph, so
        # extracting it from the live tree would corrupt later lookups.
        clone = BeautifulSoup(str(p), "lxml")
        for span in clone.select("span.text_blink"):
            span.decompose()
        title = " ".join(clone.get_text(" ", strip=True).split())
        # Some cards repeat the window without the blink class.
        title = WINDOW.sub("", title)
        title = re.sub(r"\(\s*Apply Online\s*(from)?\s*\)?", "", title, flags=re.I)
        # Removing the span can leave an empty or half-open bracket behind.
        title = re.sub(r"\(\s*\)", "", title)
        title = " ".join(title.split()).strip(" -–—")
        # Only strip a trailing "(" that now opens nothing. Stripping brackets
        # indiscriminately turned "JUNIOR ASSOCIATES (CUSTOMER SUPPORT & SALES)"
        # into "...& SALES" with the closing bracket gone.
        if title.endswith("("):
            title = title[:-1].strip()
        if title.count("(") > title.count(")"):
            title += ")"
        return title

    @classmethod
    def _extra(cls, row, link) -> dict:
        text = " ".join(row.get_text(" ", strip=True).split())
        advt = ADVT_NO.search(text)
        window = WINDOW.search(text)
        return {
            "advt_no": advt.group(1) if advt else None,
            "deadline": cls._deadline(text),
            "opens": window.group(1) if window else None,
            "apply_url": cls._apply_url(row),
        }

    def _to_entry(self, card: dict) -> RawEntry | None:
        published = self._published(card["url"])
        if not self._is_relevant(card["deadline"], published):
            return None

        raw_text = "\n".join(
            filter(
                None,
                [
                    f"State Bank of India recruitment: {card['title']}",
                    f"Advertisement number: {card['advt_no']}" if card["advt_no"] else None,
                    f"Applications open: {card['opens']}" if card["opens"] else None,
                    f"Last date to apply: {card['deadline']}" if card["deadline"] else None,
                    f"Apply online: {card['apply_url']}" if card["apply_url"] else None,
                    f"Advertisement (PDF): {card['url']}",
                ],
            )
        )

        return RawEntry(
            title=card["title"][:500],
            raw_text=self.clean_text(raw_text),
            original_url=card["url"],
            category=self.config.category,
            state=self.config.state,
            department=self.config.department,
            published_date=published,
            deadline=card["deadline"],
            pdf_url=card["url"],
            extra={
                "advertisement_no": card["advt_no"],
                "apply_url": card["apply_url"],
            },
        )

    # --- site-specific helpers -------------------------------------------

    @classmethod
    def _published(cls, url: str) -> str | None:
        return cls._date_from_url(url)

    @staticmethod
    def _apply_url(card) -> str | None:
        for a in card.find_all("a", href=True):
            if "apply" in " ".join(a.get_text(" ", strip=True).split()).lower():
                return urljoin(BASE, a["href"])
        return None

    @staticmethod
    def _deadline(text: str) -> str | None:
        m = LAST_DATE.search(text)
        if m:
            return SBIScraper._iso(m.group(1))
        m = WINDOW.search(text)
        return SBIScraper._iso(m.group(2)) if m else None

    @staticmethod
    def _iso(raw: str) -> str | None:
        for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _is_relevant(deadline: str | None, published: str | None) -> bool:
        """An opening nobody can still apply for is noise, not news."""
        today = date.today()
        if deadline:
            try:
                return (today - date.fromisoformat(deadline)).days <= CLOSED_GRACE_DAYS
            except ValueError:
                pass
        if published:
            try:
                return (today - date.fromisoformat(published)).days <= MAX_AGE_DAYS
            except ValueError:
                pass
        # Undated cards are rare and cheap to carry; the AI layer sees the text
        # and a human reviews anything it is unsure about.
        return True

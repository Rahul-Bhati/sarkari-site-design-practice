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

Two traps, both of which produce plausible-looking rubbish rather than an
error:

  * The title `<p>` contains a nested `text_blink` span repeating the apply
    window. Left in, every title ends with "(Apply Online from ... to ...)".
  * The obvious "first anchor in the card" is the advertisement *download*
    link, whose text is the file's language and size — "English (1 MB)". Taking
    it as the title gives a feed full of entries called "Hindi".

Deadlines come from the "LAST DATE TO APPLY" button, which is explicit and
unambiguous, rather than from the window text.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, RawEntry, ScraperError

log = logging.getLogger(__name__)

BASE = "https://sbi.co.in"
LIST_URL = f"{BASE}/web/careers/current-openings"

LAST_DATE = re.compile(r"LAST DATE TO APPLY\s*:?\s*(\d{2}[-/.]\d{2}[-/.]\d{4})", re.I)
WINDOW = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s*to\s*(\d{2}\.\d{2}\.\d{4})", re.I)
ADVT_NO = re.compile(r"ADVERTISEMENT\s*NO\s*:?\s*([A-Z0-9/\-]+)", re.I)
#: SBI names uploads 16092026_ADV_CRPD_SCO_2026-27_20.pdf — DDMMYYYY.
DATE_IN_FILENAME = re.compile(r"/(\d{8})_")

#: Keep openings that are still open, plus a month's grace so something that
#: closed last week does not vanish from the feed the day it expires.
CLOSED_GRACE_DAYS = 30
#: Fallback when a card carries no deadline at all.
MAX_AGE_DAYS = 365

MIN_TITLE_LEN = 20


class SBIScraper(BaseScraper):
    source_key = "sbi"

    async def scrape(self) -> list[RawEntry]:
        async with self.client() as client:
            html = (await self.fetch(client, LIST_URL)).text

        cards = self._parse(html)
        if not cards:
            raise ScraperError(
                "sbi: no opening cards parsed — the careers page layout may have changed"
            )

        entries = [e for c in cards if (e := self._to_entry(c)) is not None]
        log.info("sbi: %d cards parsed, %d still relevant", len(cards), len(entries))
        return entries

    # ------------------------------------------------------------------

    @staticmethod
    def _parse(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        out: list[dict] = []
        seen: set[str] = set()

        for card in soup.select("div.card"):
            title = SBIScraper._title(card)
            if len(title) < MIN_TITLE_LEN:
                continue

            text = " ".join(card.get_text(" ", strip=True).split())
            url = SBIScraper._advert_url(card)
            if not url or url in seen:
                continue
            seen.add(url)

            advt = ADVT_NO.search(text)
            window = WINDOW.search(text)
            out.append({
                "title": title,
                "url": url,
                "advt_no": advt.group(1) if advt else None,
                "deadline": SBIScraper._deadline(text),
                "opens": window.group(1) if window else None,
                "apply_url": SBIScraper._apply_url(card),
            })

        return out

    @staticmethod
    def _title(card) -> str:
        """First paragraph, minus the blinking apply-window span inside it."""
        p = card.find("p")
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
        if title.endswith("(") :
            title = title[:-1].strip()
        if title.count("(") > title.count(")"):
            title += ")"
        return title

    @staticmethod
    def _advert_url(card) -> str | None:
        """The advertisement PDF, not the first anchor in the card.

        The first anchor is the download link, whose text is "English (1 MB)".
        We want its href but never its text.
        """
        for a in card.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf") or "/documents/" in href:
                return urljoin(BASE, href)
        return None

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
    def _published(url: str) -> str | None:
        m = DATE_IN_FILENAME.search(url)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1), "%d%m%Y").date().isoformat()
        except ValueError:
            return None

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
            category="naukri",
            state="ALL",
            department="State Bank of India",
            published_date=published,
            deadline=card["deadline"],
            pdf_url=card["url"],
            extra={
                "advertisement_no": card["advt_no"],
                "apply_url": card["apply_url"],
            },
        )

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

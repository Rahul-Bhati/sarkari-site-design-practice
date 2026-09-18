"""Press Information Bureau — https://pib.gov.in

Clean HTML, a structured release list, and a ministry name on every item —
still the best-shaped source we have. The catch is delivery, not parsing:
pib.gov.in sits behind Akamai, which 403s plain HTTP clients on TLS fingerprint
alone (verified: identical headers get 200 from curl and 403 from httpx), so
every request goes through curl_cffi.

**The list links to a page that has no release on it.** `allRel.aspx` gives
correct English titles and ministries, but its hrefs point at
`PressReleaseDetail.aspx?PRID=...`, which serves a JavaScript shell: the body
is 3 KB of Hindi navigation and `div.content-area` is empty. Parsing it yields
an entry titled "विज्ञप्ति अन्य प्रेस विज्ञप्तियाँ" — the "Other Press
Releases" menu heading — which is how this source came to be publishing a
navigation label as a news item.

The release itself lives at `PressReleasePage.aspx?PRID=...`, same PRID, 12 KB
of English inside `#PdfDiv`. So the PRID is taken from the list and the URL is
rebuilt; the href is never followed as given.

`allRel.aspx` serves the current day only. Its ministry, day, month and year
dropdowns look like a date filter, but the ASP.NET postback behind them is
ignored — posting a valid `__VIEWSTATE` with day=All, or with any past date,
returns exactly the same releases. Backfilling is not available, so the
scheduler's hourly run is what gives coverage.

Central government, so state is always 'ALL'.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, RawEntry, ScraperError

log = logging.getLogger(__name__)

# reg=3&lang=1 selects the English edition. Without it PIB serves Hindi, which
# the summarizer can still read but which loses us the English source text.
LIST_URL = "https://pib.gov.in/allRel.aspx?reg=3&lang=1"
BASE = "https://pib.gov.in/"

#: Where a release actually is, keyed by the PRID taken off the list page. See
#: the module docstring: the href on the list page points somewhere else.
DETAIL_URL = "https://pib.gov.in/PressReleasePage.aspx?PRID={prid}"
PRID = re.compile(r"PRID=(\d+)", re.I)

#: The release body on PressReleasePage.aspx. Checked first because the older
#: class-name match picks up navigation on the pages that lack it.
BODY_ID = "PdfDiv"

# Ministries whose releases usually describe a scheme rather than a bare notice.
YOJANA_HINTS = (
    "yojana", "scheme", "subsidy", "pension", "beneficiar", "awas",
    "scholarship", "insurance", "kisan", "ayushman",
)
NAUKRI_HINTS = ("recruitment", "vacanc", "appointment", "posts", "examination")
RULE_HINTS = ("amendment", "rules", "notified", "act,", "regulation", "guidelines")
MAX_ITEMS = 25

#: A real release runs to thousands of characters. The Hindi shell page that
#: broke this scraper had about 3,000 of navigation, of which roughly 400
#: survived stripping, so this is set well above a menu and well below a
#: genuine release.
MIN_BODY_CHARS = 600


class PIBScraper(BaseScraper):
    source_key = "pib"

    async def scrape(self) -> list[RawEntry]:
        list_html = await self.fetch_impersonated(LIST_URL)
        if not list_html:
            raise ScraperError(
                "pib: could not fetch the release list. pib.gov.in is behind a WAF "
                "that fingerprints the TLS handshake, so curl_cffi is required "
                "(`pip install curl_cffi`)."
            )

        links = self._parse_list(list_html)
        log.info("pib: %d release links found", len(links))
        if not links:
            raise ScraperError("pib: no release links on the list page — layout may have changed")

        entries: list[RawEntry] = []
        for link in links[:MAX_ITEMS]:
            # One bad release must never kill the run.
            html = await self.fetch_impersonated(link["url"])
            if html is None:
                log.warning("pib: skipping unreachable release %s", link["url"])
                continue
            entry = self._parse_detail(html, link)
            if entry:
                entries.append(entry)
        return entries

    # ------------------------------------------------------------------

    def _parse_list(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        found: list[dict] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            # The PRID is the only part of the href worth keeping — the page it
            # names carries no release. See the module docstring.
            prid = PRID.search(href)
            if prid is None:
                continue
            title = a.get_text(" ", strip=True)
            if len(title) < 20:
                continue
            url = DETAIL_URL.format(prid=prid.group(1))
            if url in seen:
                continue
            seen.add(url)

            # PIB groups releases under a ministry heading; walk up to find it.
            ministry = ""
            for parent in a.parents:
                heading = parent.find_previous(["h2", "h3", "h4"]) if parent else None
                if heading:
                    text = heading.get_text(" ", strip=True)
                    if text and len(text) < 200:
                        ministry = text
                    break

            found.append({"url": url, "title": title, "ministry": ministry})
        return found

    def _parse_detail(self, html: str, link: dict) -> RawEntry | None:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # "Posted On:" sits in the page chrome rather than the release body, so
        # look for it across the whole document.
        page_text = soup.get_text(" ", strip=True)

        container = (
            soup.find(id=BODY_ID)
            or soup.find("div", class_=re.compile("innner-page-main-about-us-content", re.I))
            or soup.find("main")
            or soup.body
        )
        if container is None:
            return None

        body = self.clean_text(container.get_text("\n", strip=True))
        if len(body) < MIN_BODY_CHARS:
            # A shell page rather than a release. Returning None here is what
            # stops the navigation menu being published as a news item.
            log.warning(
                "pib: %s had only %d characters of body — skipping",
                link["url"], len(body),
            )
            return None

        title = link["title"]
        heading = container.find(["h1", "h2"])
        if heading:
            heading_text = heading.get_text(" ", strip=True)
            if len(heading_text) > 20:
                title = heading_text

        published = self.parse_date(self._find_date(page_text))
        department = link.get("ministry") or self._find_ministry(body)

        return RawEntry(
            title=title[:500],
            raw_text=body,
            original_url=link["url"],
            category=self._guess_category(f"{title} {body[:800]}"),
            state="ALL",
            department=department[:200],
            published_date=published,
            deadline=self.parse_date(self._find_deadline(body)),
            extra={"source": "pib"},
        )

    @staticmethod
    def _find_date(text: str) -> str | None:
        # PIB renders "Posted On: 13 AUG 2026 10:14PM by PIB Delhi" — note the
        # uppercase month, which a [A-Z][a-z]+ pattern would miss.
        m = re.search(r"Posted On:?\s*([\d]{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", text, re.I)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b", text)
        return m.group(1) if m else None

    @staticmethod
    def _find_deadline(text: str) -> str | None:
        m = re.search(
            r"(?:last date|closing date|apply(?:\s+on\w*)? by|अंतिम तिथि)[^\n]{0,60}",
            text,
            re.I,
        )
        return m.group(0) if m else None

    @staticmethod
    def _find_ministry(text: str) -> str:
        m = re.search(r"(Ministry of [A-Z][A-Za-z ,&]{3,60})", text)
        return m.group(1).strip() if m else "Government of India"

    @staticmethod
    def _guess_category(text: str) -> str:
        lowered = text.lower()
        if any(h in lowered for h in NAUKRI_HINTS):
            return "naukri"
        if any(h in lowered for h in YOJANA_HINTS):
            return "yojana"
        if any(h in lowered for h in RULE_HINTS):
            return "rule"
        return "notice"

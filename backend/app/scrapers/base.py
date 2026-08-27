"""
Base scraper that all source-specific scrapers inherit from.

Every scraper must implement:
  - source_key: str (matches sources.scraper_key in DB)
  - scrape() -> list[RawEntry]

The runner (app/scrapers/runner.py) handles deduplication, database insertion,
error logging, and run tracking in the scraper_runs table.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Several portals (pib.gov.in among them) return 403 to any User-Agent that
# looks automated — verified: an identifying bot UA gets 403 where a browser UA
# gets 200 on the same URL. So the default is browser-shaped with a contact URL
# appended, and it stays overridable via SCRAPER_USER_AGENT. Politeness is
# enforced by the request delays below, not by the UA string.
USER_AGENT = settings.scraper_user_agent

# Government portals are slow and easily overwhelmed. One request per ~3s per
# domain, as per the PRD's rate-limit guidance.
MIN_DELAY_SECONDS = 2.0
MAX_DELAY_SECONDS = 5.0

#: Browser profile curl_cffi replays for WAF-protected portals. See
#: fetch_impersonated() for why this is needed.
IMPERSONATE_PROFILE = "chrome"


@dataclass
class RawEntry:
    """What a scraper outputs before AI processing."""

    title: str
    raw_text: str  # Full extracted text
    original_url: str
    category: str  # Best guess; AI will verify
    state: str  # State code: RJ, UP, ALL, etc.
    department: str
    published_date: Optional[str] = None  # ISO format or None
    deadline: Optional[str] = None  # ISO format or None
    pdf_url: Optional[str] = None
    budget_amount: Optional[int] = None  # In paisa
    extra: dict = field(default_factory=dict)


class ScraperError(RuntimeError):
    pass


class BaseScraper(ABC):
    #: Requests are spaced by this many seconds (plus jitter).
    request_timeout = 30.0

    @property
    @abstractmethod
    def source_key(self) -> str:
        """Must match sources.scraper_key in database."""

    @abstractmethod
    async def scrape(self) -> list[RawEntry]:
        """Fetch and parse the source. Return list of RawEntry."""

    def content_hash(self, entry: RawEntry) -> str:
        """Generate dedup hash from title + URL + date."""
        raw = f"{entry.title}|{entry.original_url}|{entry.published_date or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # --- helpers shared by every scraper ---------------------------------

    async def fetch(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        """GET with a polite delay, a real User-Agent, and one retry."""
        last_error: Exception | None = None
        for attempt in range(2):
            await asyncio.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
            try:
                resp = await client.get(url, timeout=self.request_timeout, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                log.warning("%s: fetch failed (attempt %d) %s: %s", self.source_key, attempt + 1, url, exc)
        raise ScraperError(f"{self.source_key}: could not fetch {url}") from last_error

    @staticmethod
    def client(headers: dict[str, str] | None = None, **kwargs) -> httpx.AsyncClient:
        base_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        }
        return httpx.AsyncClient(
            headers={**base_headers, **(headers or {})},
            follow_redirects=True,
            **kwargs,
        )

    async def fetch_impersonated(self, url: str) -> str | None:
        """GET a page using a real browser's TLS fingerprint.

        Some portals sit behind a WAF that fingerprints the TLS ClientHello
        rather than reading headers. pib.gov.in is one: identical headers get
        200 from curl and 403 from httpx, and headless Chromium is blocked too.
        curl_cffi replays a browser handshake, which gets through.

        Returns None if curl_cffi isn't installed, so callers can fall back.
        """
        try:
            from curl_cffi import requests as curl_requests  # noqa: PLC0415
        except ImportError:
            log.warning("%s: curl_cffi not installed; cannot bypass TLS fingerprinting", self.source_key)
            return None

        await asyncio.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
        try:
            async with curl_requests.AsyncSession() as session:
                resp = await session.get(
                    url,
                    impersonate=IMPERSONATE_PROFILE,
                    timeout=self.request_timeout,
                    headers={"Accept-Language": "en-IN,en;q=0.9,hi;q=0.8"},
                )
            if resp.status_code >= 400:
                log.warning("%s: impersonated fetch got %s for %s", self.source_key, resp.status_code, url)
                return None
            return resp.text
        except Exception as exc:
            log.warning("%s: impersonated fetch failed for %s: %s", self.source_key, url, exc)
            return None

    async def fetch_rendered(self, url: str, wait_for: str | None = None) -> str | None:
        """Load a page in headless Chromium.

        Needed for portals behind a WAF that fingerprints the TLS handshake
        (pib.gov.in sits behind Akamai and 403s httpx no matter what headers we
        send) and for pages that build their content with JavaScript. Returns
        None when Playwright is unavailable, so callers can fall back.
        """
        try:
            from playwright.async_api import async_playwright  # noqa: PLC0415
        except ImportError:
            log.warning(
                "%s: playwright not installed; run "
                "`pip install -r requirements-playwright.txt && playwright install chromium`",
                self.source_key,
            )
            return None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(args=["--no-sandbox"])
                context = await browser.new_context(
                    user_agent=USER_AGENT,
                    locale="en-IN",
                    ignore_https_errors=True,
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                if wait_for:
                    try:
                        await page.wait_for_selector(wait_for, timeout=20_000)
                    except Exception:
                        log.info("%s: selector %r never appeared", self.source_key, wait_for)
                html = await page.content()
                await browser.close()
                return html
        except Exception as exc:
            log.warning("%s: playwright render failed: %s", self.source_key, exc)
            return None

    # --- parsing helpers --------------------------------------------------

    _DATE_PATTERNS = [
        (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), ("y", "m", "d")),
        (re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})"), ("d", "m", "y")),
        (re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})"), ("d", "m", "y")),
    ]
    _MONTHS = {
        m.lower(): i
        for i, m in enumerate(
            [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            ],
            start=1,
        )
    }

    @classmethod
    def parse_date(cls, text: str | None) -> Optional[str]:
        """Best-effort ISO date from the many formats Indian portals use."""
        if not text:
            return None
        text = text.strip()

        for pattern, order in cls._DATE_PATTERNS:
            m = pattern.search(text)
            if m:
                parts = dict(zip(order, m.groups()))
                try:
                    return date(int(parts["y"]), int(parts["m"]), int(parts["d"])).isoformat()
                except ValueError:
                    continue

        # "15 March 2026" / "15 Mar 2026"
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,})\.?,?\s+(\d{4})", text)
        if m:
            day, month_name, year = m.groups()
            for name, num in cls._MONTHS.items():
                if name.startswith(month_name.lower()[:3]):
                    try:
                        return date(int(year), num, int(day)).isoformat()
                    except ValueError:
                        break
        return None

    @staticmethod
    def parse_amount_to_paisa(text: str | None) -> Optional[int]:
        """Turn 'Rs. 8.40 Crore' / '₹16,80,000' / '84 Lakh' into paisa."""
        if not text:
            return None
        cleaned = text.replace(",", "").replace("₹", " ")
        m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if not m:
            return None
        value = float(m.group(1))

        lowered = cleaned.lower()
        if "crore" in lowered or "cr." in lowered or re.search(r"\bcr\b", lowered):
            value *= 10_000_000
        elif "lakh" in lowered or "lac" in lowered:
            value *= 100_000

        paisa = int(round(value * 100))
        return paisa if paisa > 0 else None

    @staticmethod
    def clean_text(text: str, limit: int = 20_000) -> str:
        """Collapse whitespace and cap length before it reaches the AI layer."""
        collapsed = re.sub(r"[ \t\xa0]+", " ", text)
        collapsed = re.sub(r"\n{3,}", "\n\n", collapsed).strip()
        return collapsed[:limit]

    @staticmethod
    def today() -> date:
        return datetime.now().date()

"""Staff Selection Commission — https://ssc.gov.in

ssc.gov.in is an Angular SPA: the served HTML contains **zero** anchors, so the
HTML-scraping approach the PRD assumed cannot work here. The site reads JSON
APIs and so do we.

Three feeds, because SSC splits its content three ways and only together do
they amount to the notice board a candidate actually reads:

  * ``/api/general-website/portal/notice-boards`` — the notice board proper.
    Answer keys, results, exam schedules, corrigenda, vacancy tables. 695
    records, newest first, each with a PDF. This is the bulk of it.
  * ``/api/admin/5.1/liveExams`` — exams open for application right now, with
    application and correction windows, fee and age limits. The only feed that
    carries a deadline anyone can still act on.
  * ``/api/admin/5.1/getAllCandiateAdvertisements`` — Selection Post
    advertisements. Eleven records going back to 2019, so it contributes
    little, but it is the only place the Selection Post phases appear.
    (The "Candiate" typo is theirs, and load-bearing.)

**Finding the first two took reading the network tab, not the bundle.** The
main JS bundle names 53 ``admin/5.1/*`` paths and not one of them is the notice
board; the ``general-website`` namespace appears nowhere in it. Loading the
homepage and watching what it actually requested was what turned this source
from one stale advertisement into real coverage.

Two details worth keeping:

  * ``limit`` is capped at 10 server-side. Asking for 50 returns 10; asking for
    200 returns a response with no ``data`` key at all. Paging is the only way
    through, so this walks pages until the notices get older than the age cap.
  * Attachment paths come back with Windows separators
    (``uploads\\masterData\\NoticeBoards\\x.pdf``) and are served from
    ``/api/attachment/``. The bare ``/uploads/...`` path returns the SPA shell
    with HTTP 200, so a naive URL silently yields an 80 KB HTML page instead of
    the PDF.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from app.scrapers.base import BaseScraper, RawEntry, ScraperError

log = logging.getLogger(__name__)

BASE = "https://ssc.gov.in"
ADVERTISEMENTS_URL = f"{BASE}/api/admin/5.1/getAllCandiateAdvertisements"
LIVE_EXAMS_URL = f"{BASE}/api/admin/5.1/liveExams"
NOTICE_BOARD_URL = f"{BASE}/api/general-website/portal/notice-boards"
#: Attachments are served through the API, not from the document root.
ATTACHMENT_URL = f"{BASE}/api/attachment/{{path}}"

NOTICE_ATTRIBUTES = (
    "id,headline,examId,contentType,redirectUrl,startDate,endDate,language,createdAt"
)
#: The server enforces this regardless of what we ask for.
PAGE_SIZE = 10
#: 695 records reach back years. Stop well before that.
MAX_NOTICE_PAGES = 12

#: Ignore advertisements and notices older than this.
MAX_AGE_DAYS = 400
#: The notice board is dated precisely, so it can be cut much tighter than the
#: advertisement list, which only has application windows.
MAX_NOTICE_AGE_DAYS = 180


class SSCScraper(BaseScraper):
    source_key = "ssc"

    async def scrape(self) -> list[RawEntry]:
        async with self.client(headers={"Accept": "application/json"}) as client:
            notices = await self._notice_board(client)
            exams = await self._live_exams(client)
            adverts = await self._advertisements(client)

        entries = notices + exams + adverts
        if not entries:
            raise ScraperError(
                "ssc: all three feeds returned nothing — the API shape may have changed"
            )
        log.info(
            "ssc: %d notices, %d live exams, %d advertisements",
            len(notices), len(exams), len(adverts),
        )
        return entries

    # --- notice board -----------------------------------------------------

    async def _notice_board(self, client: httpx.AsyncClient) -> list[RawEntry]:
        """Walk the notice board newest-first until the entries get too old."""
        entries: list[RawEntry] = []

        for page in range(1, MAX_NOTICE_PAGES + 1):
            params = {
                "page": page,
                "limit": PAGE_SIZE,
                "contentType": "notice-boards",
                "key": "createdAt",
                "order": "DESC",
                "isAttachment": "true",
                "language": "english",
                "attributes": NOTICE_ATTRIBUTES,
            }
            try:
                payload = (await self.fetch(client, NOTICE_BOARD_URL, params=params)).json()
            except (ValueError, ScraperError) as exc:
                log.warning("ssc: notice board page %d failed: %s", page, exc)
                break

            records = payload.get("data")
            if not isinstance(records, list) or not records:
                break

            fresh = [r for r in records if not self._too_old(
                self._date_only(r.get("createdAt")), MAX_NOTICE_AGE_DAYS)]
            entries.extend(e for r in fresh if (e := self._notice_entry(r)) is not None)

            if len(fresh) < len(records):
                # Sorted newest-first, so the first stale page is the last one
                # worth asking for.
                break

        return entries

    def _notice_entry(self, record: dict[str, Any]) -> RawEntry | None:
        headline = (record.get("headline") or "").strip()
        record_id = (record.get("id") or "").strip()
        if not headline or not record_id:
            return None

        published = self._date_only(record.get("createdAt"))
        pdf = self._attachment_url(record)
        # Prefer the document, then whatever the notice redirects to, and only
        # then a bare anchor — an entry nobody can click through is half useless.
        url = pdf or (record.get("redirectUrl") or "").strip() or (
            f"{BASE}/candidate-portal/notice-board#{record_id}"
        )

        raw_text = "\n".join(
            filter(
                None,
                [
                    f"Staff Selection Commission notice: {headline}",
                    f"Published: {published}" if published else None,
                    "The Staff Selection Commission recruits for Group B and Group C "
                    "posts across central government departments. Its notice board "
                    "carries exam schedules, answer keys, results and corrigenda.",
                    f"Notice document (PDF): {pdf}" if pdf else None,
                ],
            )
        )

        return RawEntry(
            title=headline[:500],
            raw_text=self.clean_text(raw_text),
            original_url=url,
            # Mostly results, answer keys and schedules. The AI reclassifies the
            # ones that are really vacancies.
            category="notice",
            state="ALL",
            department="Staff Selection Commission",
            published_date=published,
            pdf_url=pdf,
            extra={"notice_id": record_id, "exam_id": record.get("examId") or None},
        )

    @staticmethod
    def _attachment_url(record: dict[str, Any]) -> str | None:
        attachments = record.get("attachments") or []
        if not isinstance(attachments, list):
            return None
        for att in attachments:
            path = (att or {}).get("path")
            if path:
                # Windows separators, straight from their file server.
                return ATTACHMENT_URL.format(path=str(path).replace("\\", "/").lstrip("/"))
        return None

    # --- live exams -------------------------------------------------------

    async def _live_exams(self, client: httpx.AsyncClient) -> list[RawEntry]:
        try:
            payload = (await self.fetch(client, LIVE_EXAMS_URL)).json()
        except (ValueError, ScraperError) as exc:
            log.warning("ssc: live exams feed failed: %s", exc)
            return []

        records = payload.get("data")
        if not isinstance(records, list):
            return []
        return [e for r in records if (e := self._exam_entry(r)) is not None]

    def _exam_entry(self, record: dict[str, Any]) -> RawEntry | None:
        exam_id = (record.get("id") or "").strip()
        name = (record.get("examName") or record.get("examDescription") or "").strip()
        if not exam_id or not name:
            return None

        opens = self._date_only(record.get("applicationStartDate"))
        closes = self._date_only(record.get("applicationEndDate"))
        fee_last = self._date_only(record.get("lastDateForFee"))
        code = (record.get("displayExamCode") or record.get("examCode") or "").strip()
        title = f"SSC {code}: {name}" if code else f"SSC {name}"

        raw_text = "\n".join(
            filter(
                None,
                [
                    f"Staff Selection Commission recruitment: {name}",
                    f"Exam code: {code}" if code else None,
                    f"Applications open: {opens}" if opens else None,
                    f"Last date to apply: {closes}" if closes else None,
                    f"Last date to pay the fee: {fee_last}" if fee_last else None,
                    self._correction_window(record),
                    self._eligibility(record),
                    f"Apply online at {BASE}/candidate-portal/apply",
                ],
            )
        )

        return RawEntry(
            title=title[:500],
            raw_text=self.clean_text(raw_text),
            original_url=f"{BASE}/candidate-portal/apply#{exam_id}",
            category="naukri",
            state="ALL",
            department="Staff Selection Commission",
            published_date=opens,
            deadline=closes,
            extra={
                "exam_id": exam_id,
                "exam_code": code or None,
                "exam_year": record.get("examYear") or None,
            },
        )

    @classmethod
    def _correction_window(cls, record: dict[str, Any]) -> str | None:
        start = cls._date_only(record.get("correctionStartDate"))
        end = cls._date_only(record.get("correctionEndDate"))
        if not (start and end):
            return None
        return f"Application corrections can be made between {start} and {end}."

    @staticmethod
    def _eligibility(record: dict[str, Any]) -> str | None:
        bits = []
        if (fee := record.get("fee")) not in (None, ""):
            bits.append(f"Application fee is Rs {fee}")
        min_age, max_age = record.get("minAge"), record.get("maxAge")
        if min_age and max_age:
            bits.append(f"age limit is {min_age} to {max_age} years")
        return f"{'; '.join(bits)}." if bits else None

    # --- selection post advertisements ------------------------------------

    async def _advertisements(self, client: httpx.AsyncClient) -> list[RawEntry]:
        try:
            payload = (await self.fetch(client, ADVERTISEMENTS_URL)).json()
        except (ValueError, ScraperError) as exc:
            log.warning("ssc: advertisements feed failed: %s", exc)
            return []

        records = payload.get("data")
        if not isinstance(records, list):
            log.warning("ssc: advertisements payload shape was %s", list(payload)[:5])
            return []
        return [e for r in records if (e := self._to_entry(r)) is not None]

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

    # --- shared -----------------------------------------------------------

    @staticmethod
    def _iso(value: Any) -> str | None:
        """The API already returns YYYY-MM-DD; validate rather than trust it."""
        if not value or not isinstance(value, str):
            return None
        return BaseScraper.parse_date(value)

    @classmethod
    def _date_only(cls, value: Any) -> str | None:
        """Date part of an API value, which may be a date or an ISO timestamp.

        `parse_date` alone would do for "2026-09-10", but application deadlines
        arrive as "2026-09-30T17:30:00.000Z".
        """
        if not value or not isinstance(value, str):
            return None
        return cls._iso(value.split("T", 1)[0])

    @staticmethod
    def _too_old(iso: str | None, max_age_days: int = MAX_AGE_DAYS) -> bool:
        if not iso:
            return False
        try:
            return (date.today() - date.fromisoformat(iso)).days > max_age_days
        except ValueError:
            return False

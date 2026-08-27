"""Scraper unit tests — parsing only, no network."""

from __future__ import annotations

import pytest

from app.scrapers.base import BaseScraper, RawEntry
from app.scrapers.sources.pib import PIBScraper
from app.scrapers.sources.raj_eproc import RajasthanEProcScraper
from app.scrapers.sources.ssc import SSCScraper


class DummyScraper(BaseScraper):
    source_key = "dummy"

    async def scrape(self):
        return []


def entry(**kwargs) -> RawEntry:
    defaults = dict(
        title="Road work tender",
        raw_text="text",
        original_url="https://example.gov.in/t/1",
        category="tender",
        state="RJ",
        department="PWD",
        published_date="2026-03-01",
    )
    return RawEntry(**{**defaults, **kwargs})


class TestContentHash:
    def test_stable_for_same_input(self):
        s = DummyScraper()
        assert s.content_hash(entry()) == s.content_hash(entry())

    def test_differs_when_url_differs(self):
        s = DummyScraper()
        a = s.content_hash(entry())
        b = s.content_hash(entry(original_url="https://example.gov.in/t/2"))
        assert a != b

    def test_differs_when_date_differs(self):
        s = DummyScraper()
        assert s.content_hash(entry()) != s.content_hash(entry(published_date="2026-03-02"))


class TestDateParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("2026-03-15", "2026-03-15"),
            ("15/03/2026", "2026-03-15"),
            ("15-03-2026", "2026-03-15"),
            ("15.03.2026", "2026-03-15"),
            ("Last date: 15 March 2026", "2026-03-15"),
            ("Posted On: 09 Aug 2026", "2026-08-09"),
            ("no date at all", None),
            ("", None),
            (None, None),
            ("32/13/2026", None),  # invalid components must not raise
        ],
    )
    def test_parse_date(self, text, expected):
        assert BaseScraper.parse_date(text) == expected


class TestAmountParsing:
    @pytest.mark.parametrize(
        "text,expected_paisa",
        [
            ("Rs. 8.40 Crore", 84_000_000_00),
            ("₹16,80,000", 1_680_000_00),
            ("22.5 crore", 22_50_00_000_00),
            ("29.4 Lakh", 29_40_000_00),
            ("N/A", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse_amount(self, text, expected_paisa):
        assert BaseScraper.parse_amount_to_paisa(text) == expected_paisa


class TestCleanText:
    def test_collapses_whitespace_and_caps_length(self):
        messy = "a  \t b\n\n\n\nc" + "x" * 100
        cleaned = BaseScraper.clean_text(messy, limit=20)
        assert "  " not in cleaned
        assert "\n\n\n" not in cleaned
        assert len(cleaned) <= 20


class TestPIBParsing:
    def test_category_guessing(self):
        guess = PIBScraper._guess_category
        assert guess("SSC announces recruitment for 500 posts") == "naukri"
        assert guess("PM Kisan Yojana instalment released to farmers") == "yojana"
        assert guess("Income tax rules amendment notified") == "rule"
        assert guess("Press briefing on the meeting held today") == "notice"

    def test_parse_list_finds_release_links(self):
        html = """
        <html><body>
          <h3>Ministry of Agriculture</h3>
          <a href="/PressReleasePage.aspx?PRID=1234">PM Kisan 19th instalment released to farmers</a>
          <a href="/about.aspx">About</a>
          <a href="/PressReleasePage.aspx?PRID=1234">PM Kisan 19th instalment released to farmers</a>
        </body></html>
        """
        links = PIBScraper()._parse_list(html)
        assert len(links) == 1, "duplicate URLs must be collapsed"
        assert links[0]["url"].endswith("PRID=1234")

    def test_short_link_text_is_ignored(self):
        html = '<a href="/PressReleasePage.aspx?PRID=1">Read</a>'
        assert PIBScraper()._parse_list(html) == []


class TestSSCApiParsing:
    """SSC is a JSON API, not HTML — ssc.gov.in serves an SPA with zero anchors."""

    RECORD = {
        "id": "abc123xyz",
        "advertisementName": "Phase-XIV/2026/Selection Posts",
        "startDate": "2026-03-06",
        "endDate": "2026-04-19",
        "year": "2026",
    }

    def test_maps_a_record_to_an_entry(self):
        e = SSCScraper()._to_entry(self.RECORD)
        assert e is not None
        assert e.category == "naukri"
        assert e.state == "ALL"
        assert e.department == "Staff Selection Commission"
        assert e.published_date == "2026-03-06"
        assert e.deadline == "2026-04-19"
        assert e.extra["advertisement_id"] == "abc123xyz"
        assert "Phase-XIV/2026" in e.title

    def test_does_not_double_prefix_ssc(self):
        e = SSCScraper()._to_entry({**self.RECORD, "advertisementName": "SSC CGL 2026"})
        assert e is not None
        assert e.title.count("SSC") == 1

    def test_raw_text_carries_the_dates_for_the_ai_layer(self):
        e = SSCScraper()._to_entry(self.RECORD)
        assert e is not None
        assert "2026-04-19" in e.raw_text
        assert "Staff Selection Commission" in e.raw_text

    @pytest.mark.parametrize(
        "record",
        [
            {"id": "x", "advertisementName": ""},
            {"id": "", "advertisementName": "Something"},
            {},
        ],
    )
    def test_skips_incomplete_records(self, record):
        assert SSCScraper()._to_entry(record) is None

    def test_drops_advertisements_that_closed_long_ago(self):
        old = {**self.RECORD, "startDate": "2019-05-31", "endDate": "2019-06-14"}
        assert SSCScraper()._to_entry(old) is None

    def test_tolerates_a_malformed_date(self):
        e = SSCScraper()._to_entry({**self.RECORD, "endDate": "not-a-date"})
        assert e is not None
        assert e.deadline is None


class TestRajEprocParsing:
    TABLE = """
    <table>
      <tr><th>Tender ID</th><th>Title</th><th>Department</th><th>Value</th>
          <th>EMD</th><th>Published Date</th><th>Closing Date</th></tr>
      <tr><td>RJ-PWD-2026-0412</td>
          <td>Road widening on Jaipur-Sikar highway</td>
          <td>Public Works Department</td>
          <td>Rs. 8.40 Crore</td><td>Rs. 16.80 Lakh</td>
          <td>01/03/2026</td><td>20/03/2026</td></tr>
    </table>
    """

    def test_parses_row_into_entry(self):
        scraper = RajasthanEProcScraper()
        rows = scraper._parse_table(self.TABLE)
        assert len(rows) == 1

        e = scraper._to_entry(rows[0])
        assert e.category == "tender"
        assert e.state == "RJ"
        assert e.budget_amount == 84_000_000_00
        assert e.deadline == "2026-03-20"
        assert e.published_date == "2026-03-01"
        assert e.extra["tender_id"] == "RJ-PWD-2026-0412"
        assert e.extra["emd_amount"] == 1_680_000  # Rs 16.80 Lakh, in rupees

    def test_ignores_unrelated_tables(self):
        html = "<table><tr><th>Name</th></tr><tr><td>Something</td></tr></table>"
        assert RajasthanEProcScraper._parse_table(html) == []

    # The portal's own search form has a header row reading "Tender ID | Tender
    # Title", so a header check alone let its controls through as entries titled
    # "Enter Captcha" and "Active Tenders Back". These pin that shut.
    SEARCH_FORM = """
    <table>
      <tr><th>Tender ID</th><th>Tender Title</th><th>Select Sorting Option</th></tr>
      <tr><td>Active Tenders Back</td><td>Enter Captcha Refresh</td><td>Search</td></tr>
      <tr><td>Provide Captcha and click</td><td>Active Tenders listing</td><td>Refresh</td></tr>
    </table>
    """

    def test_rejects_the_search_form_masquerading_as_tenders(self):
        assert RajasthanEProcScraper._parse_table(self.SEARCH_FORM) == []

    def test_keeps_rows_with_a_real_tender_id(self):
        assert RajasthanEProcScraper._is_tender_row(
            {"tender_id": "RJ-PWD-2026-0412", "published": "", "closing": ""}
        )

    def test_keeps_rows_with_a_parseable_date(self):
        assert RajasthanEProcScraper._is_tender_row(
            {"tender_id": "", "published": "01/03/2026", "closing": ""}
        )

    def test_rejects_rows_with_neither_id_nor_date(self):
        assert not RajasthanEProcScraper._is_tender_row(
            {"tender_id": "Back", "published": "Search", "closing": "Refresh"}
        )

    def test_detects_the_captcha_gate(self):
        assert RajasthanEProcScraper._is_captcha_gated("<p>Enter Captcha to search</p>")
        assert not RajasthanEProcScraper._is_captcha_gated(self.TABLE)

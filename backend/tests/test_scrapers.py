"""Scraper unit tests — parsing only, no network."""

from __future__ import annotations

import pytest

from app.scrapers.base import BaseScraper, RawEntry
from app.scrapers.sources.gem import GeMScraper
from app.scrapers.sources.nta import NTAScraper
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


class TestGeMParsing:
    """GeM's docs come from Solr, so every value arrives wrapped in a list."""

    DOC = {
        "id": "9880902",
        "b_id": [9880902],
        "b_bid_number": ["GEM/2026/R/733024"],
        "b_category_name": ["Procurement of Face Shield"],
        "bd_category_name": ["Personal Protective Equipment; Face Shield"],
        "b_total_quantity": [260],
        "ba_official_details_minName": ["Ministry of Defence"],
        "ba_official_details_deptName": ["Department of Military Affairs"],
        "final_start_date_sort": ["2026-09-12T13:00:00Z"],
        "final_end_date_sort": ["2026-09-14T15:00:00Z"],
        "is_high_value": True,
    }

    def test_maps_a_doc_to_an_entry(self):
        e = GeMScraper()._to_entry(self.DOC)
        assert e is not None
        assert e.category == "tender"
        assert e.published_date == "2026-09-12"
        assert e.deadline == "2026-09-14"
        assert e.extra["bid_number"] == "GEM/2026/R/733024"
        assert e.extra["quantity"] == 260

    def test_links_to_the_bid_document(self):
        e = GeMScraper()._to_entry(self.DOC)
        assert e is not None
        # GeM has no per-bid HTML page; the document is the only permalink.
        assert e.original_url.endswith("/showbidDocument/9880902")
        assert e.pdf_url == e.original_url

    def test_joins_ministry_and_department(self):
        e = GeMScraper()._to_entry(self.DOC)
        assert e is not None
        assert "Ministry of Defence" in e.department
        assert "Department of Military Affairs" in e.department

    def test_drops_the_literal_na_department(self):
        # The API writes "NA" rather than omitting the field.
        e = GeMScraper()._to_entry({**self.DOC, "ba_official_details_deptName": ["NA"]})
        assert e is not None
        assert "NA" not in e.department
        assert e.department == "Ministry of Defence"

    def test_falls_back_when_no_office_is_named(self):
        doc = {k: v for k, v in self.DOC.items()
               if k not in ("ba_official_details_minName", "ba_official_details_deptName")}
        e = GeMScraper()._to_entry(doc)
        assert e is not None
        assert e.department == "Government e-Marketplace"

    def test_prefers_the_fuller_classification_for_the_title(self):
        e = GeMScraper()._to_entry(self.DOC)
        assert e is not None
        assert e.title.startswith("Personal Protective Equipment")

    def test_falls_back_to_the_item_list_when_classification_is_missing(self):
        doc = {k: v for k, v in self.DOC.items() if k != "bd_category_name"}
        e = GeMScraper()._to_entry(doc)
        assert e is not None
        assert e.title.startswith("Procurement of Face Shield")

    def test_raw_text_carries_the_dates_for_the_ai_layer(self):
        e = GeMScraper()._to_entry(self.DOC)
        assert e is not None
        assert "2026-09-14" in e.raw_text
        assert "Ministry of Defence" in e.raw_text

    @pytest.mark.parametrize(
        "doc",
        [
            {"b_id": [1]},                       # no bid number
            {"b_bid_number": ["GEM/1"]},         # no id
            {},
        ],
    )
    def test_skips_docs_missing_their_identifiers(self, doc):
        assert GeMScraper()._to_entry(doc) is None

    def test_tolerates_a_malformed_date(self):
        e = GeMScraper()._to_entry({**self.DOC, "final_end_date_sort": ["not-a-date"]})
        assert e is not None
        assert e.deadline is None

    @pytest.mark.parametrize(
        "value,expected",
        [(["x"], "x"), ([], None), ("x", "x"), (None, None), ([1, 2], 1)],
    )
    def test_unwraps_solr_single_element_lists(self, value, expected):
        assert GeMScraper._one(value) == expected


class TestNTAParsing:
    """NTA's anchors all read 'Read More' — the title lives in the row."""

    ROW = """
    <table>
      <tr><th>#</th><th>Notice Title</th><th>Attachement</th></tr>
      <tr><td>1</td><td>Declaration of results of UGC-NET June 2026 Exam</td>
          <td><a href="/Download/Notice/Notice_20260918000302.pdf">Read More</a></td></tr>
    </table>
    """

    def _html(self, *rows: str) -> str:
        return "<table>" + "".join(rows) + "</table>"

    def _row(self, title: str, href: str, index: int = 1) -> str:
        return (f'<tr><td>{index}</td><td>{title}</td>'
                f'<td><a href="{href}">Read More</a></td></tr>')

    @staticmethod
    def _stamp(days_ago: int, prefix: str = "Notice_") -> str:
        from datetime import date, timedelta
        d = date.today() - timedelta(days=days_ago)
        return f"/Download/Notice/{prefix}{d.strftime('%Y%m%d')}120000.pdf"

    def test_parses_a_row_into_an_entry(self):
        rows = NTAScraper._parse(self.ROW)
        assert len(rows) == 1
        e = NTAScraper()._to_entry(rows[0])
        assert e.category == "naukri"
        assert e.state == "ALL"
        assert e.department == "National Testing Agency"
        assert e.published_date == "2026-09-18"
        assert e.original_url.startswith("https://www.nta.ac.in/")
        assert e.pdf_url == e.original_url

    def test_title_comes_from_the_row_not_the_anchor(self):
        rows = NTAScraper._parse(self.ROW)
        # Anchor text is "Read More" on every single link; an anchor-driven
        # scraper produces 1,891 identically-titled entries.
        assert "Read More" not in rows[0]["title"]
        assert rows[0]["title"] == "Declaration of results of UGC-NET June 2026 Exam"

    def test_strips_the_leading_row_index(self):
        rows = NTAScraper._parse(self._html(
            self._row("Public Notice for CUET-UG 2026", "/Download/Notice/Notice_20260101120000.pdf", index=42)
        ))
        assert rows[0]["title"] == "Public Notice for CUET-UG 2026"

    @pytest.mark.parametrize("prefix", ["Notice_", ""])
    def test_reads_both_filename_date_formats(self, prefix):
        # Files before ~2020 are a bare YYYYMMDDHHMMSS.pdf. Treating those as
        # undated let 2019 notices past the age cap.
        url = f"https://www.nta.ac.in/Download/Notice/{prefix}20190724190100.pdf"
        assert NTAScraper._date_from_url(url) == "2019-07-24"

    def test_undated_filename_yields_no_date(self):
        url = "https://www.nta.ac.in/Download/Notice/PressReleaseCMAT.pdf"
        assert NTAScraper._date_from_url(url) is None

    def test_impossible_timestamp_is_absent_rather_than_wrong(self):
        url = "https://www.nta.ac.in/Download/Notice/Notice_20261332120000.pdf"
        assert NTAScraper._date_from_url(url) is None

    def test_ignores_rows_without_a_pdf_link(self):
        html = self._html(
            '<tr><td>1</td><td>Some heading</td><td><a href="/about">Read More</a></td></tr>',
            self._row("A real notice about the UGC-NET exam", "/Download/Notice/Notice_20260101120000.pdf", 2),
        )
        assert len(NTAScraper._parse(html)) == 1

    def test_drops_rows_whose_title_is_too_short(self):
        html = self._html(self._row("PDF", "/Download/Notice/Notice_20260101120000.pdf"))
        assert NTAScraper._parse(html) == []

    def test_collapses_duplicate_urls(self):
        href = "/Download/Notice/Notice_20260101120000.pdf"
        html = self._html(self._row("Notice about the CUET examination", href, 1),
                          self._row("Notice about the CUET examination", href, 2))
        assert len(NTAScraper._parse(html)) == 1

    # --- age cap -----------------------------------------------------

    def test_keeps_recent_rows(self):
        rows = [{"title": "t", "url": self._stamp(d)} for d in (1, 10, 100, 300)]
        assert NTAScraper._within_age_cap(rows) == rows

    def test_cuts_the_tail_once_past_the_cap(self):
        rows = [{"title": "t", "url": self._stamp(d)}
                for d in (1, 10, 400, 500, 600, 700)]
        kept = NTAScraper._within_age_cap(rows)
        assert len(kept) == 2, "everything from the first sustained old run is dropped"

    def test_one_stray_old_date_does_not_truncate_the_run(self):
        # A single mis-stamped filename must not discard the whole archive.
        rows = [{"title": "t", "url": self._stamp(d)}
                for d in (1, 5000, 2, 3, 4)]
        assert len(NTAScraper._within_age_cap(rows)) == 5

    def test_undated_rows_in_the_tail_are_cut_with_it(self):
        # Pre-2020 notices have no timestamp at all and sit at the very end;
        # judging them individually let them bypass the cap entirely.
        rows = ([{"title": "t", "url": self._stamp(d)} for d in (1, 2)]
                + [{"title": "t", "url": self._stamp(d)} for d in (400, 500, 600)]
                + [{"title": "old", "url": "/Download/Notice/PressReleaseCMAT.pdf"}])
        kept = NTAScraper._within_age_cap(rows)
        assert len(kept) == 2
        assert all("PressRelease" not in r["url"] for r in kept)

    def test_undated_rows_near_the_top_are_kept(self):
        # A future rename shows up here; losing new notices silently is worse
        # than carrying a few undated ones.
        rows = [{"title": "t", "url": "/Download/Notice/SomeNewFormat.pdf"},
                {"title": "t", "url": self._stamp(1)}]
        assert len(NTAScraper._within_age_cap(rows)) == 2

    def test_raw_text_carries_the_title_and_date_for_the_ai_layer(self):
        e = NTAScraper()._to_entry(NTAScraper._parse(self.ROW)[0])
        assert "UGC-NET" in e.raw_text
        assert "2026-09-18" in e.raw_text
        assert "National Testing Agency" in e.raw_text

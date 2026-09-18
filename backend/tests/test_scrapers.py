"""Scraper unit tests — parsing only, no network."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from app.scrapers.base import BaseScraper, RawEntry, ScraperError
from app.scrapers.base_notice import NoticeBoard, NoticeBoardScraper
from app.scrapers.sources import ibps
from app.scrapers.sources.gem import GeMScraper
from app.scrapers.sources.ibps import IBPSRecruitmentScraper, IBPSUpdatesScraper
from app.scrapers.sources.nta import NTAScraper
from app.scrapers.sources.pib import PIBScraper
from app.scrapers.sources import rrb
from app.scrapers.sources.raj_eproc import RajasthanEProcScraper
from app.scrapers.sources.rrb import RRBSecunderabadScraper
from app.scrapers.sources.sbi import SBIScraper
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
        # Results, answer keys and exam calendars, not vacancies — the AI put
        # 128 of the first 130 in `notice`, and unsummarised entries are shown
        # under the scraper's category, so the hint has to be right.
        assert e.category == "notice"
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


class TestSBIParsing:
    """SBI cards hide two traps: a nested span inside the title, and a first
    anchor whose text is the file size rather than the post name."""

    CARD = """
    <div class="card">
      <div class="col-md-8 text-uppercase">
        <p>ENGAGEMENT OF SPECIALIST CADRE OFFICERS ON CONTRACT BASIS
           <span class="text_blink">(Apply Online from 16.09.2026 to 06.10.2026)</span></p>
        <p>ADVERTISEMENT NO: CRPD/SCO/2026-27/20</p>
      </div>
      <div class="col-md-4">
        <button class="btn">LAST DATE TO APPLY : 06-10-2026</button>
      </div>
      <div class="accordion-content collapse">
        <ul class="text-link">
          <li><a href="/documents/77530/57941334/16092026_ADV_CRPD_SCO.pdf/72f2">English (1 MB)</a></li>
          <li><a href="https://recruitment.sbi.bank.in/crpd-sco-2026-27-20/apply">APPLY ONLINE (16.09.2026 to 06.10.2026)</a></li>
        </ul>
      </div>
    </div>
    """

    def test_parses_a_card(self):
        cards = SBIScraper._parse(self.CARD)
        assert len(cards) == 1
        c = cards[0]
        assert c["advt_no"] == "CRPD/SCO/2026-27/20"
        assert c["deadline"] == "2026-10-06"
        assert c["apply_url"].endswith("/apply")

    def test_title_excludes_the_apply_window_span(self):
        c = SBIScraper._parse(self.CARD)[0]
        assert "Apply Online" not in c["title"]
        assert "16.09.2026" not in c["title"]
        assert c["title"] == "ENGAGEMENT OF SPECIALIST CADRE OFFICERS ON CONTRACT BASIS"

    def test_title_is_not_the_download_link_text(self):
        # The first anchor reads "English (1 MB)"; using it as the title gives
        # a feed full of entries called "Hindi".
        c = SBIScraper._parse(self.CARD)[0]
        assert "MB" not in c["title"]
        assert c["title"].lower() not in ("english", "hindi")

    def test_keeps_a_balanced_closing_bracket(self):
        # Stripping brackets indiscriminately truncated
        # "JUNIOR ASSOCIATES (CUSTOMER SUPPORT & SALES)".
        html = self.CARD.replace(
            "ENGAGEMENT OF SPECIALIST CADRE OFFICERS ON CONTRACT BASIS",
            "RECRUITMENT OF JUNIOR ASSOCIATES (CUSTOMER SUPPORT & SALES)",
        )
        c = SBIScraper._parse(html)[0]
        assert c["title"].endswith("(CUSTOMER SUPPORT & SALES)")

    def test_links_to_the_advertisement_pdf(self):
        c = SBIScraper._parse(self.CARD)[0]
        assert c["url"].endswith("16092026_ADV_CRPD_SCO.pdf/72f2")
        assert c["url"].startswith("https://sbi.co.in/")

    def test_published_date_comes_from_the_filename(self):
        assert SBIScraper._published(
            "https://sbi.co.in/documents/77530/57941334/16092026_ADV_X.pdf/abc"
        ) == "2026-09-16"

    def test_published_date_absent_when_filename_has_none(self):
        assert SBIScraper._published("https://sbi.co.in/documents/x/y/advert.pdf") is None

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("LAST DATE TO APPLY : 06-10-2026", "2026-10-06"),
            ("LAST DATE TO APPLY: 06.10.2026", "2026-10-06"),
            ("Apply Online from 16.09.2026 to 06.10.2026", "2026-10-06"),
            ("no dates here", None),
        ],
    )
    def test_deadline_extraction(self, text, expected):
        assert SBIScraper._deadline(text) == expected

    def test_last_date_wins_over_the_window(self):
        text = "Apply Online from 01.01.2026 to 02.02.2026 LAST DATE TO APPLY : 09-09-2026"
        assert SBIScraper._deadline(text) == "2026-09-09"

    def test_drops_cards_with_no_real_title(self):
        html = '<div class="card"><p>PDF</p><a href="/x.pdf">English</a></div>'
        assert SBIScraper._parse(html) == []

    def test_drops_cards_with_no_document_link(self):
        html = ('<div class="card"><p>RECRUITMENT OF SOMETHING SUBSTANTIAL HERE</p>'
                '<a href="/about">About</a></div>')
        assert SBIScraper._parse(html) == []

    def test_collapses_duplicate_documents(self):
        assert len(SBIScraper._parse(self.CARD + self.CARD)) == 1

    # --- relevance ----------------------------------------------------

    @staticmethod
    def _iso(days_from_today: int) -> str:
        from datetime import date, timedelta
        return (date.today() + timedelta(days=days_from_today)).isoformat()

    def test_keeps_open_and_recently_closed_openings(self):
        assert SBIScraper._is_relevant(self._iso(10), None) is True
        assert SBIScraper._is_relevant(self._iso(-5), None) is True

    def test_drops_long_closed_openings(self):
        assert SBIScraper._is_relevant(self._iso(-200), None) is False

    def test_falls_back_to_publish_date_when_applications_have_closed(self):
        # No "LAST DATE TO APPLY" means the card has moved on to call letters
        # or results — still worth carrying while it is recent.
        assert SBIScraper._is_relevant(None, self._iso(-60)) is True
        assert SBIScraper._is_relevant(None, self._iso(-500)) is False

    def test_to_entry_carries_the_details_for_the_ai_layer(self):
        e = SBIScraper()._to_entry(SBIScraper._parse(self.CARD)[0])
        assert e is not None
        assert e.category == "naukri"
        assert e.department == "State Bank of India"
        assert e.deadline == "2026-10-06"
        assert "CRPD/SCO/2026-27/20" in e.raw_text
        assert "2026-10-06" in e.raw_text


class TestRRBParsing:
    """One config serves every board: the common portal is identical across
    Secunderabad, Chandigarh and Mumbai."""

    LI = """
    <ul><li>
      <a href="/getdata?loc=secunderabad&cenum=03/2026&category=Application (Special Notice)">
        <strong>(03/2026)</strong>
        Application (Special Notice)
        <span class="pub_date">(16-09-2026)</span>
      </a>
    </li></ul>
    """

    def test_parses_a_notice(self):
        rows = RRBSecunderabadScraper._parse(self.LI)
        assert len(rows) == 1
        assert rows[0]["published"] == "2026-09-16"

    def test_title_pairs_the_cen_with_the_category(self):
        # "Application (Special Notice)" alone does not say which recruitment,
        # and the CEN number is what candidates actually follow.
        row = RRBSecunderabadScraper._parse(self.LI)[0]
        assert row["title"] == "CEN 03/2026 — Application (Special Notice)"

    def test_the_publication_date_is_not_left_in_the_title(self):
        assert "16-09-2026" not in RRBSecunderabadScraper._parse(self.LI)[0]["title"]

    def test_a_space_in_the_query_string_is_escaped(self):
        # The portal writes `category=Application (Special Notice)` raw.
        url = RRBSecunderabadScraper._parse(self.LI)[0]["url"]
        assert " " not in url
        assert url.endswith("category=Application%20(Special%20Notice)")

    def test_rows_without_a_date_are_not_notices(self):
        # The page is mostly navigation; the date span is what marks a notice.
        html = '<ul><li><a href="/getdata?loc=x">Contact Us and other links</a></li></ul>'
        assert RRBSecunderabadScraper._parse(html) == []

    def test_ignores_links_that_are_not_notices(self):
        html = ('<ul><li><a href="/about">Some long heading about the board</a>'
                '<span class="pub_date">(16-09-2026)</span></li></ul>')
        assert RRBSecunderabadScraper._parse(html) == []

    @pytest.mark.parametrize(
        "text,expected",
        [("(16-09-2026)", "2026-09-16"), ("(32-09-2026)", None), ("none", None), ("", None)],
    )
    def test_date_parsing(self, text, expected):
        assert rrb._iso(text) == expected

    def test_drops_notices_older_than_a_year(self):
        from datetime import date, timedelta
        fresh = (date.today() - timedelta(days=30)).isoformat()
        stale = (date.today() - timedelta(days=500)).isoformat()
        rows = [{"published": fresh}, {"published": stale}, {"published": None}]
        kept = RRBSecunderabadScraper._select(rows)
        assert {r["published"] for r in kept} == {fresh, None}

    def test_becomes_an_entry(self):
        e = RRBSecunderabadScraper()._to_entry(
            RRBSecunderabadScraper._parse(self.LI)[0]
        )
        assert e.department == "Railway Recruitment Board, Secunderabad"
        assert e.category == "naukri"
        assert e.published_date == "2026-09-16"
        assert "Centralised Employment Notice" in e.raw_text

    def test_any_board_is_one_line_of_configuration(self):
        # CENs are national, so the other twenty boards are deliberately not
        # registered — but nothing technical stands in the way.
        config = rrb.board_config("chandigarh", "Chandigarh")
        assert config.source_key == "rrb_chandigarh"
        assert config.list_url.endswith("/chandigarh")
        assert config.row_selector == RRBSecunderabadScraper.config.row_selector


class TestIBPSParsing:
    """IBPS wraps each row in the anchor and prints a real date column."""

    def _row(self, href: str, *cells: str) -> str:
        inner = "".join(
            f'<div class="detail-{n}-heading">{c}</div>'
            for n, c in zip(("first", "second", "third", "fourth"), cells)
        )
        return (f'<a href="{href}"><div class="detail-section">'
                f'<div class="detail-list">{inner}</div></div></a>')

    @staticmethod
    def _iso_ago(days: int) -> str:
        from datetime import date, timedelta
        return (date.today() - timedelta(days=days)).isoformat()

    # --- CRP updates --------------------------------------------------

    def test_reads_the_title_from_the_details_cell(self):
        html = self._row(
            "https://www.ibps.in/wp-content/uploads/Corrigendum-CRP-RRBs-XV-1.pdf",
            "15 Sep 26", "Corrigendum dated 15.09.2026 in connection with CRP-RRBs-XV",
        )
        rows = IBPSUpdatesScraper._parse(html)
        assert len(rows) == 1
        assert rows[0]["title"] == (
            "Corrigendum dated 15.09.2026 in connection with CRP-RRBs-XV"
        )
        # The date column must not end up in the title.
        assert "15 Sep 26" not in rows[0]["title"]

    def test_reads_the_date_from_the_date_cell(self):
        html = self._row("/x.pdf", "15 Sep 26", "Notification for CRP-RRB-XV 2026 season")
        assert IBPSUpdatesScraper._parse(html)[0]["published"] == "2026-09-15"

    def test_a_two_digit_year_is_this_century(self):
        # "%Y" reads "26" as the year 26 AD, which would date the notice to the
        # Roman empire and silently drop it as too old.
        assert ibps._iso("15 Sep 26") == "2026-09-15"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("15 Sep 26", "2026-09-15"),
            ("15-Sep-2026", "2026-09-15"),
            ("08-Sep-26", "2026-09-08"),
            ("15 September 2026", "2026-09-15"),
            ("no date at all", None),
            ("", None),
        ],
    )
    def test_date_formats(self, text, expected):
        assert ibps._iso(text) == expected

    def test_keeps_rows_that_are_not_pdfs(self):
        # Several updates link to a CRP landing page rather than a document.
        html = self._row("https://www.ibps.in/index.php/rural-bank-xv/",
                         "01 Sep 26", "Apply Online for CRP under CRP-RRBs-XV")
        assert len(IBPSUpdatesScraper._parse(html)) == 1

    def test_two_notices_may_share_one_landing_page(self):
        html = (self._row("/index.php/rural-bank-xv/", "01 Sep 26",
                          "Apply Online for Common Recruitment under CRP-RRBs-XV")
                + self._row("/index.php/rural-bank-xv/", "01 Sep 26",
                            "Notification for CRP-RRB-XV and related matters"))
        assert len(IBPSUpdatesScraper._parse(html)) == 2

    def test_drops_stale_updates(self):
        rows = [{"published": self._iso_ago(20)}, {"published": self._iso_ago(500)}]
        assert IBPSUpdatesScraper._select(rows) == [rows[0]]

    def test_an_update_becomes_an_entry(self):
        html = self._row("https://www.ibps.in/wp-content/uploads/cal.pdf",
                         "16 Jan 26", "Tentative Calendar of CRP Online Examinations")
        e = IBPSUpdatesScraper()._to_entry(IBPSUpdatesScraper._parse(html)[0])
        assert e.department == "Institute of Banking Personnel Selection"
        assert e.category == "naukri"
        assert e.published_date == "2026-01-16"
        assert "Common Recruitment Process" in e.raw_text

    # --- recruitment --------------------------------------------------

    def test_recruitment_title_keeps_the_organisation(self):
        # "Recruitment of Human Resource" alone says nothing about who is
        # hiring, and BOB is not guessable from the URL.
        html = self._row("https://ibpsreg.ibps.in/bonwejul26/", "BOB",
                         "Recruitment of Human Resource", "04-Sep-26 24-Sep-26",
                         "04-Sep-26 24-Sep-26")
        rows = IBPSRecruitmentScraper._parse(html)
        assert rows[0]["title"] == "BOB — Recruitment of Human Resource"

    def test_recruitment_reads_the_window(self):
        html = self._row("https://ibpsreg.ibps.in/mecljul26/", "MECL",
                         "Recruitment of Non-Executive Posts",
                         "12-Sep-2026 11-Oct-2026", "12-Sep-2026 11-Oct-2026")
        row = IBPSRecruitmentScraper._parse(html)[0]
        assert row["published"] == "2026-09-12"
        assert row["deadline"] == "2026-10-11", "the close date is the deadline"

    def test_recruitment_keeps_open_and_recently_closed(self):
        rows = [{"deadline": self._iso_ago(-10)}, {"deadline": self._iso_ago(5)}]
        assert IBPSRecruitmentScraper._select(rows) == rows

    def test_recruitment_drops_long_closed(self):
        rows = [{"deadline": self._iso_ago(200)}]
        assert IBPSRecruitmentScraper._select(rows) == []

    def test_recruitment_entry_carries_the_deadline(self):
        html = self._row("https://ibpsreg.ibps.in/rcfaojul26/", "RCF",
                         "Recruitment of Assistant Officer (Secretarial) E0 Grade",
                         "10-Sep-2026 26-Sep-2026", "10-Sep-2026 26-Sep-2026")
        e = IBPSRecruitmentScraper()._to_entry(IBPSRecruitmentScraper._parse(html)[0])
        assert e.deadline == "2026-09-26"
        assert "2026-09-26" in e.raw_text
        assert e.original_url.startswith("https://ibpsreg.ibps.in/")

    # --- shared -------------------------------------------------------

    def test_both_sources_repair_the_certificate_chain(self):
        # ibps.in omits an intermediate; a plain fetch fails outright.
        assert IBPSUpdatesScraper.config.fetch == "aia_tls"
        assert IBPSRecruitmentScraper.config.fetch == "aia_tls"

    def test_a_header_row_is_not_a_notice(self):
        # The "Date / Details" header sits in a sibling class and carries no
        # anchor, but guard the shape anyway.
        assert IBPSUpdatesScraper._parse(
            '<div class="detail-section-header"><div class="detail-list">'
            '<div class="detail-first-heading">Date</div>'
            '<div class="detail-second-heading">Details</div></div></div>'
        ) == []


class _Board(NoticeBoardScraper):
    """A notice board that does not exist, so these tests describe the base
    class rather than any one portal's quirks."""

    config = NoticeBoard(
        source_key="fake",
        list_url="https://board.example.gov.in/notices/archive",
        department="Example Directorate",
        row_selector="table tr",
        title_strip=("Read More",),
        date_in_url=r"(\d{8})\.pdf",
        date_format="%Y%m%d",
        context="The Example Directorate issues these notices.",
    )


class _WrappedBoard(_Board):
    """A board whose anchor wraps the row, as IBPS's does."""

    config = replace(_Board.config, row_selector="a.notice")

    @classmethod
    def _title(cls, row, link) -> str:
        return " ".join(row.find("div").get_text(" ", strip=True).split())


def _row(cells: str, href: str = "/files/20260301.pdf", text: str = "Read More") -> str:
    return f"<tr>{cells}<td><a href='{href}'>{text}</a></td></tr>"


def _table(*rows: str) -> str:
    return "<table>" + "".join(rows) + "</table>"


class TestNoticeBoardExtraction:
    """The generic row extractor, independent of any single site."""

    def test_takes_the_title_from_the_row_and_the_href_from_the_link(self):
        rows = _Board._parse(_table(_row("<td>Recruitment of Junior Engineers 2026</td>")))
        assert rows == [{
            "title": "Recruitment of Junior Engineers 2026",
            "url": "https://board.example.gov.in/files/20260301.pdf",
        }]

    def test_link_text_never_reaches_the_title(self):
        # The whole reason extraction is row-based: anchor text is boilerplate.
        rows = _Board._parse(_table(_row("<td>Recruitment of Junior Engineers 2026</td>")))
        assert "Read More" not in rows[0]["title"]

    def test_strips_a_leading_row_index(self):
        rows = _Board._parse(_table(_row("<td>17.</td><td>Recruitment of Junior Engineers</td>")))
        assert rows[0]["title"] == "Recruitment of Junior Engineers"

    def test_resolves_relative_and_absolute_hrefs(self):
        rows = _Board._parse(_table(
            _row("<td>Notice about the annual recruitment drive</td>", "/a/20260101.pdf"),
            _row("<td>Another notice about the recruitment drive</td>",
                 "https://cdn.example.gov.in/b/20260102.pdf"),
        ))
        assert [r["url"] for r in rows] == [
            "https://board.example.gov.in/a/20260101.pdf",
            "https://cdn.example.gov.in/b/20260102.pdf",
        ]

    def test_ignores_rows_whose_links_do_not_match_the_pattern(self):
        html = _table(
            _row("<td>A perfectly good looking heading</td>", "/about-us"),
            _row("<td>Recruitment of Junior Engineers 2026</td>"),
        )
        assert len(_Board._parse(html)) == 1

    def test_min_title_len_excludes_navigation_rows(self):
        # A sidebar menu is rows with links to PDFs too — length is what
        # separates "Downloads" from a real notice.
        html = _table(
            _row("<td>Downloads</td>", "/files/20260101.pdf", text="PDF"),
            _row("<td>RTI</td>", "/files/20260102.pdf", text="PDF"),
            _row("<td>Recruitment of Junior Engineers 2026</td>", "/files/20260103.pdf"),
        )
        rows = _Board._parse(html)
        assert [r["title"] for r in rows] == ["Recruitment of Junior Engineers 2026"]

    def test_a_row_that_is_only_a_link_yields_no_title(self):
        # Removing the link text leaves nothing behind, so the row drops out.
        assert _Board._parse(_table(_row("", text="Annual Report 2026 Download"))) == []

    def test_collapses_rows_that_repeat_verbatim(self):
        # Portals often print the same notice twice, in a "latest" strip and
        # again in the full list.
        row = _row("<td>Recruitment of Junior Engineers 2026</td>", "/files/20260301.pdf")
        rows = _Board._parse(_table(row, row))
        assert len(rows) == 1
        assert rows[0]["title"] == "Recruitment of Junior Engineers 2026"

    def test_keeps_two_notices_that_share_a_landing_page(self):
        # IBPS lists "Notification for CRP-RRB-XV" and "Apply Online for
        # CRP-RRBs-XV" as separate notices pointing at one page. Keying the
        # dedup on the URL alone silently dropped the second.
        class AnyLink(_Board):
            config = replace(_Board.config, link_pattern=r".")

        html = _table(
            _row("<td>Notification for the Junior Engineer exam</td>", "/exam-page/"),
            _row("<td>Apply online for the Junior Engineer exam</td>", "/exam-page/"),
        )
        rows = AnyLink._parse(html)
        assert [r["title"] for r in rows] == [
            "Notification for the Junior Engineer exam",
            "Apply online for the Junior Engineer exam",
        ]

    def test_the_row_itself_may_be_the_link(self):
        # IBPS wraps each row in the anchor, so find_all() on the row returns
        # the cells and never the link.
        html = ("<a class='notice' href='/files/20260301.pdf'>"
                "<div>Recruitment of Junior Engineers 2026</div></a>")
        rows = _WrappedBoard._parse(html)
        assert rows[0]["url"].endswith("/files/20260301.pdf")
        assert rows[0]["title"] == "Recruitment of Junior Engineers 2026"

    def test_a_wrapping_anchor_still_honours_the_link_pattern(self):
        html = "<a class='notice' href='/about-us'><div>Some long heading here</div></a>"
        assert _WrappedBoard._parse(html) == []

    def test_a_wrapping_anchor_defeats_the_default_title(self):
        # Row text minus link text leaves nothing when they are the same
        # element, so a board shaped like this has to override _title. Worth
        # pinning down: the failure is an empty title, not an exception.
        class NoOverride(_Board):
            config = replace(_Board.config, row_selector="a.notice")

        html = ("<a class='notice' href='/files/20260301.pdf'>"
                "<div>Recruitment of Junior Engineers 2026</div></a>")
        assert NoOverride._parse(html) == []

    def test_row_selector_is_not_limited_to_tables(self):
        class ListBoard(_Board):
            config = replace(_Board.config, row_selector="ul.notices li")

        html = ("<ul class='notices'><li>Recruitment of Junior Engineers 2026"
                "<a href='/files/20260301.pdf'>Read More</a></li></ul>")
        assert len(ListBoard._parse(html)) == 1

    # --- dates --------------------------------------------------------

    def test_reads_the_date_out_of_the_url(self):
        assert _Board._date_from_url("https://x.gov.in/files/20260301.pdf") == "2026-03-01"

    def test_no_date_pattern_configured_means_no_date(self):
        class Undated(_Board):
            config = replace(_Board.config, date_in_url=None)

        assert Undated._date_from_url("https://x.gov.in/files/20260301.pdf") is None

    def test_unmatched_filename_yields_no_date(self):
        assert _Board._date_from_url("https://x.gov.in/files/brochure.pdf") is None

    def test_impossible_date_is_absent_rather_than_wrong(self):
        # Absent beats wrong: urgency badges are computed from these.
        assert _Board._date_from_url("https://x.gov.in/files/20261340.pdf") is None

    def test_date_format_is_configurable(self):
        class DayFirst(_Board):
            config = replace(_Board.config, date_in_url=r"/(\d{8})_", date_format="%d%m%Y")

        assert DayFirst._date_from_url("https://x.gov.in/d/16092026_adv.pdf") == "2026-09-16"

    # --- entry construction -------------------------------------------

    def test_entry_carries_the_configured_identity_and_the_context_line(self):
        e = _Board()._to_entry(_Board._parse(_table(
            _row("<td>Recruitment of Junior Engineers 2026</td>")
        ))[0])
        assert e.department == "Example Directorate"
        assert e.category == "naukri"
        assert e.state == "ALL"
        assert e.published_date == "2026-03-01"
        assert e.pdf_url == e.original_url
        # The AI layer gets the title, the date and a line saying who issued it.
        assert "Recruitment of Junior Engineers 2026" in e.raw_text
        assert "2026-03-01" in e.raw_text
        assert "The Example Directorate issues these notices." in e.raw_text

    def test_a_date_column_beats_the_url_pattern(self):
        # A board that prints its own dates knows better than a filename.
        e = _Board()._to_entry({
            "title": "Recruitment of Junior Engineers 2026",
            "url": "https://x.gov.in/files/20260301.pdf",
            "published": "2026-05-20",
        })
        assert e.published_date == "2026-05-20"
        assert "2026-05-20" in e.raw_text

    def test_a_deadline_from_the_row_reaches_the_entry(self):
        e = _Board()._to_entry({
            "title": "Recruitment of Junior Engineers 2026",
            "url": "https://x.gov.in/apply/",
            "deadline": "2026-10-06",
        })
        assert e.deadline == "2026-10-06"
        assert "2026-10-06" in e.raw_text

    def test_undated_entry_omits_the_published_line(self):
        e = _Board()._to_entry({"title": "A notice with no date in its URL",
                                "url": "https://x.gov.in/files/brochure.pdf"})
        assert e.published_date is None
        assert "Published:" not in e.raw_text

    # --- scrape() -----------------------------------------------------

    async def test_zero_rows_raises_rather_than_reporting_success(self):
        # The layout-changed signal. Returning [] would look like a quiet day.
        class Empty(_Board):
            async def _fetch_list(self):
                return "<html><body><p>Site under maintenance</p></body></html>"

        with pytest.raises(ScraperError, match="no rows parsed"):
            await Empty().scrape()

    async def test_scrape_applies_the_select_hook(self):
        class TopTwo(_Board):
            async def _fetch_list(self):
                return _table(*(
                    _row(f"<td>Recruitment notice number {n} of 2026</td>",
                         f"/files/2026030{n}.pdf")
                    for n in (1, 2, 3, 4)
                ))

            @classmethod
            def _select(cls, rows):
                return rows[:2]

        entries = await TopTwo().scrape()
        assert len(entries) == 2
        assert entries[0].published_date == "2026-03-01"

    async def test_to_entry_returning_none_drops_the_row(self):
        class Picky(_Board):
            async def _fetch_list(self):
                return _table(
                    _row("<td>Recruitment notice worth keeping 2026</td>", "/files/20260301.pdf"),
                    _row("<td>Recruitment notice to discard 2026</td>", "/files/20260302.pdf"),
                )

            def _to_entry(self, row):
                return None if "discard" in row["title"] else super()._to_entry(row)

        entries = await Picky().scrape()
        assert [e.published_date for e in entries] == ["2026-03-01"]

    def test_source_key_comes_from_the_config(self):
        assert _Board().source_key == "fake"


class TestFetchMode:
    """How a board opens its connection. Neither mode may skip verification."""

    def test_defaults_to_plain(self):
        assert _Board.config.fetch == "plain"

    def test_a_typo_is_rejected_at_definition_time(self):
        # `aia-tls` would otherwise fall through to a plain connection and the
        # source would just look broken, or worse, quietly unverified.
        with pytest.raises(ValueError, match="unknown fetch mode"):
            replace(_Board.config, fetch="aia-tls")

    def test_aia_tls_is_accepted(self):
        assert replace(_Board.config, fetch="aia_tls").fetch == "aia_tls"

    async def test_aia_mode_asks_for_the_repaired_client(self, monkeypatch):
        class Repaired(_Board):
            config = replace(_Board.config, fetch="aia_tls")

        asked: list[str] = []

        async def fake_client_aia(self, url):
            asked.append(url)
            return _StubClient("<table></table>")

        monkeypatch.setattr(Repaired, "client_aia", fake_client_aia)
        monkeypatch.setattr(Repaired, "fetch", _stub_fetch)

        await Repaired()._fetch_list()
        assert asked == [_Board.config.list_url]

    async def test_plain_mode_does_not(self, monkeypatch):
        called = False

        async def fake_client_aia(self, url):
            nonlocal called
            called = True
            raise AssertionError("plain mode must not build an AIA client")

        monkeypatch.setattr(_Board, "client_aia", fake_client_aia)
        monkeypatch.setattr(_Board, "client", staticmethod(lambda **kw: _StubClient("<table></table>")))
        monkeypatch.setattr(_Board, "fetch", _stub_fetch)

        await _Board()._fetch_list()
        assert called is False

    async def test_an_unrepairable_chain_raises_instead_of_downgrading(self, monkeypatch):
        # ssl_context_for returns None when the certificate names no CA Issuers
        # URI — an expired certificate, or a hostname mismatch. There is nothing
        # to repair, and continuing unverified is never the answer.
        monkeypatch.setattr("app.scrapers.base.ssl_context_for", lambda host: None)

        with pytest.raises(ScraperError, match="Refusing to continue unverified"):
            await _Board().client_aia("https://broken.example.gov.in/notices")

    async def test_a_repaired_context_is_handed_to_httpx(self, monkeypatch):
        import ssl

        context = ssl.create_default_context()
        monkeypatch.setattr("app.scrapers.base.ssl_context_for", lambda host: context)

        client = await _Board().client_aia("https://portal.example.gov.in/notices")
        async with client:
            assert client is not None


class _StubClient:
    """Stands in for an httpx.AsyncClient in the fetch-mode tests."""

    def __init__(self, body: str):
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def _stub_fetch(self, client, url, **kwargs):
    return httpx.Response(200, text=client.body, request=httpx.Request("GET", url))

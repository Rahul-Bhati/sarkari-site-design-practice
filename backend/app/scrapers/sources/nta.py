"""National Testing Agency — https://www.nta.ac.in

NTA runs JEE, NEET, UGC-NET, CUET and CMAT, so its notice board is the widest
single source of exam news we have. `/NoticeBoardArchive` carries the full
history — around 1,900 rows — as a plain table, no WAF and no JavaScript.

Extraction is row-based, which `NoticeBoardScraper` handles: every link on the
page reads "Read More", so the title has to come from the containing `<tr>`.

    <tr> <td>4</td>
         <td>Publication of the Examination Calendar ... - reg.</td>
         <td><a href="/Download/Notice/Notice_20260916195948.pdf">Read More</a></td>
    </tr>

An anchor-driven scraper gets 1,891 entries all titled "Read More".

Dates come from the filename rather than the page: NTA stamps every notice
`Notice_YYYYMMDDHHMMSS.pdf`, which is exact, whereas the table shows no date at
all.

The one thing NTA needs beyond the shared config is the age cap below.
"""

from __future__ import annotations

from datetime import date

from app.scrapers.base_notice import NoticeBoard, NoticeBoardScraper

#: The archive goes back years. Older notices are almost all expired, and
#: summarising the lot would cost ~1,900 AI calls to bury the feed in dead
#: entries.
MAX_AGE_DAYS = 365


class NTAScraper(NoticeBoardScraper):
    config = NoticeBoard(
        source_key="nta",
        list_url="https://www.nta.ac.in/NoticeBoardArchive",
        department="National Testing Agency",
        row_selector="table tr",
        # Current files are `Notice_YYYYMMDDHHMMSS.pdf`; everything before
        # roughly 2020 is a bare `YYYYMMDDHHMMSS.pdf`. Both must be matched —
        # treating the old form as undated let 64 notices from 2019 straight
        # past the age cap.
        date_in_url=r"(?:Notice_)?(\d{14})\.pdf",
        date_format="%Y%m%d%H%M%S",
        #: Link text carries no information and must come out of the title.
        title_strip=("Read More",),
        min_title_len=15,
        # The board mixes exam notices with NTA's own procurement and hiring
        # ("NOTICE INVITING QUOTATION FOR EMPANELMENT OF HOTELS", "EoI for
        # Translation Reviewers"), so this is a hint only.
        category="naukri",
        context=(
            "The National Testing Agency conducts entrance examinations "
            "including JEE (Main), NEET, UGC-NET, CUET and CMAT."
        ),
    )

    @classmethod
    def _select(cls, rows: list[dict]) -> list[dict]:
        return cls._within_age_cap(rows)

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

    @staticmethod
    def _too_old(iso: str | None) -> bool:
        if not iso:
            return False
        try:
            return (date.today() - date.fromisoformat(iso)).days > MAX_AGE_DAYS
        except ValueError:
            return False

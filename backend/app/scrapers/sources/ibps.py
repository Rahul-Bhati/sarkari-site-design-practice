"""Institute of Banking Personnel Selection — https://www.ibps.in

IBPS runs the common recruitment processes that fill most public-sector bank
jobs in India: CRP PO/MT, CRP Clerk (CSA), CRP RRB and CRP Specialist Officers.
It also administers recruitment on behalf of other public bodies.

The host omits an intermediate certificate, so both scrapers here set
`fetch="aia_tls"`. See `utils/tls.py` — verification stays on.

Two listing pages, two sources, because they answer different questions:

  * `/crp-updates/` — IBPS's own exam notices: notifications, corrigenda,
    updated vacancy tables, the annual exam calendar. What someone means when
    they search "IBPS PO notification".
  * `/recruitment/` — live recruitment IBPS is running for other bodies (Bank
    of Baroda, MECL, RCF, PFRDA...), each with an open and close date.

Both pages are built from the same markup, which is unusual for a government
portal in being genuinely tidy:

    <a href="...">                            <- the anchor wraps the row
      <div class="detail-section">
        <div class="detail-list">
          <div class="detail-first-heading">15 Sep 26</div>
          <div class="detail-second-heading">Corrigendum ... CRP-RRBs-XV</div>

Two consequences for `NoticeBoardScraper`:

  * The row *is* the anchor, so the default title (row text minus link text)
    comes out empty. Both scrapers read the cells directly instead, which is
    better than what NTA and SBI have to do — the date is a real column rather
    than something recovered from a filename.
  * Links are not all PDFs. Several point at a landing page, and two different
    notices can point at the *same* landing page, which is why row identity is
    the title and URL together rather than the URL alone.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.scrapers.base_notice import NoticeBoard, NoticeBoardScraper

BASE = "https://www.ibps.in"

#: Every row links somewhere — a PDF, a CRP landing page, or the registration
#: portal — and all three are worth carrying, so any href qualifies.
ANY_LINK = r"."

#: "15 Sep 26" on the updates page; "15-Sep-2026" or "08-Sep-26" on the
#: recruitment page. IBPS is inconsistent about the year even within one table,
#: so separators are normalised and both year widths are tried.
#:
#: Two-digit first, and that ordering is load-bearing: `%Y` happily reads "26"
#: as the year 26 AD, which would date a 2026 notice to the Roman empire and
#: quietly drop it as too old.
DATE_FORMATS = ("%d %b %y", "%d %b %Y", "%d %B %y", "%d %B %Y")
DATE_TOKEN = re.compile(r"\d{1,2}[- ][A-Za-z]{3,}[- ]\d{2,4}")

#: Both pages are short and complete, so age is filtered per row rather than by
#: position the way NTA's thousand-row archive needs.
MAX_AGE_DAYS = 365
#: Keep a recruitment for a month after it closes, so something that ended last
#: week does not vanish the day it expires.
CLOSED_GRACE_DAYS = 30


def _iso(text: str | None) -> str | None:
    """First date in `text`, ISO formatted."""
    if not text:
        return None
    match = DATE_TOKEN.search(text)
    if not match:
        return None
    token = match.group(0).replace("-", " ")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _cells(row) -> list[str]:
    """The row's visible cells, in order."""
    return [
        " ".join(cell.get_text(" ", strip=True).split())
        for cell in row.select("div[class*=heading]")
    ]


def _not_too_old(iso: str | None, days: int = MAX_AGE_DAYS) -> bool:
    if not iso:
        # Undated rows are rare on these pages and cheap to carry; the AI layer
        # reads the text and a human reviews anything it is unsure about.
        return True
    try:
        return (date.today() - date.fromisoformat(iso)).days <= days
    except ValueError:
        return True


class IBPSUpdatesScraper(NoticeBoardScraper):
    """IBPS's own CRP notices — notifications, corrigenda, vacancy updates."""

    config = NoticeBoard(
        source_key="ibps_crp",
        list_url=f"{BASE}/index.php/crp-updates/",
        department="Institute of Banking Personnel Selection",
        row_selector="a:has(.detail-section)",
        link_pattern=ANY_LINK,
        fetch="aia_tls",
        min_title_len=15,
        category="naukri",
        context=(
            "The Institute of Banking Personnel Selection runs the Common "
            "Recruitment Process (CRP) for probationary officers, clerks, "
            "specialist officers and regional rural bank staff across India's "
            "public sector banks."
        ),
    )

    @classmethod
    def _title(cls, row, link) -> str:
        cells = _cells(row)
        # [date, details] — the first cell is the date column.
        return cells[1] if len(cells) > 1 else ""

    @classmethod
    def _extra(cls, row, link) -> dict:
        cells = _cells(row)
        return {"published": _iso(cells[0]) if cells else None}

    @classmethod
    def _select(cls, rows: list[dict]) -> list[dict]:
        return [r for r in rows if _not_too_old(r.get("published"))]


class IBPSRecruitmentScraper(NoticeBoardScraper):
    """Recruitment IBPS administers for other public bodies, with deadlines."""

    config = NoticeBoard(
        source_key="ibps_recruitment",
        list_url=f"{BASE}/index.php/recruitment/",
        department="Institute of Banking Personnel Selection",
        row_selector="a:has(.detail-section)",
        link_pattern=ANY_LINK,
        fetch="aia_tls",
        min_title_len=15,
        category="naukri",
        context=(
            "The Institute of Banking Personnel Selection conducts this "
            "recruitment on behalf of the organisation named in the title. "
            "Applications are submitted on the IBPS registration portal."
        ),
    )

    @classmethod
    def _title(cls, row, link) -> str:
        cells = _cells(row)
        # [organisation, details, window, window] — the window is repeated for
        # the mobile layout. The organisation is an abbreviation ("MECL",
        # "UIICL") and means nothing on its own, so it is kept with the post.
        if len(cells) < 2:
            return ""
        organisation, details = cells[0], cells[1]
        return f"{organisation} — {details}" if organisation else details

    @classmethod
    def _extra(cls, row, link) -> dict:
        cells = _cells(row)
        window = cells[2] if len(cells) > 2 else ""
        dates = DATE_TOKEN.findall(window)
        return {
            "published": _iso(dates[0]) if dates else None,
            # The second date is when registration closes, which is the only
            # deadline that matters to someone reading the feed.
            "deadline": _iso(dates[1]) if len(dates) > 1 else None,
        }

    @classmethod
    def _select(cls, rows: list[dict]) -> list[dict]:
        """A recruitment nobody can still apply for is noise, not news."""
        kept = []
        for row in rows:
            if row.get("deadline"):
                if _not_too_old(row["deadline"], CLOSED_GRACE_DAYS):
                    kept.append(row)
            elif _not_too_old(row.get("published")):
                kept.append(row)
        return kept

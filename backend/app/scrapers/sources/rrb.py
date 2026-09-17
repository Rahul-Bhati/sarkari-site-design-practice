"""Railway Recruitment Boards — https://rrb.indianrailways.gov.in/<board>

The 21 RRBs recruit for Indian Railways, one of the largest employers in the
country. Until recently each board ran its own site with its own markup, which
is why an earlier survey concluded there was no shared structure to exploit.

That has changed. The boards are migrating onto one common portal — RRB
Secunderabad published a migration notice on 2026-08-18 pointing at
`rrb.indianrailways.gov.in/secunderabad`, and `rrbcdg.gov.in` already redirects
to the Chandigarh path. Secunderabad, Chandigarh and Mumbai were checked and
serve byte-for-byte the same layout, so one config covers any board:

    <li>
      <a href="/getdata?loc=secunderabad&cenum=03/2026&category=Application (Special Notice)">
        <strong>(03/2026)</strong>              <- the CEN number
        Application (Special Notice)            <- the category
        <span class="pub_date">(16-09-2026)</span>
      </a>
    </li>

The anchor fills the row, so the default row-text title comes out empty and
`_title` is overridden — the same shape IBPS has.

**Only Secunderabad is registered.** CENs are national: "CEN 03/2026" appears on
all 21 boards with the same text, so adding the other twenty would put twenty
copies of every notice in the feed. `board_config()` makes each a one-line
addition if a regional split is ever wanted; that is a product decision, not a
technical one.

A caution worth recording: the old per-board sites are now frozen. RRB
Secunderabad's own site still serves 600 dated notices, but nothing newer than
its migration notice, so scraping it would import a dead archive. The live
content is here.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from app.scrapers.base_notice import NoticeBoard, NoticeBoardScraper

BASE = "https://rrb.indianrailways.gov.in"

#: "(16-09-2026)" in the pub_date span.
PUB_DATE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")

#: The portal carries roughly 200 notices per board spread over the year.
MAX_AGE_DAYS = 365

CONTEXT = (
    "Railway Recruitment Boards conduct recruitment for Indian Railways. A CEN "
    "(Centralised Employment Notice) number identifies one recruitment drive, "
    "and the same CEN is published by every regional board."
)


def _iso(text: str | None) -> str | None:
    if not text:
        return None
    m = PUB_DATE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime("-".join(m.groups()), "%d-%m-%Y").date().isoformat()
    except ValueError:
        return None


def board_config(board: str, name: str, state: str = "ALL") -> NoticeBoard:
    """A config for one regional board. `board` is the portal's path segment."""
    return NoticeBoard(
        source_key=f"rrb_{board}",
        list_url=f"{BASE}/{board}",
        department=f"Railway Recruitment Board, {name}",
        # Anchored on the date span: the page is mostly navigation, and a
        # notice is exactly the thing that carries a publication date.
        row_selector="li:has(span.pub_date)",
        link_pattern=r"/getdata",
        # "CEN 03/2026 — Exam Results" is the shortest realistic title.
        min_title_len=10,
        state=state,
        category="naukri",
        context=CONTEXT,
    )


class RRBScraper(NoticeBoardScraper):
    """Shared behaviour for any board on the common portal."""

    @classmethod
    def _title(cls, row, link) -> str:
        """CEN number and category, without the trailing publication date.

        The anchor is the whole row, so the inherited "row text minus link
        text" leaves nothing behind.
        """
        # A copy, so decomposing nodes cannot disturb the caller's tree.
        clone = BeautifulSoup(str(link), "lxml")
        for span in clone.select("span.pub_date"):
            span.decompose()

        cen = ""
        if (strong := clone.find("strong")) is not None:
            cen = " ".join(strong.get_text(" ", strip=True).split()).strip("() ")
            strong.decompose()

        category = " ".join(clone.get_text(" ", strip=True).split())
        if not category:
            return ""
        return f"CEN {cen} — {category}" if cen else category

    @classmethod
    def _extra(cls, row, link) -> dict:
        span = row.select_one("span.pub_date")
        return {"published": _iso(span.get_text(" ", strip=True) if span else None)}

    @classmethod
    def _select(cls, rows: list[dict]) -> list[dict]:
        today = date.today()
        kept = []
        for row in rows:
            published = row.get("published")
            if not published:
                kept.append(row)
                continue
            try:
                if (today - date.fromisoformat(published)).days <= MAX_AGE_DAYS:
                    kept.append(row)
            except ValueError:
                kept.append(row)
        return kept


class RRBSecunderabadScraper(RRBScraper):
    config = board_config("secunderabad", "Secunderabad")

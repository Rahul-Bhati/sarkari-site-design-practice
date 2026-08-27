"""Digest building and rendering — no database, no Resend."""

from __future__ import annotations

from datetime import date, timedelta

from app.models.notification import Digest, DigestGroup
from app.services.notifier import _deadline_badge, render_digest_html, render_digest_text


def make_digest(**kwargs) -> Digest:
    entries = [
        {
            "id": "e1",
            "title": "Road widening on Jaipur-Sikar highway",
            "summary_en": "Rajasthan PWD invited bids for a 12 km stretch.",
            "category": "tender",
            "state": "RJ",
            "department": "Public Works Department",
            "deadline": (date.today() + timedelta(days=3)).isoformat(),
        },
        {
            "id": "e2",
            "title": "SSC CGL 2026 notification",
            "summary_en": "8,326 vacancies for graduates.",
            "category": "naukri",
            "state": "ALL",
            "department": "Staff Selection Commission",
            "deadline": None,
        },
    ]
    defaults = dict(
        subscriber_id="s1",
        email="user@example.com",
        phone=None,
        frequency="weekly",
        groups=[
            DigestGroup("tender", [entries[0]]),
            DigestGroup("naukri", [entries[1]]),
        ],
        unsubscribe_token="tok" * 8,
    )
    return Digest(**{**defaults, **kwargs})


class TestDigestModel:
    def test_totals_and_ids(self):
        d = make_digest()
        assert d.total == 2
        assert d.entry_ids == ["e1", "e2"]
        assert d.states == {"RJ", "ALL"}

    def test_empty_digest(self):
        d = make_digest(groups=[])
        assert d.total == 0
        assert d.entry_ids == []


class TestDeadlineBadge:
    def test_red_within_a_week(self):
        badge = _deadline_badge((date.today() + timedelta(days=3)).isoformat())
        assert "#EF4444" in badge and "3 days left" in badge

    def test_yellow_within_a_month(self):
        assert "#F59E0B" in _deadline_badge((date.today() + timedelta(days=20)).isoformat())

    def test_green_beyond_a_month(self):
        assert "#10B981" in _deadline_badge((date.today() + timedelta(days=60)).isoformat())

    def test_today_reads_as_today(self):
        assert "Today" in _deadline_badge(date.today().isoformat())

    def test_past_and_missing_deadlines_render_nothing(self):
        assert _deadline_badge((date.today() - timedelta(days=1)).isoformat()) == ""
        assert _deadline_badge(None) == ""
        assert _deadline_badge("not-a-date") == ""


class TestRendering:
    def test_html_contains_entries_and_unsubscribe(self):
        html = render_digest_html(make_digest())
        assert "Jaipur-Sikar" in html
        assert "SSC CGL 2026" in html
        assert "unsubscribe" in html.lower()
        assert "Tenders" in html and "Naukri" in html

    def test_html_escapes_untrusted_titles(self):
        d = make_digest()
        d.groups[0].entries[0]["title"] = "<script>alert('x')</script>"
        html = render_digest_html(d)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_text_version_lists_links(self):
        text = render_digest_text(make_digest())
        assert "/entry/e1" in text
        assert "Unsubscribe:" in text

    def test_daily_and_weekly_headings_differ(self):
        assert "Daily Government Update" in render_digest_html(make_digest(frequency="daily"))
        assert "Weekly Government Update" in render_digest_html(make_digest(frequency="weekly"))

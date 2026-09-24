"""A source is stale when it keeps failing or its last success is too old."""

from datetime import datetime, timedelta, timezone

from app.services.freshness import source_staleness, stale_sources

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def source(**kwargs):
    base = {
        "scraper_key": "nta",
        "is_active": True,
        "consecutive_failures": 0,
        "frequency_minutes": 60,
        "last_success_at": (NOW - timedelta(minutes=30)).isoformat(),
        "last_run_at": (NOW - timedelta(minutes=30)).isoformat(),
    }
    return {**base, **kwargs}


class TestSourceStaleness:
    def test_three_failures_are_stale(self):
        assert source_staleness(source(consecutive_failures=3), NOW) == "3 consecutive failures"

    def test_a_recent_success_is_fresh(self):
        assert source_staleness(source(consecutive_failures=1), NOW) is None

    def test_a_success_older_than_three_intervals_is_stale(self):
        old = (NOW - timedelta(minutes=60 * 3 + 1)).isoformat()
        assert (
            source_staleness(source(last_success_at=old), NOW)
            == "last success is older than 3 intervals"
        )

    def test_a_run_that_never_succeeded_is_stale(self):
        assert source_staleness(source(last_success_at=None), NOW) == "no successful run"

    def test_a_source_that_has_never_run_is_not_an_alarm(self):
        assert source_staleness(source(last_success_at=None, last_run_at=None), NOW) is None

    def test_an_inactive_source_is_not_an_alarm(self):
        row = source(is_active=False, consecutive_failures=9)
        assert source_staleness(row, NOW) is None

    def test_stale_sources_keeps_only_the_key_and_the_reason(self):
        rows = [
            source(scraper_key="nta", consecutive_failures=3),
            source(scraper_key="ssc"),
        ]
        assert stale_sources(rows, NOW) == [
            {"scraper_key": "nta", "reason": "3 consecutive failures"},
        ]

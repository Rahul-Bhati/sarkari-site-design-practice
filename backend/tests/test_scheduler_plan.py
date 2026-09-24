"""Which scrapers the scheduler should fire, decided from source rows."""

from app.services.scheduler import jobs_for_sources


class TestJobsForSources:
    def test_active_registered_source_uses_its_frequency(self):
        jobs = jobs_for_sources(
            [{"scraper_key": "nta", "frequency_minutes": 120, "is_active": True}],
            {"nta", "ssc"},
        )
        assert jobs == [("nta", 120)]

    def test_inactive_and_unknown_keys_are_dropped(self):
        jobs = jobs_for_sources(
            [
                {"scraper_key": "nta", "frequency_minutes": 60, "is_active": False},
                {"scraper_key": "not_a_scraper", "frequency_minutes": 60, "is_active": True},
                {"scraper_key": "ssc", "frequency_minutes": None, "is_active": True},
            ],
            {"nta", "ssc"},
        )
        assert jobs == [("ssc", 60)]

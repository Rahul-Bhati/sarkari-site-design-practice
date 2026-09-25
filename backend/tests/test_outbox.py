"""Digest planning — one shared pool, no database, no Resend."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.services.outbox import (
    MAX_ENTRIES_PER_DIGEST,
    MAX_POOL_DAYS,
    PlannedDigest,
    entries_for,
    plan_digests,
    pool_cutoff,
)

NOW = datetime(2026, 9, 25, 7, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 25)


def subscriber(**kwargs) -> dict:
    base = {
        "id": "s1",
        "email": "user@example.com",
        "frequency": "daily",
        "categories": [],
        "states": [],
        "keywords": [],
        "departments": [],
        "min_budget": None,
        "max_budget": None,
        "last_digest_at": (NOW - timedelta(hours=24)).isoformat(),
    }
    return {**base, **kwargs}


def entry(**kwargs) -> dict:
    base = {
        "id": "e1",
        "title": "SSC CGL 2026 notification",
        "summary_en": "8,326 vacancies for graduates.",
        "category": "naukri",
        "state": "ALL",
        "department": "Staff Selection Commission",
        "deadline": None,
        "budget_amount": None,
        "urgency": "low",
        "published_at": (NOW - timedelta(hours=1)).isoformat(),
    }
    return {**base, **kwargs}


class TestPoolCutoff:
    def test_the_oldest_subscriber_sets_the_window(self):
        subs = [
            subscriber(id="a", last_digest_at=(NOW - timedelta(hours=2)).isoformat()),
            subscriber(id="b", last_digest_at=(NOW - timedelta(hours=20)).isoformat()),
        ]
        assert pool_cutoff(subs, NOW) == NOW - timedelta(hours=20)

    def test_a_subscriber_who_never_got_one_falls_back_to_the_frequency(self):
        subs = [subscriber(last_digest_at=None, frequency="weekly")]
        assert pool_cutoff(subs, NOW) == NOW - timedelta(days=7)

    def test_a_dormant_subscriber_cannot_widen_the_pool_past_the_cap(self):
        """One subscriber who vanished for a year must not select the whole table."""
        subs = [subscriber(last_digest_at=(NOW - timedelta(days=400)).isoformat())]
        assert pool_cutoff(subs, NOW) == NOW - timedelta(days=MAX_POOL_DAYS)

    def test_no_subscribers_is_the_shortest_window(self):
        assert pool_cutoff([], NOW) == NOW - timedelta(days=1)


class TestEntriesFor:
    def test_keywords_are_applied_before_the_cap(self):
        """The bug this task exists to fix.

        The old digest let the database cut to 25 and then filtered by
        keyword in Python, so a subscriber tracking "railway" saw an empty
        digest on a day when a railway notice ranked 30th.
        """
        pool = [
            entry(
                id=f"e{i}",
                title="Assistant Professor recruitment",
                published_at=(NOW - timedelta(minutes=i)).isoformat(),
            )
            for i in range(30)
        ]
        pool.append(
            entry(
                id="wanted",
                title="Railway Recruitment Board technician posts",
                published_at=(NOW - timedelta(minutes=99)).isoformat(),
            )
        )

        picked = entries_for(subscriber(keywords=["railway"]), pool, NOW)

        assert [e["id"] for e in picked] == ["wanted"]

    def test_a_keyword_matches_the_summary_too(self):
        pool = [entry(title="Recruitment notice", summary_en="For Indian Railways staff.")]
        assert len(entries_for(subscriber(keywords=["railways"]), pool, NOW)) == 1

    def test_central_entries_reach_a_subscriber_who_picked_states(self):
        pool = [entry(id="central", state="ALL"), entry(id="mine", state="RJ"), entry(id="other", state="UP")]
        picked = entries_for(subscriber(states=["RJ"]), pool, NOW)
        assert {e["id"] for e in picked} == {"central", "mine"}

    def test_categories_filter(self):
        pool = [entry(id="job", category="naukri"), entry(id="bid", category="tender")]
        picked = entries_for(subscriber(categories=["tender"]), pool, NOW)
        assert [e["id"] for e in picked] == ["bid"]

    def test_departments_filter(self):
        pool = [entry(id="ssc"), entry(id="rrb", department="Railway Recruitment Board")]
        picked = entries_for(subscriber(departments=["Railway Recruitment Board"]), pool, NOW)
        assert [e["id"] for e in picked] == ["rrb"]

    def test_a_budget_bound_drops_an_entry_with_no_budget(self):
        """Postgres `budget_amount >= n` never matches NULL. In-memory must agree."""
        pool = [entry(id="unpriced", budget_amount=None), entry(id="priced", budget_amount=5_000_000)]
        picked = entries_for(subscriber(min_budget=1_000_000), pool, NOW)
        assert [e["id"] for e in picked] == ["priced"]

    def test_budget_bounds_are_inclusive(self):
        pool = [entry(id="floor", budget_amount=100), entry(id="ceiling", budget_amount=900)]
        picked = entries_for(subscriber(min_budget=100, max_budget=900), pool, NOW)
        assert {e["id"] for e in picked} == {"floor", "ceiling"}

    def test_urgency_orders_by_rank_not_alphabetically(self):
        """'critical' sorts above 'medium' — the Postgres enum order, not the string order."""
        stamp = (NOW - timedelta(minutes=5)).isoformat()
        pool = [
            entry(id="med", urgency="medium", published_at=stamp),
            entry(id="crit", urgency="critical", published_at=stamp),
            entry(id="low", urgency="low", published_at=stamp),
            entry(id="high", urgency="high", published_at=stamp),
        ]
        picked = entries_for(subscriber(), pool, NOW)
        assert [e["id"] for e in picked] == ["crit", "high", "med", "low"]

    def test_newest_first_within_one_urgency(self):
        pool = [
            entry(id="older", published_at=(NOW - timedelta(hours=5)).isoformat()),
            entry(id="newer", published_at=(NOW - timedelta(hours=1)).isoformat()),
        ]
        assert [e["id"] for e in entries_for(subscriber(), pool, NOW)] == ["newer", "older"]

    def test_the_subscribers_own_cutoff_still_applies_inside_the_shared_pool(self):
        """The pool is as wide as the oldest subscriber; each one sees only their slice."""
        pool = [
            entry(id="fresh", published_at=(NOW - timedelta(hours=2)).isoformat()),
            entry(id="already_sent", published_at=(NOW - timedelta(hours=10)).isoformat()),
        ]
        recent = subscriber(last_digest_at=(NOW - timedelta(hours=4)).isoformat())
        assert [e["id"] for e in entries_for(recent, pool, NOW)] == ["fresh"]

    def test_the_cap_holds(self):
        pool = [
            entry(id=f"e{i}", published_at=(NOW - timedelta(minutes=i)).isoformat())
            for i in range(MAX_ENTRIES_PER_DIGEST + 10)
        ]
        assert len(entries_for(subscriber(), pool, NOW)) == MAX_ENTRIES_PER_DIGEST


class TestPlanDigests:
    def test_one_row_per_subscriber_with_matches(self):
        pool = [entry(id="job", category="naukri"), entry(id="bid", category="tender")]
        subs = [
            subscriber(id="a", categories=["naukri"]),
            subscriber(id="b", categories=["tender"]),
        ]
        planned = plan_digests(subs, pool, TODAY, NOW)
        assert [(p.subscriber_id, p.entry_ids) for p in planned] == [
            ("a", ["job"]),
            ("b", ["bid"]),
        ]

    def test_a_subscriber_with_nothing_to_say_is_not_queued(self):
        """An empty digest is not an email. It must not reserve an outbox row."""
        pool = [entry(category="naukri")]
        planned = plan_digests([subscriber(categories=["auction"])], pool, TODAY, NOW)
        assert planned == []

    def test_an_empty_pool_plans_nothing(self):
        assert plan_digests([subscriber()], [], TODAY, NOW) == []

    def test_the_row_carries_the_outbox_key(self):
        planned = plan_digests([subscriber(id="s9")], [entry(id="x")], TODAY, NOW)
        row = planned[0].row()
        assert row["subscriber_id"] == "s9"
        assert row["channel"] == "email"
        assert row["digest_date"] == "2026-09-25"
        assert row["status"] == "pending"
        assert row["payload"] == {"entry_ids": ["x"], "frequency": "daily"}

    def test_the_channel_is_part_of_the_plan(self):
        planned = plan_digests([subscriber()], [entry()], TODAY, NOW, channel="whatsapp")
        assert planned[0].channel == "whatsapp"
        assert planned[0].row()["channel"] == "whatsapp"


class TestPlannedDigest:
    def test_two_plans_for_the_same_day_are_the_same_key(self):
        """The unique index is (subscriber_id, channel, digest_date)."""
        a = PlannedDigest("s1", "email", TODAY, ["e1"], "daily")
        b = PlannedDigest("s1", "email", TODAY, ["e2"], "daily")
        assert a.key == b.key

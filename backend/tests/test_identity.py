"""Notice identity: a repeat of the same URL updates, it does not insert."""

from app.scrapers.base import RawEntry
from app.scrapers.identity import StoredNotice, plan_persist


def entry(**kwargs) -> RawEntry:
    defaults = dict(
        title="Road work tender",
        raw_text="text",
        original_url="https://example.gov.in/t/1",
        category="tender",
        state="RJ",
        department="PWD",
        published_date="2026-03-01",
        deadline="2026-03-20",
        pdf_url="https://example.gov.in/t/1.pdf",
    )
    return RawEntry(**{**defaults, **kwargs})


def stored(**kwargs) -> StoredNotice:
    defaults = dict(
        id="row-1",
        original_url="https://example.gov.in/t/1",
        title="Road work tender",
        deadline="2026-03-20",
        published_date="2026-03-01",
        pdf_url="https://example.gov.in/t/1.pdf",
    )
    return StoredNotice(**{**defaults, **kwargs})


class TestPlanPersist:
    def test_new_url_is_an_insert(self):
        plan = plan_persist([("hash-a", entry())], [])
        assert len(plan.inserts) == 1
        assert plan.inserts[0][0] == "hash-a"
        assert plan.updates == []
        assert plan.duplicates == 0

    def test_same_facts_are_a_duplicate(self):
        plan = plan_persist([("hash-a", entry())], [stored()])
        assert plan.inserts == []
        assert plan.updates == []
        assert plan.duplicates == 1

    def test_new_deadline_updates_the_stored_row(self):
        plan = plan_persist(
            [("hash-b", entry(deadline="2026-04-01"))],
            [stored()],
        )
        assert plan.inserts == []
        assert plan.duplicates == 0
        assert plan.updates == [
            {"id": "row-1", "deadline": "2026-04-01"},
        ]

    def test_utm_and_trailing_slash_match_the_stored_url(self):
        incoming = entry(
            original_url="https://Example.gov.in/t/1/?utm_source=share",
        )
        plan = plan_persist(
            [("hash-c", incoming)],
            [stored(original_url="https://example.gov.in/t/1/")],
        )
        assert plan.inserts == []
        assert plan.updates == []
        assert plan.duplicates == 1

    def test_changed_title_is_included_in_the_update(self):
        plan = plan_persist(
            [("hash-d", entry(title="Road work tender — corrigendum"))],
            [stored()],
        )
        assert plan.updates == [
            {"id": "row-1", "title": "Road work tender — corrigendum"},
        ]

    def test_second_copy_in_the_same_batch_is_a_duplicate(self):
        plan = plan_persist(
            [("hash-a", entry()), ("hash-b", entry(deadline="2026-04-02"))],
            [],
        )
        assert len(plan.inserts) == 1
        assert plan.inserts[0][1].deadline == "2026-04-02"
        assert plan.duplicates == 1

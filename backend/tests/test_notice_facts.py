"""Notice text is kept only when the PDF actually contains it."""

from datetime import date

from app.services.follows import deadline_moved, reminder_due
from app.services.notice_facts import keep_supported_facts, whatsapp_text


class TestWhatsAppText:
    def test_includes_posts_when_we_have_a_count(self):
        text = whatsapp_text("SSC JE 2026", "2026-09-22", 120, "https://sarkarisaar.com/entry/1")
        assert text == (
            "SSC JE 2026\n"
            "Last date: 2026-09-22\n"
            "Posts: 120\n"
            "https://sarkarisaar.com/entry/1"
        )

    def test_omits_posts_when_the_count_is_unknown(self):
        text = whatsapp_text("PM Awas", None, None, "https://sarkarisaar.com/entry/2")
        assert "Posts:" not in text
        assert "Last date: not listed" in text
        assert text.endswith("https://sarkarisaar.com/entry/2")


class TestSupportedFacts:
    TEXT = "Posts: Junior Engineer. Vacancies: 1,204. Fee Rs 100. Age 18-27. Apply at ssc.gov.in."

    def test_keeps_a_vacancy_count_written_in_the_notice(self):
        kept = keep_supported_facts({"vacancies": 1204, "fee": "Rs 100", "age": "18-27"}, self.TEXT)
        assert kept["vacancies"] == 1204
        assert kept["fee"] == "Rs 100"
        assert kept["age"] == "18-27"

    def test_drops_a_count_the_notice_does_not_contain(self):
        kept = keep_supported_facts({"vacancies": 99999, "fee": "Rs 500"}, self.TEXT)
        assert "vacancies" not in kept
        assert "fee" not in kept

    def test_keeps_important_dates_written_in_the_notice(self):
        text = "Apply by 2026-10-07. Exam on 2026-12-01."
        kept = keep_supported_facts({"important_dates": "Apply by 2026-10-07"}, text)
        assert kept["important_dates"] == "Apply by 2026-10-07"

    def test_drops_important_dates_the_notice_does_not_contain(self):
        kept = keep_supported_facts({"important_dates": "Apply by 2026-10-07"}, "Last date to apply: 2026-10-07")
        assert "important_dates" not in kept


class TestReminders:
    def test_due_only_on_the_day_three_days_before(self):
        deadline = date(2026, 10, 7)
        assert reminder_due(deadline, date(2026, 10, 4), already_sent=False) is True
        assert reminder_due(deadline, date(2026, 10, 5), already_sent=False) is False
        assert reminder_due(deadline, date(2026, 10, 4), already_sent=True) is False

    def test_a_notice_without_a_deadline_is_never_due(self):
        assert reminder_due(None, date(2026, 10, 4), already_sent=False) is False

    def test_a_changed_deadline_is_a_move(self):
        assert deadline_moved(date(2026, 10, 7), date(2026, 10, 14)) is True
        assert deadline_moved(date(2026, 10, 7), date(2026, 10, 7)) is False
        assert deadline_moved(None, date(2026, 10, 7)) is False

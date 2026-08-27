"""API tests that don't need a live Supabase project."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import settings
from app.main import app
from app.models.user import Channel, Frequency, SubscribeRequest
from app.routers.entries import _csv, _shape

settings.scheduler_enabled = False
client = TestClient(app)


class TestHealth:
    def test_health_returns_ok(self):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_docs_are_served_outside_production(self):
        assert client.get("/docs").status_code == 200

    def test_root_describes_the_service(self):
        assert client.get("/").json()["service"] == "SarkariSaar API"


class TestAdminAuth:
    def test_admin_routes_reject_anonymous_callers(self):
        for path in ("/api/admin/entries/pending", "/api/admin/scraper-status", "/api/admin/pending-count"):
            assert client.get(path).status_code == 401, path

    def test_admin_scrape_rejects_anonymous_callers(self):
        assert client.post("/api/admin/scrape").status_code == 401

    def test_wrong_admin_key_is_rejected(self):
        settings.admin_api_key = "correct-key"
        res = client.get("/api/admin/pending-count", headers={"X-Admin-Key": "wrong-key"})
        assert res.status_code == 401

    def test_bookmarks_require_sign_in(self):
        assert client.get("/api/bookmarks").status_code == 401


class TestQueryParsing:
    def test_csv_filters_to_allowed_values(self):
        assert _csv("tender,naukri,banana", {"tender", "naukri"}) == ["tender", "naukri"]

    def test_csv_handles_empty_and_none(self):
        assert _csv(None) == []
        assert _csv("") == []
        assert _csv(" , ,") == []

    def test_csv_lowercases(self):
        assert _csv("TENDER") == ["tender"]


class TestResponseShaping:
    def test_strips_internal_fields(self):
        row = {
            "id": "1",
            "title": "T",
            "original_text": "a lot of raw scraped text",
            "content_hash": "abc",
            "search_vector": "'road':1",
            "sources": {"id": 1, "name": "PIB", "url": "https://pib.gov.in"},
        }
        shaped = _shape(row)
        assert "original_text" not in shaped
        assert "content_hash" not in shaped
        assert "search_vector" not in shaped
        assert shaped["source"]["name"] == "PIB"

    def test_does_not_mutate_the_input_row(self):
        row = {"id": "1", "original_text": "raw", "sources": None}
        _shape(row)
        assert "original_text" in row


class TestValidation:
    def test_entries_rejects_oversized_limit(self):
        assert client.get("/api/entries?limit=500").status_code == 422

    def test_entries_rejects_page_zero(self):
        assert client.get("/api/entries?page=0").status_code == 422

    def test_subscribe_rejects_bad_email(self):
        res = client.post("/api/subscribe", json={"email": "not-an-email"})
        assert res.status_code == 422

    def test_subscribe_rejects_empty_body(self):
        res = client.post("/api/subscribe", json={})
        assert res.status_code == 422


class TestSubscribeModel:
    def test_requires_email_or_phone(self):
        with pytest.raises(ValidationError):
            SubscribeRequest()

    def test_whatsapp_channel_requires_a_phone(self):
        with pytest.raises(ValidationError):
            SubscribeRequest(email="a@b.com", channel=Channel.whatsapp)

    def test_accepts_indian_mobile_numbers(self):
        req = SubscribeRequest(phone="+919876543210", channel=Channel.whatsapp)
        assert req.phone == "+919876543210"

    @pytest.mark.parametrize("phone", ["9876543210", "+911234567890", "+1234567890", "+9198765"])
    def test_rejects_malformed_phone_numbers(self, phone):
        with pytest.raises(ValidationError):
            SubscribeRequest(phone=phone, channel=Channel.whatsapp)

    def test_uppercases_state_codes(self):
        req = SubscribeRequest(email="a@b.com", states=["rj", "up"])
        assert req.states == ["RJ", "UP"]

    def test_rejects_non_alpha_state_codes(self):
        with pytest.raises(ValidationError):
            SubscribeRequest(email="a@b.com", states=["R1"])

    def test_defaults_to_weekly_email(self):
        req = SubscribeRequest(email="a@b.com")
        assert req.channel is Channel.email
        assert req.frequency is Frequency.weekly


class TestCors:
    def test_production_drops_localhost_origin(self):
        original = settings.environment
        try:
            settings.environment = "production"
            settings.frontend_url = "https://sarkarisaar.com"
            assert "http://localhost:3000" not in settings.cors_origins
            assert "https://sarkarisaar.com" in settings.cors_origins
        finally:
            settings.environment = original
            settings.frontend_url = "http://localhost:3000"

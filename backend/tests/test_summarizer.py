"""Summarizer tests — schema validation, provider selection, cost maths.

No API calls: every provider is exercised through its pure methods or a stub.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import settings
from app.models.entry import Summary
from app.services.ai_provider import (
    GEMINI_FREE_DAILY_REQUESTS,
    GEMINI_FREE_RPM,
    AnthropicProvider,
    GeminiProvider,
    PermanentAIError,
    Usage,
    get_provider,
)
from app.services.summarizer import estimate_cost_inr

VALID = {
    "title": "SSC CGL 2026: 8,326 vacancies for graduates",
    "summary_en": "The SSC has announced 8,326 vacancies. Any graduate aged 18-32 can apply.",
    "summary_hi": "एसएससी ने 8,326 पदों की घोषणा की है। 18-32 वर्ष का कोई भी स्नातक आवेदन कर सकता है।",
    "category": "naukri",
    "urgency": "high",
    "deadline": "2026-03-20",
    "department": "Staff Selection Commission",
    "eligibility": "Graduates aged 18-32",
    "budget_or_salary": 81100,
    "confidence": 0.96,
    "key_details": {"vacancies": 8326},
}


class TestSummarySchema:
    def test_accepts_a_complete_response(self):
        s = Summary.model_validate(VALID)
        assert s.category == "naukri"
        assert s.key_details.vacancies == 8326
        assert s.key_details.helpline is None

    def test_nullable_fields_may_be_omitted(self):
        minimal = {
            k: v
            for k, v in VALID.items()
            if k in {"title", "summary_en", "summary_hi", "category", "urgency", "confidence"}
        }
        s = Summary.model_validate(minimal)
        assert s.deadline is None
        assert s.budget_or_salary is None

    @pytest.mark.parametrize("bad_category", ["job", "JOBS", "", "tender "])
    def test_rejects_unknown_category(self, bad_category):
        with pytest.raises(ValidationError):
            Summary.model_validate({**VALID, "category": bad_category})

    def test_rejects_unknown_urgency(self):
        with pytest.raises(ValidationError):
            Summary.model_validate({**VALID, "urgency": "urgent"})

    def test_missing_required_field_fails(self):
        payload = {k: v for k, v in VALID.items() if k != "summary_en"}
        with pytest.raises(ValidationError):
            Summary.model_validate(payload)

    def test_hindi_summary_is_devanagari(self):
        s = Summary.model_validate(VALID)
        assert any("ऀ" <= ch <= "ॿ" for ch in s.summary_hi)


class TestProviderSelection:
    def setup_method(self):
        get_provider.cache_clear()
        self._provider = settings.ai_provider
        self._gemini_key = settings.gemini_api_key
        self._anthropic_key = settings.anthropic_api_key

    def teardown_method(self):
        settings.ai_provider = self._provider
        settings.gemini_api_key = self._gemini_key
        settings.anthropic_api_key = self._anthropic_key
        get_provider.cache_clear()

    def test_gemini_is_the_default(self):
        assert settings.ai_provider == "gemini", "free tier should be the out-of-box default"

    def test_unknown_provider_is_rejected_by_name(self):
        settings.ai_provider = "openai"
        with pytest.raises(PermanentAIError, match="Unknown AI_PROVIDER"):
            get_provider()

    def test_gemini_without_a_key_says_where_to_get_one(self):
        settings.ai_provider = "gemini"
        settings.gemini_api_key = ""
        with pytest.raises(PermanentAIError, match="aistudio.google.com"):
            get_provider()

    def test_anthropic_without_a_key_fails_clearly(self):
        settings.ai_provider = "anthropic"
        settings.anthropic_api_key = ""
        with pytest.raises(PermanentAIError, match="ANTHROPIC_API_KEY"):
            get_provider()

    def test_provider_is_cached(self):
        settings.ai_provider = "gemini"
        settings.gemini_api_key = "test-key"
        assert get_provider() is get_provider()


class TestGeminiFreeTier:
    def _provider(self, model: str) -> GeminiProvider:
        settings.gemini_api_key = "test-key"
        settings.gemini_model = model
        return GeminiProvider()

    def test_free_tier_calls_cost_nothing(self):
        p = self._provider("gemini-2.5-flash-lite")
        assert p.cost_inr(Usage(input_tokens=6_000, output_tokens=700)) == 0.0

    def test_paces_calls_under_the_rate_limit(self):
        p = self._provider("gemini-2.5-flash-lite")
        # 15 RPM with headroom -> at least 4s between calls.
        assert p.min_interval_seconds >= 4.0
        assert 60 / p.min_interval_seconds < GEMINI_FREE_RPM["gemini-2.5-flash-lite"]

    def test_slower_models_are_paced_more_conservatively(self):
        lite = self._provider("gemini-2.5-flash-lite").min_interval_seconds
        pro = self._provider("gemini-2.5-pro").min_interval_seconds
        assert pro > lite

    def test_default_model_has_the_largest_free_allowance(self):
        assert (
            max(GEMINI_FREE_DAILY_REQUESTS, key=GEMINI_FREE_DAILY_REQUESTS.get)
            == "gemini-2.5-flash-lite"
        )

    def test_request_cap_stays_under_the_free_quota(self):
        assert settings.ai_daily_request_cap < GEMINI_FREE_DAILY_REQUESTS["gemini-2.5-flash-lite"]


class TestAnthropicCost:
    def _provider(self, model: str) -> AnthropicProvider:
        settings.anthropic_api_key = "test-key"
        settings.anthropic_model = model
        return AnthropicProvider()

    def test_known_model_pricing(self):
        p = self._provider("claude-sonnet-5")
        # 1M in + 1M out == 264 + 1320 INR
        assert p.cost_inr(Usage(1_000_000, 1_000_000)) == pytest.approx(1584.0)

    def test_typical_entry_costs_a_few_rupees(self):
        # ~6k in / ~700 out is a representative notification, so roughly Rs 2.5
        # each — which is exactly why Gemini is the default.
        p = self._provider("claude-sonnet-5")
        assert 1.0 < p.cost_inr(Usage(6_000, 700)) < 4.0

    def test_unknown_model_falls_back_to_default_rates(self):
        p = self._provider("claude-some-future-model")
        assert p.cost_inr(Usage(1_000_000, 0)) == pytest.approx(264.0)

    def test_zero_tokens_costs_nothing(self):
        p = self._provider("claude-sonnet-5")
        assert p.cost_inr(Usage(0, 0)) == 0


class TestGeminiSchemaCompatibility:
    """Gemini's structured output supports only a subset of JSON Schema.

    If someone adds a field type Gemini can't express, every summarization call
    fails at runtime with the same error. These tests catch that at build time.
    """

    @staticmethod
    def _converted():
        from google.genai._transformers import t_schema

        return t_schema(None, Summary).model_dump(exclude_none=True)

    def test_summary_schema_converts(self):
        schema = self._converted()
        assert set(schema["properties"]) == {
            "title", "summary_en", "summary_hi", "category", "urgency", "deadline",
            "department", "eligibility", "budget_or_salary", "confidence", "key_details",
        }

    def test_nested_key_details_survives_conversion(self):
        nested = self._converted()["properties"]["key_details"]
        assert set(nested["properties"]) == {
            "application_link", "helpline", "vacancies", "emd_amount",
        }

    def test_only_the_non_nullable_fields_are_required(self):
        required = set(self._converted().get("required", []))
        assert required == {
            "title", "summary_en", "summary_hi", "category", "urgency", "confidence",
        }
        # These must stay optional — the prompt tells the model to null them out
        # rather than guess, and a "required" deadline invites invention.
        assert "deadline" not in required
        assert "budget_or_salary" not in required


class TestCostEstimateHelper:
    def test_resolves_gemini_models(self):
        assert estimate_cost_inr("gemini-2.5-flash-lite", 100_000, 10_000) == 0.0

    def test_resolves_anthropic_models(self):
        assert estimate_cost_inr("claude-sonnet-5", 1_000_000, 0) == pytest.approx(264.0)

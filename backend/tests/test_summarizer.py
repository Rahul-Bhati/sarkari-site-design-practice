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
    EST_TOKENS_PER_SUMMARY,
    GROQ_FREE_TPM,
    AnthropicProvider,
    GeminiProvider,
    GroqProvider,
    PermanentAIError,
    TransientAIError,
    Usage,
    _strict_schema,
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
        self._groq_key = settings.groq_api_key
        self._gemini_key = settings.gemini_api_key
        self._anthropic_key = settings.anthropic_api_key

    def teardown_method(self):
        settings.ai_provider = self._provider
        settings.groq_api_key = self._groq_key
        settings.gemini_api_key = self._gemini_key
        settings.anthropic_api_key = self._anthropic_key
        get_provider.cache_clear()

    def test_groq_is_the_default(self):
        assert settings.ai_provider == "groq", "free tier should be the out-of-box default"

    def test_unknown_provider_is_rejected_by_name(self):
        settings.ai_provider = "openai"
        with pytest.raises(PermanentAIError, match="Unknown AI_PROVIDER"):
            get_provider()

    def test_groq_without_a_key_says_where_to_get_one(self):
        settings.ai_provider = "groq"
        settings.groq_api_key = ""
        with pytest.raises(PermanentAIError, match="console.groq.com"):
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


class TestGroqFreeTier:
    def setup_method(self):
        self._key = settings.groq_api_key
        self._model = settings.groq_model

    def teardown_method(self):
        settings.groq_api_key = self._key
        settings.groq_model = self._model

    def _provider(self, model: str | None = None) -> GroqProvider:
        settings.groq_api_key = "test-key"
        if model:
            settings.groq_model = model
        return GroqProvider()

    def test_free_tier_calls_cost_nothing(self):
        assert self._provider().cost_inr(Usage(input_tokens=9000, output_tokens=900)) == 0.0

    def test_paces_calls_inside_the_token_budget(self):
        p = self._provider("openai/gpt-oss-120b")
        calls_per_minute = 60 / p.min_interval_seconds
        spend = calls_per_minute * EST_TOKENS_PER_SUMMARY
        # The tokens/minute cap binds long before the requests/minute one, so
        # pacing has to be derived from it or every batch 429s.
        assert spend <= GROQ_FREE_TPM["openai/gpt-oss-120b"]

    def test_unknown_model_still_gets_paced(self):
        assert self._provider("some/unlisted-model").min_interval_seconds > 0

    def test_retunes_from_the_rate_limit_headers(self):
        p = self._provider("openai/gpt-oss-120b")
        # A paid tier reports a far larger budget; pacing should open up
        # without anyone editing the table.
        p._retune({"x-ratelimit-limit-tokens": "300000"}, 1800)
        assert 60 / p.min_interval_seconds * 1800 <= 300_000
        assert p.min_interval_seconds < 1.0

    def test_retune_slows_down_for_costlier_entries(self):
        p = self._provider("openai/gpt-oss-120b")
        before = p.min_interval_seconds
        p._retune({"x-ratelimit-limit-tokens": "8000"}, EST_TOKENS_PER_SUMMARY * 3)
        assert p.min_interval_seconds > before

    def test_retune_survives_missing_or_junk_headers(self):
        p = self._provider("openai/gpt-oss-120b")
        p._retune({}, 1800)
        assert p.min_interval_seconds > 0
        p._retune({"x-ratelimit-limit-tokens": "not-a-number"}, 1800)
        assert p.min_interval_seconds > 0

    def test_leaves_headroom_under_the_cap(self):
        p = self._provider("openai/gpt-oss-120b")
        spend = 60 / p.min_interval_seconds * EST_TOKENS_PER_SUMMARY
        assert spend < GROQ_FREE_TPM["openai/gpt-oss-120b"] * 0.95

    def test_asks_for_a_strict_schema_by_default(self):
        rf = self._provider()._response_format()
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["strict"] is True

    def test_falls_back_to_json_object_with_the_schema_in_the_prompt(self):
        p = self._provider()
        assert "JSON Schema" not in p._system_prompt("SYS")
        p._schema_mode = "json_object"
        assert p._response_format() == {"type": "json_object"}
        prompt = p._system_prompt("SYS")
        assert prompt.startswith("SYS")
        # Without the schema in the prompt, json_object mode returns valid JSON
        # of entirely the wrong shape.
        assert "summary_hi" in prompt


class _FakeRawResponse:
    """Mimics the async SDK's raw-response wrapper: parse() is a coroutine."""

    def __init__(self, payload: str, headers: dict[str, str]):
        self._payload = payload
        self.headers = headers

    async def parse(self):
        import types as _t

        usage = _t.SimpleNamespace(prompt_tokens=900, completion_tokens=800)
        message = _t.SimpleNamespace(content=self._payload)
        choice = _t.SimpleNamespace(message=message, finish_reason="stop")
        return _t.SimpleNamespace(choices=[choice], usage=usage)


class _FakeGroqClient:
    def __init__(self, payload: str, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {"x-ratelimit-limit-tokens": "8000"}
        self.calls: list[dict] = []
        outer = self

        class _Create:
            async def create(self, **kwargs):
                outer.calls.append(kwargs)
                return _FakeRawResponse(outer.payload, outer.headers)

        class _Completions:
            with_raw_response = _Create()

        self.chat = type("_Chat", (), {"completions": _Completions()})()


@pytest.mark.asyncio
class TestGroqSummarizeRoundTrip:
    """Exercises summarize() itself — the unit tests above only touch helpers,
    so an unawaited coroutine or a renamed attribute slips straight past them.
    """

    def _provider(self, client) -> GroqProvider:
        settings.groq_api_key = "test-key"
        p = GroqProvider()
        p._client = client
        return p

    async def test_returns_a_validated_summary_and_usage(self):
        import json

        client = _FakeGroqClient(json.dumps(VALID))
        summary, usage = await self._provider(client).summarize("SYS", "USER")
        assert summary.category == "naukri"
        assert summary.key_details.vacancies == 8326
        assert usage.input_tokens == 900
        assert usage.output_tokens == 800

    async def test_paces_itself_from_the_response_headers(self):
        import json

        client = _FakeGroqClient(
            json.dumps(VALID), {"x-ratelimit-limit-tokens": "300000"}
        )
        p = self._provider(client)
        before = p.min_interval_seconds
        await p.summarize("SYS", "USER")
        assert p.min_interval_seconds < before

    async def test_truncated_output_is_retryable_not_silently_wrong(self):
        import json
        import types as _t

        client = _FakeGroqClient(json.dumps(VALID))

        class _Truncated(_FakeRawResponse):
            async def parse(self):
                r = await super().parse()
                return _t.SimpleNamespace(
                    choices=[
                        _t.SimpleNamespace(
                            message=r.choices[0].message, finish_reason="length"
                        )
                    ],
                    usage=r.usage,
                )

        async def _create(**kwargs):
            return _Truncated(client.payload, client.headers)

        client.chat.completions.with_raw_response.create = _create
        with pytest.raises(TransientAIError, match="truncated"):
            await self._provider(client).summarize("SYS", "USER")

    async def test_off_schema_json_is_retryable(self):
        client = _FakeGroqClient('{"title": "only a title"}')
        with pytest.raises(TransientAIError, match="unusable JSON"):
            await self._provider(client).summarize("SYS", "USER")


class TestStrictSchema:
    def test_every_field_is_required_even_the_optional_ones(self):
        schema = _strict_schema(Summary.model_json_schema())
        # Pydantic marks deadline/department optional; strict mode needs them
        # listed anyway, nullable via anyOf.
        assert set(schema["required"]) == set(schema["properties"])
        assert "deadline" in schema["required"]

    def test_additional_properties_are_closed_off(self):
        schema = _strict_schema(Summary.model_json_schema())
        assert schema["additionalProperties"] is False

    def test_nested_definitions_are_rewritten_too(self):
        schema = _strict_schema(Summary.model_json_schema())
        key_details = schema["$defs"]["KeyDetails"]
        assert key_details["additionalProperties"] is False
        assert set(key_details["required"]) == set(key_details["properties"])

    def test_leaves_non_object_nodes_alone(self):
        assert _strict_schema({"type": "string"}) == {"type": "string"}
        assert _strict_schema([{"type": "null"}]) == [{"type": "null"}]


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

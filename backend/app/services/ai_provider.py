"""Pluggable summarization backends.

Three providers, same contract:

  groq      — Groq. Free tier (no card) and by far the fastest; the default.
  gemini    — Google Gemini. Also has a real free tier (no card, 1,000
              requests/day on Flash-Lite).
  anthropic — Claude. Better summaries, especially the Hindi; costs about
              Rs 2.5 per notification.

All three return a validated `Summary`, so nothing downstream cares which one
ran. Switch with AI_PROVIDER in .env.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.config import settings
from app.models.entry import Summary

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


class TransientAIError(RuntimeError):
    """Rate limit, timeout, overload — worth retrying."""


class PermanentAIError(RuntimeError):
    """Bad key, bad request, refusal — retrying will not help."""


class SummaryProvider(ABC):
    #: Identifier stored on each ai_usage row.
    name: str
    #: Seconds to wait between calls, to stay inside the provider's rate limit.
    min_interval_seconds: float = 0.0

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    async def summarize(self, system: str, user: str) -> tuple[Summary, Usage]: ...

    @abstractmethod
    def cost_inr(self, usage: Usage) -> float: ...


# --- Gemini ----------------------------------------------------------------

# Free tier costs nothing, so these stay 0. If you enable billing in Google AI
# Studio the free tier is switched off entirely and real rates apply — put them
# here at that point, or the daily spend cap will read as Rs 0 forever.
GEMINI_RATES_INR_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.0, 0.0),
    "gemini-2.5-flash": (0.0, 0.0),
    "gemini-2.5-pro": (0.0, 0.0),
}

#: Free-tier requests/day, for reference when setting AI_DAILY_REQUEST_CAP.
GEMINI_FREE_DAILY_REQUESTS = {
    "gemini-2.5-flash-lite": 1000,
    "gemini-2.5-flash": 250,
    "gemini-2.5-pro": 100,
}

#: Free-tier requests/minute. The scheduler batches 10 at a time, so we pace
#: calls rather than risk a 429 midway through a batch.
GEMINI_FREE_RPM = {
    "gemini-2.5-flash-lite": 15,
    "gemini-2.5-flash": 10,
    "gemini-2.5-pro": 5,
}


class GeminiProvider(SummaryProvider):
    name = "gemini"

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise PermanentAIError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey — no credit card needed."
            )
        from google import genai  # noqa: PLC0415

        self._client = genai.Client(api_key=settings.gemini_api_key)
        rpm = GEMINI_FREE_RPM.get(self.model, 10)
        # A little headroom under the published limit.
        self.min_interval_seconds = 60 / max(rpm - 2, 1)

    @property
    def model(self) -> str:
        return settings.gemini_model

    async def summarize(self, system: str, user: str) -> tuple[Summary, Usage]:
        from google.genai import types  # noqa: PLC0415
        from google.genai import errors as genai_errors  # noqa: PLC0415

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            # The SDK accepts a Pydantic model directly and validates the reply
            # against it, so `.parsed` is already a Summary.
            response_schema=Summary,
            max_output_tokens=4096,
        )
        # Extraction doesn't benefit from thinking, and on the free tier the
        # thinking tokens eat into the per-minute token budget.
        if settings.gemini_disable_thinking and "lite" in self.model:
            config.thinking_config = types.ThinkingConfig(thinking_budget=0)

        try:
            response = await self._client.aio.models.generate_content(
                model=self.model, contents=user, config=config
            )
        except genai_errors.ClientError as exc:
            # 429 is the free-tier quota; everything else is our fault.
            if getattr(exc, "code", None) == 429:
                raise TransientAIError(f"gemini rate limited: {exc}") from exc
            raise PermanentAIError(f"gemini rejected the request: {exc}") from exc
        except genai_errors.ServerError as exc:
            raise TransientAIError(f"gemini server error: {exc}") from exc
        except Exception as exc:
            raise TransientAIError(f"gemini call failed: {exc}") from exc

        parsed = response.parsed
        if not isinstance(parsed, Summary):
            raise TransientAIError("gemini returned no schema-valid summary")

        meta = response.usage_metadata
        return parsed, Usage(
            input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
            output_tokens=(getattr(meta, "candidates_token_count", 0) or 0)
            + (getattr(meta, "thoughts_token_count", 0) or 0),
        )

    def cost_inr(self, usage: Usage) -> float:
        rate_in, rate_out = GEMINI_RATES_INR_PER_MTOK.get(self.model, (0.0, 0.0))
        return (usage.input_tokens * rate_in + usage.output_tokens * rate_out) / 1_000_000


# --- Anthropic -------------------------------------------------------------

# INR per million tokens at roughly 88 INR/USD.
ANTHROPIC_RATES_INR_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (264.0, 1320.0),      # $3 / $15
    "claude-sonnet-4-6": (264.0, 1320.0),    # $3 / $15
    "claude-opus-5": (440.0, 2200.0),        # $5 / $25
    "claude-haiku-4-5": (88.0, 440.0),       # $1 / $5
}
ANTHROPIC_DEFAULT_RATE = (264.0, 1320.0)


class AnthropicProvider(SummaryProvider):
    name = "anthropic"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise PermanentAIError("ANTHROPIC_API_KEY is not set")
        import anthropic  # noqa: PLC0415

        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    @property
    def model(self) -> str:
        return settings.anthropic_model

    async def summarize(self, system: str, user: str) -> tuple[Summary, Usage]:
        import anthropic  # noqa: PLC0415

        try:
            response = await self._client.messages.parse(
                model=self.model,
                max_tokens=4096,
                system=[
                    {
                        "type": "text",
                        "text": system,
                        # Identical on every call, so cache it.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user}],
                output_format=Summary,
            )
        except anthropic.AuthenticationError as exc:
            raise PermanentAIError(f"anthropic auth failed: {exc}") from exc
        except anthropic.BadRequestError as exc:
            raise PermanentAIError(f"anthropic rejected the request: {exc}") from exc
        except (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        ) as exc:
            raise TransientAIError(f"anthropic transient failure: {exc}") from exc
        except Exception as exc:
            raise TransientAIError(f"anthropic call failed: {exc}") from exc

        if response.stop_reason == "refusal":
            raise PermanentAIError("model refused to summarize this notification")

        parsed = response.parsed_output
        if parsed is None:
            raise TransientAIError("anthropic returned no parsable output")

        usage = response.usage
        return parsed, Usage(
            input_tokens=usage.input_tokens
            + (usage.cache_read_input_tokens or 0)
            + (usage.cache_creation_input_tokens or 0),
            output_tokens=usage.output_tokens,
        )

    def cost_inr(self, usage: Usage) -> float:
        rate_in, rate_out = ANTHROPIC_RATES_INR_PER_MTOK.get(
            self.model, ANTHROPIC_DEFAULT_RATE
        )
        return (usage.input_tokens * rate_in + usage.output_tokens * rate_out) / 1_000_000


# --- Groq ------------------------------------------------------------------

# Groq's free tier costs nothing, so these stay 0 for the same reason Gemini's
# do — the real free-tier limit is requests/day, which AI_DAILY_REQUEST_CAP
# guards. If you move to a paid Groq Developer plan, put the published rates
# here or the daily spend cap will read as Rs 0 forever. At ~88 INR/USD the
# developer rates are roughly:
#   openai/gpt-oss-120b        (13.2, 66.0)    # $0.15 / $0.75 per Mtok
#   llama-3.3-70b-versatile    (51.9, 69.5)    # $0.59 / $0.79 per Mtok
GROQ_RATES_INR_PER_MTOK: dict[str, tuple[float, float]] = {}
GROQ_DEFAULT_RATE = (0.0, 0.0)

#: Free-tier tokens/minute. This, not requests/minute, is what actually binds:
#: a summary costs roughly EST_TOKENS_PER_SUMMARY, so 8,000 TPM allows about
#: four calls a minute even though the request limit is far higher. Measured
#: from x-ratelimit-limit-tokens; anything unlisted falls back to the default.
GROQ_FREE_TPM = {
    "openai/gpt-oss-120b": 8_000,
    "openai/gpt-oss-20b": 8_000,
    "llama-3.3-70b-versatile": 12_000,
    "moonshotai/kimi-k2-instruct-0905": 10_000,
}
GROQ_DEFAULT_TPM = 8_000

#: Prompt plus completion for a typical notification, measured against
#: gpt-oss-120b. Only the opening estimate — real usage from the rate-limit
#: headers takes over after the first call.
EST_TOKENS_PER_SUMMARY = 1_800

#: Leave part of the budget unused. Token accounting is approximate on both
#: sides and landing exactly on the limit means a 429 and a ~50s SDK backoff,
#: which costs far more than pacing slightly slower would have.
GROQ_TPM_HEADROOM = 0.80


def _strict_schema(schema: Any) -> Any:
    """Rewrite a Pydantic JSON schema into the strict subset Groq requires.

    Strict structured outputs need every object to set additionalProperties
    false and to list *all* its properties as required. Pydantic marks fields
    with defaults as optional, so they have to be forced back in — they are
    already nullable via `anyOf: [..., null]`, which strict mode allows.
    """
    if isinstance(schema, list):
        return [_strict_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema

    out = {k: _strict_schema(v) for k, v in schema.items()}
    if out.get("type") == "object" and isinstance(out.get("properties"), dict):
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


class GroqProvider(SummaryProvider):
    name = "groq"

    def __init__(self) -> None:
        if not settings.groq_api_key:
            raise PermanentAIError(
                "GROQ_API_KEY is not set. Get a free key at "
                "https://console.groq.com/keys — no credit card needed."
            )
        import groq  # noqa: PLC0415

        self._client = groq.AsyncGroq(api_key=settings.groq_api_key)
        # Set once the model tells us it can't do json_schema, so we only pay
        # for that discovery on the first call rather than every call.
        self._schema_mode = "json_schema"
        self._tpm = GROQ_FREE_TPM.get(self.model, GROQ_DEFAULT_TPM)
        self.min_interval_seconds = self._interval_for(EST_TOKENS_PER_SUMMARY)

    def _interval_for(self, tokens_per_call: float) -> float:
        """Seconds to wait between calls to stay inside the tokens/minute budget."""
        budget = max(self._tpm * GROQ_TPM_HEADROOM, 1.0)
        return 60.0 * tokens_per_call / budget

    def _retune(self, headers: Any, usage_tokens: int) -> None:
        """Adapt pacing to what the API just told us about the budget.

        Groq reports the real limit and what is left of it on every response,
        so the hardcoded table above only has to be right enough for the first
        call. Later calls pace off measured numbers, which keeps this correct
        across models and across free/paid tiers without a code change.
        """
        try:
            limit = int(headers.get("x-ratelimit-limit-tokens", 0))
        except (TypeError, ValueError):
            limit = 0
        if limit > 0:
            self._tpm = limit
        if usage_tokens > 0:
            self.min_interval_seconds = self._interval_for(usage_tokens)

    @property
    def model(self) -> str:
        return settings.groq_model

    def _response_format(self) -> dict[str, Any]:
        if self._schema_mode == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "summary",
                "strict": True,
                "schema": _strict_schema(Summary.model_json_schema()),
            },
        }

    def _system_prompt(self, system: str) -> str:
        if self._schema_mode != "json_object":
            return system
        # json_object mode only guarantees *valid* JSON, not the right shape,
        # so the schema has to go in the prompt and Pydantic does the checking.
        schema = json.dumps(_strict_schema(Summary.model_json_schema()))
        return (
            f"{system}\n\nRespond with a single JSON object matching this "
            f"JSON Schema exactly. No prose, no markdown fence.\n{schema}"
        )

    async def summarize(self, system: str, user: str) -> tuple[Summary, Usage]:
        import groq  # noqa: PLC0415

        for _ in range(2):  # at most one retry, to switch into json_object mode
            try:
                # Raw response so the rate-limit headers survive; the free tier
                # is tight enough that pacing needs them. See _retune.
                raw = await self._client.chat.completions.with_raw_response.create(
                    model=self.model,
                    max_completion_tokens=4096,
                    response_format=self._response_format(),
                    messages=[
                        {"role": "system", "content": self._system_prompt(system)},
                        {"role": "user", "content": user},
                    ],
                )
                # The async client's parse() is itself a coroutine.
                response = await raw.parse()
            except groq.AuthenticationError as exc:
                raise PermanentAIError(f"groq auth failed: {exc}") from exc
            except groq.BadRequestError as exc:
                # Not every Groq model supports strict json_schema. Drop to
                # json_object once and carry the schema in the prompt instead.
                if self._schema_mode == "json_schema" and "json_schema" in str(exc):
                    log.warning(
                        "groq model %s rejected json_schema; using json_object "
                        "with prompt-carried schema instead",
                        self.model,
                    )
                    self._schema_mode = "json_object"
                    continue
                raise PermanentAIError(f"groq rejected the request: {exc}") from exc
            except (
                groq.RateLimitError,
                groq.APIConnectionError,
                groq.InternalServerError,
            ) as exc:
                raise TransientAIError(f"groq transient failure: {exc}") from exc
            except Exception as exc:
                raise TransientAIError(f"groq call failed: {exc}") from exc
            break
        else:
            raise PermanentAIError("groq could not be coaxed into returning JSON")

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise TransientAIError("groq truncated the summary at max_completion_tokens")

        content = choice.message.content or ""
        try:
            parsed = Summary.model_validate_json(content)
        except ValueError as exc:
            # Malformed or off-schema JSON — a different sample may well be
            # fine, so let the summarizer's retry loop have another go.
            raise TransientAIError(f"groq returned unusable JSON: {exc}") from exc

        usage = response.usage
        result = Usage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
        self._retune(raw.headers, result.input_tokens + result.output_tokens)
        return parsed, result

    def cost_inr(self, usage: Usage) -> float:
        rate_in, rate_out = GROQ_RATES_INR_PER_MTOK.get(self.model, GROQ_DEFAULT_RATE)
        return (usage.input_tokens * rate_in + usage.output_tokens * rate_out) / 1_000_000


PROVIDERS: dict[str, type[SummaryProvider]] = {
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
}


@lru_cache
def get_provider() -> SummaryProvider:
    try:
        provider_cls = PROVIDERS[settings.ai_provider]
    except KeyError:
        raise PermanentAIError(
            f"Unknown AI_PROVIDER {settings.ai_provider!r}. "
            f"Choose one of: {', '.join(sorted(PROVIDERS))}"
        ) from None
    provider = provider_cls()
    log.info("AI provider: %s (%s)", provider.name, provider.model)
    return provider

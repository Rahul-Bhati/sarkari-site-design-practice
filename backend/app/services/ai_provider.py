"""Pluggable summarization backends.

Two providers, same contract:

  gemini    — Google Gemini. Has a real free tier (no card, 1,000 requests/day
              on Flash-Lite), which is why it is the default.
  anthropic — Claude. Better summaries, especially the Hindi; costs about
              Rs 2.5 per notification.

Both return a validated `Summary`, so nothing downstream cares which one ran.
Switch with AI_PROVIDER in .env.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

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


PROVIDERS: dict[str, type[SummaryProvider]] = {
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

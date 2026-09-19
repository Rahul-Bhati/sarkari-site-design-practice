from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_anon_key: str = ""

    # AI
    # "groq" (free tier, fastest, the default), "gemini" (also free) or
    # "anthropic" (better summaries, paid).
    ai_provider: str = "groq"

    # Groq — free key, no card: https://console.groq.com/keys
    groq_api_key: str = ""
    # gpt-oss-120b follows the schema reliably and handles Devanagari well.
    groq_model: str = "openai/gpt-oss-120b"

    # Gemini — free key, no card: https://aistudio.google.com/apikey
    gemini_api_key: str = ""
    # flash-lite has the largest free allowance (1,000 requests/day).
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_disable_thinking: bool = True

    anthropic_api_key: str = ""
    # The PRD names claude-sonnet-4-6. Sonnet 5 is used instead because the
    # summarizer relies on structured outputs (output_config.format), which
    # Sonnet 4.6 does not support, and Sonnet 5 is the same price tier.
    anthropic_model: str = "claude-sonnet-5"

    ai_daily_cap_inr: float = 500.0
    # Guards the free tier's requests/day quota, which no spend cap can catch
    # because free-tier calls cost nothing. Keep it under the model's limit.
    ai_daily_request_cap: int = 900
    # And the quota that actually bites first. Groq's free tier allows 200,000
    # tokens per day; at roughly 1,800 tokens a summary that is about 110
    # summaries, not 900. Without this the request cap reports plenty of
    # headroom while the real budget is gone, and every entry then burns three
    # retries against a 429 before being marked failed.
    # 0 disables the check, for paid tiers that have no daily token quota.
    ai_daily_token_cap: int = 195_000
    ai_batch_size: int = 10
    # Notices sent to the model in a single call. The schema and system prompt
    # are ~87% of a one-notice request and identical every time, so batching
    # pays that overhead once and roughly halves tokens per entry. 0 means
    # "use the provider's own default"; 1 disables batching.
    ai_batch_entries: int = 0
    ai_auto_approve_confidence: float = 0.90

    # Notifications
    resend_api_key: str = ""
    resend_from: str = "SarkariSaar <updates@sarkarisaar.com>"
    gupshup_api_key: str = ""
    gupshup_app_name: str = "SarkariSaar"
    gupshup_source_number: str = ""
    gupshup_daily_limit: int = 1000

    # Payments
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_pro_monthly: str = ""
    razorpay_plan_pro_yearly: str = ""
    razorpay_plan_thekedar_monthly: str = ""
    razorpay_plan_thekedar_yearly: str = ""

    # Cache
    upstash_redis_url: str = ""
    feed_cache_ttl_seconds: int = 300

    # Scrapers
    # Browser-shaped by default because several portals 403 anything that looks
    # automated; the contact URL keeps us identifiable to anyone reading logs.
    scraper_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
        "(+https://sarkarisaar.com/about)"
    )

    # Ops
    sentry_dsn: str = ""
    admin_api_key: str = ""  # Shared secret for machine-triggered admin endpoints
    scheduler_enabled: bool = True

    # App
    environment: str = "development"
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        origins = {self.frontend_url, "http://localhost:3000"}
        if self.is_production:
            origins.discard("http://localhost:3000")
        return sorted(o for o in origins if o)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

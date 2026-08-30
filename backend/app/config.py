"""Centralised settings. All secrets come from environment variables
(populated from `.env` by docker-compose / pydantic-settings). Nothing is
hardcoded."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Agentic Conversion & Merchant Growth Engine"

    # --- LLM (Google AI Studio) ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_embedding_model: str = Field(
        default="gemini-embedding-001", alias="GEMINI_EMBEDDING_MODEL"
    )

    # --- Razorpay sandbox ---
    razorpay_key_id: str = Field(default="", alias="RAZORPAY_KEY_ID")
    razorpay_key_secret: str = Field(default="", alias="RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str = Field(default="", alias="RAZORPAY_WEBHOOK_SECRET")

    # --- Data stores ---
    database_url: str = Field(
        default="postgresql://postgres:postgres@postgres:5432/growth_engine",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # --- Behaviour ---
    session_ttl_seconds: int = Field(default=1800, alias="SESSION_TTL_SECONDS")
    max_guardrail_retries: int = Field(default=3, alias="MAX_GUARDRAIL_RETRIES")
    max_negotiation_turns: int = Field(default=3, alias="MAX_NEGOTIATION_TURNS")
    default_merchant_id: str = Field(default="merchant_demo", alias="MERCHANT_ID")


@lru_cache
def get_settings() -> Settings:
    return Settings()

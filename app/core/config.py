from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    vision_api_key: str
    redis_url: str
    supabase_url: str
    supabase_service_role_key: str
    openrouter_jev_api_key: str = ""
    openrouter_jev_model: str = "typesafe/jev-1.14"
    receipt_classifier_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    receipt_category_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    trial_days: int = Field(default=7, ge=1)
    trial_daily_scan_limit: int = Field(default=3, ge=1)
    revenuecat_webhook_auth_token: str = ""
    openrouter_timeout_seconds: float = Field(default=5.0, gt=0.0)
    posthog_enabled: bool = False
    posthog_project_api_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"
    environment: str = "development"
    rate_limit_per_minute: int = 30
    max_image_bytes: int = 10 * 1024 * 1024
    max_image_dimension: int = 1600
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

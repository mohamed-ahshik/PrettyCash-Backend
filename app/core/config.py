from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    vision_api_key: str
    redis_url: str
    supabase_url: str
    supabase_service_role_key: str
    rate_limit_per_minute: int = 30
    max_image_bytes: int = 10 * 1024 * 1024
    max_image_dimension: int = 1600
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

from app.core.config import Settings
from app.core.errors import (
    AppError,
    ErrorCode,
    InternalError,
    InvalidImageError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    UnprocessableError,
)


def test_settings_defaults():
    s = Settings(
        gemini_api_key="g",
        vision_api_key="v",
        redis_url="redis://localhost:6379/0",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="key",
    )
    assert s.gemini_model == "gemini-3.1-flash-lite"
    assert s.rate_limit_per_minute == 30
    assert s.max_image_bytes == 10 * 1024 * 1024
    assert s.max_image_dimension == 1600
    assert s.redis_url == "redis://localhost:6379/0"


def test_app_error_carries_status_and_code():
    e = UnauthorizedError()
    assert e.status_code == 401
    assert e.code == ErrorCode.UNAUTHORIZED
    assert isinstance(e, AppError)


def test_app_error_custom_message():
    e = InvalidImageError("bad image")
    assert e.message == "bad image"


def test_all_error_codes_exist():
    assert {c.value for c in ErrorCode} == {
        "UNAUTHORIZED",
        "INVALID_IMAGE",
        "UNPROCESSABLE",
        "RATE_LIMITED",
        "INTERNAL",
        "NOT_FOUND",
    }
    assert InternalError().status_code == 500
    assert RateLimitedError().status_code == 429
    assert UnprocessableError().status_code == 422
    assert NotFoundError().status_code == 404
    assert NotFoundError().code == ErrorCode.NOT_FOUND

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.1-flash-lite",
        vision_api_key="test-vision-key",
        rate_limit_per_minute=30,
    )


@pytest.fixture
def client(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")

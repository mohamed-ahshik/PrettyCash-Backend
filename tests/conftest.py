import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


class FakeJobStore:
    def __init__(self):
        self.rows = {}
        self.counter = 0

    def create(self) -> str:
        self.counter += 1
        job_id = f"job-{self.counter}"
        self.rows[job_id] = {"status": "pending"}
        return job_id

    def mark_processing(self, job_id: str) -> None:
        self.rows.setdefault(job_id, {})["status"] = "processing"

    def complete(self, job_id: str, result: dict) -> None:
        self.rows[job_id] = {"status": "completed", "result": result}

    def fail(self, job_id: str, code: str, message: str) -> None:
        self.rows[job_id] = {"status": "failed", "error_code": code, "error_message": message}

    def get(self, job_id: str) -> dict | None:
        return self.rows.get(job_id)


@pytest.fixture
def job_store() -> FakeJobStore:
    return FakeJobStore()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.1-flash-lite",
        vision_api_key="test-vision-key",
        redis_url="redis://localhost:6379/0",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-role-key",
        rate_limit_per_minute=30,
    )


@pytest.fixture
def client(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")

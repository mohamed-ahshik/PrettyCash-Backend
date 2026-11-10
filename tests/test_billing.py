from types import SimpleNamespace

import httpx

from app.api.deps import require_user
from app.core.config import Settings
from app.main import create_app


class FakeTable:
    def __init__(self):
        self.updated = None

    def update(self, patch):
        self.updated = patch
        return self

    def eq(self, key, value):
        self.eq_value = (key, value)
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class FakeSupabase:
    def __init__(self):
        self.table_obj = FakeTable()

    def table(self, name):
        assert name == "profiles"
        return self.table_obj


async def _client(settings, supabase):
    app = create_app(settings, redis_client=None)
    app.state.supabase = supabase
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id="test-user")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_revenuecat_webhook_requires_secret():
    settings = Settings(
        gemini_api_key="g",
        vision_api_key="v",
        redis_url="redis://localhost:6379/0",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="key",
        revenuecat_webhook_auth_token="secret",
    )
    async with await _client(settings, FakeSupabase()) as client:
        response = await client.post("/api/v1/billing/revenuecat/webhook", json={"event": {}})
    assert response.status_code == 401


async def test_revenuecat_webhook_updates_pro_status():
    settings = Settings(
        gemini_api_key="g",
        vision_api_key="v",
        redis_url="redis://localhost:6379/0",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="key",
        revenuecat_webhook_auth_token="secret",
    )
    supabase = FakeSupabase()
    async with await _client(settings, supabase) as client:
        response = await client.post(
            "/api/v1/billing/revenuecat/webhook",
            headers={"Authorization": "Bearer secret"},
            json={
                "event": {
                    "type": "INITIAL_PURCHASE",
                    "app_user_id": "test-user",
                }
            },
        )
    assert response.status_code == 204
    assert supabase.table_obj.updated == {"is_pro": True, "pro_source": "revenuecat"}
    assert supabase.table_obj.eq_value == ("user_id", "test-user")

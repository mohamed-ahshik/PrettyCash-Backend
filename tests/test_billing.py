from types import SimpleNamespace

import httpx
import pytest

from app.api.deps import require_user
from app.api.v1.billing import _entitlement_payload
from app.core.config import Settings
from app.main import create_app
from app.services.quota import Entitlement


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


def _settings():
    return Settings(
        gemini_api_key="g",
        vision_api_key="v",
        redis_url="redis://localhost:6379/0",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="key",
        revenuecat_webhook_auth_token="secret",
    )


async def _client(settings, supabase, quota=None):
    app = create_app(settings, redis_client=None)
    app.state.supabase = supabase
    if quota is not None:
        app.state.quota = quota
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id="test-user")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _post_webhook(client, event_type):
    return await client.post(
        "/api/v1/billing/revenuecat/webhook",
        headers={"Authorization": "Bearer secret"},
        json={"event": {"type": event_type, "app_user_id": "test-user"}},
    )


def test_entitlement_payload_shape():
    assert _entitlement_payload(Entitlement(True, True, None)) == {
        "isPro": True,
        "canScan": True,
        "blockReason": None,
    }


async def test_entitlement_endpoint_returns_only_current_fields():
    quota = SimpleNamespace(
        entitlement=lambda user_id: Entitlement(
            is_pro=False, can_scan=False, block_reason="subscription_required"
        )
    )
    async with await _client(_settings(), FakeSupabase(), quota=quota) as client:
        response = await client.get("/api/v1/billing/entitlement")
    assert response.status_code == 200
    assert response.json() == {
        "isPro": False,
        "canScan": False,
        "blockReason": "subscription_required",
    }


async def test_revenuecat_webhook_requires_secret():
    async with await _client(_settings(), FakeSupabase()) as client:
        response = await client.post("/api/v1/billing/revenuecat/webhook", json={"event": {}})
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("INITIAL_PURCHASE", {"is_pro": True, "pro_source": "revenuecat"}),
        ("RENEWAL", {"is_pro": True, "pro_source": "revenuecat"}),
        ("UNCANCELLATION", {"is_pro": True, "pro_source": "revenuecat"}),
        ("PRODUCT_CHANGE", {"is_pro": True, "pro_source": "revenuecat"}),
        ("EXPIRATION", {"is_pro": False, "pro_source": "revenuecat"}),
        ("SUBSCRIPTION_PAUSED", {"is_pro": False, "pro_source": "revenuecat"}),
        ("BILLING_ISSUE", None),
        ("CANCELLATION", None),
    ],
)
async def test_revenuecat_webhook_event_mapping(event_type, expected):
    supabase = FakeSupabase()
    async with await _client(_settings(), supabase) as client:
        response = await _post_webhook(client, event_type)
    assert response.status_code == 204
    if expected is None:
        assert supabase.table_obj.updated is None
    else:
        assert supabase.table_obj.updated == expected
        assert supabase.table_obj.eq_value == ("user_id", "test-user")

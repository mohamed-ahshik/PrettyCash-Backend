from types import SimpleNamespace

import pytest

from app.core.errors import SubscriptionRequiredError
from app.services.quota import Entitlement, QuotaService, evaluate_entitlement


class FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, columns):
        return self

    def eq(self, key, value):
        return self

    def limit(self, count):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


class FakeSupabase:
    def __init__(self, data):
        self._data = data
        self.tables = []

    def table(self, name):
        assert name == "profiles"
        self.tables.append(name)
        return FakeQuery(self._data)


def profile(*, is_pro=False):
    return {"is_pro": is_pro}


def test_pro_is_unlimited():
    assert evaluate_entitlement(profile(is_pro=True)) == Entitlement(
        is_pro=True, can_scan=True, block_reason=None
    )


def test_free_profile_is_blocked():
    result = evaluate_entitlement(profile(is_pro=False))
    assert result.can_scan is False
    assert result.block_reason == "subscription_required"


def test_missing_profile_is_blocked():
    result = evaluate_entitlement(None)
    assert result.can_scan is False
    assert result.block_reason == "subscription_required"


def test_consume_scan_for_pro_returns_entitlement_without_scan_usage():
    client = FakeSupabase([{"is_pro": True}])
    result = QuotaService(client).consume_scan("test-user")
    assert result == Entitlement(is_pro=True, can_scan=True, block_reason=None)
    assert client.tables == ["profiles"]


def test_consume_scan_for_free_profile_raises():
    client = FakeSupabase([{"is_pro": False}])
    with pytest.raises(SubscriptionRequiredError):
        QuotaService(client).consume_scan("test-user")
    assert client.tables == ["profiles"]


def test_consume_scan_for_missing_profile_raises():
    client = FakeSupabase([])
    with pytest.raises(SubscriptionRequiredError):
        QuotaService(client).consume_scan("test-user")
    assert client.tables == ["profiles"]

from datetime import UTC, datetime, timedelta

from app.services.quota import evaluate_entitlement

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def profile(*, is_pro=False, days_ago=0):
    return {
        "created_at": (NOW - timedelta(days=days_ago)).isoformat(),
        "is_pro": is_pro,
        "timezone": "Asia/Singapore",
    }


def test_trial_allows_three_scans_per_day():
    assert evaluate_entitlement(profile(days_ago=1), 0, now=NOW).can_scan is True
    assert evaluate_entitlement(profile(days_ago=1), 2, now=NOW).can_scan is True
    result = evaluate_entitlement(profile(days_ago=1), 3, now=NOW)
    assert result.can_scan is False
    assert result.block_reason == "daily_trial_limit"


def test_trial_expires_after_seven_days():
    result = evaluate_entitlement(profile(days_ago=8), 0, now=NOW)
    assert result.can_scan is False
    assert result.block_reason == "subscription_required"


def test_pro_is_unlimited_and_missing_profile_is_blocked():
    assert evaluate_entitlement(profile(is_pro=True), 999, now=NOW).can_scan is True
    assert evaluate_entitlement(None, 0, now=NOW).can_scan is False

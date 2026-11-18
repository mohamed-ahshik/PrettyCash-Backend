from app.services.quota import evaluate_entitlement


def profile(*, is_pro=False):
    return {"is_pro": is_pro}


def test_pro_is_unlimited():
    assert evaluate_entitlement(profile(is_pro=True)).can_scan is True


def test_free_profile_is_blocked():
    result = evaluate_entitlement(profile(is_pro=False))
    assert result.can_scan is False
    assert result.block_reason == "subscription_required"


def test_missing_profile_is_blocked():
    result = evaluate_entitlement(None)
    assert result.can_scan is False
    assert result.block_reason == "subscription_required"

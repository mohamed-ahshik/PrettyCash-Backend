# RevenueCat-Only Quota Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend quota depend only on RevenueCat's `profiles.is_pro`, remove the account-age trial and daily scan limit, and keep access during billing issues/grace until `EXPIRATION`.

**Architecture:** RevenueCat's webhook is the only subscription source. A trial's `INITIAL_PURCHASE` sets `is_pro=true`, so trials are full Pro. `QuotaService` allows `is_pro` and rejects everyone else; no `scan_usage` reads or writes.

**Tech Stack:** FastAPI, Python 3.12, Supabase, pytest.

**Spec:** `/Users/user/Documents/PrettyCash/docs/specs/10-subscriptions/2026-11-19-play-trial-revenuecat-only-design.md`

**Branch:** `mohamedahshik/addTrialPeriod` (already checked out and clean).

**Implementation status:** Implemented; device verification pending.

**Note:** This repo has no existing billing architecture/API document; the frontend spec is the cross-repo contract.

## Global Constraints

- `prettycash_pro` entitlement is the source of truth; `profiles.is_pro` is set by the RevenueCat webhook.
- Trial and active Pro both have unlimited scans.
- Free users get 0 scans and receive `subscription_required`.
- No account-age trial, daily trial limit, or `scan_usage` gating.
- `CANCELLATION` and `BILLING_ISSUE` do not revoke access; `EXPIRATION` and `SUBSCRIPTION_PAUSED` do.
- No database migration and no new dependencies.
- Update implementation status in the plan when done.

## Review Focus

- A trial `INITIAL_PURCHASE` grants Pro.
- A `BILLING_ISSUE` does not revoke access; `EXPIRATION` does.
- A cancellation keeps access until expiration.
- A paused subscription loses access.
- Missing profile / `is_pro=false` returns `canScan: false`.
- `is_pro=true` allows scans without consulting `scan_usage`.
- No lingering `DailyTrialLimitError`, trial settings, or fixtures.

---

### Task 1: Simplify quota and remove the app-managed trial

**Files:**
- Modify: `app/services/quota.py`
- Modify: `app/core/errors.py`
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Test: `tests/test_quota.py`
- Test: `tests/test_core.py`
- Test: `tests/conftest.py`
- Test: `tests/test_api_receipt.py`

**Interfaces:**
- Produces: `Entitlement(is_pro: bool, can_scan: bool, block_reason: str | None)`
- Produces: `evaluate_entitlement(profile: dict | None) -> Entitlement`
- `QuotaService.entitlement(user_id: str) -> Entitlement`
- `QuotaService.consume_scan(user_id: str) -> Entitlement`

- [x] **Step 1: Write the failing quota tests**

Replace `tests/test_quota.py` with:

```python
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
```

Remove the daily-trial tests. Update `profile()` to return only `{"is_pro": ...}`.

- [x] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_quota.py -q`
Expected: FAIL — `evaluate_entitlement` still expects `scans_used` and returns the old fields.

- [x] **Step 3: Simplify `quota.py`**

- `Entitlement` fields: `is_pro`, `can_scan`, `block_reason`.
- `_profile` selects only `is_pro`.
- Remove `_usage`, `_local_date`, `timedelta`, timezone imports.
- `evaluate_entitlement(profile)`: `is_pro` → `Entitlement(True, True, None)`; otherwise `Entitlement(False, False, "subscription_required")`.
- `QuotaService.entitlement` no longer reads usage.
- `QuotaService.consume_scan`: if `is_pro` return; otherwise raise `SubscriptionRequiredError`; do not write `scan_usage`.
- Remove `DailyTrialLimitError` import.

- [x] **Step 4: Remove the trial error and settings**

- Delete `DailyTrialLimitError` and `DAILY_TRIAL_LIMIT_REACHED` from `app/core/errors.py`; update `tests/test_core.py`'s expected error-code set.
- Remove `trial_days` and `trial_daily_scan_limit` from `app/core/config.py`.
- Remove `TRIAL_DAYS` and `TRIAL_DAILY_SCAN_LIMIT` from `.env.example`.

- [x] **Step 5: Update fixtures**

- `tests/conftest.py`: `Entitlement(is_pro=True, can_scan=True, block_reason=None)` for the allow-scan override.
- `tests/test_api_receipt.py`: same for `_allow_scan`.

- [x] **Step 6: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_quota.py tests/test_core.py tests/test_api_receipt.py -q`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add app/services/quota.py app/core/errors.py app/core/config.py .env.example tests/test_quota.py tests/test_core.py tests/conftest.py tests/test_api_receipt.py
git commit -m "feat: make quota depend only on RevenueCat entitlement"
```

---

### Task 2: Simplify the entitlement payload and webhook mapping

**Files:**
- Modify: `app/api/v1/billing.py`
- Test: `tests/test_billing.py`

**Interfaces:**
- Produces: `GET /api/v1/billing/entitlement` → `{isPro, canScan, blockReason}`
- Produces: webhook active set `{INITIAL_PURCHASE, RENEWAL, UNCANCELLATION, PRODUCT_CHANGE}`; inactive set `{EXPIRATION, SUBSCRIPTION_PAUSED}`.

- [x] **Step 1: Write the failing billing tests**

Add to `tests/test_billing.py`:

```python
def test_entitlement_payload_shape():
    from app.api.v1.billing import _entitlement_payload
    from app.services.quota import Entitlement
    assert _entitlement_payload(Entitlement(True, True, None)) == {
        "isPro": True, "canScan": True, "blockReason": None,
    }
```

Add webhook cases using `FakeSupabase`:

- `INITIAL_PURCHASE` → `updated == {"is_pro": True, "pro_source": "revenuecat"}`
- `EXPIRATION` → `is_pro: False`
- `SUBSCRIPTION_PAUSED` → `is_pro: False`
- `BILLING_ISSUE` → `updated is None`
- `CANCELLATION` → `updated is None`

- [x] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_billing.py -q`
Expected: FAIL — the payload still has the trial/daily fields and ignored events still update.

- [x] **Step 3: Implement the payload and webhook mapping**

`_entitlement_payload` returns only `isPro`, `canScan`, `blockReason`.

In the webhook:

```python
active_events = {"INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE"}
inactive_events = {"EXPIRATION", "SUBSCRIPTION_PAUSED"}
if event_type not in active_events | inactive_events:
    return
is_pro = event_type in active_events
```

`BILLING_ISSUE` and `CANCELLATION` therefore return without an update.

- [x] **Step 4: Run the tests**

Run: `./.venv/bin/python -m pytest tests/test_billing.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/api/v1/billing.py tests/test_billing.py
git commit -m "feat: simplify entitlement payload and keep access during grace"
```

---

### Task 3: Documentation and final verification

**Files:**
- Modify: `docs/plans/PLANS.md`
- Modify: `docs/plans/05-subscriptions/2026-11-19-revenuecat-only-quota.md`

- [x] **Step 1: Index the plan**

Add a `05-subscriptions/` section to `docs/plans/PLANS.md`.

- [x] **Step 2: Update statuses**

Set the plan implementation status to `Implemented; device verification pending.` Tick the completed steps.

- [x] **Step 3: Run the full backend checks**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS.

Run: `./.venv/bin/python -m ruff check app tests`
Expected: PASS (or only pre-existing findings, which must be reported).

- [x] **Step 4: Commit**

```bash
git add docs/plans/PLANS.md docs/plans/05-subscriptions/2026-11-19-revenuecat-only-quota.md
git commit -m "docs: document RevenueCat-only quota"
```

---

## Implementation status

**Implementation status:** Implemented; device verification pending.

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, Request

from app.api.deps import require_user
from app.core.errors import UnauthorizedError

router = APIRouter(prefix="/billing")


def _entitlement_payload(entitlement: Any) -> dict[str, Any]:
    return {
        "isPro": entitlement.is_pro,
        "inTrial": entitlement.in_trial,
        "trialDaysLeft": entitlement.trial_days_left,
        "dailyScansUsed": entitlement.daily_scans_used,
        "dailyLimit": entitlement.daily_limit,
        "canScan": entitlement.can_scan,
        "blockReason": entitlement.block_reason,
    }


@router.get("/entitlement")
async def entitlement(request: Request, user: Any = Depends(require_user)):
    return _entitlement_payload(request.app.state.quota.entitlement(str(user.id)))


@router.post("/revenuecat/webhook", status_code=204)
async def revenuecat_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
):
    expected = request.app.state.settings.revenuecat_webhook_auth_token
    if not expected or not authorization or not secrets.compare_digest(
        authorization, f"Bearer {expected}"
    ):
        raise UnauthorizedError("Invalid RevenueCat webhook authorization")

    payload = await request.json()
    event = payload.get("event") or {}
    event_type = event.get("type")
    user_id = event.get("app_user_id") or event.get("original_app_user_id")
    if not user_id:
        return

    active_events = {"INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE"}
    inactive_events = {"EXPIRATION", "BILLING_ISSUE"}
    if event_type not in active_events | inactive_events:
        return

    is_pro = event_type in active_events
    request.app.state.supabase.table("profiles").update(
        {"is_pro": is_pro, "pro_source": "revenuecat"}
    ).eq("user_id", user_id).execute()

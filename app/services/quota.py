from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from supabase import Client

from app.core.config import Settings
from app.core.errors import DailyTrialLimitError, SubscriptionRequiredError


@dataclass(frozen=True)
class Entitlement:
    is_pro: bool
    in_trial: bool
    trial_days_left: int
    daily_scans_used: int
    daily_limit: int
    can_scan: bool
    block_reason: str | None


def _profile(client: Client, user_id: str) -> dict | None:
    result = (
        client.table("profiles")
        .select("created_at,is_pro,timezone")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _usage(client: Client, user_id: str, local_date: date) -> int:
    result = (
        client.table("scan_usage")
        .select("scan_count")
        .eq("user_id", user_id)
        .eq("usage_date", local_date.isoformat())
        .limit(1)
        .execute()
    )
    return int(result.data[0]["scan_count"]) if result.data else 0


def _local_date(timezone_name: str | None, now: datetime) -> date:
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError:
        zone = UTC
    return now.astimezone(zone).date()


def evaluate_entitlement(
    profile: dict | None,
    scans_used: int,
    *,
    now: datetime | None = None,
    trial_days: int = 7,
    daily_limit: int = 3,
) -> Entitlement:
    now = now or datetime.now(UTC)
    if not profile:
        return Entitlement(False, False, 0, scans_used, daily_limit, False, "subscription_required")

    if bool(profile.get("is_pro")):
        return Entitlement(True, False, 0, scans_used, daily_limit, True, None)

    created_at = profile.get("created_at")
    if not created_at:
        return Entitlement(False, False, 0, scans_used, daily_limit, False, "subscription_required")

    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    trial_end = created_at + timedelta(days=trial_days)
    in_trial = now < trial_end
    days_left = max(0, (trial_end - now).days + (1 if (trial_end - now).seconds else 0))
    if not in_trial:
        return Entitlement(False, False, 0, scans_used, daily_limit, False, "subscription_required")
    if scans_used >= daily_limit:
        return Entitlement(False, True, days_left, scans_used, daily_limit, False, "daily_trial_limit")
    return Entitlement(False, True, days_left, scans_used, daily_limit, True, None)


class QuotaService:
    def __init__(self, client: Client, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    def entitlement(self, user_id: str) -> Entitlement:
        profile = _profile(self._client, user_id)
        local_date = _local_date(profile.get("timezone") if profile else "UTC", datetime.now(UTC))
        scans_used = _usage(self._client, user_id, local_date) if profile else 0
        return evaluate_entitlement(
            profile,
            scans_used,
            trial_days=self._settings.trial_days,
            daily_limit=self._settings.trial_daily_scan_limit,
        )

    def consume_scan(self, user_id: str) -> Entitlement:
        profile = _profile(self._client, user_id)
        local_date = _local_date(profile.get("timezone") if profile else "UTC", datetime.now(UTC))
        scans_used = _usage(self._client, user_id, local_date) if profile else 0
        entitlement = evaluate_entitlement(
            profile,
            scans_used,
            trial_days=self._settings.trial_days,
            daily_limit=self._settings.trial_daily_scan_limit,
        )
        if entitlement.is_pro:
            return entitlement
        if entitlement.block_reason == "daily_trial_limit":
            raise DailyTrialLimitError(
                f"You have used {scans_used}/{self._settings.trial_daily_scan_limit} AI scans today."
            )
        if entitlement.block_reason == "subscription_required":
            raise SubscriptionRequiredError()

        self._client.table("scan_usage").upsert(
            {
                "user_id": user_id,
                "usage_date": local_date.isoformat(),
                "scan_count": scans_used + 1,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="user_id,usage_date",
        ).execute()
        return evaluate_entitlement(
            profile,
            scans_used + 1,
            trial_days=self._settings.trial_days,
            daily_limit=self._settings.trial_daily_scan_limit,
        )

from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import SubscriptionRequiredError
from supabase import Client


@dataclass(frozen=True)
class Entitlement:
    is_pro: bool
    can_scan: bool
    block_reason: str | None


def _profile(client: Client, user_id: str) -> dict | None:
    result = (
        client.table("profiles")
        .select("is_pro")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def evaluate_entitlement(profile: dict | None) -> Entitlement:
    if profile and bool(profile.get("is_pro")):
        return Entitlement(True, True, None)
    return Entitlement(False, False, "subscription_required")


class QuotaService:
    def __init__(self, client: Client, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    def entitlement(self, user_id: str) -> Entitlement:
        return evaluate_entitlement(_profile(self._client, user_id))

    def consume_scan(self, user_id: str) -> Entitlement:
        entitlement = self.entitlement(user_id)
        if entitlement.is_pro:
            return entitlement
        raise SubscriptionRequiredError()

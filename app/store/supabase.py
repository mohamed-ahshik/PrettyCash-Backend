from typing import Any

from app.store.base import JobStatus
from supabase import Client


class SupabaseJobStore:
    TABLE = "receipt_jobs"

    def __init__(self, client: Client) -> None:
        self._client = client

    def create(self) -> str:
        res = self._client.table(self.TABLE).insert({"status": JobStatus.PENDING.value}).execute()
        return res.data[0]["id"]

    def mark_processing(self, job_id: str) -> None:
        self._client.table(self.TABLE).update(
            {"status": JobStatus.PROCESSING.value}
        ).eq("id", job_id).execute()

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        self._client.table(self.TABLE).update(
            {"status": JobStatus.COMPLETED.value, "result": result}
        ).eq("id", job_id).execute()

    def fail(self, job_id: str, code: str, message: str) -> None:
        self._client.table(self.TABLE).update(
            {"status": JobStatus.FAILED.value, "error_code": code, "error_message": message}
        ).eq("id", job_id).execute()

    def get(self, job_id: str) -> dict[str, Any] | None:
        res = self._client.table(self.TABLE).select("*").eq("id", job_id).execute()
        return res.data[0] if res.data else None

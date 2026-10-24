from typing import Any

from postgrest.exceptions import APIError

from app.store.base import CreatedJob, JobStatus
from supabase import Client


class SupabaseJobStore:
    TABLE = "receipt_jobs"

    def __init__(self, client: Client) -> None:
        self._client = client

    def create(self, request_id: str | None = None) -> CreatedJob:
        if request_id:
            existing = self._find_by_request_id(request_id)
            if existing:
                return CreatedJob(existing, False)

        payload: dict[str, Any] = {"status": JobStatus.PENDING.value}
        if request_id:
            payload["request_id"] = request_id
        try:
            res = self._client.table(self.TABLE).insert(payload).execute()
        except APIError as exc:
            if request_id and exc.code == "23505":
                existing = self._find_by_request_id(request_id)
                if existing:
                    return CreatedJob(existing, False)
            raise
        return CreatedJob(res.data[0]["id"], True)

    def _find_by_request_id(self, request_id: str) -> str | None:
        res = (
            self._client.table(self.TABLE)
            .select("id")
            .eq("request_id", request_id)
            .limit(1)
            .execute()
        )
        return res.data[0]["id"] if res.data else None

    def mark_processing(self, job_id: str) -> None:
        self._client.table(self.TABLE).update(
            {"status": JobStatus.PROCESSING.value}
        ).eq("id", job_id).execute()

    def record_classification(self, job_id: str, score: float, model: str) -> None:
        self._client.table(self.TABLE).update(
            {"classifier_score": score, "classifier_model": model}
        ).eq("id", job_id).execute()

    def reject(self, job_id: str, code: str, message: str) -> None:
        self._client.table(self.TABLE).update(
            {
                "status": JobStatus.REJECTED.value,
                "error_code": code,
                "error_message": message,
            }
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

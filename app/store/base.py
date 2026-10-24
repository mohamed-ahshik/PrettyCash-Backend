from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CreatedJob:
    job_id: str
    created: bool


class JobStore(Protocol):
    def create(self, request_id: str | None = None) -> CreatedJob: ...

    def mark_processing(self, job_id: str) -> None: ...

    def record_classification(self, job_id: str, score: float, model: str) -> None: ...

    def complete(self, job_id: str, result: dict[str, Any]) -> None: ...

    def fail(self, job_id: str, code: str, message: str) -> None: ...

    def reject(self, job_id: str, code: str, message: str) -> None: ...

    def get(self, job_id: str) -> dict[str, Any] | None: ...

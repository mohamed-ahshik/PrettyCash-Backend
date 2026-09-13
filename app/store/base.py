from enum import StrEnum
from typing import Any, Protocol


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStore(Protocol):
    def create(self) -> str: ...

    def mark_processing(self, job_id: str) -> None: ...

    def complete(self, job_id: str, result: dict[str, Any]) -> None: ...

    def fail(self, job_id: str, code: str, message: str) -> None: ...

    def get(self, job_id: str) -> dict[str, Any] | None: ...

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Job:
    job_id: str
    image_base64: str
    mime_type: str


class TaskQueue(Protocol):
    def enqueue(self, job: Job) -> None: ...

    def dequeue(self) -> Job | None: ...

    def size(self) -> int: ...

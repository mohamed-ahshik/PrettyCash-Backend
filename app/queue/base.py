from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Job:
    job_id: str
    image_base64: str
    mime_type: str
    auto_categorize: bool = False
    categories: list[dict[str, str]] = field(default_factory=list)


class TaskQueue(Protocol):
    def enqueue(self, job: Job) -> None: ...

    def dequeue(self) -> Job | None: ...

    def size(self) -> int: ...

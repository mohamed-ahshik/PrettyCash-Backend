from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4


@dataclass
class Job:
    image_bytes: bytes
    mime_type: str
    id: str = field(default_factory=lambda: uuid4().hex)


class TaskQueue(Protocol):
    def enqueue(self, job: Job) -> None: ...

    def dequeue(self) -> Job | None: ...

    def size(self) -> int: ...

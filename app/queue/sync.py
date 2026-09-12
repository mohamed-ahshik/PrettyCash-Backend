from collections import deque

from app.queue.base import Job


class SyncQueue:
    def __init__(self) -> None:
        self._jobs: deque[Job] = deque()

    def enqueue(self, job: Job) -> None:
        self._jobs.append(job)

    def dequeue(self) -> Job | None:
        return self._jobs.popleft() if self._jobs else None

    def size(self) -> int:
        return len(self._jobs)

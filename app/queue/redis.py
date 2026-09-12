from app.queue.base import Job


class RedisQueue:
    """Placeholder for the future Redis-backed queue.

    Not wired yet — the API currently uses SyncQueue. When Redis lands,
    this class will implement enqueue/dequeue/size over a Redis list.
    """

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("RedisQueue is not implemented yet; use SyncQueue.")

    def enqueue(self, job: Job) -> None:
        raise NotImplementedError

    def dequeue(self) -> Job | None:
        raise NotImplementedError

    def size(self) -> int:
        raise NotImplementedError

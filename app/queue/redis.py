import json

from app.queue.base import Job

QUEUE_KEY = "receipt:queue"


class RedisQueue:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def enqueue(self, job: Job) -> None:
        payload = json.dumps(
            {"job_id": job.job_id, "image_base64": job.image_base64, "mime_type": job.mime_type}
        )
        self._redis.lpush(QUEUE_KEY, payload)

    def dequeue(self) -> Job | None:
        item = self._redis.brpop(QUEUE_KEY, timeout=1)
        if item is None:
            return None
        data = json.loads(item[1])
        return Job(
            job_id=data["job_id"],
            image_base64=data["image_base64"],
            mime_type=data["mime_type"],
        )

    def size(self) -> int:
        return self._redis.llen(QUEUE_KEY)

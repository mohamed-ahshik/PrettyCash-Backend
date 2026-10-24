import json

from app.queue.base import Job

EXTRACT_QUEUE = "receipt:queue"
CLASSIFY_QUEUE = "receipt:classify"


class RedisQueue:
    def __init__(self, redis_client, queue_key: str = EXTRACT_QUEUE) -> None:
        self._redis = redis_client
        self._queue_key = queue_key

    def enqueue(self, job: Job) -> None:
        payload = json.dumps(
            {
                "job_id": job.job_id,
                "image_base64": job.image_base64,
                "mime_type": job.mime_type,
                "auto_categorize": job.auto_categorize,
                "categories": job.categories,
            }
        )
        self._redis.lpush(self._queue_key, payload)

    def dequeue(self) -> Job | None:
        item = self._redis.brpop(self._queue_key, timeout=1)
        if item is None:
            return None
        data = json.loads(item[1])
        return Job(
            job_id=data["job_id"],
            image_base64=data["image_base64"],
            mime_type=data["mime_type"],
            auto_categorize=bool(data.get("auto_categorize", False)),
            categories=data.get("categories") or [],
        )

    def size(self) -> int:
        return self._redis.llen(self._queue_key)

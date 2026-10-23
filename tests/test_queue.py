import fakeredis

from app.queue.base import Job
from app.queue.redis import RedisQueue
from app.queue.sync import SyncQueue


def test_sync_queue_roundtrip():
    q = SyncQueue()
    job = Job(job_id="abc", image_base64="aGk=", mime_type="image/jpeg")
    q.enqueue(job)
    assert q.size() == 1
    assert q.dequeue() is job
    assert q.dequeue() is None


def test_redis_queue_roundtrip():
    r = fakeredis.FakeRedis(decode_responses=True)
    q = RedisQueue(r)
    job = Job(
        job_id="abc",
        image_base64="aGk=",
        mime_type="image/jpeg",
        auto_categorize=True,
        categories=[{"id": "cat-1", "name": "Food", "description": "Groceries"}],
    )
    q.enqueue(job)
    assert q.size() == 1
    dequeued = q.dequeue()
    assert dequeued == job
    assert dequeued.job_id == "abc"
    assert dequeued.image_base64 == "aGk="
    assert dequeued.auto_categorize is True
    assert dequeued.categories == [{"id": "cat-1", "name": "Food", "description": "Groceries"}]
    assert q.size() == 0


def test_redis_queue_dequeues_legacy_payload():
    r = fakeredis.FakeRedis(decode_responses=True)
    r.lpush("receipt:queue", '{"job_id": "old", "image_base64": "aGk=", "mime_type": "image/jpeg"}')
    q = RedisQueue(r)
    job = q.dequeue()
    assert job is not None
    assert job.auto_categorize is False
    assert job.categories == []


def test_redis_queue_dequeue_empty():
    r = fakeredis.FakeRedis(decode_responses=True)
    q = RedisQueue(r)
    assert q.dequeue() is None


def test_redis_queue_uses_custom_key():
    r = fakeredis.FakeRedis(decode_responses=True)
    q = RedisQueue(r, queue_key="custom:queue")
    job = Job(job_id="abc", image_base64="aGk=", mime_type="image/jpeg")

    q.enqueue(job)

    assert r.llen("custom:queue") == 1
    assert r.llen("receipt:queue") == 0
    assert q.dequeue() == job

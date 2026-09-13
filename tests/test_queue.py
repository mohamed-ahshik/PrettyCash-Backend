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
    job = Job(job_id="abc", image_base64="aGk=", mime_type="image/jpeg")
    q.enqueue(job)
    assert q.size() == 1
    dequeued = q.dequeue()
    assert dequeued == job
    assert dequeued.job_id == "abc"
    assert dequeued.image_base64 == "aGk="
    assert q.size() == 0


def test_redis_queue_dequeue_empty():
    r = fakeredis.FakeRedis(decode_responses=True)
    q = RedisQueue(r)
    assert q.dequeue() is None

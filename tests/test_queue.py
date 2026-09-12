import pytest

from app.queue.base import Job
from app.queue.redis import RedisQueue
from app.queue.sync import SyncQueue


def test_sync_queue_roundtrip():
    q = SyncQueue()
    job = Job(image_bytes=b"img", mime_type="image/jpeg")
    q.enqueue(job)
    assert q.size() == 1
    assert q.dequeue() is job
    assert q.dequeue() is None
    assert q.size() == 0


def test_job_has_unique_id():
    a = Job(image_bytes=b"a", mime_type="image/jpeg")
    b = Job(image_bytes=b"b", mime_type="image/jpeg")
    assert a.id != b.id


def test_redis_queue_is_stub():
    with pytest.raises(NotImplementedError):
        RedisQueue()

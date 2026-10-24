import pytest

from app.queue.base import Job
from app.queue.sync import SyncQueue
from app.services.jev import ClassificationResult, ClassifierUnavailable
from app.workers.classifier import NOT_A_RECEIPT_MESSAGE, process_job


class FakeClassifier:
    def __init__(self, noul=0.9, error=None):
        self.noul = noul
        self.error = error

    def classify(self, image_bytes: bytes) -> ClassificationResult:
        if self.error is not None:
            raise self.error
        return ClassificationResult(noul=self.noul, model="typesafe/jev-1.14")


class FailingQueue:
    def enqueue(self, job: Job) -> None:
        raise RuntimeError("redis down")

    def dequeue(self) -> Job | None:
        return None

    def size(self) -> int:
        return 0


class RecordingStore:
    def __init__(self):
        self.rows = {}
        self.rejected = None

    def mark_processing(self, job_id: str) -> None:
        self.rows.setdefault(job_id, {})["status"] = "processing"

    def record_classification(self, job_id: str, score: float, model: str) -> None:
        self.rows.setdefault(job_id, {}).update(
            {"classifier_score": score, "classifier_model": model}
        )

    def reject(self, job_id: str, code: str, message: str) -> None:
        self.rejected = (job_id, code, message)
        self.rows.setdefault(job_id, {}).update(
            {"status": "rejected", "error_code": code, "error_message": message}
        )

    def fail(self, job_id: str, code: str, message: str) -> None:
        self.rows.setdefault(job_id, {}).update(
            {"status": "failed", "error_code": code, "error_message": message}
        )

    def get(self, job_id: str):
        return self.rows.get(job_id)


class FailingRecordStore(RecordingStore):
    def record_classification(self, job_id: str, score: float, model: str) -> None:
        raise RuntimeError("db down")


class FailingRejectStore(RecordingStore):
    def reject(self, job_id: str, code: str, message: str) -> None:
        raise RuntimeError("db down")


def _job() -> Job:
    return Job(job_id="job-1", image_base64="aGk=", mime_type="image/jpeg")


def test_process_job_rejects_non_receipt(job_store):
    extract = SyncQueue()

    result = process_job(_job(), FakeClassifier(noul=0.1), extract, job_store, threshold=0.3)

    assert result is False
    row = job_store.get("job-1")
    assert row["status"] == "rejected"
    assert row["error_code"] == "NOT_A_RECEIPT"
    assert row["error_message"] == NOT_A_RECEIPT_MESSAGE
    assert row["classifier_score"] == 0.1
    assert row["classifier_model"] == "typesafe/jev-1.14"
    assert extract.size() == 0


def test_process_job_forwards_receipt(job_store):
    extract = SyncQueue()
    job = _job()

    result = process_job(job, FakeClassifier(noul=0.9), extract, job_store, threshold=0.3)

    assert result is True
    row = job_store.get("job-1")
    assert row["status"] == "processing"
    assert row["classifier_score"] == 0.9
    assert row["classifier_model"] == "typesafe/jev-1.14"
    assert extract.dequeue() == job


@pytest.mark.parametrize("error", [ClassifierUnavailable("down"), RuntimeError("boom")])
def test_process_job_fails_open_on_classifier_error(job_store, error):
    extract = SyncQueue()
    job = _job()

    result = process_job(job, FakeClassifier(error=error), extract, job_store, threshold=0.3)

    assert result is True
    row = job_store.get("job-1")
    assert row["status"] == "processing"
    assert "classifier_score" not in row
    assert extract.dequeue() == job


def test_process_job_fails_when_forwarding_fails(job_store):
    result = process_job(
        _job(), FakeClassifier(noul=0.9), FailingQueue(), job_store, threshold=0.3
    )

    assert result is False
    row = job_store.get("job-1")
    assert row["status"] == "failed"
    assert row["error_code"] == "INTERNAL"
    assert row["error_message"] == "Receipt processing failed"


def test_process_job_forwards_category_fields(job_store):
    extract = SyncQueue()
    job = Job(
        job_id="job-1",
        image_base64="aGk=",
        mime_type="image/jpeg",
        auto_categorize=True,
        categories=[{"id": "cat-food", "name": "Food", "description": "Groceries"}],
    )

    result = process_job(job, FakeClassifier(noul=0.9), extract, job_store, threshold=0.3)

    assert result is True
    forwarded = extract.dequeue()
    assert forwarded is not None
    assert forwarded.auto_categorize is True
    assert forwarded.categories == [
        {"id": "cat-food", "name": "Food", "description": "Groceries"}
    ]


def test_record_failure_does_not_change_routing_to_reject():
    store = FailingRecordStore()
    extract = SyncQueue()

    result = process_job(_job(), FakeClassifier(noul=0.1), extract, store, threshold=0.3)

    assert result is False
    assert store.rejected == ("job-1", "NOT_A_RECEIPT", NOT_A_RECEIPT_MESSAGE)
    assert extract.size() == 0


def test_record_failure_does_not_prevent_forwarding_receipt():
    store = FailingRecordStore()
    extract = SyncQueue()
    job = _job()

    result = process_job(job, FakeClassifier(noul=0.9), extract, store, threshold=0.3)

    assert result is True
    assert extract.dequeue() == job


def test_reject_failure_does_not_forward_to_gemini():
    store = FailingRejectStore()
    extract = SyncQueue()

    result = process_job(_job(), FakeClassifier(noul=0.1), extract, store, threshold=0.3)

    assert result is False
    assert extract.size() == 0
    assert store.get("job-1")["status"] == "processing"

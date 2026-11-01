import pytest

from app.queue.base import Job
from app.services.analytics import LLMCallRecord
from app.services.receipt import ReceiptDraft
from app.workers.worker import process_job


class FakeAnalyzer:
    def analyze(self, image_bytes: bytes, mime_type: str, **kwargs) -> ReceiptDraft:
        return ReceiptDraft(merchant="X", amount=1.0)


class FailingAnalyzer:
    def analyze(self, image_bytes: bytes, mime_type: str, **kwargs) -> ReceiptDraft:
        raise RuntimeError("boom")


class RecordingAnalyzer:
    def __init__(self):
        self.kwargs = None

    def analyze(self, image_bytes: bytes, mime_type: str, **kwargs) -> ReceiptDraft:
        self.kwargs = kwargs
        return ReceiptDraft(merchant="X", amount=1.0)


def test_process_job_completes(job_store):
    job = Job(job_id="job-1", image_base64="aGk=", mime_type="image/jpeg")
    draft = process_job(job, FakeAnalyzer(), job_store)
    assert draft.merchant == "X"
    assert job_store.get("job-1")["status"] == "completed"
    assert job_store.get("job-1")["result"]["merchant"] == "X"


def test_process_job_passes_category_fields(job_store):
    job = Job(
        job_id="job-1",
        image_base64="aGk=",
        mime_type="image/jpeg",
        auto_categorize=True,
        categories=[{"id": "cat-food", "name": "Food", "description": "Groceries"}],
    )
    analyzer = RecordingAnalyzer()

    process_job(job, analyzer, job_store)

    assert analyzer.kwargs == {
        "categories": [{"id": "cat-food", "name": "Food", "description": "Groceries"}],
        "auto_categorize": True,
        "job_id": "job-1",
        "on_llm_call": None,
    }


class FakeAnalytics:
    def __init__(self):
        self.calls = []

    def capture_generation(self, record, **kwargs):
        self.calls.append((record, kwargs))


class EmittingAnalyzer:
    def analyze(self, image_bytes: bytes, mime_type: str, **kwargs) -> ReceiptDraft:
        callback = kwargs.get("on_llm_call")
        if callback is not None:
            callback(
                LLMCallRecord(
                    model="gemini/gemini-3.1-flash-lite",
                    provider="google",
                    input_tokens=10,
                    output_tokens=2,
                    total_tokens=12,
                    cost_usd=0.001,
                    cost_source="litellm",
                    latency_seconds=0.5,
                )
            )
        return ReceiptDraft(merchant="X", amount=1.0)


def test_process_job_emits_extraction_event(job_store):
    job = Job(
        job_id="job-1",
        image_base64="aGk=",
        mime_type="image/jpeg",
        auto_categorize=True,
        user_id="user-1",
    )
    analytics = FakeAnalytics()

    process_job(job, EmittingAnalyzer(), job_store, analytics)

    assert len(analytics.calls) == 1
    record, kwargs = analytics.calls[0]
    assert record.model == "gemini/gemini-3.1-flash-lite"
    assert kwargs == {
        "job_id": "job-1",
        "span_name": "receipt_extraction",
        "user_id": "user-1",
        "auto_categorize": True,
    }


def test_process_job_fails_on_error(job_store):
    job = Job(job_id="job-1", image_base64="aGk=", mime_type="image/jpeg")
    with pytest.raises(RuntimeError):
        process_job(job, FailingAnalyzer(), job_store)
    assert job_store.get("job-1")["status"] == "failed"
    assert job_store.get("job-1")["error_code"] == "INTERNAL"
    assert job_store.get("job-1")["error_message"] == "Receipt analysis failed"

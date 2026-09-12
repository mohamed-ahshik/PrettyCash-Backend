from app.queue.base import Job
from app.services.receipt import ReceiptDraft
from app.workers.worker import process_job


class FakeAnalyzer:
    def analyze(self, image_bytes: bytes, mime_type: str) -> ReceiptDraft:
        return ReceiptDraft(merchant="X", amount=1.0)


def test_process_job_returns_draft():
    analyzer = FakeAnalyzer()
    job = Job(image_bytes=b"img", mime_type="image/jpeg")
    draft = process_job(job, analyzer)
    assert draft.merchant == "X"
    assert draft.amount == 1.0

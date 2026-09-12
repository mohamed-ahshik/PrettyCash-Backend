import logging
import threading
import time

from app.core.config import get_settings
from app.queue.base import Job, TaskQueue
from app.queue.sync import SyncQueue
from app.services.gemini import GeminiClient
from app.services.receipt import ReceiptAnalyzer, ReceiptDraft

logger = logging.getLogger(__name__)


def process_job(job: Job, analyzer: ReceiptAnalyzer) -> ReceiptDraft:
    return analyzer.analyze(job.image_bytes, job.mime_type)


def run_worker(
    queue: TaskQueue,
    analyzer: ReceiptAnalyzer,
    stop_event: threading.Event | None = None,
    poll_interval: float = 1.0,
) -> None:
    while stop_event is None or not stop_event.is_set():
        job = queue.dequeue()
        if job is None:
            time.sleep(poll_interval)
            continue
        try:
            process_job(job, analyzer)
            logger.info("Processed job %s", job.id)
        except Exception:  # noqa: BLE001 - worker must keep running on bad jobs
            logger.exception("Failed to process job %s", job.id)


def main() -> None:
    settings = get_settings()
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model)
    analyzer = ReceiptAnalyzer(gemini)
    queue = SyncQueue()
    run_worker(queue, analyzer)


if __name__ == "__main__":
    main()

import base64
import logging
import threading
import time

from redis import Redis

from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.core.logging import configure_logging
from app.queue.base import Job, TaskQueue
from app.queue.redis import CLASSIFY_QUEUE, EXTRACT_QUEUE, RedisQueue
from app.services.classifier import ReceiptClassifier
from app.services.jev import ClassifierUnavailable, JevClient
from app.store.base import JobStore
from app.store.supabase import SupabaseJobStore
from supabase import create_client

logger = logging.getLogger(__name__)

NOT_A_RECEIPT_MESSAGE = "This image doesn't look like a receipt or invoice."
PROCESSING_FAILED_MESSAGE = "Receipt processing failed"


def _forward(job: Job, extract_queue: TaskQueue, job_store: JobStore) -> bool:
    try:
        extract_queue.enqueue(job)
        return True
    except Exception:
        logger.exception("Could not enqueue job %s for extraction", job.job_id)
        job_store.fail(job.job_id, ErrorCode.INTERNAL.value, PROCESSING_FAILED_MESSAGE)
        return False


def _log_fallback(job_id: str, reason: str, started: float) -> None:
    logger.warning(
        "Classifier fallback job_id=%s fallback_reason=%s latency_ms=%d",
        job_id,
        reason,
        int((time.monotonic() - started) * 1000),
    )


def process_job(
    job: Job,
    classifier: ReceiptClassifier,
    extract_queue: TaskQueue,
    job_store: JobStore,
    threshold: float,
) -> bool:
    started = time.monotonic()
    job_store.mark_processing(job.job_id)

    try:
        image_bytes = base64.b64decode(job.image_base64)
    except Exception:
        logger.exception("Could not decode job %s; forwarding to extraction", job.job_id)
        _log_fallback(job.job_id, "invalid_base64", started)
        return _forward(job, extract_queue, job_store)

    try:
        result = classifier.classify(image_bytes)
    except ClassifierUnavailable as exc:
        _log_fallback(job.job_id, str(exc), started)
        return _forward(job, extract_queue, job_store)
    except Exception as exc:
        logger.exception(
            "Unexpected classifier error for job %s; forwarding to extraction", job.job_id
        )
        _log_fallback(job.job_id, type(exc).__name__, started)
        return _forward(job, extract_queue, job_store)

    decision = "reject" if result.noul < threshold else "accept"
    logger.info(
        "Classifier decision job_id=%s noul=%.4f threshold=%.2f decision=%s latency_ms=%d",
        job.job_id,
        result.noul,
        threshold,
        decision,
        int((time.monotonic() - started) * 1000),
    )

    try:
        job_store.record_classification(job.job_id, result.noul, result.model)
    except Exception:
        logger.exception("Could not persist classifier score for job %s", job.job_id)

    if result.noul < threshold:
        try:
            job_store.reject(
                job.job_id, ErrorCode.NOT_A_RECEIPT.value, NOT_A_RECEIPT_MESSAGE
            )
        except Exception:
            logger.exception("Could not mark job %s rejected", job.job_id)
        return False

    return _forward(job, extract_queue, job_store)


def run_worker(
    queue: TaskQueue,
    extract_queue: TaskQueue,
    classifier: ReceiptClassifier,
    job_store: JobStore,
    threshold: float,
    stop_event: threading.Event | None = None,
    poll_interval: float = 1.0,
) -> None:
    while stop_event is None or not stop_event.is_set():
        try:
            job = queue.dequeue()
        except Exception:
            logger.exception("Queue dequeue failed; retrying")
            time.sleep(poll_interval)
            continue
        if job is None:
            time.sleep(poll_interval)
            continue
        try:
            process_job(job, classifier, extract_queue, job_store, threshold)
            logger.info("Classified job %s", job.job_id)
        except Exception:
            logger.exception("Failed to classify job %s", job.job_id)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.openrouter_jev_api_key:
        logger.warning(
            "OPENROUTER_JEV_API_KEY is empty; all jobs will be forwarded to Gemini"
        )

    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    queue = RedisQueue(redis_client, CLASSIFY_QUEUE)
    extract_queue = RedisQueue(redis_client, EXTRACT_QUEUE)
    job_store = SupabaseJobStore(
        create_client(settings.supabase_url, settings.supabase_service_role_key)
    )
    jev = JevClient(
        settings.openrouter_jev_api_key,
        settings.openrouter_jev_model,
        timeout=settings.openrouter_timeout_seconds,
    )
    classifier = ReceiptClassifier(jev)
    run_worker(
        queue,
        extract_queue,
        classifier,
        job_store,
        settings.receipt_classifier_threshold,
    )


if __name__ == "__main__":
    main()

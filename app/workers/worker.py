import base64
import logging
import threading
import time

from redis import Redis

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging
from app.queue.base import Job, TaskQueue
from app.queue.redis import EXTRACT_QUEUE, RedisQueue
from app.services.analytics import Analytics, PostHogAnalytics
from app.services.gemini import GeminiClient
from app.services.receipt import ReceiptAnalyzer, ReceiptDraft
from app.store.base import JobStore
from app.store.supabase import SupabaseJobStore
from supabase import create_client

logger = logging.getLogger(__name__)


def _to_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, AppError) and exc.code != ErrorCode.INTERNAL:
        return exc.code.value, exc.message
    return ErrorCode.INTERNAL.value, "Receipt analysis failed"


def process_job(
    job: Job,
    analyzer: ReceiptAnalyzer,
    job_store: JobStore,
    analytics: Analytics | None = None,
) -> ReceiptDraft:
    on_llm_call = None
    if analytics is not None:
        def on_llm_call(record):
            analytics.capture_generation(
                record,
                job_id=job.job_id,
                span_name="receipt_extraction",
                user_id=job.user_id,
                auto_categorize=job.auto_categorize,
            )

    try:
        job_store.mark_processing(job.job_id)
        image_bytes = base64.b64decode(job.image_base64)
        draft = analyzer.analyze(
            image_bytes,
            job.mime_type,
            categories=job.categories,
            auto_categorize=job.auto_categorize,
            job_id=job.job_id,
            on_llm_call=on_llm_call,
        )
    except Exception as exc:
        code, message = _to_error(exc)
        job_store.fail(job.job_id, code, message)
        raise
    job_store.complete(job.job_id, draft.model_dump(exclude_none=True))
    return draft


def run_worker(
    queue: TaskQueue,
    analyzer: ReceiptAnalyzer,
    job_store: JobStore,
    analytics: Analytics | None = None,
    stop_event: threading.Event | None = None,
    poll_interval: float = 1.0,
) -> None:
    while stop_event is None or not stop_event.is_set():
        try:
            job = queue.dequeue()
        except Exception:  # noqa: BLE001 - Redis blip must not kill the worker
            logger.exception("Queue dequeue failed; retrying")
            time.sleep(poll_interval)
            continue
        if job is None:
            time.sleep(poll_interval)
            continue
        try:
            process_job(job, analyzer, job_store, analytics)
            logger.info("Processed job %s", job.job_id)
        except Exception:  # noqa: BLE001 - worker must keep running on bad jobs
            logger.exception("Failed to process job %s", job.job_id)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    queue = RedisQueue(redis_client, EXTRACT_QUEUE)
    job_store = SupabaseJobStore(
        create_client(settings.supabase_url, settings.supabase_service_role_key)
    )
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model)
    analyzer = ReceiptAnalyzer(
        gemini, settings.receipt_category_confidence_threshold
    )
    analytics = PostHogAnalytics.from_settings(settings)
    try:
        run_worker(queue, analyzer, job_store, analytics)
    finally:
        analytics.flush()


if __name__ == "__main__":
    main()

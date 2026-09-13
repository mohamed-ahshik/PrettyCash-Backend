import base64

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_api_key, require_rate_limit
from app.api.v1.schemas import AnalyzeReceiptAccepted, AnalyzeReceiptRequest, JobStatusResponse
from app.core.errors import NotFoundError
from app.queue.base import Job
from app.services.image import decode_and_process

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/analyze-receipt", response_model=AnalyzeReceiptAccepted, status_code=202)
async def analyze_receipt(
    payload: AnalyzeReceiptRequest,
    request: Request,
    _token: str = Depends(require_rate_limit),
):
    settings = request.app.state.settings
    queue = request.app.state.queue
    job_store = request.app.state.job_store

    image_bytes, mime_type = await run_in_threadpool(
        decode_and_process, payload.image.base64, settings
    )
    job_id = job_store.create()
    queue.enqueue(
        Job(
            job_id=job_id,
            image_base64=base64.b64encode(image_bytes).decode(),
            mime_type=mime_type,
        )
    )
    return {"jobId": job_id, "status": "pending"}


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    response_model_exclude_none=True,
)
async def get_job(job_id: str, request: Request, _token: str = Depends(require_api_key)):
    row = request.app.state.job_store.get(job_id)
    if row is None:
        raise NotFoundError("Job not found")
    return _to_status_response(row)


def _to_status_response(row: dict) -> dict:
    status = row["status"]
    if status == "completed":
        return {"status": status, "result": row["result"]}
    if status == "failed":
        return {
            "status": status,
            "error": {"code": row["error_code"], "message": row["error_message"]},
        }
    return {"status": status}

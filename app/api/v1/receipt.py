from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_rate_limit
from app.api.v1.schemas import AnalyzeReceiptRequest, AnalyzeReceiptResponse
from app.services.image import decode_and_process

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/analyze-receipt",
    response_model=AnalyzeReceiptResponse,
    response_model_exclude_none=True,
)
async def analyze_receipt(
    payload: AnalyzeReceiptRequest,
    request: Request,
    _token: str = Depends(require_rate_limit),
):
    settings = request.app.state.settings
    analyzer = request.app.state.analyzer

    image_bytes, mime_type = await run_in_threadpool(
        decode_and_process, payload.image.base64, settings
    )
    return await run_in_threadpool(analyzer.analyze, image_bytes, mime_type)

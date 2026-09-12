import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.deps import RateLimiter
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode, InternalError
from app.core.logging import configure_logging
from app.queue.sync import SyncQueue
from app.services.gemini import GeminiClient
from app.services.receipt import ReceiptAnalyzer


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="PrettyCash Backend", version="0.1.0")

    app.state.settings = settings
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.queue = SyncQueue()
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model)
    app.state.analyzer = ReceiptAnalyzer(gemini)

    app.include_router(api_router)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        message = exc.default_message if exc.code == ErrorCode.INTERNAL else exc.message
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code.value, "message": message}},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("Unhandled error", exc_info=exc)
        internal = InternalError()
        return JSONResponse(
            status_code=internal.status_code,
            content={"error": {"code": internal.code.value, "message": internal.message}},
        )

    return app

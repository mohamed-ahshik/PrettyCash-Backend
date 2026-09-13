import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode, InternalError
from app.core.logging import configure_logging
from app.queue.redis import RedisQueue
from app.services.ratelimit import RedisRateLimiter
from app.store.base import JobStore
from app.store.supabase import SupabaseJobStore
from supabase import create_client


def create_app(
    settings: Settings | None = None,
    *,
    job_store: JobStore | None = None,
    redis_client: Redis | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    redis_client = redis_client or Redis.from_url(settings.redis_url, decode_responses=True)
    job_store = job_store or SupabaseJobStore(
        create_client(settings.supabase_url, settings.supabase_service_role_key)
    )

    app = FastAPI(title="PrettyCash Backend", version="0.1.0")

    app.state.settings = settings
    app.state.queue = RedisQueue(redis_client)
    app.state.rate_limiter = RedisRateLimiter(redis_client, settings.rate_limit_per_minute)
    app.state.job_store = job_store

    app.include_router(api_router)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        message = exc.default_message if exc.code == ErrorCode.INTERNAL else exc.message
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code.value, "message": message}},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": ErrorCode.UNPROCESSABLE.value, "message": "Invalid request"}
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = ErrorCode.INTERNAL if exc.status_code >= 500 else ErrorCode.UNPROCESSABLE
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code.value, "message": str(exc.detail)}},
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

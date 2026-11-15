from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse

router = APIRouter()

PRIVACY_PAGE = Path(__file__).resolve().parents[1] / "static" / "privacy.html"


@router.get("/", include_in_schema=False)
async def root() -> PlainTextResponse:
    return PlainTextResponse("PrettyCash")


@router.get("/privacy", include_in_schema=False)
async def privacy_policy() -> FileResponse:
    return FileResponse(
        PRIVACY_PAGE,
        media_type="text/html",
        headers={"Cache-Control": "public, max-age=300"},
    )

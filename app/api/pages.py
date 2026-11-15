from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

PRIVACY_PAGE = Path(__file__).resolve().parents[1] / "static" / "privacy.html"


@router.get("/privacy", include_in_schema=False)
async def privacy_policy() -> FileResponse:
    return FileResponse(
        PRIVACY_PAGE,
        media_type="text/html",
        headers={"Cache-Control": "public, max-age=300"},
    )

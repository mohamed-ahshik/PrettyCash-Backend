from fastapi import APIRouter

from app.api.v1 import receipt

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(receipt.router)

from fastapi import APIRouter

from app.api.v1 import billing, receipt

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(receipt.router)
api_router.include_router(billing.router)

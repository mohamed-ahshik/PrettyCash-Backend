from pydantic import BaseModel

from app.services.receipt import LineItem


class ImagePayload(BaseModel):
    base64: str
    mimeType: str


class AnalyzeReceiptRequest(BaseModel):
    image: ImagePayload


class AnalyzeReceiptResponse(BaseModel):
    merchant: str
    amount: float
    date: str | None = None
    time: str | None = None
    note: str = ""
    items: list[LineItem] = []

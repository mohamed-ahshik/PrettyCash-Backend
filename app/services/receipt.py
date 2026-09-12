import base64
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import UnprocessableError
from app.services.gemini import GeminiClient


class LineItem(BaseModel):
    name: str
    quantity: float | None = None
    price: float


class ReceiptDraft(BaseModel):
    merchant: str = ""
    amount: float = Field(gt=0)
    date: str | None = None
    time: str | None = None
    note: str = ""
    items: list[LineItem] = Field(default_factory=list)


class ReceiptAnalyzer:
    def __init__(self, gemini: GeminiClient) -> None:
        self._gemini = gemini

    def analyze(self, image_bytes: bytes, mime_type: str) -> ReceiptDraft:
        image_base64 = base64.b64encode(image_bytes).decode()
        raw = self._gemini.analyze(image_base64, mime_type)
        return self._normalize(raw)

    def _normalize(self, raw: dict[str, Any]) -> ReceiptDraft:
        try:
            return ReceiptDraft(**raw)
        except ValidationError as exc:
            raise UnprocessableError("Receipt data could not be parsed") from exc

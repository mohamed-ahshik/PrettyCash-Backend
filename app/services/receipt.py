import base64
import logging
import math
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import UnprocessableError
from app.services.gemini import GeminiClient

logger = logging.getLogger(__name__)


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
    categoryId: str | None = None
    categoryConfidence: float | None = None


def _valid_confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    confidence = float(value)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return None
    return confidence


class ReceiptAnalyzer:
    def __init__(
        self,
        gemini: GeminiClient,
        category_confidence_threshold: float = 0.7,
    ) -> None:
        self._gemini = gemini
        self._category_confidence_threshold = category_confidence_threshold

    def analyze(
        self,
        image_bytes: bytes,
        mime_type: str,
        categories: list[dict[str, str]] | None = None,
        auto_categorize: bool = False,
        job_id: str | None = None,
    ) -> ReceiptDraft:
        keyed_categories: list[dict[str, str]] = []
        if auto_categorize and categories:
            keyed_categories = [
                {
                    "key": f"c{index}",
                    "id": category["id"],
                    "name": category["name"],
                    "description": category.get("description", ""),
                }
                for index, category in enumerate(categories, start=1)
            ]

        image_base64 = base64.b64encode(image_bytes).decode()
        raw = self._gemini.analyze(
            image_base64,
            mime_type,
            categories=keyed_categories,
        )
        return self._normalize(raw, keyed_categories, job_id)

    def _normalize(
        self,
        raw: dict[str, Any],
        keyed_categories: list[dict[str, str]],
        job_id: str | None = None,
    ) -> ReceiptDraft:
        data = dict(raw)
        category_key = data.pop("categoryKey", None)
        confidence = _valid_confidence(data.pop("categoryConfidence", None))
        if not keyed_categories:
            category_key = None
            confidence = None

        category_id = None
        if (
            category_key
            and confidence is not None
            and confidence >= self._category_confidence_threshold
        ):
            category_id = next(
                (
                    category["id"]
                    for category in keyed_categories
                    if category["key"] == category_key
                ),
                None,
            )

        if not keyed_categories:
            decision = "not_requested"
        elif category_key is None:
            decision = "no_match"
        elif confidence is None:
            decision = "invalid_confidence"
        elif confidence < self._category_confidence_threshold:
            decision = "below_threshold"
        elif category_id is None:
            decision = "no_match"
        else:
            decision = "accepted"

        logger.info(
            "Receipt category decision job_id=%s category_key=%s confidence=%s "
            "threshold=%.2f decision=%s",
            job_id,
            category_key,
            confidence,
            self._category_confidence_threshold,
            decision,
        )

        data["categoryId"] = category_id
        data["categoryConfidence"] = confidence

        try:
            return ReceiptDraft(**data)
        except ValidationError as exc:
            raise UnprocessableError("Receipt data could not be parsed") from exc

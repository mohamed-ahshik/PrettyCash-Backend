import json

import httpx

from app.core.errors import InternalError

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

RECEIPT_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "merchant": {"type": "STRING"},
        "amount": {"type": "NUMBER"},
        "date": {"type": "STRING", "nullable": True},
        "time": {"type": "STRING", "nullable": True},
        "note": {"type": "STRING"},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "quantity": {"type": "NUMBER", "nullable": True},
                    "price": {"type": "NUMBER"},
                },
                "required": ["name", "price"],
            },
        },
    },
    "required": ["merchant", "amount", "items"],
}

PROMPT = (
    "You are a receipt scanner. Extract the following fields from the receipt image and "
    "return them as JSON matching the requested schema:\n"
    "- merchant: the store or merchant name (empty string if unreadable)\n"
    "- amount: the receipt grand total as a positive number\n"
    "- date: the receipt date as YYYY-MM-DD if present, otherwise null\n"
    "- time: the receipt time as HH:mm in 24-hour format if present, otherwise null\n"
    "- note: a short note about the purchase, empty string if none\n"
    "- items: the line items; each item has name, quantity (if meaningful), and price "
    "(the line-item total)\n"
    "Return only JSON."
)


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def analyze(self, image_base64: str, mime_type: str) -> dict:
        url = GEMINI_URL.format(model=self._model)
        body = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": image_base64}},
                        {"text": PROMPT},
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RECEIPT_RESPONSE_SCHEMA,
            },
        }
        try:
            response = httpx.post(
                url, params={"key": self._api_key}, json=body, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise InternalError("AI provider unavailable") from exc

        if response.status_code != 200:
            raise InternalError("AI provider error")

        try:
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise InternalError("Unexpected AI provider response") from exc

import base64
import io
import json

import httpx
import respx
from PIL import Image

from app.core.config import Settings
from app.main import create_app

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite"
    ":generateContent"
)

AUTH = {"Authorization": "Bearer test-vision-key"}


def _png_base64() -> str:
    img = Image.new("RGB", (64, 64), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _payload() -> dict:
    return {"image": {"base64": _png_base64(), "mimeType": "image/png"}}


def _gemini_body() -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "merchant": "Whole Foods",
                                    "amount": 42.75,
                                    "date": "2026-09-13",
                                    "time": "14:30",
                                    "note": "groceries",
                                    "items": [
                                        {"name": "Almond Milk", "quantity": 2, "price": 6.98}
                                    ],
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }


async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_analyze_receipt_success(client):
    with respx.mock:
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=_gemini_body()))
        response = await client.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["merchant"] == "Whole Foods"
    assert body["amount"] == 42.75
    assert body["date"] == "2026-09-13"
    assert body["time"] == "14:30"
    assert body["note"] == "groceries"
    assert body["items"][0] == {"name": "Almond Milk", "quantity": 2, "price": 6.98}


async def test_analyze_receipt_omits_null_date_and_time(client):
    text = json.dumps({"merchant": "X", "amount": 5.0})
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    with respx.mock:
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=body))
        response = await client.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)

    assert response.status_code == 200
    data = response.json()
    assert "date" not in data
    assert "time" not in data
    assert data["items"] == []


async def test_analyze_receipt_missing_key(client):
    response = await client.post("/api/v1/analyze-receipt", json=_payload())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_analyze_receipt_wrong_key(client):
    response = await client.post(
        "/api/v1/analyze-receipt",
        json=_payload(),
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_analyze_receipt_validation_error_uses_contract_shape(client):
    response = await client.post(
        "/api/v1/analyze-receipt",
        json={"image": {"mimeType": "image/png"}},  # missing base64
        headers=AUTH,
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "UNPROCESSABLE", "message": "Invalid request"}
    }


async def test_analyze_receipt_invalid_image(client):
    response = await client.post(
        "/api/v1/analyze-receipt",
        json={"image": {"base64": "!!!", "mimeType": "image/png"}},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IMAGE"


async def test_analyze_receipt_provider_error_is_internal(client):
    with respx.mock:
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(500))
        response = await client.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "INTERNAL", "message": "Internal server error"}}


async def test_analyze_receipt_rate_limited():
    app = create_app(
        Settings(
            gemini_api_key="g",
            vision_api_key="test-vision-key",
            redis_url="redis://localhost:6379/0",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="key",
            rate_limit_per_minute=1,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        with respx.mock:
            respx.post(GEMINI_URL).mock(
                return_value=httpx.Response(200, json=_gemini_body())
            )
            first = await c.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)
            second = await c.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"

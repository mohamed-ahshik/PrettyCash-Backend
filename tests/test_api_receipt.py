import base64
import io
import json

import fakeredis
import httpx
from PIL import Image

from app.core.config import Settings
from app.main import create_app

AUTH = {"Authorization": "Bearer test-vision-key"}


def _png_base64() -> str:
    img = Image.new("RGB", (64, 64), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _payload() -> dict:
    return {"image": {"base64": _png_base64(), "mimeType": "image/png"}}


async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_analyze_receipt_enqueues(client, job_store):
    response = await client.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    job_id = body["jobId"]
    assert job_id
    assert job_store.get(job_id)["status"] == "pending"


async def test_analyze_receipt_missing_key(client):
    response = await client.post("/api/v1/analyze-receipt", json=_payload())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_analyze_receipt_wrong_key(client):
    response = await client.post(
        "/api/v1/analyze-receipt", json=_payload(), headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 401


async def test_analyze_receipt_validation_error_uses_contract_shape(client):
    response = await client.post(
        "/api/v1/analyze-receipt",
        json={"image": {"mimeType": "image/png"}},
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


async def test_get_job_not_found(client):
    response = await client.get("/api/v1/jobs/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_get_job_pending(client):
    response = await client.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)
    job_id = response.json()["jobId"]

    get_response = await client.get(f"/api/v1/jobs/{job_id}", headers=AUTH)
    assert get_response.status_code == 200
    assert get_response.json() == {"status": "pending"}


async def test_get_job_completed(client, job_store):
    job_id = job_store.create()
    job_store.complete(
        job_id,
        {"merchant": "Whole Foods", "amount": 42.75, "note": "", "items": []},
    )
    response = await client.get(f"/api/v1/jobs/{job_id}", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["merchant"] == "Whole Foods"
    assert body["result"]["amount"] == 42.75


async def test_get_job_failed(client, job_store):
    job_id = job_store.create()
    job_store.fail(job_id, "INTERNAL", "Receipt analysis failed")
    response = await client.get(f"/api/v1/jobs/{job_id}", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == {"code": "INTERNAL", "message": "Receipt analysis failed"}


async def test_analyze_receipt_rate_limited(job_store):
    app = create_app(
        Settings(
            gemini_api_key="g",
            vision_api_key="test-vision-key",
            redis_url="redis://localhost:6379/0",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="key",
            rate_limit_per_minute=1,
        ),
        job_store=job_store,
        redis_client=fakeredis.FakeRedis(decode_responses=True),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        first = await c.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)
        second = await c.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"


async def test_get_job_not_rate_limited(job_store):
    app = create_app(
        Settings(
            gemini_api_key="g",
            vision_api_key="test-vision-key",
            redis_url="redis://localhost:6379/0",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="key",
            rate_limit_per_minute=1,
        ),
        job_store=job_store,
        redis_client=fakeredis.FakeRedis(decode_responses=True),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        post = await c.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)
        assert post.status_code == 202
        job_id = post.json()["jobId"]
        get = await c.get(f"/api/v1/jobs/{job_id}", headers=AUTH)

    assert get.status_code == 200


async def test_analyze_receipt_enqueues_to_classify_queue(job_store):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    app = create_app(
        Settings(
            gemini_api_key="g",
            vision_api_key="test-vision-key",
            redis_url="redis://localhost:6379/0",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="key",
        ),
        job_store=job_store,
        redis_client=redis_client,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/api/v1/analyze-receipt", json=_payload(), headers=AUTH)

    assert response.status_code == 202
    assert redis_client.llen("receipt:classify") == 1
    assert redis_client.llen("receipt:queue") == 0


async def test_analyze_receipt_enqueues_category_fields(job_store):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    app = create_app(
        Settings(
            gemini_api_key="g",
            vision_api_key="test-vision-key",
            redis_url="redis://localhost:6379/0",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="key",
        ),
        job_store=job_store,
        redis_client=redis_client,
    )
    transport = httpx.ASGITransport(app=app)
    categories = [
        {"id": "cat-food", "name": "Food", "description": "Groceries & dining"},
        {"id": "cat-travel", "name": "Travel", "description": "Commute & transit"},
    ]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post(
            "/api/v1/analyze-receipt",
            json={**_payload(), "autoCategorize": True, "categories": categories},
            headers=AUTH,
        )

    assert response.status_code == 202
    payload = json.loads(redis_client.lindex("receipt:classify", 0))
    assert payload["auto_categorize"] is True
    assert payload["categories"] == categories


async def test_analyze_receipt_rejects_too_many_categories(client):
    response = await client.post(
        "/api/v1/analyze-receipt",
        json={
            **_payload(),
            "autoCategorize": True,
            "categories": [
                {"id": f"cat-{index}", "name": f"Category {index}", "description": ""}
                for index in range(51)
            ],
        },
        headers=AUTH,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNPROCESSABLE"


async def test_analyze_receipt_rejects_long_category_description(client):
    response = await client.post(
        "/api/v1/analyze-receipt",
        json={
            **_payload(),
            "autoCategorize": True,
            "categories": [
                {"id": "cat-1", "name": "Food", "description": "x" * 201}
            ],
        },
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_analyze_receipt_rejects_long_category_name(client):
    response = await client.post(
        "/api/v1/analyze-receipt",
        json={
            **_payload(),
            "autoCategorize": True,
            "categories": [
                {"id": "cat-1", "name": "x" * 81, "description": ""}
            ],
        },
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_get_job_rejected(client, job_store):
    job_id = job_store.create()
    job_store.record_classification(job_id, 0.05, "typesafe/jev-1.14")
    job_store.reject(
        job_id,
        "NOT_A_RECEIPT",
        "This image doesn't look like a receipt or invoice.",
    )

    response = await client.get(f"/api/v1/jobs/{job_id}", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "status": "rejected",
        "error": {
            "code": "NOT_A_RECEIPT",
            "message": "This image doesn't look like a receipt or invoice.",
        },
    }

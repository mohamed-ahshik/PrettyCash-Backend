---
title: "Receipt Analysis Service Implementation Plan"
type: plan
status: implemented
date: 2026-09-13
section: api
tags:
  - prettycash
  - plan
  - api
  - gemini
---

# PrettyCash Backend — Receipt Analysis Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Related

- Spec: [[2026-09-13-prettycash-backend-receipt-analysis-design|Receipt Analysis Service]]
- Section: [[API]]
- Plans: [[API-PLANS]]
- Architecture: [[ARCHITECTURE#8. API Contract|API Contract]], [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]]

## Architecture Alignment

- Builds the HTTP layer, image service, Gemini provider client, queue seam, and worker entrypoint.
- Keeps provider calls in `app/services/` and HTTP concerns in `app/api/`.
- Does not create the classifier queue or LiteLLM dependency; those are later specs.

**Goal:** Build a FastAPI backend that exposes `POST /api/v1/analyze-receipt`, authenticates callers with an API key, and uses the Gemini vision API to extract receipt data into the frontend's §5.4 JSON shape.

**Architecture:** Layered — `api → service → queue interface → worker`. The Gemini call lives in a pure `ReceiptAnalyzer` service; a `TaskQueue` protocol with a `SyncQueue` (now) and `RedisQueue` (later) provides the future Redis/worker seam. The endpoint stays synchronous per the frontend contract.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, pydantic-settings, httpx (Gemini REST), Pillow + pillow-heif (image), pytest + pytest-asyncio + respx (tests), ruff (lint), uv (env/deps), Docker Compose.

## Global Constraints

- Python **3.12** (`.python-version`).
- Gemini model **`gemini-3.1-flash-lite`**; key `GEMINI_API_KEY` is server-side only, never returned to clients.
- API is locked by an API key: `Authorization: Bearer <VISION_API_KEY>`.
- Endpoint: **`POST /api/v1/analyze-receipt`** with request body `{ "image": { "base64": "<raw base64, no data URI prefix>", "mimeType": "image/jpeg" } }`.
- Success response `200` shape: `{ merchant, amount, date?, time?, note, items[] }` (date/time omitted when absent).
- Error response shape: `{ "error": { "code", "message" } }` with codes `UNAUTHORIZED`, `INVALID_IMAGE`, `UNPROCESSABLE`, `RATE_LIMITED`, `INTERNAL`.
- Rate limiting is in-memory now, Redis-backed later.
- Deps managed by `uv`; the app runs under uvicorn via the factory (`uvicorn app.main:create_app --factory`).
- All Python code is lint-clean under ruff (E, F, I, UP, B) at line-length 100.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `app/__init__.py`, `app/core/__init__.py`, `app/services/__init__.py`, `app/queue/__init__.py`, `app/workers/__init__.py`, `app/api/__init__.py`, `app/api/v1/__init__.py` (all empty)

**Interfaces:**
- Produces: a `uv`-installable package named `prettycash-backend` (editable install of `app/`) so `import app` works from anywhere.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "prettycash-backend"
version = "0.1.0"
description = "PrettyCash backend: AI receipt analysis service"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic-settings>=2.4",
    "httpx>=0.27",
    "pillow>=10.4",
    "pillow-heif>=0.18",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Write `.python-version`**

```
3.12
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.env
.pytest_cache/
.ruff_cache/
dist/
*.egg-info/
.DS_Store
```

- [ ] **Step 4: Write `.env.example`**

```
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
VISION_API_KEY=
RATE_LIMIT_PER_MINUTE=30
MAX_IMAGE_BYTES=10485760
MAX_IMAGE_DIMENSION=1600
LOG_LEVEL=INFO
```

- [ ] **Step 5: Write `README.md`**

```markdown
# PrettyCash Backend

FastAPI backend for PrettyCash's AI receipt scanning. Exposes a single, API-key-locked endpoint
that analyzes a receipt image with the Gemini vision API and returns structured transaction data.

## Setup

```bash
uv sync
cp .env.example .env   # then fill in GEMINI_API_KEY and VISION_API_KEY
```

## Run

```bash
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

## Run worker (drains the sync queue; Redis-backed worker comes later)

```bash
uv run python -m app.workers.worker
```

## Test & lint

```bash
uv run pytest
uv run ruff check .
```

## API

`POST /api/v1/analyze-receipt` — see `docs/specs/SPECS.md` for the full contract.
```

- [ ] **Step 6: Create empty `__init__.py` files**

```bash
touch app/__init__.py app/core/__init__.py app/services/__init__.py app/queue/__init__.py app/workers/__init__.py app/api/__init__.py app/api/v1/__init__.py
```

- [ ] **Step 7: Install dependencies**

Run: `uv sync`
Expected: `uv.lock` is created, exit 0.

- [ ] **Step 8: Verify import**

Run: `uv run python -c "import fastapi, pydantic_settings, httpx, PIL; print('ok')"`
Expected: `ok`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Add project scaffolding for PrettyCash backend"
```

---

### Task 2: Core config, errors, and logging

**Files:**
- Create: `app/core/config.py`
- Create: `app/core/errors.py`
- Create: `app/core/logging.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: nothing (foundation).
- Produces:
  - `Settings` (pydantic-settings `BaseSettings`) with fields `gemini_api_key: str`, `gemini_model: str = "gemini-3.1-flash-lite"`, `vision_api_key: str`, `rate_limit_per_minute: int = 30`, `max_image_bytes: int = 10 * 1024 * 1024`, `max_image_dimension: int = 1600`, `log_level: str = "INFO"`.
  - `get_settings() -> Settings` (lru-cached).
  - `ErrorCode` enum + `AppError` base and subclasses `UnauthorizedError`, `InvalidImageError`, `UnprocessableError`, `RateLimitedError`, `InternalError`.
  - `configure_logging(level: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_core.py
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ErrorCode,
    InternalError,
    InvalidImageError,
    RateLimitedError,
    UnauthorizedError,
    UnprocessableError,
)


def test_settings_defaults():
    s = Settings(gemini_api_key="g", vision_api_key="v")
    assert s.gemini_model == "gemini-3.1-flash-lite"
    assert s.rate_limit_per_minute == 30
    assert s.max_image_bytes == 10 * 1024 * 1024
    assert s.max_image_dimension == 1600


def test_app_error_carries_status_and_code():
    e = UnauthorizedError()
    assert e.status_code == 401
    assert e.code == ErrorCode.UNAUTHORIZED
    assert isinstance(e, AppError)


def test_app_error_custom_message():
    e = InvalidImageError("bad image")
    assert e.message == "bad image"


def test_all_error_codes_exist():
    assert {c.value for c in ErrorCode} == {
        "UNAUTHORIZED",
        "INVALID_IMAGE",
        "UNPROCESSABLE",
        "RATE_LIMITED",
        "INTERNAL",
    }
    assert InternalError().status_code == 500
    assert RateLimitedError().status_code == 429
    assert UnprocessableError().status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 3: Write `app/core/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    vision_api_key: str
    rate_limit_per_minute: int = 30
    max_image_bytes: int = 10 * 1024 * 1024
    max_image_dimension: int = 1600
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Write `app/core/errors.py`**

```python
from enum import Enum


class ErrorCode(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_IMAGE = "INVALID_IMAGE"
    UNPROCESSABLE = "UNPROCESSABLE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"


class AppError(Exception):
    status_code = 500
    code = ErrorCode.INTERNAL
    default_message = "Internal server error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class UnauthorizedError(AppError):
    status_code = 401
    code = ErrorCode.UNAUTHORIZED
    default_message = "Unauthorized"


class InvalidImageError(AppError):
    status_code = 400
    code = ErrorCode.INVALID_IMAGE
    default_message = "Could not read the receipt image"


class UnprocessableError(AppError):
    status_code = 422
    code = ErrorCode.UNPROCESSABLE
    default_message = "Could not process the receipt"


class RateLimitedError(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    default_message = "Too many requests"


class InternalError(AppError):
    status_code = 500
    code = ErrorCode.INTERNAL
    default_message = "Internal server error"
```

- [ ] **Step 5: Write `app/core/logging.py`**

```python
import logging
import sys


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Lint**

Run: `uv run ruff check app/core tests/test_core.py`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add core config, errors, and logging"
```

---

### Task 3: Image service (decode, validate, downscale)

**Files:**
- Create: `app/services/image.py`
- Test: `tests/test_services_image.py`

**Interfaces:**
- Consumes: `Settings` (Task 2), `InvalidImageError` (Task 2).
- Produces: `decode_and_process(base64_data: str, settings: Settings) -> tuple[bytes, str]` — returns `(jpeg_bytes, "image/jpeg")` after validating and downscaling.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_image.py
import base64
import io

import pytest
from PIL import Image

from app.core.config import Settings
from app.core.errors import InvalidImageError
from app.services.image import decode_and_process


def _settings(**overrides) -> Settings:
    values = {"gemini_api_key": "g", "vision_api_key": "v"}
    values.update(overrides)
    return Settings(**values)


def _png_base64(size=(200, 100)) -> str:
    img = Image.new("RGB", size, "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_decodes_and_reencodes_to_jpeg():
    data, mime = decode_and_process(_png_base64(), _settings())
    assert mime == "image/jpeg"
    assert data[:2] == b"\xff\xd8"


def test_downscales_large_image():
    data, _ = decode_and_process(_png_base64((4000, 2000)), _settings())
    img = Image.open(io.BytesIO(data))
    assert max(img.size) <= 1600


def test_rejects_invalid_base64():
    with pytest.raises(InvalidImageError):
        decode_and_process("!!!not-base64!!!", _settings())


def test_rejects_non_image_bytes():
    with pytest.raises(InvalidImageError):
        decode_and_process(base64.b64encode(b"hello").decode(), _settings())


def test_rejects_oversized_image():
    settings = _settings(max_image_bytes=10)
    with pytest.raises(InvalidImageError):
        decode_and_process(_png_base64(), settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services_image.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.image'`

- [ ] **Step 3: Write `app/services/image.py`**

```python
import base64
import binascii
import io

from PIL import Image

from app.core.config import Settings
from app.core.errors import InvalidImageError

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - pillow-heif is a required dep; this is defensive
    pass

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}


def decode_and_process(base64_data: str, settings: Settings) -> tuple[bytes, str]:
    try:
        raw = base64.b64decode(base64_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidImageError("Image is not valid base64") from exc

    if len(raw) > settings.max_image_bytes:
        raise InvalidImageError("Image is too large")

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise InvalidImageError("Could not decode the image") from exc

    if image.format not in ALLOWED_FORMATS:
        raise InvalidImageError(f"Unsupported image format: {image.format}")

    image.thumbnail((settings.max_image_dimension, settings.max_image_dimension))

    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue(), "image/jpeg"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services_image.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint**

Run: `uv run ruff check app/services/image.py tests/test_services_image.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add image decode, validation, and downscaling service"
```

---

### Task 4: Gemini client

**Files:**
- Create: `app/services/gemini.py`
- Test: `tests/test_services_gemini.py`

**Interfaces:**
- Consumes: `InternalError` (Task 2).
- Produces: `GeminiClient(api_key: str, model: str, timeout: float = 60.0)` with `analyze(image_base64: str, mime_type: str) -> dict` (the parsed JSON object from Gemini).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_gemini.py
import json

import httpx
import pytest
import respx

from app.core.errors import InternalError
from app.services.gemini import GeminiClient

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite"
    ":generateContent"
)


def _candidates(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_analyze_returns_parsed_json():
    client = GeminiClient("key", "gemini-3.1-flash-lite")
    with respx.mock:
        route = respx.post(GEMINI_URL).mock(
            return_value=httpx.Response(
                200, json=_candidates(json.dumps({"merchant": "Whole Foods", "amount": 42.75}))
            )
        )
        result = client.analyze("aGVsbG8=", "image/jpeg")

    assert result == {"merchant": "Whole Foods", "amount": 42.75}
    assert route.called


def test_analyze_raises_internal_on_provider_error():
    client = GeminiClient("key", "gemini-3.1-flash-lite")
    with respx.mock:
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(InternalError):
            client.analyze("aGVsbG8=", "image/jpeg")


def test_analyze_raises_internal_on_malformed_body():
    client = GeminiClient("key", "gemini-3.1-flash-lite")
    with respx.mock:
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))
        with pytest.raises(InternalError):
            client.analyze("aGVsbG8=", "image/jpeg")


def test_analyze_raises_internal_on_network_error():
    client = GeminiClient("key", "gemini-3.1-flash-lite")
    with respx.mock:
        respx.post(GEMINI_URL).mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(InternalError):
            client.analyze("aGVsbG8=", "image/jpeg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services_gemini.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.gemini'`

- [ ] **Step 3: Write `app/services/gemini.py`**

```python
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
            response = httpx.post(url, params={"key": self._api_key}, json=body, timeout=self._timeout)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services_gemini.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint**

Run: `uv run ruff check app/services/gemini.py tests/test_services_gemini.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add Gemini vision client"
```

---

### Task 5: Receipt analyzer (normalize Gemini output → ReceiptDraft)

**Files:**
- Create: `app/services/receipt.py`
- Test: `tests/test_services_receipt.py`

**Interfaces:**
- Consumes: `GeminiClient` (Task 4), `UnprocessableError` (Task 2).
- Produces: `ReceiptDraft` and `LineItem` pydantic models, and `ReceiptAnalyzer(gemini)` with `analyze(image_bytes: bytes, mime_type: str) -> ReceiptDraft`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_receipt.py
import pytest

from app.core.errors import UnprocessableError
from app.services.receipt import ReceiptAnalyzer


class FakeGemini:
    def __init__(self, payload: dict):
        self.payload = payload

    def analyze(self, image_base64: str, mime_type: str) -> dict:
        return self.payload


def test_normalizes_valid_payload():
    analyzer = ReceiptAnalyzer(FakeGemini({
        "merchant": "Whole Foods",
        "amount": 42.75,
        "date": "2026-09-13",
        "time": "14:30",
        "note": "groceries",
        "items": [{"name": "Almond Milk", "quantity": 2, "price": 6.98}],
    }))
    draft = analyzer.analyze(b"fake", "image/jpeg")
    assert draft.merchant == "Whole Foods"
    assert draft.amount == 42.75
    assert draft.date == "2026-09-13"
    assert draft.time == "14:30"
    assert draft.note == "groceries"
    assert draft.items[0].name == "Almond Milk"
    assert draft.items[0].quantity == 2
    assert draft.items[0].price == 6.98


def test_defaults_missing_optional_fields():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "", "amount": 10.0}))
    draft = analyzer.analyze(b"fake", "image/jpeg")
    assert draft.merchant == ""
    assert draft.date is None
    assert draft.time is None
    assert draft.note == ""
    assert draft.items == []


def test_raises_unprocessable_on_missing_amount():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "X"}))
    with pytest.raises(UnprocessableError):
        analyzer.analyze(b"fake", "image/jpeg")


def test_raises_unprocessable_on_negative_amount():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "X", "amount": -5}))
    with pytest.raises(UnprocessableError):
        analyzer.analyze(b"fake", "image/jpeg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_services_receipt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.receipt'`

- [ ] **Step 3: Write `app/services/receipt.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_services_receipt.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint**

Run: `uv run ruff check app/services/receipt.py tests/test_services_receipt.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add receipt analyzer with normalization"
```

---

### Task 6: Queue interface + sync queue + Redis stub

**Files:**
- Create: `app/queue/base.py`
- Create: `app/queue/sync.py`
- Create: `app/queue/redis.py`
- Test: `tests/test_queue.py`

**Interfaces:**
- Consumes: nothing (foundation).
- Produces:
  - `Job` dataclass with `image_bytes: bytes`, `mime_type: str`, `id: str` (auto-generated).
  - `TaskQueue` protocol with `enqueue(job: Job) -> None`, `dequeue() -> Job | None`, `size() -> int`.
  - `SyncQueue` (in-process, structurally satisfies `TaskQueue`).
  - `RedisQueue` (stub; raises `NotImplementedError` on construction until Redis lands).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_queue.py
import pytest

from app.queue.base import Job
from app.queue.redis import RedisQueue
from app.queue.sync import SyncQueue


def test_sync_queue_roundtrip():
    q = SyncQueue()
    job = Job(image_bytes=b"img", mime_type="image/jpeg")
    q.enqueue(job)
    assert q.size() == 1
    assert q.dequeue() is job
    assert q.dequeue() is None
    assert q.size() == 0


def test_job_has_unique_id():
    a = Job(image_bytes=b"a", mime_type="image/jpeg")
    b = Job(image_bytes=b"b", mime_type="image/jpeg")
    assert a.id != b.id


def test_redis_queue_is_stub():
    with pytest.raises(NotImplementedError):
        RedisQueue()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_queue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.queue.base'`

- [ ] **Step 3: Write `app/queue/base.py`**

```python
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4


@dataclass
class Job:
    image_bytes: bytes
    mime_type: str
    id: str = field(default_factory=lambda: uuid4().hex)


class TaskQueue(Protocol):
    def enqueue(self, job: Job) -> None: ...

    def dequeue(self) -> Job | None: ...

    def size(self) -> int: ...
```

- [ ] **Step 4: Write `app/queue/sync.py`**

```python
from collections import deque

from app.queue.base import Job


class SyncQueue:
    def __init__(self) -> None:
        self._jobs: deque[Job] = deque()

    def enqueue(self, job: Job) -> None:
        self._jobs.append(job)

    def dequeue(self) -> Job | None:
        return self._jobs.popleft() if self._jobs else None

    def size(self) -> int:
        return len(self._jobs)
```

- [ ] **Step 5: Write `app/queue/redis.py`**

```python
from app.queue.base import Job


class RedisQueue:
    """Placeholder for the future Redis-backed queue.

    Not wired yet — the API currently uses SyncQueue. When Redis lands,
    this class will implement enqueue/dequeue/size over a Redis list.
    """

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("RedisQueue is not implemented yet; use SyncQueue.")

    def enqueue(self, job: Job) -> None:
        raise NotImplementedError

    def dequeue(self) -> Job | None:
        raise NotImplementedError

    def size(self) -> int:
        raise NotImplementedError
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_queue.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Lint**

Run: `uv run ruff check app/queue tests/test_queue.py`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add task queue interface, sync queue, and Redis stub"
```

---

### Task 7: Worker CLI

**Files:**
- Create: `app/workers/worker.py`
- Test: `tests/test_workers.py`

**Interfaces:**
- Consumes: `Job`, `TaskQueue` (Task 6), `ReceiptAnalyzer`/`ReceiptDraft` (Task 5), `get_settings` (Task 2).
- Produces: `process_job(job: Job, analyzer: ReceiptAnalyzer) -> ReceiptDraft`, `run_worker(queue: TaskQueue, analyzer: ReceiptAnalyzer, stop_event: threading.Event | None = None, poll_interval: float = 1.0) -> None`, and a `main()` CLI entrypoint.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workers.py
from app.queue.base import Job
from app.services.receipt import ReceiptDraft
from app.workers.worker import process_job


class FakeAnalyzer:
    def analyze(self, image_bytes: bytes, mime_type: str) -> ReceiptDraft:
        return ReceiptDraft(merchant="X", amount=1.0)


def test_process_job_returns_draft():
    analyzer = FakeAnalyzer()
    job = Job(image_bytes=b"img", mime_type="image/jpeg")
    draft = process_job(job, analyzer)
    assert draft.merchant == "X"
    assert draft.amount == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_workers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workers.worker'`

- [ ] **Step 3: Write `app/workers/worker.py`**

```python
import logging
import threading
import time

from app.core.config import get_settings
from app.queue.base import Job, TaskQueue
from app.queue.sync import SyncQueue
from app.services.gemini import GeminiClient
from app.services.receipt import ReceiptAnalyzer, ReceiptDraft

logger = logging.getLogger(__name__)


def process_job(job: Job, analyzer: ReceiptAnalyzer) -> ReceiptDraft:
    return analyzer.analyze(job.image_bytes, job.mime_type)


def run_worker(
    queue: TaskQueue,
    analyzer: ReceiptAnalyzer,
    stop_event: threading.Event | None = None,
    poll_interval: float = 1.0,
) -> None:
    while stop_event is None or not stop_event.is_set():
        job = queue.dequeue()
        if job is None:
            time.sleep(poll_interval)
            continue
        try:
            process_job(job, analyzer)
            logger.info("Processed job %s", job.id)
        except Exception:  # noqa: BLE001 - worker must keep running on bad jobs
            logger.exception("Failed to process job %s", job.id)


def main() -> None:
    settings = get_settings()
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model)
    analyzer = ReceiptAnalyzer(gemini)
    queue = SyncQueue()
    run_worker(queue, analyzer)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_workers.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Lint**

Run: `uv run ruff check app/workers tests/test_workers.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add worker CLI entrypoint"
```

---

### Task 8: API schemas and dependencies (auth + rate limiting)

**Files:**
- Create: `app/api/v1/schemas.py`
- Create: `app/api/deps.py`
- Test: `tests/test_deps.py`

**Interfaces:**
- Consumes: `LineItem` (Task 5), `RateLimitedError`/`UnauthorizedError` (Task 2).
- Produces:
  - `ImagePayload`, `AnalyzeReceiptRequest`, `AnalyzeReceiptResponse` pydantic models.
  - `RateLimiter(per_minute: int)` with `check(key: str) -> None`.
  - `require_api_key(request: Request) -> str` and `require_rate_limit(request: Request, token: str = Depends(require_api_key)) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deps.py
import pytest

from app.api.deps import RateLimiter
from app.core.errors import RateLimitedError


def test_rate_limiter_allows_up_to_limit():
    limiter = RateLimiter(per_minute=2)
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(RateLimitedError):
        limiter.check("k")


def test_rate_limiter_isolates_keys():
    limiter = RateLimiter(per_minute=1)
    limiter.check("a")
    limiter.check("b")  # different key, allowed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_deps.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.deps'`

- [ ] **Step 3: Write `app/api/v1/schemas.py`**

```python
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
```

- [ ] **Step 4: Write `app/api/deps.py`**

```python
import secrets
import threading
import time
from collections import deque

from fastapi import Depends, Request

from app.core.errors import RateLimitedError, UnauthorizedError


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and now - bucket[0] > 60.0:
                bucket.popleft()
            if len(bucket) >= self._per_minute:
                raise RateLimitedError("Rate limit exceeded")
            bucket.append(now)


def require_api_key(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header")
    token = header[len("Bearer "):]
    expected = request.app.state.settings.vision_api_key
    if not secrets.compare_digest(token, expected):
        raise UnauthorizedError("Invalid API key")
    return token


def require_rate_limit(request: Request, token: str = Depends(require_api_key)) -> str:
    request.app.state.rate_limiter.check(token)
    return token
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_deps.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Lint**

Run: `uv run ruff check app/api tests/test_deps.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add API schemas and auth/rate-limit dependencies"
```

---

### Task 9: Endpoint, router, app factory, and integration tests

**Files:**
- Create: `app/api/v1/receipt.py`
- Create: `app/api/v1/router.py`
- Create: `app/main.py`
- Test: `tests/test_api_receipt.py`
- Test: `tests/conftest.py`

**Interfaces:**
- Consumes: schemas/deps (Task 8), `decode_and_process` (Task 3), `ReceiptAnalyzer` (Task 5), `SyncQueue` (Task 6), `GeminiClient` (Task 4), config/errors/logging (Task 2).
- Produces: `create_app(settings: Settings | None = None) -> FastAPI` (used by uvicorn via `--factory`), routes `GET /api/v1/health` and `POST /api/v1/analyze-receipt`.

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.1-flash-lite",
        vision_api_key="test-vision-key",
        rate_limit_per_minute=30,
    )


@pytest.fixture
def client(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")
```

- [ ] **Step 2: Write the failing integration test**

```python
# tests/test_api_receipt.py
import base64
import io
import json

import httpx
import pytest
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_api_receipt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'` (or route 404)

- [ ] **Step 4: Write `app/api/v1/receipt.py`**

```python
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_rate_limit
from app.api.v1.schemas import AnalyzeReceiptRequest, AnalyzeReceiptResponse
from app.services.image import decode_and_process

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/analyze-receipt",
    response_model=AnalyzeReceiptResponse,
    response_model_exclude_none=True,
)
async def analyze_receipt(
    payload: AnalyzeReceiptRequest,
    request: Request,
    _token: str = Depends(require_rate_limit),
):
    settings = request.app.state.settings
    analyzer = request.app.state.analyzer

    image_bytes, mime_type = decode_and_process(payload.image.base64, settings)
    return await run_in_threadpool(analyzer.analyze, image_bytes, mime_type)
```

- [ ] **Step 5: Write `app/api/v1/router.py`**

```python
from fastapi import APIRouter

from app.api.v1 import receipt

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(receipt.router)
```

- [ ] **Step 6: Write `app/main.py`**

```python
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.deps import RateLimiter
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, InternalError
from app.core.logging import configure_logging
from app.queue.sync import SyncQueue
from app.services.gemini import GeminiClient
from app.services.receipt import ReceiptAnalyzer


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="PrettyCash Backend", version="0.1.0")

    app.state.settings = settings
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.queue = SyncQueue()
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model)
    app.state.analyzer = ReceiptAnalyzer(gemini)

    app.include_router(api_router)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code.value, "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("Unhandled error", exc_info=exc)
        internal = InternalError()
        return JSONResponse(
            status_code=internal.status_code,
            content={"error": {"code": internal.code.value, "message": internal.message}},
        )

    return app
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_api_receipt.py -v`
Expected: PASS (9 tests)

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest`
Expected: all tests PASS

- [ ] **Step 9: Lint**

Run: `uv run ruff check app tests`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Add analyze-receipt endpoint, router, and app factory"
```

---

### Task 10: Docker, README finalization, and lint gate

**Files:**
- Create: `docker/Dockerfile`
- Create: `docker/compose.yaml`
- Modify: `README.md` (add Docker section)

**Interfaces:**
- Consumes: everything above.
- Produces: buildable `api` and `worker` images; a `compose.yaml` with redis commented out until the queue lands.

- [ ] **Step 1: Write `docker/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

COPY app ./app

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `docker/compose.yaml`**

```yaml
services:
  api:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - ../.env

  worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    command: ["python", "-m", "app.workers.worker"]
    env_file:
      - ../.env

  # redis:
  #   image: redis:7-alpine
  #   ports:
  #     - "6379:6379"
```

- [ ] **Step 3: Add a Docker section to `README.md`**

Append:

```markdown
## Docker

```bash
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up
```

The `worker` service is wired now (drains the sync queue). Uncomment the `redis` service
and swap `SyncQueue` for `RedisQueue` when the Redis-backed queue is implemented.
```

- [ ] **Step 4: Full lint and test gate**

Run: `uv run ruff check .`
Expected: no errors

Run: `uv run pytest`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add Dockerfile, compose, and README Docker section"
```

---

## Self-Review Notes

- **Spec coverage:** §5.1 endpoint (Task 9), §5.2 headers/auth (Tasks 8–9), §5.3 request body (Task 8), §5.4 success shape incl. date/time omission and line items (Tasks 4–5, 9), §5.5 error shape + codes (Tasks 2, 9), §5.6 backend responsibilities — Gemini key server-side, rate limits, downscale, strict JSON, hide provider errors (Tasks 3, 4, 8, 9). Worker-ready Redis seam (Tasks 6–7). Docker Compose (Task 10). uv (Task 1).
- **Type consistency:** `decode_and_process(base64_data, settings) -> tuple[bytes, str]` used in Task 9; `ReceiptAnalyzer.analyze(image_bytes, mime_type) -> ReceiptDraft` used in Tasks 5, 7, 9; `LineItem` shared between `receipt.py` and `schemas.py`; `Job`/`TaskQueue`/`SyncQueue` consistent across Tasks 6–7.
- **Model name:** `gemini-3.1-flash-lite` used verbatim in config, client, tests, and Docker.

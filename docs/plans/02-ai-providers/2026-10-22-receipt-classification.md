---
title: "Receipt Classification with Jev Implementation Plan"
type: plan
status: implemented
date: 2026-10-22
section: ai-providers
tags:
  - prettycash
  - plan
  - ai
  - jev
  - classifier
  - queue
---

# Receipt Classification with Jev Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Superseded task (completed):** Task 4 was implemented by the LiteLLM migration plan's Task 3,
> using `litellm.systemone` per
> `docs/specs/02-ai-providers/2026-10-22-litellm-migration-design.md`. The direct-`httpx` steps in
> Task 4 are historical and were not executed.

## Related

- Spec: [[2026-10-22-receipt-classification-design|Receipt Pre-Classification with Jev]]
- Transport: [[2026-10-22-litellm-migration-design|Gemini and Jev via LiteLLM]]
- Section: [[AI-PROVIDERS]]
- Plans: [[AI-PROVIDERS-PLANS]]
- Architecture: [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]], [[ARCHITECTURE#7. Request and Data Flow|Request and Data Flow]]

**Goal:** Add an isolated OpenRouter Jev classifier that rejects non-receipt images before Gemini, persists the `noul` score, and fails open to Gemini on any classifier failure.

**Architecture:** The API keeps returning `202 {jobId}` but enqueues to a new `receipt:classify` Redis list. A dedicated classifier worker consumes it, records `classifier_score` / `classifier_model` in Supabase, and either marks the job `rejected` or republishes it to the existing `receipt:queue`, where the unchanged Gemini worker extracts it.

**Tech Stack:** Python 3.12, FastAPI, pydantic-settings, httpx, Redis (redis-py), Supabase (supabase-py), Pillow, pytest, respx, ruff, Docker Compose.

## Global Constraints

- Use Python 3.12 and the existing dependencies. Do not add new packages.
- Run tests with `uv run pytest`; run lint with `uv run ruff check .`.
- Jev endpoint: `https://openrouter.ai/api/alpha/decisions`.
- Jev model: `typesafe/jev-1.14` (`OPENROUTER_JEV_MODEL`), key `OPENROUTER_JEV_API_KEY`.
- Reject only when `noul < RECEIPT_CLASSIFIER_THRESHOLD` (default `0.3`).
- Jev timeout: `OPENROUTER_TIMEOUT_SECONDS` default `5.0`.
- Fail open to Gemini on every classifier/image failure. No retries.
- Queue names: `receipt:classify` for classification, `receipt:queue` for Gemini extraction.
- Jev images: JPEG, each side 256–1568 px, total 78,400–2,458,624 px. Never upscale.
- API contract is unchanged except the new terminal status `rejected` with code `NOT_A_RECEIPT`.
- Never log or commit image bytes, API keys, or raw provider errors.
- Never stage `.env`; it is gitignored. Replace real values in `.env.example` with placeholders.
- Follow TDD: write the failing test, run it, implement, run it again, then commit.

## Architecture Alignment

Read `docs/prettycash-backend-architecture/ARCHITECTURE.md` before executing this plan.

- **Layers touched:** API queue target/status mapping, queue, services (Jev + classifier), worker,
  store, Supabase migration, Compose.
- **New boundaries:** `receipt:classify`, `classifier` worker, `rejected` status, classifier columns.
- **Boundaries preserved:** provider logic stays in services; the classifier worker orchestrates;
  the API does not call Jev/Gemini directly.
- **After implementation:** update `ARCHITECTURE.md` current-state sections and change log.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/core/config.py` | Classifier env settings |
| `app/core/errors.py` | `NOT_A_RECEIPT` job error code |
| `app/store/base.py` | `JobStatus.REJECTED`, `record_classification`, `reject` protocol |
| `app/store/supabase.py` | Persist classifier score/model and rejected status |
| `app/queue/redis.py` | Parameterized queue key and queue-name constants |
| `app/services/image.py` | EXIF orientation before downscale/encode |
| `app/services/jev.py` | OpenRouter Decisions request/response |
| `app/services/classifier.py` | Jev-safe image normalization + classify |
| `app/workers/classifier.py` | Classifier queue consumer and fail-open routing |
| `app/main.py` | Enqueue to `receipt:classify` |
| `app/api/v1/receipt.py` | Render the `rejected` poll response |
| `app/workers/worker.py` | Explicitly consume `receipt:queue` |
| `supabase/migrations/0002_add_classifier_columns.sql` | Add `classifier_score` / `classifier_model` |
| `docker/compose.yaml` | Add the `classifier` service |
| `.env.example` | Add new vars and remove committed secrets |
| `README.md` | Document the classifier, queues, and rejected status |

---

### Task 1: Storage, Config, and Error Contract

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/core/errors.py`
- Modify: `app/store/base.py`
- Modify: `app/store/supabase.py`
- Create: `supabase/migrations/0002_add_classifier_columns.sql`
- Modify: `tests/conftest.py`
- Modify: `tests/test_core.py`
- Modify: `tests/test_store.py`

**Interfaces:**
- Consumes: existing `Settings`, `ErrorCode`, `JobStatus`, `JobStore`, `SupabaseJobStore`, `FakeJobStore`.
- Produces:
  - `Settings.openrouter_jev_api_key: str`
  - `Settings.openrouter_jev_model: str`
  - `Settings.receipt_classifier_threshold: float`
  - `Settings.openrouter_timeout_seconds: float`
  - `ErrorCode.NOT_A_RECEIPT`
  - `JobStatus.REJECTED`
  - `JobStore.record_classification(job_id: str, score: float, model: str) -> None`
  - `JobStore.reject(job_id: str, code: str, message: str) -> None`

- [ ] **Step 1: Write the failing tests**

In `tests/test_core.py`, replace `test_settings_defaults` with:

```python
def test_settings_defaults():
    s = Settings(
        gemini_api_key="g",
        vision_api_key="v",
        redis_url="redis://localhost:6379/0",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="key",
    )
    assert s.gemini_model == "gemini-3.1-flash-lite"
    assert s.rate_limit_per_minute == 30
    assert s.max_image_bytes == 10 * 1024 * 1024
    assert s.max_image_dimension == 1600
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.openrouter_jev_api_key == ""
    assert s.openrouter_jev_model == "typesafe/jev-1.14"
    assert s.receipt_classifier_threshold == 0.3
    assert s.openrouter_timeout_seconds == 5.0
```

In `test_all_error_codes_exist`, add `"NOT_A_RECEIPT"` to the expected set:

```python
def test_all_error_codes_exist():
    assert {c.value for c in ErrorCode} == {
        "UNAUTHORIZED",
        "INVALID_IMAGE",
        "UNPROCESSABLE",
        "RATE_LIMITED",
        "INTERNAL",
        "NOT_FOUND",
        "NOT_A_RECEIPT",
    }
    assert InternalError().status_code == 500
    assert RateLimitedError().status_code == 429
    assert UnprocessableError().status_code == 422
    assert NotFoundError().status_code == 404
    assert NotFoundError().code == ErrorCode.NOT_FOUND
```

Append to `tests/test_store.py`:

```python
def test_record_classification_updates_score_and_model():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.record_classification("abc", 0.42, "typesafe/jev-1.14")
    assert client.calls[0] == (
        "update",
        {"classifier_score": 0.42, "classifier_model": "typesafe/jev-1.14"},
    )
    assert client.calls[1] == ("eq", "id", "abc")


def test_reject_updates_status_and_error():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.reject("abc", "NOT_A_RECEIPT", "This image doesn't look like a receipt or invoice.")
    assert client.calls[0] == (
        "update",
        {
            "status": JobStatus.REJECTED.value,
            "error_code": "NOT_A_RECEIPT",
            "error_message": "This image doesn't look like a receipt or invoice.",
        },
    )
    assert client.calls[1] == ("eq", "id", "abc")
```

In `tests/conftest.py`, add these methods to `FakeJobStore`:

```python
    def record_classification(self, job_id: str, score: float, model: str) -> None:
        row = self.rows.setdefault(job_id, {})
        row["classifier_score"] = score
        row["classifier_model"] = model

    def reject(self, job_id: str, code: str, message: str) -> None:
        row = self.rows.setdefault(job_id, {})
        row.update(
            {"status": "rejected", "error_code": code, "error_message": message}
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_core.py tests/test_store.py -v
```

Expected: FAIL. `Settings` has no `openrouter_jev_api_key`; `ErrorCode` has no `NOT_A_RECEIPT`; `SupabaseJobStore` has no `record_classification` / `reject`.

- [ ] **Step 3: Implement config and error codes**

Replace `app/core/config.py` with:

```python
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    vision_api_key: str
    redis_url: str
    supabase_url: str
    supabase_service_role_key: str
    openrouter_jev_api_key: str = ""
    openrouter_jev_model: str = "typesafe/jev-1.14"
    receipt_classifier_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    openrouter_timeout_seconds: float = Field(default=5.0, gt=0.0)
    rate_limit_per_minute: int = 30
    max_image_bytes: int = 10 * 1024 * 1024
    max_image_dimension: int = 1600
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

In `app/core/errors.py`, add the new code to `ErrorCode`:

```python
class ErrorCode(StrEnum):
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_IMAGE = "INVALID_IMAGE"
    UNPROCESSABLE = "UNPROCESSABLE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"
    NOT_FOUND = "NOT_FOUND"
    NOT_A_RECEIPT = "NOT_A_RECEIPT"
```

- [ ] **Step 4: Implement the store contract**

In `app/store/base.py`, replace the file with:

```python
from enum import StrEnum
from typing import Any, Protocol


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class JobStore(Protocol):
    def create(self) -> str: ...

    def mark_processing(self, job_id: str) -> None: ...

    def record_classification(self, job_id: str, score: float, model: str) -> None: ...

    def complete(self, job_id: str, result: dict[str, Any]) -> None: ...

    def fail(self, job_id: str, code: str, message: str) -> None: ...

    def reject(self, job_id: str, code: str, message: str) -> None: ...

    def get(self, job_id: str) -> dict[str, Any] | None: ...
```

In `app/store/supabase.py`, add these methods after `mark_processing`:

```python
    def record_classification(self, job_id: str, score: float, model: str) -> None:
        self._client.table(self.TABLE).update(
            {"classifier_score": score, "classifier_model": model}
        ).eq("id", job_id).execute()

    def reject(self, job_id: str, code: str, message: str) -> None:
        self._client.table(self.TABLE).update(
            {
                "status": JobStatus.REJECTED.value,
                "error_code": code,
                "error_message": message,
            }
        ).eq("id", job_id).execute()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_core.py tests/test_store.py -v
```

Expected: PASS.

- [ ] **Step 6: Add the migration**

Create `supabase/migrations/0002_add_classifier_columns.sql`:

```sql
alter table receipt_jobs
    add column if not exists classifier_score double precision,
    add column if not exists classifier_model text;

alter table receipt_jobs
    drop constraint if exists receipt_jobs_classifier_score_range;
alter table receipt_jobs
    add constraint receipt_jobs_classifier_score_range
    check (classifier_score is null or classifier_score between 0 and 1);
```

Apply this migration to the Supabase project before the manual verification in Task 9. Do not apply
it to production as part of this task.

- [ ] **Step 7: Commit**

```bash
git add app/core/config.py app/core/errors.py app/store/base.py app/store/supabase.py \
  tests/conftest.py tests/test_core.py tests/test_store.py \
  supabase/migrations/0002_add_classifier_columns.sql
git commit -m "feat: add classifier storage and config"
```

---

### Task 2: Apply EXIF Orientation in the API Image Pipeline

**Files:**
- Modify: `app/services/image.py`
- Modify: `tests/test_services_image.py`

**Interfaces:**
- Consumes: `decode_and_process(base64_data: str, settings: Settings) -> tuple[bytes, str]`.
- Produces: the same function, now with pixels rotated according to EXIF orientation before downscaling.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services_image.py`:

```python
def test_applies_exif_orientation():
    img = Image.new("RGB", (200, 100), "red")
    exif = Image.Exif()
    exif[274] = 6
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    data, _ = decode_and_process(
        base64.b64encode(buf.getvalue()).decode(), _settings()
    )

    out = Image.open(io.BytesIO(data))
    assert out.size == (100, 200)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_services_image.py::test_applies_exif_orientation -v
```

Expected: FAIL with `assert (200, 100) == (100, 200)`.

- [ ] **Step 3: Implement the fix**

In `app/services/image.py`, change the Pillow import and apply `exif_transpose` after the format
check (the check must run before `exif_transpose`, which returns an image with `format = None`):

```python
from PIL import Image, ImageOps
```

```python
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise InvalidImageError("Could not decode the image") from exc

    if image.format not in ALLOWED_FORMATS:
        raise InvalidImageError(f"Unsupported image format: {image.format}")

    image = ImageOps.exif_transpose(image)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_services_image.py -v
```

Expected: PASS for all image tests.

- [ ] **Step 5: Commit**

```bash
git add app/services/image.py tests/test_services_image.py
git commit -m "fix: apply EXIF orientation before image encoding"
```

---

### Task 3: Parameterize Redis Queue Keys

**Files:**
- Modify: `app/queue/redis.py`
- Modify: `tests/test_queue.py`

**Interfaces:**
- Consumes: existing `Job` dataclass.
- Produces:
  - `EXTRACT_QUEUE = "receipt:queue"`
  - `CLASSIFY_QUEUE = "receipt:classify"`
  - `RedisQueue(redis_client, queue_key: str = EXTRACT_QUEUE)`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_queue.py`:

```python
def test_redis_queue_uses_custom_key():
    r = fakeredis.FakeRedis(decode_responses=True)
    q = RedisQueue(r, queue_key="custom:queue")
    job = Job(job_id="abc", image_base64="aGk=", mime_type="image/jpeg")

    q.enqueue(job)

    assert r.llen("custom:queue") == 1
    assert r.llen("receipt:queue") == 0
    assert q.dequeue() == job
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_queue.py::test_redis_queue_uses_custom_key -v
```

Expected: FAIL with `TypeError: RedisQueue.__init__() got an unexpected keyword argument 'queue_key'`.

- [ ] **Step 3: Implement the queue key parameter**

Replace `app/queue/redis.py` with:

```python
import json

from app.queue.base import Job

EXTRACT_QUEUE = "receipt:queue"
CLASSIFY_QUEUE = "receipt:classify"


class RedisQueue:
    def __init__(self, redis_client, queue_key: str = EXTRACT_QUEUE) -> None:
        self._redis = redis_client
        self._queue_key = queue_key

    def enqueue(self, job: Job) -> None:
        payload = json.dumps(
            {"job_id": job.job_id, "image_base64": job.image_base64, "mime_type": job.mime_type}
        )
        self._redis.lpush(self._queue_key, payload)

    def dequeue(self) -> Job | None:
        item = self._redis.brpop(self._queue_key, timeout=1)
        if item is None:
            return None
        data = json.loads(item[1])
        return Job(
            job_id=data["job_id"],
            image_base64=data["image_base64"],
            mime_type=data["mime_type"],
        )

    def size(self) -> int:
        return self._redis.llen(self._queue_key)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_queue.py -v
```

Expected: PASS for all queue tests.

- [ ] **Step 5: Commit**

```bash
git add app/queue/redis.py tests/test_queue.py
git commit -m "feat: allow RedisQueue to use named queues"
```

---

### Task 4: Jev Client (Superseded by LiteLLM Plan)

> **Completed via LiteLLM plan.** `app/services/jev.py` and `tests/test_services_jev.py` were
> created using `litellm.systemone` in
> `docs/plans/02-ai-providers/2026-10-22-litellm-migration.md` Task 3. The direct-`httpx` steps
> below are retained only as historical reference and were not executed.

- [x] **Verified:** `app/services/jev.py` exists with `litellm.systemone`, and
  `uv run pytest tests/test_services_jev.py -v` passes.

> **End of active Task 4. The historical steps below were not executed. Continue at Task 5.**

- [ ] **Step 1 (historical): Write the failing tests**

Create `tests/test_services_jev.py`:

```python
import json

import httpx
import pytest
import respx

from app.services.jev import (
    ClassificationResult,
    ClassifierUnavailable,
    JevClient,
)

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


def _response(noul=0.9, model="typesafe/jev-1.14"):
    return {
        "model": model,
        "answers": {"is_receipt": {"type": "noul", "noul": noul}},
    }


def test_classify_returns_score_and_model():
    client = JevClient("key", "typesafe/jev-1.14")
    with respx.mock:
        route = respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(200, json=_response(0.92))
        )
        result = client.classify("aGVsbG8=")

    assert result == ClassificationResult(noul=0.92, model="typesafe/jev-1.14")
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer key"
    body = json.loads(request.content)
    assert body["model"] == "typesafe/jev-1.14"
    assert body["state"] == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="},
        }
    ]
    question = body["questions"]["is_receipt"]
    assert question["type"] == "noul"
    assert question["criteria"]["true"]
    assert question["criteria"]["false"]


@pytest.mark.parametrize("status_code", [401, 402, 429, 500, 503])
def test_classify_raises_on_provider_error(status_code):
    client = JevClient("key", "typesafe/jev-1.14")
    with respx.mock:
        respx.post(DECISIONS_URL).mock(return_value=httpx.Response(status_code))
        with pytest.raises(ClassifierUnavailable):
            client.classify("aGVsbG8=")


def test_classify_raises_on_network_error():
    client = JevClient("key", "typesafe/jev-1.14")
    with respx.mock:
        respx.post(DECISIONS_URL).mock(side_effect=httpx.ConnectTimeout("boom"))
        with pytest.raises(ClassifierUnavailable):
            client.classify("aGVsbG8=")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"answers": {}},
        {"answers": {"is_receipt": {"type": "choice", "choice": "receipt"}}},
        {"answers": {"is_receipt": {"type": "noul", "noul": 1.5}}},
        {"answers": {"is_receipt": {"type": "noul", "noul": -0.1}}},
        {"answers": {"is_receipt": {"type": "noul", "noul": "not-a-number"}}},
    ],
)
def test_classify_raises_on_malformed_answer(body):
    client = JevClient("key", "typesafe/jev-1.14")
    with respx.mock:
        respx.post(DECISIONS_URL).mock(return_value=httpx.Response(200, json=body))
        with pytest.raises(ClassifierUnavailable):
            client.classify("aGVsbG8=")


def test_classify_raises_without_api_key():
    client = JevClient("", "typesafe/jev-1.14")
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_services_jev.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.jev'`.

- [ ] **Step 3: Implement the client**

Create `app/services/jev.py`:

```python
import math
from dataclasses import dataclass

import httpx

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"

IS_RECEIPT_QUESTION = {
    "is_receipt": {
        "type": "noul",
        "instructions": (
            "The image shows a receipt, bill, or invoice containing merchant and amount "
            "information."
        ),
        "criteria": {
            "true": (
                "A photo, scan, or screenshot of a merchant receipt, bill, or invoice with a "
                "total amount and/or line items."
            ),
            "false": (
                "Any other image, including a selfie, landscape, product photo, unrelated "
                "screenshot, bank statement, order confirmation, or other document without a "
                "merchant receipt or invoice."
            ),
        },
    }
}


class ClassifierUnavailable(Exception):
    """Raised when Jev cannot produce a usable answer; callers fail open to Gemini."""


@dataclass(frozen=True)
class ClassificationResult:
    noul: float
    model: str


class JevClient:
    def __init__(self, api_key: str, model: str, timeout: float = 5.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def classify(self, image_base64: str) -> ClassificationResult:
        if not self._api_key:
            raise ClassifierUnavailable("OpenRouter Jev API key is not configured")

        body = {
            "model": self._model,
            "state": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}",
                    },
                }
            ],
            "questions": IS_RECEIPT_QUESTION,
        }

        try:
            response = httpx.post(
                DECISIONS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ClassifierUnavailable("Jev request failed") from exc

        if response.status_code != 200:
            raise ClassifierUnavailable(f"Jev returned HTTP {response.status_code}")

        try:
            data = response.json()
            answer = data["answers"]["is_receipt"]
            if answer["type"] != "noul":
                raise ClassifierUnavailable("Unexpected Jev answer type")
            raw_noul = answer["noul"]
            if isinstance(raw_noul, bool):
                raise ClassifierUnavailable("Jev returned a boolean score")
            noul = float(raw_noul)
            model = str(data.get("model") or self._model)
        except ClassifierUnavailable:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ClassifierUnavailable("Unexpected Jev response") from exc

        if not math.isfinite(noul) or not 0.0 <= noul <= 1.0:
            raise ClassifierUnavailable("Jev returned an invalid noul score")

        return ClassificationResult(noul=noul, model=model)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_services_jev.py -v
```

Expected: PASS for all Jev client tests.

- [ ] **Step 5: Commit**

```bash
git add app/services/jev.py tests/test_services_jev.py
git commit -m "feat: add OpenRouter Jev decisions client"
```

---

### Task 5: Classifier Image Normalization

**Files:**
- Create: `app/services/classifier.py`
- Create: `tests/test_services_classifier.py`

**Interfaces:**
- Consumes: `JevClient.classify(image_base64: str) -> ClassificationResult`, `ClassifierUnavailable`, `ClassificationResult`.
- Produces: `ReceiptClassifier(jev).classify(image_bytes: bytes) -> ClassificationResult`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services_classifier.py`:

```python
import base64
import io

import pytest
from PIL import Image

from app.services.classifier import ReceiptClassifier
from app.services.jev import ClassificationResult, ClassifierUnavailable


class FakeJev:
    def __init__(self):
        self.image_base64 = None

    def classify(self, image_base64: str) -> ClassificationResult:
        self.image_base64 = image_base64
        return ClassificationResult(noul=0.9, model="typesafe/jev-1.14")


def _image_bytes(size=(600, 900), fmt="JPEG") -> bytes:
    img = Image.new("RGB", size, "white")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_downscales_to_jev_max_side():
    jev = FakeJev()

    ReceiptClassifier(jev).classify(_image_bytes((1600, 1200)))

    sent = Image.open(io.BytesIO(base64.b64decode(jev.image_base64)))
    assert max(sent.size) <= 1568
    assert min(sent.size) >= 256
    assert sent.size[0] * sent.size[1] >= 78_400


@pytest.mark.parametrize("size", [(200, 200), (256, 300)])
def test_skips_images_outside_jev_size_window(size):
    jev = FakeJev()

    with pytest.raises(ClassifierUnavailable):
        ReceiptClassifier(jev).classify(_image_bytes(size))

    assert jev.image_base64 is None


def test_encodes_jpeg_data():
    jev = FakeJev()

    ReceiptClassifier(jev).classify(_image_bytes((600, 900), fmt="PNG"))

    raw = base64.b64decode(jev.image_base64)
    assert raw[:2] == b"\xff\xd8"


def test_raises_on_undecodable_image():
    jev = FakeJev()

    with pytest.raises(ClassifierUnavailable):
        ReceiptClassifier(jev).classify(b"not an image")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_services_classifier.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.classifier'`.

- [ ] **Step 3: Implement the classifier**

Create `app/services/classifier.py`:

```python
import base64
import io

from PIL import Image, ImageOps

from app.services.jev import ClassificationResult, ClassifierUnavailable, JevClient

MIN_SIDE = 256
MAX_SIDE = 1568
MIN_PIXELS = 78_400


class ReceiptClassifier:
    def __init__(self, jev: JevClient) -> None:
        self._jev = jev

    def classify(self, image_bytes: bytes) -> ClassificationResult:
        return self._jev.classify(self._to_jev_base64(image_bytes))

    def _to_jev_base64(self, image_bytes: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image.load()
        except Exception as exc:
            raise ClassifierUnavailable("Could not decode image for classification") from exc

        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")

        width, height = image.size
        if min(width, height) < MIN_SIDE or width * height < MIN_PIXELS:
            raise ClassifierUnavailable("Image is too small for Jev")

        if max(width, height) > MAX_SIDE:
            image.thumbnail((MAX_SIDE, MAX_SIDE))

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_services_classifier.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/classifier.py tests/test_services_classifier.py
git commit -m "feat: normalize images for Jev classification"
```

---

### Task 6: Classifier Worker

**Files:**
- Create: `app/workers/classifier.py`
- Create: `tests/test_workers_classifier.py`

**Interfaces:**
- Consumes:
  - `ReceiptClassifier.classify(image_bytes) -> ClassificationResult`
  - `JevClient`, `ClassifierUnavailable`
  - `RedisQueue`, `CLASSIFY_QUEUE`, `EXTRACT_QUEUE`
  - `JobStore.mark_processing`, `record_classification`, `reject`, `fail`
- Produces:
  - `NOT_A_RECEIPT_MESSAGE`
  - `process_job(job, classifier, extract_queue, job_store, threshold) -> bool`
  - `run_worker(queue, extract_queue, classifier, job_store, threshold, stop_event=None, poll_interval=1.0)`
  - `main()`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workers_classifier.py`:

```python
import pytest

from app.queue.base import Job
from app.queue.sync import SyncQueue
from app.services.jev import ClassificationResult, ClassifierUnavailable
from app.workers.classifier import NOT_A_RECEIPT_MESSAGE, process_job


class FakeClassifier:
    def __init__(self, noul=0.9, error=None):
        self.noul = noul
        self.error = error

    def classify(self, image_bytes: bytes) -> ClassificationResult:
        if self.error is not None:
            raise self.error
        return ClassificationResult(noul=self.noul, model="typesafe/jev-1.14")


class FailingQueue:
    def enqueue(self, job: Job) -> None:
        raise RuntimeError("redis down")

    def dequeue(self) -> Job | None:
        return None

    def size(self) -> int:
        return 0


class RecordingStore:
    def __init__(self):
        self.rows = {}
        self.rejected = None

    def mark_processing(self, job_id: str) -> None:
        self.rows.setdefault(job_id, {})["status"] = "processing"

    def record_classification(self, job_id: str, score: float, model: str) -> None:
        self.rows.setdefault(job_id, {}).update(
            {"classifier_score": score, "classifier_model": model}
        )

    def reject(self, job_id: str, code: str, message: str) -> None:
        self.rejected = (job_id, code, message)
        self.rows.setdefault(job_id, {}).update(
            {"status": "rejected", "error_code": code, "error_message": message}
        )

    def fail(self, job_id: str, code: str, message: str) -> None:
        self.rows.setdefault(job_id, {}).update(
            {"status": "failed", "error_code": code, "error_message": message}
        )

    def get(self, job_id: str):
        return self.rows.get(job_id)


class FailingRecordStore(RecordingStore):
    def record_classification(self, job_id: str, score: float, model: str) -> None:
        raise RuntimeError("db down")


class FailingRejectStore(RecordingStore):
    def reject(self, job_id: str, code: str, message: str) -> None:
        raise RuntimeError("db down")


def _job() -> Job:
    return Job(job_id="job-1", image_base64="aGk=", mime_type="image/jpeg")


def test_process_job_rejects_non_receipt(job_store):
    extract = SyncQueue()

    result = process_job(_job(), FakeClassifier(noul=0.1), extract, job_store, threshold=0.3)

    assert result is False
    row = job_store.get("job-1")
    assert row["status"] == "rejected"
    assert row["error_code"] == "NOT_A_RECEIPT"
    assert row["error_message"] == NOT_A_RECEIPT_MESSAGE
    assert row["classifier_score"] == 0.1
    assert row["classifier_model"] == "typesafe/jev-1.14"
    assert extract.size() == 0


def test_process_job_forwards_receipt(job_store):
    extract = SyncQueue()
    job = _job()

    result = process_job(job, FakeClassifier(noul=0.9), extract, job_store, threshold=0.3)

    assert result is True
    row = job_store.get("job-1")
    assert row["status"] == "processing"
    assert row["classifier_score"] == 0.9
    assert row["classifier_model"] == "typesafe/jev-1.14"
    assert extract.dequeue() == job


@pytest.mark.parametrize("error", [ClassifierUnavailable("down"), RuntimeError("boom")])
def test_process_job_fails_open_on_classifier_error(job_store, error):
    extract = SyncQueue()
    job = _job()

    result = process_job(job, FakeClassifier(error=error), extract, job_store, threshold=0.3)

    assert result is True
    row = job_store.get("job-1")
    assert row["status"] == "processing"
    assert "classifier_score" not in row
    assert extract.dequeue() == job


def test_process_job_fails_when_forwarding_fails(job_store):
    result = process_job(
        _job(), FakeClassifier(noul=0.9), FailingQueue(), job_store, threshold=0.3
    )

    assert result is False
    row = job_store.get("job-1")
    assert row["status"] == "failed"
    assert row["error_code"] == "INTERNAL"
    assert row["error_message"] == "Receipt processing failed"


def test_record_failure_does_not_change_routing_to_reject():
    store = FailingRecordStore()
    extract = SyncQueue()

    result = process_job(_job(), FakeClassifier(noul=0.1), extract, store, threshold=0.3)

    assert result is False
    assert store.rejected == ("job-1", "NOT_A_RECEIPT", NOT_A_RECEIPT_MESSAGE)
    assert extract.size() == 0


def test_record_failure_does_not_prevent_forwarding_receipt():
    store = FailingRecordStore()
    extract = SyncQueue()
    job = _job()

    result = process_job(job, FakeClassifier(noul=0.9), extract, store, threshold=0.3)

    assert result is True
    assert extract.dequeue() == job


def test_reject_failure_does_not_forward_to_gemini():
    store = FailingRejectStore()
    extract = SyncQueue()

    result = process_job(_job(), FakeClassifier(noul=0.1), extract, store, threshold=0.3)

    assert result is False
    assert extract.size() == 0
    assert store.get("job-1")["status"] == "processing"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_workers_classifier.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.workers.classifier'`.

- [ ] **Step 3: Implement the classifier worker**

Create `app/workers/classifier.py`:

```python
import base64
import logging
import threading
import time

from redis import Redis

from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.queue.base import Job, TaskQueue
from app.queue.redis import CLASSIFY_QUEUE, EXTRACT_QUEUE, RedisQueue
from app.services.classifier import ReceiptClassifier
from app.services.jev import ClassifierUnavailable, JevClient
from app.store.base import JobStore
from app.store.supabase import SupabaseJobStore
from supabase import create_client

logger = logging.getLogger(__name__)

NOT_A_RECEIPT_MESSAGE = "This image doesn't look like a receipt or invoice."
PROCESSING_FAILED_MESSAGE = "Receipt processing failed"


def _forward(job: Job, extract_queue: TaskQueue, job_store: JobStore) -> bool:
    try:
        extract_queue.enqueue(job)
        return True
    except Exception:
        logger.exception("Could not enqueue job %s for extraction", job.job_id)
        job_store.fail(job.job_id, ErrorCode.INTERNAL.value, PROCESSING_FAILED_MESSAGE)
        return False


def _log_fallback(job_id: str, reason: str, started: float) -> None:
    logger.warning(
        "Classifier fallback job_id=%s fallback_reason=%s latency_ms=%d",
        job_id,
        reason,
        int((time.monotonic() - started) * 1000),
    )


def process_job(
    job: Job,
    classifier: ReceiptClassifier,
    extract_queue: TaskQueue,
    job_store: JobStore,
    threshold: float,
) -> bool:
    started = time.monotonic()
    job_store.mark_processing(job.job_id)

    try:
        image_bytes = base64.b64decode(job.image_base64)
    except Exception:
        logger.exception("Could not decode job %s; forwarding to extraction", job.job_id)
        _log_fallback(job.job_id, "invalid_base64", started)
        return _forward(job, extract_queue, job_store)

    try:
        result = classifier.classify(image_bytes)
    except ClassifierUnavailable as exc:
        _log_fallback(job.job_id, str(exc), started)
        return _forward(job, extract_queue, job_store)
    except Exception as exc:
        logger.exception(
            "Unexpected classifier error for job %s; forwarding to extraction", job.job_id
        )
        _log_fallback(job.job_id, type(exc).__name__, started)
        return _forward(job, extract_queue, job_store)

    decision = "reject" if result.noul < threshold else "accept"
    logger.info(
        "Classifier decision job_id=%s noul=%.4f threshold=%.2f decision=%s latency_ms=%d",
        job.job_id,
        result.noul,
        threshold,
        decision,
        int((time.monotonic() - started) * 1000),
    )

    try:
        job_store.record_classification(job.job_id, result.noul, result.model)
    except Exception:
        logger.exception("Could not persist classifier score for job %s", job.job_id)

    if result.noul < threshold:
        try:
            job_store.reject(
                job.job_id, ErrorCode.NOT_A_RECEIPT.value, NOT_A_RECEIPT_MESSAGE
            )
        except Exception:
            logger.exception("Could not mark job %s rejected", job.job_id)
        return False

    return _forward(job, extract_queue, job_store)


def run_worker(
    queue: TaskQueue,
    extract_queue: TaskQueue,
    classifier: ReceiptClassifier,
    job_store: JobStore,
    threshold: float,
    stop_event: threading.Event | None = None,
    poll_interval: float = 1.0,
) -> None:
    while stop_event is None or not stop_event.is_set():
        try:
            job = queue.dequeue()
        except Exception:
            logger.exception("Queue dequeue failed; retrying")
            time.sleep(poll_interval)
            continue
        if job is None:
            time.sleep(poll_interval)
            continue
        try:
            process_job(job, classifier, extract_queue, job_store, threshold)
            logger.info("Classified job %s", job.job_id)
        except Exception:
            logger.exception("Failed to classify job %s", job.job_id)


def main() -> None:
    settings = get_settings()
    if not settings.openrouter_jev_api_key:
        logger.warning(
            "OPENROUTER_JEV_API_KEY is empty; all jobs will be forwarded to Gemini"
        )

    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    queue = RedisQueue(redis_client, CLASSIFY_QUEUE)
    extract_queue = RedisQueue(redis_client, EXTRACT_QUEUE)
    job_store = SupabaseJobStore(
        create_client(settings.supabase_url, settings.supabase_service_role_key)
    )
    jev = JevClient(
        settings.openrouter_jev_api_key,
        settings.openrouter_jev_model,
        timeout=settings.openrouter_timeout_seconds,
    )
    classifier = ReceiptClassifier(jev)
    run_worker(
        queue,
        extract_queue,
        classifier,
        job_store,
        settings.receipt_classifier_threshold,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_workers_classifier.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workers/classifier.py tests/test_workers_classifier.py
git commit -m "feat: add classifier worker with fail-open routing"
```

---

### Task 7: Route the API Through the Classifier Queue

**Files:**
- Modify: `app/main.py`
- Modify: `app/api/v1/receipt.py`
- Modify: `app/workers/worker.py`
- Modify: `tests/test_api_receipt.py`

**Interfaces:**
- Consumes: `CLASSIFY_QUEUE`, `EXTRACT_QUEUE`, `JobStatus.REJECTED`.
- Produces: POST enqueues to `receipt:classify`; GET renders `rejected`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_receipt.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_api_receipt.py -v
```

Expected: FAIL. The POST test sees `receipt:classify` empty; the rejected test gets only `{"status": "rejected"}`.

- [ ] **Step 3: Implement the API and worker wiring**

In `app/main.py`, update the queue import and construction:

```python
from app.queue.redis import CLASSIFY_QUEUE, RedisQueue
```

```python
    app.state.queue = RedisQueue(redis_client, CLASSIFY_QUEUE)
```

In `app/api/v1/receipt.py`, update `_to_status_response` to add the rejected branch after the failed branch:

```python
def _to_status_response(row: dict) -> dict:
    status = row["status"]
    if status == "completed":
        return {"status": status, "result": row["result"]}
    if status == "failed":
        return {
            "status": status,
            "error": {"code": row["error_code"], "message": row["error_message"]},
        }
    if status == "rejected":
        return {
            "status": status,
            "error": {"code": row["error_code"], "message": row["error_message"]},
        }
    return {"status": status}
```

In `app/workers/worker.py`, make the extract queue explicit:

```python
from app.queue.redis import EXTRACT_QUEUE, RedisQueue
```

```python
    queue = RedisQueue(redis_client, EXTRACT_QUEUE)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_api_receipt.py tests/test_workers.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/api/v1/receipt.py app/workers/worker.py tests/test_api_receipt.py
git commit -m "feat: route uploads through classifier queue and expose rejected status"
```

---

### Task 8: Docker Compose, Env Example, and README

**Files:**
- Modify: `docker/compose.yaml`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: `python -m app.workers.classifier`.
- Produces: a Compose service named `classifier`, new documented env vars, and README coverage.

- [ ] **Step 1: Add the failing verification commands**

Run:

```bash
docker compose -f docker/compose.yaml config --services | grep -qx classifier
grep -q '^OPENROUTER_JEV_API_KEY=' .env.example
grep -q 'classifier' README.md
```

Expected: the first and third commands fail before the changes; the second fails because the var is absent.

- [ ] **Step 2: Update Compose**

Replace `docker/compose.yaml` with:

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
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy

  classifier:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    command: ["python", "-m", "app.workers.classifier"]
    env_file:
      - ../.env
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy

  worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    command: ["python", "-m", "app.workers.worker"]
    env_file:
      - ../.env
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data
    ports:
      - "6379:6379"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  redis-data:
```

- [ ] **Step 3: Update `.env.example`**

Replace the contents with placeholders only:

```dotenv
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
VISION_API_KEY=
RATE_LIMIT_PER_MINUTE=30
MAX_IMAGE_BYTES=10485760
MAX_IMAGE_DIMENSION=1600
LOG_LEVEL=INFO
REDIS_URL=redis://redis:6379/0
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
OPENROUTER_JEV_API_KEY=
OPENROUTER_JEV_MODEL=typesafe/jev-1.14
RECEIPT_CLASSIFIER_THRESHOLD=0.3
OPENROUTER_TIMEOUT_SECONDS=5
```

The real keys that were previously committed in `.env.example` must be rotated in their provider
dashboards (Gemini, the vision API, and Supabase). This plan does not perform that rotation.

- [ ] **Step 4: Update the README**

In the Setup section, add the OpenRouter variables to the `cp .env.example .env` note:

```markdown
cp .env.example .env   # fill in GEMINI_API_KEY, VISION_API_KEY, REDIS_URL, SUPABASE_URL,
                       # SUPABASE_SERVICE_ROLE_KEY, and OPENROUTER_JEV_API_KEY
```

In the API section, add the rejected state:

```markdown
- `GET /api/v1/jobs/{jobId}` → `{ status }` | `{ status, result }` | `{ status, error }`
- A non-receipt image returns `200 { "status": "rejected", "error": { "code": "NOT_A_RECEIPT", ... } }`
```

In the Docker Compose section, describe the classifier:

```markdown
Runs `api`, `classifier`, `worker`, and `redis` (persisted via the `redis-data` volume with AOF).
`classifier` drains `receipt:classify`, calls OpenRouter Jev, and either rejects the job or forwards
it to `receipt:queue` for Gemini extraction. Supabase is external — configure `SUPABASE_URL` /
`SUPABASE_SERVICE_ROLE_KEY` and apply the migrations in `supabase/migrations/` to your project.
```

- [ ] **Step 5: Verify the configuration**

Run:

```bash
docker compose -f docker/compose.yaml config --services | grep -qx classifier
docker compose -f docker/compose.yaml config -q
grep -q '^OPENROUTER_JEV_API_KEY=' .env.example
grep -q 'classifier' README.md
```

Expected: all commands exit `0`.

- [ ] **Step 6: Build the classifier image**

Run:

```bash
docker compose -f docker/compose.yaml build classifier
```

Expected: image builds successfully.

- [ ] **Step 7: Commit**

```bash
git add docker/compose.yaml .env.example README.md
git commit -m "chore: add classifier service and document new config"
```

Do not stage `.env`.

---

### Task 9: Full Verification

**Files:**
- No new files. Fix any failures found.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified tests, lint, Compose config, and a manual fail-open check.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run pytest -v
```

Expected: PASS. If a test fails, fix the implementation and rerun before continuing.

- [ ] **Step 2: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 3: Verify Compose**

Run:

```bash
docker compose -f docker/compose.yaml config -q
docker compose -f docker/compose.yaml config --services | sort
```

Expected: `api`, `classifier`, `redis`, `worker` are listed.

- [ ] **Step 4: Apply the migration and start the stack**

Apply `supabase/migrations/0002_add_classifier_columns.sql` in the Supabase SQL editor or with the
Supabase CLI, then run:

```bash
docker compose -f docker/compose.yaml up -d --build
docker compose -f docker/compose.yaml ps
curl -sS http://localhost:8000/api/v1/health
```

Expected: all four services are running; health returns `{"status":"ok"}`.

- [ ] **Step 5: Verify the end-to-end classifier path manually**

Create a valid image and submit it with the configured `VISION_API_KEY`, then poll the job until it
leaves `pending`/`processing`:

```bash
uv run python - <<'PY'
import base64, io, json, os, time, urllib.request
from PIL import Image

img = Image.new("RGB", (600, 900), "white")
buf = io.BytesIO(); img.save(buf, format="JPEG")
payload = json.dumps({
    "image": {"base64": base64.b64encode(buf.getvalue()).decode(), "mimeType": "image/jpeg"}
}).encode()
key = [l.split("=", 1)[1].strip() for l in open(".env") if l.startswith("VISION_API_KEY=")][0]
headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
req = urllib.request.Request(
    "http://localhost:8000/api/v1/analyze-receipt", data=payload, headers=headers
)
with urllib.request.urlopen(req) as r:
    job = json.load(r)
print("created", job)
for _ in range(90):
    req = urllib.request.Request(
        f"http://localhost:8000/api/v1/jobs/{job['jobId']}",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req) as r:
        status = json.load(r)
    print(status)
    if status["status"] in {"completed", "failed", "rejected"}:
        break
    time.sleep(1)
PY
```

Expected with Jev available: the blank image is rejected with a low `classifier_score`. If Jev is
unavailable, the job is forwarded to Gemini and ends `completed` or `failed`; that fail-open path
is also covered by `tests/test_workers_classifier.py`.

To verify score storage, run this in the Supabase SQL editor after a real Jev call:

```sql
select status, classifier_score, classifier_model
from receipt_jobs
order by created_at desc
limit 5;
```

Expected: `classifier_score` / `classifier_model` are populated when Jev answered, null when the
classifier fail-opened.

- [ ] **Step 6: Commit any verification fixes**

If Step 1 or 2 required code changes, review the diff, stage the modified tracked files, and commit:

```bash
git diff
git add -u
git commit -m "fix: address classifier verification findings"
```

If no changes were needed, skip this step.

# PrettyCash Backend — Dockerise with Redis Queue & Supabase Job Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make receipt analysis asynchronous (enqueue → jobId → poll), backed by Redis as the job queue and Supabase as the durable job-status/result store, all wired together with Docker Compose.

**Architecture:** `api` enqueues a job into a Redis list and creates a `pending` row in Supabase, returning `202 {jobId}`. A `worker` drains the queue, calls Gemini, and writes `completed`/`failed` to Supabase. The app polls `GET /jobs/{id}` (reads Supabase). Rate limiting moves from in-memory to Redis.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, redis-py, supabase-py, Pillow, httpx, pydantic-settings, pytest + pytest-asyncio + respx + fakeredis, ruff, uv, Docker Compose.

## Global Constraints

- Python **3.12**; deps managed by `uv`; lint-clean under ruff (E, F, I, UP, B) at line-length 100.
- Gemini model **`gemini-3.1-flash-lite`**; `GEMINI_API_KEY` server-side only.
- `POST /api/v1/analyze-receipt` becomes **async**: returns **`202 { "jobId", "status": "pending" }`** (replaces the old synchronous 200 result).
- `GET /api/v1/jobs/{job_id}` returns `{ status }`, `{ status, result }`, or `{ status, error }`; unknown id → **404** (`NOT_FOUND`).
- Redis queue key **`receipt:queue`** (list); rate-limit key **`rate_limit:{api_key}`** (60s window, `INCR`+`EXPIRE`).
- Supabase table **`receipt_jobs`**; statuses exactly `pending`, `processing`, `completed`, `failed`.
- New required env vars: **`REDIS_URL`**, **`SUPABASE_URL`**, **`SUPABASE_SERVICE_ROLE_KEY`**.
- Error shape is always `{ "error": { "code", "message" } }`; worker failures store a **generic** message (never provider details/keys).
- New runtime deps `redis`, `supabase`; dev dep `fakeredis`.

---

### Task 1: Dependencies, config, errors, and Supabase migration

**Files:**
- Modify: `pyproject.toml` (add deps)
- Modify: `app/core/config.py`
- Modify: `app/core/errors.py`
- Modify: `.env.example`
- Create: `supabase/migrations/0001_create_receipt_jobs.sql`
- Modify: `tests/conftest.py` (settings fixture)
- Modify: `tests/test_core.py`
- Modify: `tests/test_api_receipt.py:140-147` (inline `Settings(...)` in rate-limit test)

**Interfaces:**
- Produces: `Settings` gains required fields `redis_url: str`, `supabase_url: str`, `supabase_service_role_key: str`; `ErrorCode.NOT_FOUND` and `NotFoundError` (status 404); a migration SQL file for the `receipt_jobs` table.

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

In `[project]` `dependencies`, add two lines after `"pillow-heif>=0.18",`:

```toml
    "redis>=5.0",
    "supabase>=2.6",
```

In `[dependency-groups]` `dev`, add one line after `"respx>=0.21",`:

```toml
    "fakeredis>=2.24",
```

- [ ] **Step 2: Install dependencies**

Run: `uv sync`
Expected: exit 0; `uv.lock` regenerated.

- [ ] **Step 3: Update `app/core/config.py`**

Add three required fields (keep existing fields and defaults):

```python
class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    vision_api_key: str
    redis_url: str
    supabase_url: str
    supabase_service_role_key: str
    rate_limit_per_minute: int = 30
    max_image_bytes: int = 10 * 1024 * 1024
    max_image_dimension: int = 1600
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
```

- [ ] **Step 4: Update `app/core/errors.py`**

Add `NOT_FOUND` to `ErrorCode` and a `NotFoundError` class:

```python
class ErrorCode(StrEnum):
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_IMAGE = "INVALID_IMAGE"
    UNPROCESSABLE = "UNPROCESSABLE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"
    NOT_FOUND = "NOT_FOUND"
```

Add after `InternalError`:

```python
class NotFoundError(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    default_message = "Not found"
```

- [ ] **Step 5: Update `.env.example`**

Append three lines:

```
REDIS_URL=redis://redis:6379/0
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

- [ ] **Step 6: Create `supabase/migrations/0001_create_receipt_jobs.sql`**

```sql
create table if not exists receipt_jobs (
    id            uuid primary key default gen_random_uuid(),
    status        text not null default 'pending',
    result        jsonb,
    error_code    text,
    error_message text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create or replace function set_updated_at() returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists receipt_jobs_set_updated_at on receipt_jobs;
create trigger receipt_jobs_set_updated_at
before update on receipt_jobs
for each row execute function set_updated_at();
```

- [ ] **Step 7: Update `tests/conftest.py` settings fixture**

```python
@pytest.fixture
def settings() -> Settings:
    return Settings(
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.1-flash-lite",
        vision_api_key="test-vision-key",
        redis_url="redis://localhost:6379/0",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-role-key",
        rate_limit_per_minute=30,
    )
```

- [ ] **Step 8: Update `tests/test_core.py`**

```python
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ErrorCode,
    InternalError,
    InvalidImageError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    UnprocessableError,
)


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
        "NOT_FOUND",
    }
    assert InternalError().status_code == 500
    assert RateLimitedError().status_code == 429
    assert UnprocessableError().status_code == 422
    assert NotFoundError().status_code == 404
    assert NotFoundError().code == ErrorCode.NOT_FOUND
```

- [ ] **Step 9: Update `tests/test_api_receipt.py` inline `Settings(...)`**

In `test_analyze_receipt_rate_limited`, replace the `Settings(...)` block with:

```python
        Settings(
            gemini_api_key="g",
            vision_api_key="test-vision-key",
            redis_url="redis://localhost:6379/0",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="key",
            rate_limit_per_minute=1,
        )
```

- [ ] **Step 10: Run tests to verify green**

Run: `uv run pytest -q`
Expected: all tests pass (the new fields are required but supplied everywhere).

- [ ] **Step 11: Lint**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "Add redis/supabase deps, config, NotFoundError, and migration"
```

---

### Task 2: Job model, Redis queue, Redis rate limiter, job store, and worker

**Files:**
- Modify: `app/queue/base.py` (redefine `Job`)
- Modify: `app/queue/redis.py` (real implementation)
- Create: `app/services/ratelimit.py`
- Create: `app/store/__init__.py`
- Create: `app/store/base.py`
- Create: `app/store/supabase.py`
- Modify: `app/workers/worker.py` (use new `Job` + `JobStore` + `RedisQueue`)
- Test: `tests/test_queue.py` (rewrite)
- Create: `tests/test_ratelimit.py`
- Create: `tests/test_store.py`
- Test: `tests/test_workers.py` (rewrite)

**Interfaces:**
- Consumes: `RateLimitedError`, `AppError`/`ErrorCode`, `Settings`, `ReceiptAnalyzer`/`ReceiptDraft`, `GeminiClient`.
- Produces:
  - `Job` dataclass: `job_id: str`, `image_base64: str`, `mime_type: str`.
  - `TaskQueue` protocol (unchanged shape): `enqueue(job) -> None`, `dequeue() -> Job | None`, `size() -> int`.
  - `SyncQueue` (in-memory, unchanged) and `RedisQueue(redis_client)` (over Redis list `receipt:queue`).
  - `RedisRateLimiter(redis_client, per_minute)` with `check(key) -> None`.
  - `JobStatus` StrEnum (`pending`/`processing`/`completed`/`failed`), `JobStore` protocol, `SupabaseJobStore(client)`.
  - worker `process_job(job, analyzer, job_store) -> ReceiptDraft` and updated `run_worker`.

- [ ] **Step 1: Rewrite `app/queue/base.py`**

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Job:
    job_id: str
    image_base64: str
    mime_type: str


class TaskQueue(Protocol):
    def enqueue(self, job: Job) -> None: ...

    def dequeue(self) -> Job | None: ...

    def size(self) -> int: ...
```

- [ ] **Step 2: Rewrite `app/queue/redis.py`**

```python
import json

from app.queue.base import Job

QUEUE_KEY = "receipt:queue"


class RedisQueue:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def enqueue(self, job: Job) -> None:
        payload = json.dumps(
            {"job_id": job.job_id, "image_base64": job.image_base64, "mime_type": job.mime_type}
        )
        self._redis.lpush(QUEUE_KEY, payload)

    def dequeue(self) -> Job | None:
        item = self._redis.brpop(QUEUE_KEY, timeout=1)
        if item is None:
            return None
        data = json.loads(item[1])
        return Job(job_id=data["job_id"], image_base64=data["image_base64"], mime_type=data["mime_type"])

    def size(self) -> int:
        return self._redis.llen(QUEUE_KEY)
```

- [ ] **Step 3: Create `app/services/ratelimit.py`**

```python
from app.core.errors import RateLimitedError

RATE_LIMIT_KEY = "rate_limit:{key}"
RATE_LIMIT_WINDOW_SECONDS = 60


class RedisRateLimiter:
    def __init__(self, redis_client, per_minute: int) -> None:
        self._redis = redis_client
        self._per_minute = per_minute

    def check(self, key: str) -> None:
        redis_key = RATE_LIMIT_KEY.format(key=key)
        count = self._redis.incr(redis_key)
        if count == 1:
            self._redis.expire(redis_key, RATE_LIMIT_WINDOW_SECONDS)
        if count > self._per_minute:
            raise RateLimitedError("Rate limit exceeded")
```

- [ ] **Step 4: Create `app/store/__init__.py` (empty) and `app/store/base.py`**

```python
from enum import StrEnum
from typing import Any, Protocol


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStore(Protocol):
    def create(self) -> str: ...

    def mark_processing(self, job_id: str) -> None: ...

    def complete(self, job_id: str, result: dict[str, Any]) -> None: ...

    def fail(self, job_id: str, code: str, message: str) -> None: ...

    def get(self, job_id: str) -> dict[str, Any] | None: ...
```

- [ ] **Step 5: Create `app/store/supabase.py`**

```python
from typing import Any

from supabase import Client

from app.store.base import JobStatus


class SupabaseJobStore:
    TABLE = "receipt_jobs"

    def __init__(self, client: Client) -> None:
        self._client = client

    def create(self) -> str:
        res = self._client.table(self.TABLE).insert({"status": JobStatus.PENDING.value}).execute()
        return res.data[0]["id"]

    def mark_processing(self, job_id: str) -> None:
        self._client.table(self.TABLE).update({"status": JobStatus.PROCESSING.value}).eq("id", job_id).execute()

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        self._client.table(self.TABLE).update(
            {"status": JobStatus.COMPLETED.value, "result": result}
        ).eq("id", job_id).execute()

    def fail(self, job_id: str, code: str, message: str) -> None:
        self._client.table(self.TABLE).update(
            {"status": JobStatus.FAILED.value, "error_code": code, "error_message": message}
        ).eq("id", job_id).execute()

    def get(self, job_id: str) -> dict[str, Any] | None:
        res = self._client.table(self.TABLE).select("*").eq("id", job_id).execute()
        return res.data[0] if res.data else None
```

- [ ] **Step 6: Rewrite `app/workers/worker.py`**

```python
import base64
import logging
import threading
import time

from redis import Redis
from supabase import create_client

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.queue.base import Job, TaskQueue
from app.queue.redis import RedisQueue
from app.services.gemini import GeminiClient
from app.services.receipt import ReceiptAnalyzer, ReceiptDraft
from app.store.base import JobStore
from app.store.supabase import SupabaseJobStore

logger = logging.getLogger(__name__)


def _to_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, AppError) and exc.code != ErrorCode.INTERNAL:
        return exc.code.value, exc.message
    return ErrorCode.INTERNAL.value, "Receipt analysis failed"


def process_job(job: Job, analyzer: ReceiptAnalyzer, job_store: JobStore) -> ReceiptDraft:
    job_store.mark_processing(job.job_id)
    try:
        image_bytes = base64.b64decode(job.image_base64)
        draft = analyzer.analyze(image_bytes, job.mime_type)
    except Exception as exc:
        code, message = _to_error(exc)
        job_store.fail(job.job_id, code, message)
        raise
    job_store.complete(job.job_id, draft.model_dump(exclude_none=True))
    return draft


def run_worker(
    queue: TaskQueue,
    analyzer: ReceiptAnalyzer,
    job_store: JobStore,
    stop_event: threading.Event | None = None,
    poll_interval: float = 1.0,
) -> None:
    while stop_event is None or not stop_event.is_set():
        job = queue.dequeue()
        if job is None:
            time.sleep(poll_interval)
            continue
        try:
            process_job(job, analyzer, job_store)
            logger.info("Processed job %s", job.job_id)
        except Exception:  # noqa: BLE001 - worker must keep running on bad jobs
            logger.exception("Failed to process job %s", job.job_id)


def main() -> None:
    settings = get_settings()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    queue = RedisQueue(redis_client)
    job_store = SupabaseJobStore(
        create_client(settings.supabase_url, settings.supabase_service_role_key)
    )
    gemini = GeminiClient(settings.gemini_api_key, settings.gemini_model)
    analyzer = ReceiptAnalyzer(gemini)
    run_worker(queue, analyzer, job_store)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Rewrite `tests/test_queue.py`**

```python
import fakeredis

from app.queue.base import Job
from app.queue.redis import RedisQueue
from app.queue.sync import SyncQueue


def test_sync_queue_roundtrip():
    q = SyncQueue()
    job = Job(job_id="abc", image_base64="aGk=", mime_type="image/jpeg")
    q.enqueue(job)
    assert q.size() == 1
    assert q.dequeue() is job
    assert q.dequeue() is None


def test_redis_queue_roundtrip():
    r = fakeredis.FakeRedis(decode_responses=True)
    q = RedisQueue(r)
    job = Job(job_id="abc", image_base64="aGk=", mime_type="image/jpeg")
    q.enqueue(job)
    assert q.size() == 1
    dequeued = q.dequeue()
    assert dequeued == job
    assert dequeued.job_id == "abc"
    assert dequeued.image_base64 == "aGk="
    assert q.size() == 0


def test_redis_queue_dequeue_empty():
    r = fakeredis.FakeRedis(decode_responses=True)
    q = RedisQueue(r)
    assert q.dequeue() is None
```

- [ ] **Step 8: Create `tests/test_ratelimit.py`**

```python
import fakeredis
import pytest

from app.core.errors import RateLimitedError
from app.services.ratelimit import RedisRateLimiter


def test_allows_up_to_limit():
    r = fakeredis.FakeRedis(decode_responses=True)
    limiter = RedisRateLimiter(r, per_minute=2)
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(RateLimitedError):
        limiter.check("k")


def test_isolates_keys():
    r = fakeredis.FakeRedis(decode_responses=True)
    limiter = RedisRateLimiter(r, per_minute=1)
    limiter.check("a")
    limiter.check("b")
```

- [ ] **Step 9: Create `tests/test_store.py`**

```python
from app.store.base import JobStatus
from app.store.supabase import SupabaseJobStore


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client):
        self._client = client

    def insert(self, data):
        self._client.calls.append(("insert", data))
        return self

    def update(self, data):
        self._client.calls.append(("update", data))
        return self

    def select(self, *cols):
        self._client.calls.append(("select", cols))
        return self

    def eq(self, col, val):
        self._client.calls.append(("eq", col, val))
        return self

    def execute(self):
        return FakeResponse(self._client.next_data)


class FakeSupabaseClient:
    def __init__(self):
        self.calls = []
        self.next_data = []

    def table(self, name):
        return FakeQuery(self)


def test_create_returns_id():
    client = FakeSupabaseClient()
    client.next_data = [{"id": "abc"}]
    store = SupabaseJobStore(client)
    assert store.create() == "abc"
    assert client.calls[0] == ("insert", {"status": JobStatus.PENDING.value})


def test_mark_processing():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.mark_processing("abc")
    assert client.calls[0] == ("update", {"status": JobStatus.PROCESSING.value})
    assert client.calls[1] == ("eq", "id", "abc")


def test_complete_updates_result():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.complete("abc", {"merchant": "X", "amount": 1.0})
    assert client.calls[0] == (
        "update",
        {"status": JobStatus.COMPLETED.value, "result": {"merchant": "X", "amount": 1.0}},
    )


def test_fail_updates_error():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    store.fail("abc", "INTERNAL", "boom")
    assert client.calls[0] == (
        "update",
        {"status": JobStatus.FAILED.value, "error_code": "INTERNAL", "error_message": "boom"},
    )


def test_get_returns_row_or_none():
    client = FakeSupabaseClient()
    store = SupabaseJobStore(client)
    client.next_data = [{"id": "abc", "status": "completed"}]
    assert store.get("abc") == {"id": "abc", "status": "completed"}
    client.next_data = []
    assert store.get("abc") is None
```

- [ ] **Step 10: Rewrite `tests/test_workers.py`**

```python
import pytest

from app.queue.base import Job
from app.services.receipt import ReceiptDraft
from app.workers.worker import process_job


class FakeAnalyzer:
    def analyze(self, image_bytes: bytes, mime_type: str) -> ReceiptDraft:
        return ReceiptDraft(merchant="X", amount=1.0)


class FailingAnalyzer:
    def analyze(self, image_bytes: bytes, mime_type: str) -> ReceiptDraft:
        raise RuntimeError("boom")


def test_process_job_completes(job_store):
    job = Job(job_id="job-1", image_base64="aGk=", mime_type="image/jpeg")
    draft = process_job(job, FakeAnalyzer(), job_store)
    assert draft.merchant == "X"
    assert job_store.get("job-1")["status"] == "completed"
    assert job_store.get("job-1")["result"]["merchant"] == "X"


def test_process_job_fails_on_error(job_store):
    job = Job(job_id="job-1", image_base64="aGk=", mime_type="image/jpeg")
    with pytest.raises(RuntimeError):
        process_job(job, FailingAnalyzer(), job_store)
    assert job_store.get("job-1")["status"] == "failed"
    assert job_store.get("job-1")["error_code"] == "INTERNAL"
    assert job_store.get("job-1")["error_message"] == "Receipt analysis failed"
```

- [ ] **Step 11: Add `FakeJobStore` and a `job_store` fixture to `tests/conftest.py`**

Append this class (before the fixtures) and this fixture (after the `settings` fixture):

```python
class FakeJobStore:
    def __init__(self):
        self.rows = {}
        self.counter = 0

    def create(self) -> str:
        self.counter += 1
        job_id = f"job-{self.counter}"
        self.rows[job_id] = {"status": "pending"}
        return job_id

    def mark_processing(self, job_id: str) -> None:
        self.rows[job_id]["status"] = "processing"

    def complete(self, job_id: str, result: dict) -> None:
        self.rows[job_id] = {"status": "completed", "result": result}

    def fail(self, job_id: str, code: str, message: str) -> None:
        self.rows[job_id] = {"status": "failed", "error_code": code, "error_message": message}

    def get(self, job_id: str) -> dict | None:
        return self.rows.get(job_id)


@pytest.fixture
def job_store() -> FakeJobStore:
    return FakeJobStore()
```

- [ ] **Step 12: Run tests to verify green**

Run: `uv run pytest -q`
Expected: all tests pass (main.py/receipt.py still use the in-memory `RateLimiter`/`SyncQueue`/`analyzer`, which remain untouched).

- [ ] **Step 13: Lint**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "Add Redis queue, Redis rate limiter, job store, and worker rework"
```

---

### Task 3: Async API endpoints and app wiring

**Files:**
- Modify: `app/api/v1/schemas.py`
- Modify: `app/api/v1/receipt.py`
- Modify: `app/api/deps.py` (remove in-memory `RateLimiter`)
- Modify: `app/main.py`
- Modify: `tests/conftest.py` (client fixture + `job_store` fixture)
- Test: `tests/test_api_receipt.py` (rewrite)
- Delete: `tests/test_deps.py`

**Interfaces:**
- Consumes: `RedisQueue`, `RedisRateLimiter`, `JobStore`/`SupabaseJobStore`, `Job`, `NotFoundError`, `ReceiptDraft`.
- Produces: `create_app(settings=None, *, job_store: JobStore | None = None, redis_client=None) -> FastAPI`; routes `POST /analyze-receipt` (202) and `GET /jobs/{job_id}`.

- [ ] **Step 1: Rewrite `app/api/v1/schemas.py`**

```python
from pydantic import BaseModel

from app.services.receipt import ReceiptDraft


class ImagePayload(BaseModel):
    base64: str
    mimeType: str


class AnalyzeReceiptRequest(BaseModel):
    image: ImagePayload


class AnalyzeReceiptAccepted(BaseModel):
    jobId: str
    status: str


class JobError(BaseModel):
    code: str
    message: str


class JobStatusResponse(BaseModel):
    status: str
    result: ReceiptDraft | None = None
    error: JobError | None = None
```

- [ ] **Step 2: Rewrite `app/api/v1/receipt.py`**

```python
import base64

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_rate_limit
from app.api.v1.schemas import AnalyzeReceiptAccepted, AnalyzeReceiptRequest, JobStatusResponse
from app.core.errors import NotFoundError
from app.queue.base import Job
from app.services.image import decode_and_process

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/analyze-receipt", response_model=AnalyzeReceiptAccepted, status_code=202)
async def analyze_receipt(
    payload: AnalyzeReceiptRequest,
    request: Request,
    _token: str = Depends(require_rate_limit),
):
    settings = request.app.state.settings
    queue = request.app.state.queue
    job_store = request.app.state.job_store

    image_bytes, mime_type = await run_in_threadpool(
        decode_and_process, payload.image.base64, settings
    )
    job_id = job_store.create()
    queue.enqueue(
        Job(
            job_id=job_id,
            image_base64=base64.b64encode(image_bytes).decode(),
            mime_type=mime_type,
        )
    )
    return {"jobId": job_id, "status": "pending"}


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    response_model_exclude_none=True,
)
async def get_job(job_id: str, request: Request, _token: str = Depends(require_rate_limit)):
    row = request.app.state.job_store.get(job_id)
    if row is None:
        raise NotFoundError("Job not found")
    return _to_status_response(row)


def _to_status_response(row: dict) -> dict:
    status = row["status"]
    if status == "completed":
        return {"status": status, "result": row["result"]}
    if status == "failed":
        return {
            "status": status,
            "error": {"code": row["error_code"], "message": row["error_message"]},
        }
    return {"status": status}
```

- [ ] **Step 3: Rewrite `app/api/deps.py`**

```python
import secrets

from fastapi import Depends, Request

from app.core.errors import UnauthorizedError


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

- [ ] **Step 4: Rewrite `app/main.py`**

```python
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException
from supabase import create_client

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode, InternalError
from app.core.logging import configure_logging
from app.queue.redis import RedisQueue
from app.services.ratelimit import RedisRateLimiter
from app.store.base import JobStore
from app.store.supabase import SupabaseJobStore


def create_app(
    settings: Settings | None = None,
    *,
    job_store: JobStore | None = None,
    redis_client: Redis | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    redis_client = redis_client or Redis.from_url(settings.redis_url, decode_responses=True)
    job_store = job_store or SupabaseJobStore(
        create_client(settings.supabase_url, settings.supabase_service_role_key)
    )

    app = FastAPI(title="PrettyCash Backend", version="0.1.0")

    app.state.settings = settings
    app.state.queue = RedisQueue(redis_client)
    app.state.rate_limiter = RedisRateLimiter(redis_client, settings.rate_limit_per_minute)
    app.state.job_store = job_store

    app.include_router(api_router)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        message = exc.default_message if exc.code == ErrorCode.INTERNAL else exc.message
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code.value, "message": message}},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": ErrorCode.UNPROCESSABLE.value, "message": "Invalid request"}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = ErrorCode.INTERNAL if exc.status_code >= 500 else ErrorCode.UNPROCESSABLE
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code.value, "message": str(exc.detail)}},
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

- [ ] **Step 5: Update `tests/conftest.py`**

Add `fakeredis` import and a `job_store` fixture, and rewrite the `client` fixture:

```python
import fakeredis
import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


class FakeJobStore:
    def __init__(self):
        self.rows = {}
        self.counter = 0

    def create(self) -> str:
        self.counter += 1
        job_id = f"job-{self.counter}"
        self.rows[job_id] = {"status": "pending"}
        return job_id

    def mark_processing(self, job_id: str) -> None:
        self.rows[job_id]["status"] = "processing"

    def complete(self, job_id: str, result: dict) -> None:
        self.rows[job_id] = {"status": "completed", "result": result}

    def fail(self, job_id: str, code: str, message: str) -> None:
        self.rows[job_id] = {"status": "failed", "error_code": code, "error_message": message}

    def get(self, job_id: str) -> dict | None:
        return self.rows.get(job_id)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.1-flash-lite",
        vision_api_key="test-vision-key",
        redis_url="redis://localhost:6379/0",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-role-key",
        rate_limit_per_minute=30,
    )


@pytest.fixture
def job_store() -> FakeJobStore:
    return FakeJobStore()


@pytest.fixture
def client(settings, job_store):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    app = create_app(settings, job_store=job_store, redis_client=redis_client)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")
```

- [ ] **Step 6: Rewrite `tests/test_api_receipt.py`**

```python
import base64
import io

import fakeredis
import httpx
import pytest
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
```

- [ ] **Step 7: Delete `tests/test_deps.py`**

```bash
rm tests/test_deps.py
```

- [ ] **Step 8: Run tests to verify green**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 9: Lint**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Make receipt analysis async with Redis queue and Supabase jobs"
```

---

### Task 4: Docker Compose, README, and lint gate

**Files:**
- Modify: `docker/compose.yaml`
- Modify: `README.md`

**Interfaces:**
- Produces: a Compose file with `api`, `worker`, and a durable `redis` (volume + AOF); accurate README.

- [ ] **Step 1: Rewrite `docker/compose.yaml`**

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
    depends_on:
      - redis

  worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    command: ["python", "-m", "app.workers.worker"]
    env_file:
      - ../.env
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data
    ports:
      - "6379:6379"

volumes:
  redis-data:
```

- [ ] **Step 2: Rewrite `README.md`**

```markdown
# PrettyCash Backend

FastAPI backend for PrettyCash's AI receipt scanning. Accepts a receipt image, enqueues it for
AI analysis, and exposes the result via a polling endpoint. Uses Redis for the job queue and
Supabase (Postgres) for durable job status.

## Setup

```bash
uv sync
cp .env.example .env   # fill in GEMINI_API_KEY, VISION_API_KEY, REDIS_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
```

## Run locally

```bash
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
uv run python -m app.workers.worker
```

## Test & lint

```bash
uv run pytest
uv run ruff check .
```

## API

- `POST /api/v1/analyze-receipt` → `202 { "jobId", "status": "pending" }`
- `GET /api/v1/jobs/{jobId}` → `{ status }` | `{ status, result }` | `{ status, error }`

See `docs/superpowers/specs/` for the full contract.

## Docker Compose

```bash
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up
```

Runs `api`, `worker`, and `redis` (persisted via the `redis-data` volume with AOF). Supabase is
external — configure `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` and apply the migration in
`supabase/migrations/` to your project.
```

- [ ] **Step 3: Full lint and test gate**

Run: `uv run ruff check .`
Expected: no errors.

Run: `uv run pytest`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Add Redis service to Compose and update README"
```

---

## Self-Review Notes

- **Spec coverage:** §2 architecture (queue + worker + store) → Tasks 2–3; §3.1 POST 202 async → Task 3; §3.2 GET /jobs/{id} → Task 3; §3.3 health (unchanged) → Task 3 keeps it; §4 lifecycle → worker (Task 2) + statuses; §5 Supabase schema → migration (Task 1); §6 Redis keys → `RedisQueue`/`RedisRateLimiter` (Task 2); §7 config → Task 1; §8 Compose → Task 4; §9 errors (404 `NOT_FOUND`, generic worker messages) → Tasks 1–3; §10 testing (fakes for Redis/Supabase) → Task 2/3 tests; §11 deps → Task 1.
- **Type consistency:** `Job(job_id, image_base64, mime_type)` used identically in `base.py`, `redis.py`, `receipt.py` (Task 3), `worker.py`, and tests. `JobStore` protocol methods (`create`/`mark_processing`/`complete`/`fail`/`get`) match `SupabaseJobStore` and `FakeJobStore`. `create_app(settings, *, job_store, redis_client)` signature matches conftest and the rate-limit test. `JobStatus` values (`pending`/`processing`/`completed`/`failed`) match `receipt_jobs.status` and `_to_status_response`.
- **Mid-plan greenness:** Task 1 only adds fields/deps/errors (construction sites updated in the same task). Task 2 leaves `main.py`/`receipt.py`/`deps.py` untouched so the old in-memory path still boots. Task 3 swaps the HTTP layer and wiring in one coherent change, deleting `test_deps.py` with the removed `RateLimiter`.

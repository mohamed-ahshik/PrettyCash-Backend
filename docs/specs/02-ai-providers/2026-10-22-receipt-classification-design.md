---
title: "Receipt Pre-Classification with Jev"
type: spec
status: implemented
date: 2026-10-22
section: ai-providers
tags:
  - prettycash
  - spec
  - ai
  - jev
  - classifier
  - queue
---

# PrettyCash Backend — Receipt Pre-Classification with Jev (Design)

**Date:** 2026-10-22
**Status:** Implemented
**Implementation status:** Implemented and verified end-to-end

---

## Related

- Architecture: [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]], [[ARCHITECTURE#7. Request and Data Flow|Request and Data Flow]], [[ARCHITECTURE#9. Data Storage|Data Storage]]
- Section: [[AI-PROVIDERS]]
- Plan: [[2026-10-22-receipt-classification|Classifier implementation]]
- Transport: [[2026-10-22-litellm-migration-design|Gemini and Jev via LiteLLM]]
- Queue/storage base: [[2026-09-13-prettycash-backend-redis-queue-design|Redis Queue and Supabase Job Store]]

---

## Architecture Alignment

Read `docs/prettycash-backend-architecture/ARCHITECTURE.md` before implementing this spec.

- **Layers touched:** API queue target and rejected mapping, `app/queue/`, `app/services/jev.py`,
  `app/services/classifier.py`, `app/workers/classifier.py`, `app/store/`, and Supabase migrations.
- **New boundaries:** `receipt:classify` queue, `classifier` worker/service, `rejected` job status,
  and `classifier_score` / `classifier_model` columns.
- **Boundaries preserved:** the classifier worker orchestrates; Jev stays in `app/services/`; the
  API only selects the queue and maps the new terminal status.
- **Current → target:** API → `receipt:queue` → Gemini becomes API → `receipt:classify` →
  classifier → (`rejected` | `receipt:queue`) → Gemini.
- **After implementation:** move the classifier from "Approved Target" to "Current Runtime" in
  `ARCHITECTURE.md`, update the spec/plan index, and append the change log.

---

## 1. Overview & Objective

Add a cheap, fast pre-classification step before Gemini: use the OpenRouter Decisions model
`typesafe/jev-1.14` (configured through `OPENROUTER_JEV_MODEL`) to decide whether an uploaded
image is a receipt or invoice. Non-receipts are marked `rejected` immediately and never reach
Gemini. Receipts — and anything the classifier cannot confidently decide — continue through the
existing Gemini extraction pipeline.

The API stays asynchronous. `POST /api/v1/analyze-receipt` still returns `202 {jobId, status}`;
the client still polls `GET /api/v1/jobs/{jobId}`.

The classifier runs on its own queue and worker so a slow Gemini extraction can never delay the
"not a receipt" verdict for a later upload.

### 1.1 Why this shape

- **Async, isolated classifier queue:** the user-visible verdict stays fast under load.
- **Fail-open:** an OpenRouter outage or a missing key must not reject real receipts.
- **Persisted score:** `noul` and the model version are stored for later threshold tuning.
- **No API contract change:** only a new terminal job status is added.

---

## 2. Decisions Locked During Brainstorming

| Decision | Value |
|---|---|
| Classification placement | Worker, asynchronous (not in the API request) |
| Queue topology | Separate `receipt:classify` queue + dedicated `classifier` worker |
| Non-receipt contract | New job status `rejected` with error code `NOT_A_RECEIPT` |
| Failure policy | Fail open to Gemini on any classifier failure |
| Reject threshold | `noul < 0.3` (configurable) |
| Jev timeout | 5 seconds total |
| Receipt definition | Receipts, bills, and invoices only; reject bank statements, order confirmations, and unrelated images |
| Classifier image size | Normalize a copy in the classifier to Jev's 256–1568 px window; skip Jev and fail open if too small |
| EXIF orientation | Fix in the API image pipeline for both Jev and Gemini |
| Score persistence | `classifier_score` and `classifier_model` columns; threshold is not stored per row |
| Extraction queue | Keep the existing `receipt:queue` name so old queued jobs still drain |
| Compose | Add a third app container, `classifier`, alongside `api` and `worker` |

---

## 3. Architecture

```
Client
  │ POST /api/v1/analyze-receipt
  ▼
┌─────┐   create pending row    ┌──────────┐
│ api │ ──────────────────────► │ Supabase │
│     │   LPUSH receipt:classify└──────────┘
└──┬──┘
   │ 202 {jobId, status:"pending"}
   ▼
 receipt:classify
   │ BRPOP
   ▼
┌────────────┐   noul >= 0.3         ┌─────────────────┐
│ classifier │ ────────────────────► │ receipt:queue   │
│  worker    │                       └────────┬────────┘
│            │   noul < 0.3                     │ BRPOP
│            │ ──► status=rejected              ▼
└────────────┘                          ┌──────────────┐
                                        │ Gemini worker│
                                        │  (existing)  │
                                        └──────┬───────┘
                                               │ completed | failed
                                               ▼
                                           Supabase
```

### 3.1 Components

- **API (`app/main.py`, `app/api/v1/`)** — unchanged contract. After image validation, creates the
  Supabase row and pushes the job payload to `receipt:classify`.
- **Classifier worker (`app/workers/classifier.py`, new)** — consumes `receipt:classify`, records
  the Jev score, and either rejects the job or republishes the same payload to `receipt:queue`.
- **Jev client (`app/services/jev.py`, new)** — OpenRouter Decisions API client.
- **Receipt classifier (`app/services/classifier.py`, new)** — image normalization plus the Jev
  call; raises `ClassifierUnavailable` for every fail-open condition.
- **Gemini worker (`app/workers/worker.py`)** — unchanged behavior; consumes `receipt:queue`.
- **Redis** — `receipt:classify` and `receipt:queue` lists.
- **Supabase** — `receipt_jobs` remains the single durable record for the upload. The classifier
  writes `processing`, `classifier_score`, `classifier_model`, and on rejection `rejected` to the
  same row that the API created.

### 3.2 Files touched

```
app/
├── main.py                         # enqueue to receipt:classify
├── api/v1/receipt.py               # map rejected status
├── core/config.py                  # OpenRouter/classifier settings
├── core/errors.py                  # NOT_A_RECEIPT error code
├── queue/redis.py                  # configurable queue key
├── services/image.py               # EXIF orientation fix
├── services/jev.py                 # new: Decisions API client
├── services/classifier.py          # new: normalize + classify
├── store/base.py                   # JobStatus.REJECTED, record_classification, reject
├── store/supabase.py               # implement the new store methods
└── workers/
    ├── classifier.py               # new: classifier worker loop
    └── worker.py                   # explicitly consume receipt:queue
docker/compose.yaml                 # new classifier service
README.md                           # document classifier service and rejected status
supabase/migrations/0002_add_classifier_columns.sql
.env.example                        # new vars + placeholder cleanup
tests/                              # new and updated tests (including conftest FakeJobStore)
```

---

## 4. Request and Job Lifecycle

### 4.1 `POST /api/v1/analyze-receipt` (unchanged contract)

1. Authenticate and rate-limit as today.
2. Validate the body and image as today.
3. Apply EXIF orientation, downscale to `MAX_IMAGE_DIMENSION` (default 1600), re-encode as JPEG.
4. Insert a `receipt_jobs` row with `status = 'pending'`.
5. `LPUSH receipt:classify` with `{job_id, image_base64, mime_type}`.
6. Return `202 {"jobId": "<uuid>", "status": "pending"}`.

A non-image or unreadable file still returns `400 INVALID_IMAGE` synchronously. Jev only ever
sees images that passed step 2.

### 4.2 Classifier worker

1. `BRPOP receipt:classify`.
2. `job_store.mark_processing(job_id)`.
3. Decode the base64 JPEG.
4. Build a Jev-safe image copy (Section 5).
5. Call Jev with a single `noul` question (Section 6).
6. On a valid answer:
   - `job_store.record_classification(job_id, noul, model)`.
   - If `noul < RECEIPT_CLASSIFIER_THRESHOLD`: `job_store.reject(job_id, "NOT_A_RECEIPT", message)`.
   - Otherwise: `LPUSH receipt:queue` with the same job payload.
7. On any image-normalization or Jev-call failure (no valid answer): log a warning and
   `LPUSH receipt:queue` (fail open).
8. If republishing to `receipt:queue` fails: `job_store.fail(job_id, "INTERNAL", "Receipt processing failed")`.

Store failures after a valid answer do **not** trigger fail-open: a `record_classification`
failure is logged and routing continues based on the score; a `reject` failure is logged and the
job is left as-is (it is not sent to Gemini).

The worker loop catches per-job exceptions, logs them, and continues consuming (same resilience
as the existing Gemini worker). The classifier never creates a new ID. `receipt_jobs.id` is the
only link between the API, the classifier, and the Gemini worker.

### 4.3 Job states

```
pending ──► processing ──► completed
                      └──► failed
                      └──► rejected
```

- The classifier sets `processing` when it dequeues.
- A rejected job stays `rejected`; Gemini is never called.
- A receipt remains `processing` while it waits in `receipt:queue`; the Gemini worker completes or
  fails it as today.
- No automatic retry in this milestone.

### 4.4 `GET /api/v1/jobs/{job_id}` (one new terminal shape)

Unchanged for all existing states. Add:

```json
{
  "status": "rejected",
  "error": {
    "code": "NOT_A_RECEIPT",
    "message": "This image doesn't look like a receipt or invoice."
  }
}
```

- HTTP `200`.
- The score is never returned to the client.
- Unknown jobs still return `404 NOT_FOUND`.

---

## 5. Classifier Image Normalization

The API stores a JPEG with a maximum side of `MAX_IMAGE_DIMENSION` (default 1600). Jev requires
each side to be 256–1568 px and the total to be 78,400–2,458,624 px, and accepts only JPEG/PNG.

The classifier therefore builds its own copy from the job's JPEG:

1. Decode with Pillow, `image.load()`.
2. `ImageOps.exif_transpose(image)` (defensive; new API jobs are already upright).
3. Convert to `RGB`.
4. If `min(width, height) < 256` or `width * height < 78_400`: raise `ClassifierUnavailable`
   (fail open). Tiny images are never upscaled.
5. If either side exceeds 1568: `thumbnail((1568, 1568))`.
6. Encode as JPEG quality 85 and form a data URL:
   `data:image/jpeg;base64,<...>`.

The original API image is not modified; Gemini still receives the existing JPEG.

### 5.1 EXIF fix in the API

In `app/services/image.py`, apply `ImageOps.exif_transpose` after `image.load()` and before
`thumbnail()`. This ensures both Jev and Gemini receive upright pixels. A regression test uses a
JPEG with an orientation tag and asserts the processed dimensions/pixels are rotated.

---

## 6. Jev (OpenRouter Decisions) Integration

> **Superseded implementation note:** The LiteLLM migration spec replaces this direct
> HTTP integration with `litellm.systemone`. The model, question, threshold, response shape, and
> fail-open behavior below are unchanged; only the transport changes. See
> `docs/specs/02-ai-providers/2026-10-22-litellm-migration-design.md`.

### 6.1 Endpoint and request

- URL: `https://openrouter.ai/api/alpha/decisions`
- Headers: `Authorization: Bearer <OPENROUTER_JEV_API_KEY>`, `Content-Type: application/json`
- Timeout: `OPENROUTER_TIMEOUT_SECONDS` (default 5.0 seconds, total request)

```json
{
  "model": "typesafe/jev-1.14",
  "state": [
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/jpeg;base64,<...>"
      }
    }
  ],
  "questions": {
    "is_receipt": {
      "type": "noul",
      "instructions": "The image shows a receipt, bill, or invoice containing merchant and amount information.",
      "criteria": {
        "true": "A photo, scan, or screenshot of a merchant receipt, bill, or invoice with a total amount and/or line items.",
        "false": "Any other image, including a selfie, landscape, product photo, unrelated screenshot, bank statement, order confirmation, or other document without a merchant receipt or invoice."
      }
    }
  }
}
```

`typesafe/jev-1.14` is a Decisions model, not a chat model. It must use
`/api/alpha/decisions`; `/chat/completions` returns a `400`.

### 6.2 Response parsing

```json
{
  "model": "typesafe/jev-1.14",
  "answers": {
    "is_receipt": {
      "type": "noul",
      "noul": 0.0042
    }
  },
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "cost": 0.0
  }
}
```

- `noul` is the probability that the `is_receipt` proposition is true.
- Require HTTP `200`, `answers.is_receipt.type == "noul"`, and a finite `0 <= noul <= 1`.
  Anything else is `ClassifierUnavailable`.
- Persist the response `model` when present, otherwise the configured model string.

The service returns:

```python
@dataclass(frozen=True)
class ClassificationResult:
    noul: float
    model: str
```

### 6.3 Fail-open conditions

Log a warning and forward the job to `receipt:queue` when any of these occur:

- `OPENROUTER_JEV_API_KEY` is empty (the classifier logs a startup warning).
- Image is outside Jev's size window.
- HTTP 401/402/403/429/5xx.
- Connection error or the configured timeout (default 5 seconds).
- Malformed JSON, missing/mistyped answer, non-finite or out-of-range `noul`.
- Any other unexpected exception in the classifier path.

No retries. Classifier failures never reject a job and never leak provider details to the client.

### 6.4 Cost and current account status

Jev pricing is `$0.000000042` per input token with zero completion cost (roughly `$0.042` per
1M input tokens). The implementation was verified live once credits were available: a non-receipt
returned `noul=0.01` and a receipt returned `noul=0.99`. The fail-open path remains a permanent
policy.

---

## 7. Supabase Schema

### 7.1 Migration

`supabase/migrations/0002_add_classifier_columns.sql`:

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

No change to the `status` column is needed: it is plain `text`, so `rejected` is valid without a
migration. The existing `updated_at` trigger continues to fire on every update.

### 7.2 Recording rules

| Step | `status` | `result` | `error_code` / `error_message` | `classifier_score` | `classifier_model` |
|---|---|---|---|---|---|
| POST creates row | `pending` | null | null | null | null |
| Classifier dequeues | `processing` | null | null | null | null |
| Jev says receipt | `processing` | null | null | `noul` | model |
| Jev says not receipt | `rejected` | null | `NOT_A_RECEIPT` + message | `noul` | model |
| Gemini completes | `completed` | `ReceiptDraft` | null | unchanged | unchanged |
| Gemini fails | `failed` | null | existing error | unchanged | unchanged |
| Fail-open path | `processing` → Gemini result | per Gemini | per Gemini | null | null |

- The image is never stored in Supabase; it lives only in the Redis job payload, which is removed
  on `BRPOP`.
- One row per upload. `receipt_jobs.id` is the linking ID from API to classifier to Gemini.
- The Gemini worker never overwrites `classifier_score` or `classifier_model`.

---

## 8. Configuration

Add to `Settings` (`app/core/config.py`):

| Var | Default | Required | Notes |
|---|---|---|---|
| `OPENROUTER_JEV_API_KEY` | empty | no | Server-side only. Empty means fail-open for every job. |
| `OPENROUTER_JEV_MODEL` | `typesafe/jev-1.14` | no | Pin the version; do not use a moving alias. |
| `RECEIPT_CLASSIFIER_THRESHOLD` | `0.3` | no | Constrained to `0..1`. Reject when `noul < threshold`. |
| `OPENROUTER_TIMEOUT_SECONDS` | `5.0` | no | Must be positive. |

Existing variables are unchanged.

### 8.1 `.env.example`

- Add empty `OPENROUTER_JEV_API_KEY=` and the defaults above.
- Replace the real-looking `GEMINI_API_KEY`, `VISION_API_KEY`, and `SUPABASE_SERVICE_ROLE_KEY`
  values currently committed in `.env.example` with empty placeholders.
- The real keys that were committed must be rotated separately; this design does not rotate them.

---

## 9. Error Handling

- Add `ErrorCode.NOT_A_RECEIPT = "NOT_A_RECEIPT"`; it is a job error code, not an HTTP error.
- `GET /api/v1/jobs/{id}` renders it through the existing `{error:{code,message}}` shape.
- Add `JobStatus.REJECTED = "rejected"`.
- Add `JobStore.record_classification(job_id, score, model)` and
  `JobStore.reject(job_id, code, message)`; implement both in `SupabaseJobStore`.
- Raw OpenRouter responses, keys, and stack traces are never returned to clients. Provider
  failures are logged server-side with `job_id`, `noul`, `threshold`, `decision`, `latency_ms`,
  and `fallback_reason`; image bytes and keys are never logged.
- If `record_classification` fails, log and continue routing. If `reject` fails, log; the job may
  remain `processing` (same as the existing job-store failure behavior).
- If republishing to `receipt:queue` fails, call `job_store.fail(job_id, "INTERNAL",
  "Receipt processing failed")`.

---

## 10. Docker Compose

Add a third application container. `api`, `classifier`, and `worker` use the same image.

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

- `classifier` exposes no ports.
- Scale it independently if needed: `docker compose up --scale classifier=2`.
- If the `classifier` container is down, new jobs wait in `receipt:classify`; they are not lost,
  but fail-open does not happen until the container restarts.

---

## 11. Testing

### 11.1 Unit tests

- **`tests/test_services_jev.py`**
  - `FakeSystemone` records the LiteLLM `systemone` kwargs.
  - The call contains the `openrouter/typesafe/jev-1.14` model, image data URL in `state`, the
    `is_receipt` `noul` question, and both criteria.
  - Parses `answers.is_receipt.noul` and the returned model.
  - Provider errors, malformed responses, missing/wrong-typed `noul`, and out-of-range `noul` raise
    `ClassifierUnavailable`.
- **`tests/test_services_classifier.py`**
  - Images wider/taller than 1568 are downscaled; the encoded JPEG's dimensions fit the window.
  - Images under 256 px per side or under 78,400 total pixels raise `ClassifierUnavailable`
    without an HTTP call.
  - Only JPEG data URLs are sent.
- **`tests/test_workers_classifier.py`**
  - `noul = 0.1` → `record_classification` called, `reject` called, extract queue empty.
  - `noul = 0.9` → `record_classification` called, extract queue receives the same job.
  - Classifier exception → extract queue receives the job, no rejection.
  - `receipt:queue` enqueue failure → `fail` called with `INTERNAL`.
  - `mark_processing` is called in every successful dequeue path.
- **`tests/test_store.py`**
  - `record_classification` updates only `classifier_score` and `classifier_model`.
  - `reject` sets `status = 'rejected'` and the error fields.
- **`tests/test_api_receipt.py`**
  - POST pushes to `receipt:classify`, not `receipt:queue`.
  - GET returns the `rejected` shape for a rejected row.
  - Existing pending/processing/completed/failed/404/401/422/429 tests still pass.
- **`tests/test_services_image.py`**
  - EXIF orientation is applied before downscaling and JPEG encoding.
- **`tests/test_queue.py`**
  - `RedisQueue` round-trips with a custom queue key.
- **`tests/conftest.py`**
  - Extend `FakeJobStore` with `record_classification` and `reject`; keep existing behavior for
    all current tests.

Provider clients use injected fake callables. No live network calls in unit tests.

### 11.2 Manual / integration

1. Apply the migration and start Compose: `docker compose -f docker/compose.yaml up --build`.
2. Confirm `api`, `classifier`, `worker`, and `redis` are running.
3. Verified with the live OpenRouter key:
   - POST a non-receipt image → `rejected` with `NOT_A_RECEIPT`; `classifier_score=0.01`.
   - POST a receipt image → `completed` with a `ReceiptDraft`; `classifier_score=0.99`.
   - Confirm `classifier_score` / `classifier_model` on both rows.
4. Fail-open remains covered by unit tests; it is the permanent policy for Jev errors.
5. Run `uv run pytest` and `uv run ruff check .`.

---

## 12. Rollout

1. Apply `0002_add_classifier_columns.sql` to Supabase.
2. Add the new variables to `.env`; rotate the secrets currently present in `.env.example`.
3. Rebuild and restart Compose; the new `classifier` service starts alongside `api`, `worker`, and
   `redis`.
4. Update `README.md` to document the `classifier` service, the new env vars, and the `rejected`
   status.
5. Existing jobs already in `receipt:queue` still drain through the Gemini worker without
   classification.
6. New uploads flow through `receipt:classify`.
7. Jev was verified live; fail-open remains the policy for provider failures.

---

## 13. Acceptance Criteria

1. `POST /api/v1/analyze-receipt` still returns `202 {jobId, status:"pending"}` and pushes to
   `receipt:classify`.
2. A job with a valid Jev answer `noul < 0.3` ends as `rejected`, exposes
   `{"error":{"code":"NOT_A_RECEIPT","message":...}}`, persists `classifier_score` and
   `classifier_model`, and never calls Gemini.
3. A job with `noul >= 0.3` reaches the Gemini worker, ends `completed` or `failed`, and keeps the
   persisted classifier columns.
4. Any Jev failure (402, timeout, 5xx, malformed, undersized image, missing key) forwards the job
   to Gemini and leaves `classifier_score`/`classifier_model` null.
5. Compose defines `api`, `classifier`, `worker`, and `redis`; the classifier runs
   `python -m app.workers.classifier`.
6. `uv run pytest` and `uv run ruff check .` pass.
7. No image bytes, OpenRouter keys, or raw provider errors appear in client responses or logs.

---

## 14. Risks and Open Items

- **OpenRouter credits:** resolved; live verification returned `noul=0.01` for a non-receipt and
  `0.99` for a receipt.
- **Early-feature API:** OpenRouter marks Jev image input as an early feature whose request format,
  answers, and limits can change between releases. The model slug is pinned; upgrades require
  re-checking the contract and threshold.
- **No measured p95 latency:** the 5-second timeout is a budget, not a measured p95. Approximate
  live calls completed quickly; measure under production load and adjust only with evidence.
- **Classifier outage:** fail-open is implemented inside the classifier worker. If the container is
  down, new jobs wait in `receipt:classify` rather than skipping classification.
- **Threshold:** `0.3` is a conservative starting point; use persisted scores plus logs to tune it.

---

## 15. Out of Scope

- Automatic retries, backoff, or a dead-letter queue.
- Exposing `classifier_score` or model details to clients.
- Metrics dashboards or alerting beyond logs.
- Persisting classifier error details in Supabase.
- Frontend changes (the frontend must add handling for the `rejected` status separately).
- Jev model fallback, routing aliases, or multi-model comparison.
- Storing images in Supabase or any durable blob store.

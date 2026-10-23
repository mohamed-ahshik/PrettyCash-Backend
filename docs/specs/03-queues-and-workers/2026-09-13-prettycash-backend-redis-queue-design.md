---
title: "Redis Queue and Supabase Job Store"
type: spec
status: implemented
date: 2026-09-13
section: queues-and-workers
tags:
  - prettycash
  - spec
  - queue
  - workers
  - redis
  - supabase
---

# PrettyCash Backend — Dockerise with Redis Queue & Supabase Job Store (Design)

**Date:** 2026-09-13
**Status:** Implemented
**Implementation status:** Implemented

---

## Related

- Architecture: [[ARCHITECTURE#7. Request and Data Flow|Request and Data Flow]], [[ARCHITECTURE#9. Data Storage|Data Storage]]
- Section: [[QUEUES-AND-WORKERS]]
- Plan: [[2026-09-13-prettycash-backend-redis-queue|Redis Queue implementation]]
- Extends: [[2026-10-22-receipt-classification-design|Receipt Pre-Classification with Jev]]

## Architecture Alignment

- **Layers:** API enqueue target, queue, Supabase store, worker, Docker Compose.
- **New boundaries:** `receipt:queue`, the Gemini worker, the `receipt_jobs` table, and Redis
  rate limiting.
- **Current → target:** implemented. The classifier design adds `receipt:classify` and a second
  worker without changing this queue's contract.

---

## 1. Overview & Objective

Move the receipt-analysis flow from synchronous to asynchronous, Dockerise the backend for multi-instance deployment, and introduce Redis as the job queue and rate-limit backend with Supabase (Postgres) as the durable job-status/result store.

Today `POST /api/v1/analyze-receipt` performs the Gemini call inline and returns the result synchronously. After this change the endpoint enqueues a job and returns a `jobId`; a worker drains the queue, calls Gemini, and writes the result to Supabase; the app polls `GET /api/v1/jobs/{jobId}` until the job is `completed` or `failed`.

This is a follow-up to `2026-09-13-prettycash-backend-receipt-analysis-design.md`, which deliberately left the `RedisQueue` as a stub and the endpoint synchronous ("Redis later").

**Decisions (locked during brainstorming):**
- Async job + polling, **replacing** the synchronous endpoint (frontend §5 will be updated separately).
- **Redis** = queue broker only (`redis-py`, list-based).
- **Supabase** = job status/result store (durable, queryable), accessed via the `supabase-py` REST client with a service-role key.
- Rate limiting moves from in-memory to Redis (multi-instance safe).
- Redis is made durable in Compose via a named volume + AOF.

---

## 2. Architecture

```
Client (app)
   │  POST /api/v1/analyze-receipt  (202 → jobId)
   ▼
 ┌───────────┐   LPUSH     ┌────────┐   BRPOP    ┌──────────┐
 │    api    │ ──────────► │ Redis  │ ◄───────── │  worker  │
 │ (FastAPI) │             │ (queue)│            │ (drains) │
 └─────┬─────┘             └────────┘            └────┬─────┘
       │ INSERT pending                                 │ Gemini analyze
       │                                                ▼
       │                                        ┌──────────────┐
       └─────────► UPDATE completed/failed ────►│   Supabase   │
                                                │ (job status) │
                                                └──────────────┘
Client polls GET /api/v1/jobs/{id} → reads Supabase until completed/failed
```

- **Redis** — work queue only. `redis-py` with a list (`receipt:queue`); enqueue via `LPUSH`, dequeue via `BRPOP`. Persisted with a named volume (`redis-data:/data`) and AOF (`--appendonly yes`).
- **Supabase (Postgres)** — durable job state and result, accessed via `supabase-py` (service-role key). The app polls this for status.
- **Rate limiting** — Redis `INCR` + `EXPIRE` (60s window) counter keyed by API key, replacing the current in-memory `RateLimiter` (which cannot be shared across API replicas).
- **Worker** — BRPOPs jobs, sets `processing`, calls Gemini, sets `completed`+`result` or `failed`+`error`.

The synchronous path is removed: `app.state.queue` is no longer a `SyncQueue`, and the endpoint no longer calls `analyzer.analyze` inline.

---

## 3. Endpoints

### 3.1 `POST /api/v1/analyze-receipt`

Headers: `Content-Type: application/json`, `Authorization: Bearer {VISION_API_KEY}`.

Request body (unchanged):
```json
{ "image": { "base64": "<base64, no data-uri prefix>", "mimeType": "image/jpeg" } }
```

Steps:
1. Auth → `401 UNAUTHORIZED`
2. Redis rate limit → `429 RATE_LIMITED`
3. Validate body → `422 UNPROCESSABLE`
4. Decode/validate/downscale image (threadpool) → `400 INVALID_IMAGE`
5. Insert Supabase row `status=pending` → get `job_id`
6. `LPUSH receipt:queue` a job payload `{ job_id, image_base64, mime_type }` (image re-encoded to JPEG)
7. Return `202 Accepted`:
```json
{ "jobId": "<uuid>", "status": "pending" }
```

### 3.2 `GET /api/v1/jobs/{job_id}`

Headers: `Authorization: Bearer {VISION_API_KEY}`.

Returns (from Supabase):
- `200 { "status": "pending" }`
- `200 { "status": "processing" }`
- `200 { "status": "completed", "result": { "merchant", "amount", "date", "time", "note", "items" } }`
- `200 { "status": "failed", "error": { "code", "message" } }`
- `404` (error shape) for an unknown job id

### 3.3 `GET /api/v1/health`

Unchanged: `{ "status": "ok" }`.

---

## 4. Job lifecycle

`pending` → `processing` → `completed` | `failed`

- API creates the row `pending` and enqueues.
- Worker, on dequeue: set `processing` (and `updated_at`).
- On Gemini success: set `completed`, `result` = normalized `ReceiptDraft` JSON.
- On Gemini/provider failure: set `failed`, `error_code` / `error_message` (generic — never provider details or keys).
- No automatic retry in this milestone. Failed jobs remain `failed` for the client to surface; retry/backoff is a later enhancement.

---

## 5. Supabase schema

Table `receipt_jobs` (created via `supabase/migrations/0001_create_receipt_jobs.sql`):

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
```

- `status` values: `pending`, `processing`, `completed`, `failed`.
  The classifier design extends this with `rejected`; see
  [[2026-10-22-receipt-classification-design|Receipt Pre-Classification with Jev]].
- `result` stores the normalized §5.4 `ReceiptDraft` shape; null until completed.
- RLS not required for backend access: the backend uses the service-role key (bypasses RLS). Client apps never receive this key.

---

## 6. Redis keys

| Key | Type | Purpose |
|-----|------|---------|
| `receipt:queue` | list | job payloads `{ "job_id", "image_base64", "mime_type" }` |
| `rate_limit:{api_key}` | string (INCR) | 60s counter for rate limiting |

---

## 7. Config

New env vars (added to `.env.example`):

| Var | Purpose | Required |
|-----|---------|----------|
| `REDIS_URL` | Redis connection, e.g. `redis://redis:6379/0` | ✅ |
| `SUPABASE_URL` | Supabase project URL | ✅ |
| `SUPABASE_SERVICE_ROLE_KEY` | server-side service-role key | ✅ |

Existing vars remain: `GEMINI_API_KEY`, `GEMINI_MODEL`, `VISION_API_KEY`, `RATE_LIMIT_PER_MINUTE`, `MAX_IMAGE_BYTES`, `MAX_IMAGE_DIMENSION`, `LOG_LEVEL`.

---

## 8. Docker Compose

`docker/compose.yaml` services:

- **`api`** — `uvicorn app.main:create_app --factory` (port 8000).
- **`worker`** — `python -m app.workers.worker` (same image).
- **`redis`** — `redis:7-alpine` with `command: ["redis-server", "--appendonly", "yes"]` and volume `redis-data:/data`.

`api` and `worker` `depends_on: redis`. Supabase is external SaaS, accessed via `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` (no container).

Named volume: `redis-data`.

---

## 9. Error handling

- All non-2xx responses keep the `{ "error": { "code", "message" } }` shape.
- New/notable codes: `404` for unknown job (message e.g. "Job not found"); existing `UNAUTHORIZED`, `INVALID_IMAGE`, `UNPROCESSABLE`, `RATE_LIMITED`, `INTERNAL` remain.
- Worker failures never leak provider errors/keys — store a generic `error_message`.

---

## 10. Testing

`pytest` + `respx` (stub Gemini) + test doubles for Redis and Supabase:
- API: enqueue returns `202 {jobId}`; auth `401`; rate limit `429`; invalid image `400`; malformed body `422`.
- Polling: `GET /jobs/{id}` returns `pending`/`processing`/`completed`/`failed` correctly; `404` for unknown.
- Worker: on dequeue marks `processing`, writes `completed`+result on success, `failed`+error on Gemini failure.
- Rate limiter (Redis-backed) unit behavior.
- Redis/Supabase faked in unit tests; full integration exercised via `docker compose up` manually (real Redis + Supabase + worker).

---

## 11. Dependencies

- Add `redis` (redis-py) and `supabase` (supabase-py) to `pyproject.toml`.
- Remove/rework the `SyncQueue` usage (keep `TaskQueue` protocol); implement `RedisQueue` for real; keep the worker CLI.

---

## 12. Out of scope (later)

- Automatic retry/backoff and dead-letter queue.
- Supabase RLS for multi-tenant client access.
- Job retention/cleanup (completed/failed rows kept indefinitely for now).
- Frontend update to the async polling contract (separate repo/plan).

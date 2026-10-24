# PrettyCash Backend Architecture

**Status:** Living document
**Last updated:** 2026-10-22
**Audience:** Contributors and AI agents
**Mandatory companion:** [AGENT.md](../../AGENT.md) (repository root)

> This document describes the intended structure of the backend, what is currently implemented,
> and what has been approved but not yet built. Read this before creating, writing, or implementing
> any spec. Update it after every approved spec and after every implementation.

---

## 1. Purpose

PrettyCash's backend accepts a receipt image, runs AI extraction asynchronously, and exposes the
result through a polling API. The backend is intentionally small and layered:

- HTTP concerns stay in `app/api/`.
- Business and provider logic stays in `app/services/`.
- Queue transport stays in `app/queue/`.
- Persistence stays in `app/store/`.
- Orchestration stays in `app/workers/`.
- Cross-cutting config/errors/logging stay in `app/core/`.

The architecture exists to keep those responsibilities separate as receipt classification, model
fallbacks, and additional workers are added.

---

## 2. System Context

```
Mobile client
   │  Bearer VISION_API_KEY
   ▼
FastAPI API ──────────────► Supabase (receipt_jobs)
   │                              ▲
   │ LPUSH                        │ status/result updates
   ▼                              │
Redis queue ◄────────────── Worker ──────► Gemini (receipt extraction)
                                   │
                                   └─────► OpenRouter Jev (classification, approved)
```

External systems:

| System | Role | Credential |
|---|---|---|
| Supabase | Durable job status/result store | `SUPABASE_SERVICE_ROLE_KEY` |
| Redis | Work queues and rate limiting | `REDIS_URL` |
| Google AI Studio / Gemini | Receipt extraction | `GEMINI_API_KEY` |
| OpenRouter / Jev | Receipt/non-receipt classification (approved) | `OPENROUTER_JEV_API_KEY` |
| LiteLLM | Provider abstraction for Gemini and Jev (approved) | Uses the keys above |

The client never receives the Supabase service-role key or any provider key.

---

## 3. Current Runtime (Implemented)

```
Client
  │ POST /api/v1/analyze-receipt
  ▼
┌──────┐  create pending row   ┌──────────┐
│ API  │ ────────────────────► │ Supabase │
│      │  LPUSH receipt:classify└──────────┘
└──┬───┘
   │ 202 {jobId, status:"pending"}
   ▼
 receipt:classify
   │ BRPOP
   ▼
┌──────────────┐  LiteLLM systemone   ┌─────────────────────┐
│  classifier  │ ───────────────────► │ OpenRouter Jev 1.14 │
│   worker     │                      └─────────────────────┘
│              │  noul < threshold
│              │ ───────────────────► Supabase status=rejected
│              │  receipt / fail-open
│              │ ───────────────────► receipt:queue
└──────────────┘
   │
   ▼
 receipt:queue
   │ BRPOP
   ▼
┌──────────────┐  LiteLLM completion  ┌──────────────┐
│ Gemini worker│ ────────────────────► │ Google Gemini│
│              │                       └──────────────┘
│              │  complete/fail
│              │ ────────────────────► Supabase
└──────────────┘
```

Implemented services:

| Compose service | Command | Responsibility |
|---|---|---|
| `api` | `uvicorn app.main:create_app --factory` | HTTP API, auth, rate limit, image validation, enqueue |
| `classifier` | `python -m app.workers.classifier` | Dequeue, call Jev via LiteLLM, reject or forward |
| `worker` | `python -m app.workers.worker` | Dequeue, call Gemini via LiteLLM, persist result |
| `redis` | `redis-server --appendonly yes` | Queue and rate-limit storage |

Current external AI calls:

- Gemini: `litellm.completion` from `app/services/gemini.py`.
- Jev: `litellm.systemone` from `app/services/jev.py`, with the image embedded in `state`.

Current queues:

- `receipt:classify` — jobs awaiting Jev classification.
- `receipt:queue` — jobs awaiting Gemini extraction.

Current API statuses:

- `pending`, `processing`, `completed`, `failed`, `rejected`.

The backend also accepts optional scan categories and may return `categoryId` /
`categoryConfidence`; the frontend integration is implemented in the sibling repo.

---

## 4. Approved Target

### Implemented

| Change | Spec | Status |
|---|---|---|
| Receipt pre-classification with Jev | `docs/specs/02-ai-providers/2026-10-22-receipt-classification-design.md` | Implemented |
| LiteLLM provider migration | `docs/specs/02-ai-providers/2026-10-22-litellm-migration-design.md` | Implemented |
| Gemini receipt auto-categorization | `docs/specs/02-ai-providers/2026-10-24-auto-categorization-design.md` | Implemented |

The auto-categorization frontend integration is implemented in the sibling repo:
`PrettyCash/docs/superpowers/specs/2026-10-24-auto-categorization-design.md`.
The backend remains backward compatible with older clients.

Fallbacks are still deferred; see Section 10.4.

---

## 5. Layer Responsibilities and Dependency Rules

| Layer | Directory | Owns | Must not own |
|---|---|---|---|
| HTTP | `app/api/` | Routes, auth dependency, request/response mapping, HTTP status codes | Provider SDK calls, queue internals, database queries |
| Core | `app/core/` | Settings, error types/codes, logging setup | Business rules, provider calls, HTTP routes |
| Services | `app/services/` | Image processing, prompt/schema ownership, provider calls, receipt normalization, rate-limit logic with injected clients | FastAPI, creating Redis/Supabase clients, queue orchestration |
| Queue | `app/queue/` | Queue protocol and Redis/Sync implementations | Business rules, provider calls, persistence |
| Store | `app/store/` | JobStore protocol and Supabase implementation | Business rules, provider calls, HTTP |
| Workers | `app/workers/` | Dequeue loop, status transitions, service orchestration | HTTP handlers, provider request construction |

Dependency direction:

```
api ──────► services, queue, store, core
workers ──► services, queue, store, core
services ─► core
queue ────► core
store ────► core
core ─────► standard library / third-party only
```

Rules:

1. Never import `app/api/` or `app/workers/` from services, queue, or store.
2. A service receives collaborators through its constructor. It does not read environment variables,
   open Redis connections, or create Supabase clients.
3. The API obtains queue/store/limiter through `request.app.state`; it never constructs provider
   clients.
4. Workers construct provider clients and stores in `main()`, then pass them into pure functions.
5. Provider SDKs (LiteLLM included) are imported only inside `app/services/` provider clients.
6. New shared request/response models belong in a dedicated schema module, not in a provider client.
7. Tests mirror layers: API tests use `httpx.ASGITransport`, service tests use fakes, worker tests use
   fake queues/stores/services.

### 5.1 Known separation debt

- `app/api/v1/schemas.py` imports `ReceiptDraft` from `app/services/receipt.py`, which also imports
  the provider client. Lazy provider imports avoid loading LiteLLM in the API, but a future
  refactor should move `ReceiptDraft` and `LineItem` into a shared schema module.

---

## 6. Directory Map

```
app/
├── main.py                         # App factory, state wiring, exception handlers
├── api/
│   ├── deps.py                     # Bearer auth + Redis rate limit
│   └── v1/
│       ├── router.py               # /api/v1 prefix
│       ├── receipt.py              # health, analyze-receipt, jobs
│       └── schemas.py              # HTTP request/response models
├── core/
│   ├── config.py                   # pydantic-settings
│   ├── errors.py                   # ErrorCode + AppError hierarchy
│   └── logging.py                  # logging configuration
├── queue/
│   ├── base.py                     # Job + TaskQueue protocol
│   ├── redis.py                    # RedisQueue (classify/extract)
│   └── sync.py                     # In-process test/local queue
├── services/
│   ├── gemini.py                   # Gemini provider client (LiteLLM completion)
│   ├── jev.py                      # Jev provider client (LiteLLM systemone)
│   ├── classifier.py               # Image normalization + Jev classification
│   ├── image.py                    # base64 decode, validation, EXIF, downscale
│   ├── ratelimit.py                # Redis rate-limit logic
│   └── receipt.py                  # ReceiptDraft + ReceiptAnalyzer
├── store/
│   ├── base.py                     # JobStatus + JobStore protocol
│   └── supabase.py                 # SupabaseJobStore
└── workers/
    ├── worker.py                   # Gemini extraction worker
    └── classifier.py               # Jev classifier worker
docker/
├── Dockerfile
└── compose.yaml
supabase/migrations/
├── 0001_create_receipt_jobs.sql
├── 0002_add_classifier_columns.sql # applied
└── 0003_add_receipt_job_request_id.sql # applied as remote 20261024000001
tests/
AGENT.md                             # mandatory agent workflow (repo root)
docs/
├── prettycash-backend-architecture/
│   └── ARCHITECTURE.md             # this file
├── specs/
│   ├── SPECS.md                    # specs map of content
│   ├── 01-api/
│   │   ├── API.md                  # API section MOC
│   │   └── 2026-09-13-prettycash-backend-receipt-analysis-design.md
│   ├── 02-ai-providers/
│   │   ├── AI-PROVIDERS.md         # AI section MOC
│   │   ├── 2026-10-22-receipt-classification-design.md
│   │   ├── 2026-10-22-litellm-migration-design.md
│   │   └── 2026-10-24-auto-categorization-design.md
│   └── 03-queues-and-workers/
│       ├── QUEUES-AND-WORKERS.md   # queue section MOC
│       └── 2026-09-13-prettycash-backend-redis-queue-design.md
└── plans/
    ├── PLANS.md                    # plans map of content
    ├── 01-api/
    │   ├── API-PLANS.md
    │   └── 2026-09-13-prettycash-backend-receipt-analysis.md
    ├── 02-ai-providers/
    │   ├── AI-PROVIDERS-PLANS.md
    │   ├── 2026-10-22-receipt-classification.md
    │   └── 2026-10-22-litellm-migration.md
    └── 03-queues-and-workers/
        ├── QUEUES-AND-WORKERS-PLANS.md
        └── 2026-09-13-prettycash-backend-redis-queue.md
```

---

## 7. Request and Data Flow

### 7.1 `POST /api/v1/analyze-receipt`

1. Authenticate `Authorization: Bearer <VISION_API_KEY>`.
2. Apply Redis rate limit (`RATE_LIMIT_PER_MINUTE`).
3. Validate `{ image, autoCategorize?, categories? }` (categories max 50, description max 200).
4. Decode, validate, apply EXIF orientation, downscale, re-encode JPEG.
5. Read the optional `Idempotency-Key` header and create a `receipt_jobs` row with
   `status = pending` and `request_id = key`; an existing key returns the existing row.
6. Enqueue `{job_id, image_base64, mime_type, auto_categorize, categories}` only for a newly created
   row.
7. Return `202 {"jobId": "...", "status": "<current status>"}`; duplicate keys return the same
   `jobId` and do not enqueue again.

Queue: `receipt:classify`.

### 7.2 Worker flow

Classifier worker:

1. `BRPOP receipt:classify`.
2. `mark_processing(job_id)`.
3. Normalize a Jev-safe image copy.
4. Call Jev through `litellm.systemone`.
5. Persist `classifier_score` / `classifier_model`.
6. `noul < threshold` → `reject`; otherwise republish to `receipt:queue`.
7. Any Jev/image failure → republish to `receipt:queue` (fail open).

Gemini worker:

1. `BRPOP receipt:queue`.
2. `mark_processing(job_id)`.
3. Call Gemini through `litellm.completion` with the image, strict JSON schema, and category list
   when `auto_categorize` is true.
4. Validate/normalize into `ReceiptDraft`, mapping the category key to `categoryId` and applying
   `RECEIPT_CATEGORY_CONFIDENCE_THRESHOLD`.
5. `complete(job_id, draft)` or `fail(job_id, code, message)`.

### 7.3 `GET /api/v1/jobs/{job_id}`

Returns the current Supabase row mapped to:

```json
{"status": "pending"}
{"status": "processing"}
{"status": "completed", "result": {...}}
{"status": "failed", "error": {"code": "...", "message": "..."}}
{"status": "rejected", "error": {"code": "NOT_A_RECEIPT", "message": "..."}}
```

`rejected` is a current terminal state.

---

## 8. API Contract

| Endpoint | Auth | Behavior |
|---|---|---|
| `GET /api/v1/health` | No | `{"status":"ok"}` |
| `POST /api/v1/analyze-receipt` | Bearer `VISION_API_KEY` | Validate image, create or reuse job, enqueue new jobs, `202` |
| `GET /api/v1/jobs/{job_id}` | Bearer `VISION_API_KEY` | Return job status/result/error; `404` if unknown |

`POST /api/v1/analyze-receipt` also accepts optional `autoCategorize` and `categories`:

```json
{
  "image": { "base64": "...", "mimeType": "image/jpeg" },
  "autoCategorize": true,
  "categories": [
    { "id": "uuid-food", "name": "Food", "description": "Groceries & dining" }
  ]
}
```

When Gemini makes a confident category decision, `result` may include `categoryId` and
`categoryConfidence`. The frontend owns the profile toggle, category descriptions, the
Uncategorized fallback, and the category UI.

`POST /api/v1/analyze-receipt` accepts an optional `Idempotency-Key` header (1–128 characters). A
repeated key returns the existing `jobId` and its current status, and does not enqueue the job
again. Requests without the header keep the previous behavior. A header outside the length bounds
returns `422 UNPROCESSABLE`.

All non-2xx responses use:

```json
{"error": {"code": "UNAUTHORIZED", "message": "..."}}
```

Codes: `UNAUTHORIZED`, `INVALID_IMAGE`, `UNPROCESSABLE`, `RATE_LIMITED`, `INTERNAL`, `NOT_FOUND`,
and `NOT_A_RECEIPT` as a job error code.

The API contract must not change without a spec and a frontend coordination note.

---

## 9. Data Storage

### 9.1 Supabase: `receipt_jobs`

Current columns:

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary key, returned as `jobId` |
| `status` | text | `pending`, `processing`, `completed`, `failed`, `rejected` |
| `result` | jsonb | `ReceiptDraft` when completed; may include `categoryId` / `categoryConfidence` |
| `error_code` | text | Failure code |
| `error_message` | text | Generic failure message |
| `created_at` | timestamptz | Default now |
| `updated_at` | timestamptz | Trigger-maintained |
| `request_id` | text | Client `Idempotency-Key`; unique when present (migration `0003`) |

Classifier columns (applied):

| Column | Type | Notes |
|---|---|---|
| `classifier_score` | double precision | Jev `noul`, null on fail-open |
| `classifier_model` | text | Jev model/version |

Status `rejected` is in use.

Images are never stored in Supabase. The image exists only in the Redis job payload.

### 9.2 Redis keys

| Key | Type | Status | Purpose |
|---|---|---|---|
| `receipt:queue` | list | Current | Gemini extraction jobs |
| `receipt:classify` | list | Current | Jev classification jobs |
| `rate_limit:{api_key}` | string (INCR) | Current | 60-second rate-limit counter |

Redis is configured with AOF and a named volume in Compose. It is a queue, not durable job history.

### 9.3 Migrations

Migrations live in `supabase/migrations/` and are applied manually to the Supabase project. Compose
does not run migrations. Every schema change needs a new numbered migration and an architecture
update.

The remote migration history currently contains timestamped versions that are not present in the
local migration directory. `0002_add_classifier_columns.sql` was applied directly with
`supabase db query` after the columns were missing; reconcile the history with `supabase db pull`
or `supabase migration repair` before relying on `supabase db push`.

---

## 10. AI Provider Integrations

### 10.1 Gemini extraction

- Transport: `litellm.completion` with model `gemini/<GEMINI_MODEL>`.
- Model: `gemini-3.1-flash-lite` by default.
- Key: `GEMINI_API_KEY`.
- Output: strict JSON matching `ReceiptDraft`, using standard JSON Schema.
- Errors: mapped to `INTERNAL`; provider details never reach the client.
- Owner: `app/services/gemini.py`.
- Prompt/schema owner: `app/services/gemini.py`.

### 10.2 Jev classification

- Transport: `litellm.systemone` with model `openrouter/<OPENROUTER_JEV_MODEL>`.
- Model: `typesafe/jev-1.14` by default.
- Key: `OPENROUTER_JEV_API_KEY`, passed explicitly.
- Image: embedded in `state` as an OpenRouter `image_url` data URL. Do not use LiteLLM's separate
  `images` parameter; it is marked unsupported for OpenRouter. This path was verified live.
- Answer: `response.answers["is_receipt"].noul`.
- Threshold: `RECEIPT_CLASSIFIER_THRESHOLD`, default `0.3`.
- Timeout: `OPENROUTER_TIMEOUT_SECONDS`, default `5.0`.
- Failure: `ClassifierUnavailable` → fail open to Gemini.
- Owner: `app/services/jev.py`.
- Worker: `app/workers/classifier.py`.

### 10.3 Receipt auto-categorization (implemented)

- The frontend will send its expense categories (`id`, `name`, `description` from `notes`) with the
  scan, plus an `autoCategorize` flag.
- The backend uses the same Gemini extraction call to return a short category key and confidence.
- The backend maps the key to the real category ID and accepts it only at or above
  `RECEIPT_CATEGORY_CONFIDENCE_THRESHOLD` (default `0.7`).
- Completed results may include `categoryId` and `categoryConfidence`; no backend DB migration.
- Backend verification: a Food receipt returned `categoryId=cat-food` / confidence `1.0`; a
  bookstore receipt with no matching category returned no `categoryId`.
- The frontend owns the Uncategorized fallback, profile toggle, and category edit UI.
- Spec: `docs/specs/02-ai-providers/2026-10-24-auto-categorization-design.md`.

### 10.4 Fallbacks

Not configured. LiteLLM's `completion` supports fallbacks, but `systemone` does not. Future Gemini
fallbacks can use `completion(fallbacks=[...])`; future Jev fallbacks need a Router or a custom
wrapper. Any fallback design must be a separate spec.

---

## 11. Configuration

| Var | Current default | Required | Owner |
|---|---|---|---|
| `GEMINI_API_KEY` | none | Yes | Gemini |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | No | Gemini |
| `VISION_API_KEY` | none | Yes | Inbound auth |
| `REDIS_URL` | none | Yes | Queue/rate limit |
| `SUPABASE_URL` | none | Yes | Job store |
| `SUPABASE_SERVICE_ROLE_KEY` | none | Yes | Job store |
| `RATE_LIMIT_PER_MINUTE` | `30` | No | Rate limit |
| `MAX_IMAGE_BYTES` | `10485760` | No | Image validation |
| `MAX_IMAGE_DIMENSION` | `1600` | No | Image downscale |
| `LOG_LEVEL` | `INFO` | No | Logging |
| `OPENROUTER_JEV_API_KEY` | empty | No (fail-open) | Jev |
| `OPENROUTER_JEV_MODEL` | `typesafe/jev-1.14` | No | Jev |
| `RECEIPT_CLASSIFIER_THRESHOLD` | `0.3` | No | Jev decision |
| `OPENROUTER_TIMEOUT_SECONDS` | `5.0` | No | Jev timeout |
| `RECEIPT_CATEGORY_CONFIDENCE_THRESHOLD` | `0.7` | No | Gemini category decision |

> `OPENROUTER_JEV_API_KEY`, `OPENROUTER_JEV_MODEL`, `RECEIPT_CLASSIFIER_THRESHOLD`,
> `OPENROUTER_TIMEOUT_SECONDS`, and `RECEIPT_CATEGORY_CONFIDENCE_THRESHOLD` are implemented in
> `app/core/config.py`. The LiteLLM migration adds no environment variables.

Rules:

- Configuration is loaded only through `app/core/config.py`.
- No `os.getenv()` calls outside config.
- Keys are server-side only and must never appear in logs, errors, or client responses.
- `.env` is gitignored. `.env.example` must contain placeholders only.

---

## 12. Deployment

- Docker Compose (`docker/compose.yaml`) runs `api`, `classifier`, `worker`, and `redis`.
- The `classifier` service uses the same image and consumes `receipt:classify`.
- Supabase is external.
- The API health endpoint is `GET /api/v1/health`.
- The Docker image installs runtime dependencies with `uv sync --frozen --no-dev`.
- Adding a runtime dependency requires rebuilding the image and refreshing `uv.lock`.
- No secrets are baked into the image.

---

## 13. Testing

- Framework: pytest, `httpx.AsyncClient` + `ASGITransport` for API tests, `fakeredis` for Redis.
- Provider clients use injected fake callables (`completion_fn` / `systemone_fn`).
- Fakes live in `tests/conftest.py` or the relevant test module.
- Unit tests never call external providers.
- Commands: `uv run pytest` and `uv run ruff check .`.
- Live smoke tests are manual and require real credentials. Both providers were verified live:
  Gemini returned a parsed receipt, and Jev returned `noul=0.01` for a non-receipt and `0.99` for
  a receipt.
- Auto-categorization was verified live: a Food receipt returned `categoryId=cat-food` /
  confidence `1.0`; a bookstore receipt with no matching category returned no `categoryId`; an API
  scan with `autoCategorize: false` returned no category fields.

Every behavior change needs a test at its layer. Worker tests use fake services; API tests do not
call real Redis/Supabase/providers.

---

## 14. Security

- Inbound auth: constant-time Bearer comparison against `VISION_API_KEY`.
- Rate limiting: Redis counter per API key.
- Image limits: max bytes and max dimension; unsupported/failed decode → `INVALID_IMAGE`.
- Provider errors are sanitized; raw provider bodies and keys never reach clients.
- Supabase uses the service-role key only server-side; RLS does not protect backend access.
- `.env` is gitignored.
- `.env.example` now contains placeholders only. Any keys previously committed to git history must
  still be rotated; history is not erased by replacing the file.

---

## 15. Change Process (Mandatory)

Before creating, writing, or implementing any spec:

1. Read `AGENT.md` first, then this file.
2. Read the relevant existing spec/plan and check the current-vs-target state.
3. Add an **Architecture alignment** section to the spec that lists:
   - layers/components touched,
   - new dependencies or boundaries,
   - data/queue/schema changes,
   - current behavior vs target behavior.
4. If the spec introduces a new component, dependency, queue, table, provider, or layer boundary,
   update this file **before** implementation.
5. Write the implementation plan in `docs/plans/<NN-section>/` and link it from the section MOC.
6. Implement with tests.
7. After implementation, update this file:
   - move the change from "Approved Target" to "Current Runtime",
   - update diagrams, API contract, data storage, config, deployment, and testing,
   - update the spec/plan index,
   - append an architecture change-log entry,
   - update `README.md` if user-facing behavior changed.
8. Run `uv run pytest` and `uv run ruff check .`.

A spec must never silently change the architecture. If the architecture must change, this document
changes with the spec, not after the fact.

---

## 16. Known Debt and Deviations

| Item | Impact | Resolution |
|---|---|---|
| API schema imports `ReceiptDraft` from a provider-coupled service | API loads service module; future tight coupling | Move shared schemas to a dedicated module |
| Remote migration history does not match local versions | `supabase db push` refuses until reconciled | `supabase db pull` or `supabase migration repair` |
| No retries/dead-letter queue | Provider failures end as `failed` | Future reliability spec |
| No metrics/dashboards | Only logs | Future observability spec |
| One Gemini worker | Serial extraction throughput | Scale or add workers when needed |
| Migrations are manual | Deployment can drift from code | Add a migration step/runbook |
| Keys may remain in git history | Credential exposure | Rotate keys independently of the file cleanup |
| Frontend auto-categorization on-device verification is pending | Automated frontend/backend coverage passes | Run the sibling spec §11.2 checklist |

---

## 17. Spec and Plan Index

### Section maps (Obsidian)

Every spec/plan/MOC uses YAML frontmatter and `[[wiki-links]]`. Open the repository root as an
Obsidian vault; these notes are the graph entry points.

- [[SPECS]] / [[PLANS]] — top-level maps of content.
- [[API]] / [[API-PLANS]] — API contract and initial receipt analysis.
- [[AI-PROVIDERS]] / [[AI-PROVIDERS-PLANS]] — Gemini, Jev, and LiteLLM.
- [[QUEUES-AND-WORKERS]] / [[QUEUES-AND-WORKERS-PLANS]] — queues, workers, job lifecycle, and
  storage changes.

Only sections with actual documents have folders. Folders use a two-digit ordinal (`01-`, `02-`,
`03-`) so specs and plans sort in the same order. Data storage, deployment, configuration, testing,
and security currently live in this architecture note and are linked from the section MOCs; they
do not have separate spec folders yet.

| Folder | Architecture section |
|---|---|
| `docs/specs/01-api/` / `docs/plans/01-api/` | §8 API Contract |
| `docs/specs/02-ai-providers/` / `docs/plans/02-ai-providers/` | §10 AI Provider Integrations |
| `docs/specs/03-queues-and-workers/` / `docs/plans/03-queues-and-workers/` | §5 Queue/Worker layers, §7 Request and Data Flow, §9 Data Storage |

### Documents

| Document | Type | Status | Architecture impact |
|---|---|---|---|
| `docs/specs/01-api/2026-09-13-prettycash-backend-receipt-analysis-design.md` | Spec | Implemented; Gemini transport migrated to LiteLLM | Initial API + Gemini extraction |
| `docs/specs/01-api/2026-10-24-receipt-analysis-idempotency-design.md` | Spec | Implemented | `Idempotency-Key`, `request_id`, duplicate-job reuse |
| `docs/specs/03-queues-and-workers/2026-09-13-prettycash-backend-redis-queue-design.md` | Spec | Implemented | Async queue + Supabase job store |
| `docs/specs/02-ai-providers/2026-10-22-receipt-classification-design.md` | Spec | Implemented and verified | Classifier queue/worker, `rejected`, Jev score |
| `docs/specs/02-ai-providers/2026-10-22-litellm-migration-design.md` | Spec | Implemented and verified | Provider calls via LiteLLM |
| `docs/specs/02-ai-providers/2026-10-24-auto-categorization-design.md` | Spec | Implemented | Gemini category selection, queue fields, confidence threshold |
| `docs/plans/01-api/2026-09-13-prettycash-backend-receipt-analysis.md` | Plan | Implemented | Initial API + Gemini extraction |
| `docs/plans/01-api/2026-10-24-receipt-analysis-idempotency.md` | Plan | Implemented | `Idempotency-Key`, `request_id`, duplicate-job reuse |
| `docs/plans/03-queues-and-workers/2026-09-13-prettycash-backend-redis-queue.md` | Plan | Implemented | Async queue + Supabase job store |
| `docs/plans/02-ai-providers/2026-10-22-receipt-classification.md` | Plan | Implemented | Classifier queue/worker, `rejected`, Jev score |
| `docs/plans/02-ai-providers/2026-10-22-litellm-migration.md` | Plan | Implemented | Provider calls via LiteLLM |
| `docs/plans/02-ai-providers/2026-10-24-auto-categorization.md` | Plan | Implemented | Gemini category selection, queue fields, confidence threshold |

The frontend spec in the sibling repo is implemented; on-device manual checks are outstanding:
`PrettyCash/docs/superpowers/specs/2026-10-24-auto-categorization-design.md`.

---

## 18. Architecture Change Log

| Date | Change | Spec/Plan |
|---|---|---|
| 2026-10-22 | Initial architecture document; records current runtime and approved target | This document |
| 2026-10-22 | Approved classifier architecture (not implemented) | `2026-10-22-receipt-classification-design.md` |
| 2026-10-22 | Approved LiteLLM migration (not implemented) | `2026-10-22-litellm-migration-design.md` |
| 2026-10-22 | Docs restructured by architecture section; `AGENT.md` moved to repo root; Obsidian MOCs added | This document |
| 2026-10-22 | Section folders numbered `01-`, `02-`, `03-` in specs and plans | This document |
| 2026-10-22 | Implemented classifier queue/worker, `rejected` status, classifier columns; verified end-to-end | `2026-10-22-receipt-classification-design.md` |
| 2026-10-22 | Implemented LiteLLM migration for Gemini and Jev; verified both providers live | `2026-10-22-litellm-migration-design.md` |
| 2026-10-22 | Applied `0002_add_classifier_columns.sql` directly; remote migration history mismatch noted | This document |
| 2026-10-24 | Approved Gemini receipt auto-categorization (not implemented) | `2026-10-24-auto-categorization-design.md` |
| 2026-10-24 | Implemented backend auto-categorization (queue fields, Gemini key/confidence, threshold); verified live | `2026-10-24-auto-categorization-design.md` |
| 2026-10-24 | Implemented frontend auto-categorization (profile toggle, category payload, Uncategorized fallback, category edit); migration applied; on-device checks pending | Sibling `PrettyCash` auto-categorization spec |
| 2026-10-24 | Added `Idempotency-Key` support, `receipt_jobs.request_id` unique index, and duplicate-job reuse; migration applied | `2026-10-24-receipt-analysis-idempotency-design.md` |

Append a new row for every implemented architectural change. Do not rewrite history.

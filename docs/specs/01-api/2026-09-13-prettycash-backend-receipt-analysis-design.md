---
title: "Receipt Analysis Service"
type: spec
status: implemented
date: 2026-09-13
section: api
tags:
  - prettycash
  - spec
  - api
  - gemini
  - image
---

# PrettyCash Backend — Receipt Analysis Service (Design)

**Date:** 2026-09-13
**Status:** Implemented
**Implementation status:** Implemented; Gemini client section superseded by the LiteLLM design

---

## Related

- Architecture: [[ARCHITECTURE#8. API Contract|API Contract]], [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]]
- Section: [[API]]
- Plan: [[2026-09-13-prettycash-backend-receipt-analysis|Receipt Analysis implementation]]
- Superseding design: [[2026-10-22-litellm-migration-design|Gemini and Jev via LiteLLM]]

## Architecture Alignment

- **Layers:** HTTP API, image processing service, Gemini provider client, queue seam, worker.
- **Boundaries:** HTTP stays in `app/api/`; image and provider logic stay in `app/services/`; the
  queue/worker seam is defined by `app/queue/` and `app/workers/`.
- **Current → target:** implemented. The Gemini transport is superseded by the LiteLLM design;
  the API contract and extraction schema remain.

---

## 1. Overview & Objective

Build the backend for PrettyCash's "Add Transaction with AI Receipt Scan" flow. For this first milestone the backend exposes a single synchronous endpoint, `POST /analyze-receipt`, that accepts a receipt image, calls the Gemini vision API, and returns a structured `ReceiptDraft` (merchant, amount, date, time, note, line items) that the frontend uses to pre-fill the transaction form.

The API contract is fully specified by the frontend design doc §5 (authoritative request/response model). This repo implements that contract and is architected so a Redis-backed job queue and worker can be added later without changing the endpoint or the frontend.

- **Language:** Python 3.12
- **Framework:** FastAPI (API-key locked), served by uvicorn
- **Env/deps:** `uv`
- **AI model:** `gemini-3.1-flash-lite` via Google Generative Language REST API
- **Deployment:** Docker Compose (api + worker; redis added later)

---

## 2. Scope

**In scope (now):**
- `POST /api/v1/analyze-receipt` (synchronous, matches frontend §5)
- API-key authentication (`Authorization: Bearer <key>`)
- In-memory rate limiting (Redis-backed later)
- Image validation + downscaling before Gemini
- Gemini vision call with strict-JSON structured output
- Error mapping to the §5.5 `{ error: { code, message } }` shape
- Worker-ready queue seam (`TaskQueue` protocol + `SyncQueue` now, `RedisQueue` later)
- Worker CLI entrypoint (drains the sync queue today, no-op)

**Out of scope (later):**
- Redis queue + real worker processing
- Transaction/category persistence and any database
- User accounts / multi-tenant auth

---

## 3. Architecture

```
api → service → queue interface → worker entrypoint
```

- **`api/`** knows only HTTP: parse request, authenticate, rate-limit, call the service, map errors to §5.5 JSON.
- **`services/receipt.py`** is pure: `analyze(image_bytes, mime_type) -> ReceiptDraft`. No HTTP/queue knowledge.
- **`queue/`** defines a `TaskQueue` protocol (`enqueue()` / `dequeue()`); `SyncQueue` runs inline today, `RedisQueue` replaces it later without touching `api/` or `services/`.
- **`workers/worker.py`** is the future consumer; today it drains the `SyncQueue` so the Compose `worker` service is already defined.

### 3.1 Folder structure

```
PrettyCash-Backend/
├── pyproject.toml              # uv-managed deps, ruff config
├── uv.lock
├── .env.example                # documents all vars (gitignored .env)
├── .python-version             # 3.12
├── .gitignore
├── README.md
├── docker/
│   ├── Dockerfile              # API image
│   └── compose.yaml            # api + worker (+ redis, commented until ready)
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI factory, lifespan, router mount
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py             # API-key auth + rate-limit dependency
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py       # /api/v1 prefix
│   │       ├── receipt.py      # POST /analyze-receipt, GET /health
│   │       └── schemas.py      # request/response pydantic models
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # pydantic-settings
│   │   ├── errors.py           # AppError + error codes → §5.5 shape
│   │   └── logging.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gemini.py           # Gemini REST client (model, prompt, JSON schema)
│   │   ├── receipt.py          # ReceiptAnalyzer: image → ReceiptDraft
│   │   └── image.py            # base64 decode, validate, downscale (Pillow)
│   ├── queue/
│   │   ├── __init__.py
│   │   ├── base.py             # TaskQueue protocol + Job dataclass
│   │   ├── sync.py             # SyncQueue (in-process, used now)
│   │   └── redis.py            # RedisQueue stub (implemented later)
│   └── workers/
│       ├── __init__.py
│       └── worker.py           # CLI entrypoint: pulls from queue, runs analyzer
└── tests/
    ├── conftest.py
    ├── test_api_receipt.py
    ├── test_services_receipt.py
    └── test_queue.py
```

---

## 4. Request Lifecycle

`POST /api/v1/analyze-receipt`

1. **Auth** (`deps.py`): require `Authorization: Bearer <key>`, constant-time compare against configured `VISION_API_KEY`. Missing/mismatch → `401 UNAUTHORIZED`.
2. **Rate limit** (`deps.py`): in-memory token bucket keyed by API key (`RATE_LIMIT_PER_MINUTE`). Exceeded → `429 RATE_LIMITED`.
3. **Validate body** (`schemas.py`): `{ image: { base64, mimeType } }`. Oversized/unknown → `422`/`413`.
4. **Image processing** (`services/image.py`): decode base64, verify magic bytes match `mimeType`, cap dimensions/downscale + re-encode JPEG (quality ~85). Unreadable → `400 INVALID_IMAGE`.
5. **Analyze** (`services/receipt.py`): build Gemini `inline_data` with a system prompt instructing strict JSON matching §5.4; parse + normalize → `ReceiptDraft`.
6. **Enqueue** (`queue`): result/job handed to `TaskQueue.enqueue()` for the future worker. Today `SyncQueue` returns immediately; later `RedisQueue` persists + worker drains.
7. **Respond**: `200` with §5.4 shape `{ merchant, amount, date, time, note, items }`.

### 4.1 Normalization rules (frontend §5.4)

- `amount`: positive number (grand total).
- `date`: `YYYY-MM-DD`, omitted if absent.
- `time`: `HH:mm` 24h, omitted if absent.
- `note`: string, may be empty.
- `items`: array, default `[]`; `price` = line-item total.

---

## 5. Config

`core/config.py` (pydantic-settings, `.env`):

| Var | Purpose | Required |
|-----|---------|----------|
| `GEMINI_API_KEY` | Google Generative Language API key (server-side only) | ✅ |
| `GEMINI_MODEL` | default `gemini-3.1-flash-lite` | no |
| `VISION_API_KEY` | App→backend credential sent as `Bearer` | ✅ |
| `RATE_LIMIT_PER_MINUTE` | default `30` | no |
| `MAX_IMAGE_BYTES` | default `10 MB` | no |
| `MAX_IMAGE_DIMENSION` | downscale target, default `1600` px | no |
| `LOG_LEVEL` | default `INFO` | no |

Missing required config → app refuses to boot with a clear message.

---

## 6. Error Handling

- Single exception hierarchy: `AppError` base → typed subclasses (`UnauthorizedError`, `InvalidImageError`, `UnprocessableError`, `RateLimitedError`, `InternalError`).
- Global exception handler renders `{ "error": { "code", "message" } }`.
- Codes: `UNAUTHORIZED`, `INVALID_IMAGE`, `UNPROCESSABLE`, `RATE_LIMITED`, `INTERNAL`.
- Gemini/provider failures wrapped as `INTERNAL`; never expose the Gemini key or raw provider errors.

---

## 7. Gemini Client

> **Superseded implementation note:** The LiteLLM migration spec replaces this direct
> REST client with `litellm.completion`. The model, prompt, schema fields, and validation behavior
> remain the same; see `docs/specs/02-ai-providers/2026-10-22-litellm-migration-design.md`.

`services/gemini.py`:
- Calls `generativelanguage.googleapis.com` (REST) with `gemini-3.1-flash-lite`.
- Sends image as `inline_data` (`base64` + `mime_type`).
- `generationConfig.responseMimeType = "application/json"` plus a JSON response schema matching §5.4.
- `GEMINI_API_KEY` from env only; never leaves the backend.

---

## 8. Testing

pytest + `httpx.AsyncClient` + `respx` (stub Gemini):

- `services/receipt`: valid Gemini JSON → normalized `ReceiptDraft`; malformed/missing fields → `UNPROCESSABLE`; empty `items`.
- API: `401` wrong/missing key; `429` over limit; `200` happy path; `400 INVALID_IMAGE`; Gemini failure → `500 INTERNAL` (provider error hidden).
- `queue`: `SyncQueue` enqueue/dequeue round-trip.

Run: `uv run uvicorn app.main:app`; worker `uv run python -m app.workers.worker`.

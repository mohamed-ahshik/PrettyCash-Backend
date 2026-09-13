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

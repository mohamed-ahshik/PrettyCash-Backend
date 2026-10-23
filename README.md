# PrettyCash Backend

FastAPI backend for PrettyCash's AI receipt scanning. Accepts a receipt image, classifies it with
Jev, extracts receipt data with Gemini, and exposes the result via a polling endpoint. AI provider
calls go through LiteLLM. Uses Redis for the job queues and Supabase (Postgres) for durable job
status.

## Documentation

- [Backend architecture](docs/prettycash-backend-architecture/ARCHITECTURE.md)
- [Agent workflow rules](AGENT.md)
- [Specs map](docs/specs/SPECS.md)
- [Plans map](docs/plans/PLANS.md)

Read the architecture before creating, writing, or implementing any spec.

## Setup

```bash
uv sync
cp .env.example .env   # fill in GEMINI_API_KEY, VISION_API_KEY, REDIS_URL,
                       # SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENROUTER_JEV_API_KEY
```

## Run locally

```bash
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
uv run python -m app.workers.classifier
uv run python -m app.workers.worker
```

## Test & lint

```bash
uv run pytest
uv run ruff check .
```

## API

- `POST /api/v1/analyze-receipt` → `202 { "jobId", "status": "pending" }`
- The request may also include optional `autoCategorize` + `categories` (expense categories with
  `id`, `name`, and `description`).
- `GET /api/v1/jobs/{jobId}` → `{ status }` | `{ status, result }` | `{ status, error }`
- A completed result may include `categoryId` and `categoryConfidence`.
- A non-receipt image returns `200 { "status": "rejected", "error": { "code": "NOT_A_RECEIPT", ... } }`
- Manual runs without `autoCategorize` behave exactly as before.

See `docs/specs/SPECS.md` for the full contract.

## Docker Compose

```bash
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up
```

Runs `api`, `classifier`, `worker`, and `redis` (persisted via the `redis-data` volume with AOF).
`classifier` drains `receipt:classify`, calls OpenRouter Jev through LiteLLM, and either rejects
the job or forwards it to `receipt:queue` for Gemini extraction. Supabase is external — configure
`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` and apply the migrations in `supabase/migrations/` to
your project.

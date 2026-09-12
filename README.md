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

`POST /api/v1/analyze-receipt` — see `docs/superpowers/specs/` for the full contract.

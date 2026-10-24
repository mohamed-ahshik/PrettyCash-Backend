---
title: "Receipt Analysis Idempotency"
type: spec
status: implemented
date: 2026-10-24
section: api
tags:
  - prettycash
  - spec
  - api
  - idempotency
  - redis
---

# PrettyCash Backend — Receipt Analysis Idempotency (Design)

**Date:** 2026-10-24
**Status:** Implemented
**Implementation status:** Implemented — 94 tests and ruff pass; migration applied as remote `20261024000001`; live duplicate-key POST returned the same job ID.

---

## Related

- Architecture: [[ARCHITECTURE#8. API Contract|API Contract]], [[ARCHITECTURE#9. Data Storage|Data Storage]]
- Section: [[API]]
- Plan: [[2026-10-24-receipt-analysis-idempotency|Receipt Analysis Idempotency implementation]]
- Frontend design: `PrettyCash/docs/superpowers/specs/2026-10-24-receipt-analysis-retry-design.md`

## Architecture Alignment

- **Layers:** HTTP API (`app/api/`), job store (`app/store/`), Supabase migration. No queue, worker, or provider changes.
- **Boundaries:** request validation stays at the HTTP edge; duplicate detection and row creation stay in the job store; the API only enqueues when a new row was created.
- **Current → target:** backward-compatible additive change. Requests without `Idempotency-Key` behave exactly as today.

---

## 1. Overview & Objective

A client can retry `POST /api/v1/analyze-receipt` after a network timeout even though the server created the job. Without a deduplication key, each retry creates another job and enqueues another classification. The backend must accept an optional client-generated `Idempotency-Key`, persist it on `receipt_jobs`, and return the existing job when the same key is posted again.

## 2. Scope

**In scope**

- Optional `Idempotency-Key` request header (1–128 characters).
- `receipt_jobs.request_id text` plus a partial unique index.
- Duplicate-key lookup returns the existing job without enqueueing again.
- Race-safe handling of a unique violation by re-reading the existing row.
- Backward compatibility for clients that omit the header.

**Out of scope**

- Queue/worker retries and idempotent processing.
- Request-body hashing or deduplication without a client key.
- Idempotency for any endpoint other than `POST /api/v1/analyze-receipt`.
- Changes to job status or response schema.

## 3. Contract

- Header: `Idempotency-Key: <1..128 chars>`; optional.
- New or duplicate request: `202` with `{ "jobId": "...", "status": "<current status>" }`.
- Duplicate key with an existing job: same `jobId`, current persisted status, no new queue entry.
- Invalid header length: `422` with the standard `UNPROCESSABLE` error envelope.
- Two requests without the header: independent jobs, as today.

## 4. Storage

```sql
alter table public.receipt_jobs add column if not exists request_id text;
create unique index if not exists receipt_jobs_request_id_key
  on public.receipt_jobs (request_id)
  where request_id is not null;
```

## 5. Job Store

`JobStore.create(request_id) -> CreatedJob(job_id, created)`:

1. If `request_id` is present, look it up first and return `created=False` when found.
2. Insert the row with the key.
3. If Supabase raises a unique violation (`23505`) for the key, re-read and return the existing row.
4. The API enqueues classification only when `created=True`.

## 6. Tests

- Store: new job, existing key, unique-race fallback, no-key behavior.
- API: duplicate key returns one job and one queue entry; no key creates two jobs; invalid header rejected; existing status is returned.

## 7. Deployment

Apply migration `0003_add_receipt_job_request_id.sql` to the linked Supabase project and record it in migration history.

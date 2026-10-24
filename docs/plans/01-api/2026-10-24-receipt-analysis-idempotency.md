---
title: "Receipt Analysis Idempotency Implementation Plan"
type: plan
status: implemented
date: 2026-10-24
section: api
tags:
  - prettycash
  - plan
  - api
  - idempotency
---

# PrettyCash Backend — Receipt Analysis Idempotency Implementation Plan

**Implementation status:** Implemented — automated checks and live duplicate-key verification pass.

## Related

- Spec: [[2026-10-24-receipt-analysis-idempotency-design|Receipt Analysis Idempotency]]
- Section: [[API]]
- Plans: [[API-PLANS]]
- Architecture: [[ARCHITECTURE#8. API Contract|API Contract]], [[ARCHITECTURE#9. Data Storage|Data Storage]]

## Architecture Alignment

- Adds one API header, one job-store return value, and one additive migration.
- Keeps duplicate detection in the store; HTTP only decides whether to enqueue.
- Does not touch queue names, worker logic, provider clients, or job status transitions.

**Goal:** Make `POST /api/v1/analyze-receipt` safe to retry with an `Idempotency-Key` while preserving existing behavior for clients without the header.

**Tech Stack:** Python 3.12, FastAPI, Supabase PostgREST, pytest, ruff.

## Tasks

- [x] Add `CreatedJob` and `request_id` support to the `JobStore` protocol.
- [x] Implement lookup, insert, and `23505` fallback in `SupabaseJobStore`.
- [x] Add optional `Idempotency-Key` header handling and conditional enqueue in the API route.
- [x] Update the API fake store and tests for the new return type.
- [x] Add store tests for existing/new keys and no-key behavior.
- [x] Add API tests for duplicate key, no key, invalid key, and existing status.
- [x] Add migration `supabase/migrations/0003_add_receipt_job_request_id.sql`.
- [x] Update architecture, API docs, and MOCs.
- [x] Run `pytest` and `ruff check` (94 tests; all checks passed).
- [x] Apply and record the migration on the linked project (remote `20261024000001`).

## Verification

```bash
cd /Users/user/Documents/PrettyCash-Backend/PrettyCash-Backend
uv run pytest
uv run ruff check .
```

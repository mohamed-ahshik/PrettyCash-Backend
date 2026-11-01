---
title: "LLM Observability with PostHog Implementation Plan"
type: plan
status: implemented
date: 2026-10-31
section: ai-providers
tags:
  - prettycash
  - plan
  - ai
  - posthog
  - observability
---

# LLM Observability with PostHog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Related

- Spec: [[2026-10-31-posthog-llm-observability-design|LLM Observability with PostHog]]
- Section: [[AI-PROVIDERS]]
- Plans: [[AI-PROVIDERS-PLANS]]
- Architecture: [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]]

## Architecture Alignment

- **Layers:** `app/services/analytics.py`, Gemini/Jev clients, receipt analyzer, Gemini/classifier
  workers, config, tests.
- **New dependency:** `posthog`.
- **New config:** `POSTHOG_ENABLED`, `POSTHOG_PROJECT_API_KEY`, `POSTHOG_HOST`, `ENVIRONMENT`.
- **No receipt content:** never send images, prompts, OCR, merchant, amount, or item values.
- **Attribution:** job ID is the trace/session ID; user ID is null until JWT auth provides it.
- **Failure isolation:** analytics exceptions are logged and never alter scan results.
- **Frontend:** remove the synthetic `$ai_generation` event from the sibling `PrettyCash` repo.

## Global Constraints

- PostHog disabled by default; no network in tests.
- Event name is exactly `$ai_generation`.
- Cost is `null` when unknown, never silently `0`.
- Use the same job ID for classifier and extraction events.
- No raw provider errors, keys, or receipt content in event properties.
- Do not commit unless the user asks.

---

### Task 1: PostHog Dependency, Config, and Safe Analytics Client

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Modify: `app/core/config.py`
- Create: `app/services/analytics.py`
- Create: `tests/test_services_analytics.py`
- Modify: `.env.example`
- Modify: `tests/test_core.py`

**Interfaces:**
- `LLMCallRecord` dataclass with model/provider/tokens/cost/latency/error.
- `PostHogAnalytics.capture_generation(record, *, job_id, span_name, user_id=None, auto_categorize=False)`.
- `PostHogAnalytics.from_settings(settings)` and `flush()`.
- `build_call_record(response, *, model, provider, latency_seconds, error=None)`.

- [ ] Add `posthog` and the four config fields; default `POSTHOG_ENABLED=false`.
- [ ] Implement the safe client; no-op when disabled or key-less; catch capture exceptions.
- [ ] Extract tokens from chat/decisions usage and cost from LiteLLM hidden params / usage /
  pricing table; unknown cost is `None`.
- [ ] Tests: success event, error event, disabled no-op, capture exception isolation, no content,
  unknown cost null, token/cost extraction.

---

### Task 2: Provider Callbacks

**Files:**
- Modify: `app/services/gemini.py`
- Modify: `app/services/jev.py`
- Modify: `app/services/classifier.py`
- Modify: `app/services/receipt.py`
- Modify: `tests/test_services_gemini.py`
- Modify: `tests/test_services_jev.py`
- Modify: `tests/test_services_receipt.py`
- Modify: `tests/test_services_classifier.py`

**Interfaces:**
- `GeminiClient.analyze(..., on_call=None)`
- `JevClient.classify(..., on_call=None)`
- `ReceiptClassifier.classify(..., on_call=None)`
- `ReceiptAnalyzer.analyze(..., on_llm_call=None)`

- [ ] Emit a record after each LiteLLM call, including provider/model, usage, cost, latency, and
  success/error.
- [ ] Keep existing return values and exception behavior.
- [ ] Tests: success record, provider error record, malformed response record, callback exception
  does not change scan behavior.

---

### Task 3: Worker Attribution

**Files:**
- Modify: `app/queue/base.py`
- Modify: `app/queue/redis.py`
- Modify: `app/workers/worker.py`
- Modify: `app/workers/classifier.py`
- Modify: `tests/test_queue.py`
- Modify: `tests/test_workers.py`
- Modify: `tests/test_workers_classifier.py`

**Interfaces:**
- `Job.user_id: str | None = None`
- Gemini event: `span_name="receipt_extraction"`, `auto_categorize=job.auto_categorize`.
- Jev event: `span_name="receipt_classification"`, `auto_categorize=job.auto_categorize`.

- [ ] Add optional `user_id` to the queue job; legacy payloads default `None`.
- [ ] Inject analytics into both workers; construct `PostHogAnalytics` in `main()`.
- [ ] Tests: both events share the job ID; user ID null → `distinct_id=job_id`; analytics failure
  does not change job status; classifier forwards `user_id`.

---

### Task 4: Frontend Synthetic Event Removal

**Files (sibling repo):**
- Modify: `PrettyCash/src/services/receiptAnalysis.ts`
- Modify: `PrettyCash/src/services/__tests__/receiptAnalysis.test.ts`

- [ ] Remove `captureReceiptAnalysisGeneration` and its success/error calls.
- [ ] Keep product events (`receipt_analysis_started/completed/failed`).
- [ ] Remove unused PostHog imports/helpers created only for the synthetic event.
- [ ] Run `npm test` and `npx tsc --noEmit`.

---

### Task 5: Verification

- [ ] Backend: `uv run pytest -q`, `uv run ruff check .`.
- [ ] Frontend: `npm test`, `npx tsc --noEmit`.
- [ ] Manual with `POSTHOG_ENABLED=true` and a dev key: run one receipt scan and confirm two
  `$ai_generation` events (classification + extraction) with the same trace ID.
- [ ] Confirm no image/prompt/merchant/amount/item content appears in event properties.
- [ ] Confirm cost/token fields are present; unknown cost is null.

---

### Task 6: Status and Architecture Updates

- [ ] Update the spec and this plan to implemented.
- [ ] Update `ARCHITECTURE.md`: provider/config/data/testing sections, spec/plan index, change log.
- [ ] Update `AI-PROVIDERS.md`, `AI-PROVIDERS-PLANS.md`, `PLANS.md`, `AGENT.md`, and README.
- [ ] Note frontend attribution: user ID remains null until JWT auth lands.

Do not commit unless the user asks.

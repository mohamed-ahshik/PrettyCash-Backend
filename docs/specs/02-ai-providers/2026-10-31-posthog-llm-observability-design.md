---
title: "LLM Observability with PostHog"
type: spec
status: implemented
date: 2026-10-31
section: ai-providers
tags:
  - prettycash
  - spec
  - ai
  - posthog
  - observability
  - cost
---

# PrettyCash Backend — LLM Observability with PostHog (Design)

**Date:** 2026-10-31
**Status:** Implemented
**Implementation status:** Backend instrumentation and frontend synthetic-event removal implemented;
per-user attribution remains pending until JWT auth lands.

---

## Related

- Architecture: [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]], [[ARCHITECTURE#8. API Contract|API Contract]], [[ARCHITECTURE#9. Data Storage|Data Storage]]
- Section: [[AI-PROVIDERS]]
- LiteLLM transport: [[2026-10-22-litellm-migration-design|Gemini and Jev via LiteLLM]]
- Receipt classification: [[2026-10-22-receipt-classification-design|Receipt Pre-Classification with Jev]]
- Auto-categorization: [[2026-10-24-auto-categorization-design|Auto-Categorize Receipts with Gemini]]
- Sibling repo subscription spec: `PrettyCash/docs/specs/10-subscriptions/2026-10-31-google-play-subscriptions-design.md`

## Architecture Alignment

Read `docs/prettycash-backend-architecture/ARCHITECTURE.md` before implementing this spec.

- **Layers touched:** API/request identity, `receipt_jobs` attribution, Gemini and Jev provider clients, worker event capture, config, and tests.
- **New dependency:** `posthog` Python client in the backend.
- **New config:** `POSTHOG_PROJECT_API_KEY`, `POSTHOG_HOST`, and `POSTHOG_ENABLED`.
- **New data:** optional `user_id`/`trace_id` attribution on receipt jobs; no receipt image or full text is sent to PostHog.
- **Boundaries preserved:** PostHog is observability only. It must never grant entitlements or block receipt processing.
- **After implementation:** update the architecture provider/config/data sections, spec/plan indexes, and change log.

---

## 1. Current state

Before this implementation, the frontend sent a synthetic `$ai_generation` event from
`src/services/receiptAnalysis.ts`:

- fake model name: `receipt-analysis-backend`
- fake provider: `custom`
- placeholder input/output strings
- latency
- success/error flag

That synthetic event has been removed. The backend is now the source of truth.

The FastAPI backend has no PostHog integration. `GeminiClient.analyze()` receives a LiteLLM response but discards its `usage` and cost metadata. Therefore:

- PostHog can see that a receipt-analysis attempt happened.
- It cannot see actual input tokens, output tokens, model cost, or which user incurred the cost.
- The synthetic event may produce misleading LLM analytics.
- There is no way to evaluate the economics of the planned free/trial scan limits.

## 2. Goal

Capture one authoritative PostHog LLM generation event per real model call, including:

- real provider and model,
- input/output/total tokens,
- estimated or provider-reported cost,
- latency,
- success/error,
- receipt job ID and user attribution when available.

This data must support:

- cost per receipt scan,
- cost per user and per plan,
- free/trial/Pro margin analysis,
- model latency and error monitoring,
- model/provider comparison.

## 3. Decisions locked

| Decision | Value |
|---|---|
| Analytics backend | PostHog Python client in FastAPI/worker |
| Event capture location | Backend, immediately after each LiteLLM call |
| Captured calls | Jev classification and Gemini receipt extraction |
| Primary event | `$ai_generation` |
| Cost source | LiteLLM response cost metadata when available; model price table fallback |
| User identity | Supabase user ID when available; job ID as trace/session fallback |
| Receipt content | Never send image bytes or full OCR/prompt text |
| Failure behavior | PostHog failures are logged locally and never block a scan |
| Sampling | 100% of model calls |
| Frontend synthetic event | Remove or replace with a non-LLM product event |

## 4. Event schema

### Common properties

| Property | Source |
|---|---|
| `$ai_trace_id` | Receipt job ID, stable across classifier + extraction |
| `$ai_session_id` | Receipt job ID |
| `$ai_span_name` | `receipt_classification` or `receipt_extraction` |
| `$ai_provider` | `openrouter` / `google` / LiteLLM provider |
| `$ai_model` | Exact LiteLLM model identifier |
| `$ai_input_tokens` | `response.usage.prompt_tokens` |
| `$ai_output_tokens` | `response.usage.completion_tokens` |
| `$ai_total_tokens` | Computed or `response.usage.total_tokens` |
| `$ai_total_cost_usd` | LiteLLM response cost, or pricing-table fallback |
| `$ai_cost_source` | `litellm` or `pricing_table` |
| `$ai_latency` | Seconds |
| `$ai_is_error` | Boolean |
| `$ai_error` | Sanitized error code, never raw provider secrets |
| `receipt_job_id` | Job ID |
| `user_id` | Supabase user ID when available |
| `environment` | `development` / `production` |
| `auto_categorize` | Boolean |

### Input/output representation

Do **not** send:

- receipt image bytes,
- base64 image data,
- complete prompts,
- full receipt text,
- merchant/amount/item values.

Use sanitized metadata only:

```json
{
  "$ai_input": [{"role": "user", "content": "Receipt extraction request"}],
  "$ai_output_choices": [{"role": "assistant", "content": "Structured receipt result"}]
}
```

The cost/token properties are the analytics payload; the text placeholders exist only so PostHog LLM views can render the event.

## 5. User attribution

Current receipt authentication uses a shared API key and `receipt_jobs` has no user ID. This prevents reliable per-user cost attribution.

This spec requires the subscription/API-auth work to provide:

- authenticated Supabase user ID on receipt requests,
- `receipt_jobs.user_id`,
- job ID as the trace ID.

Until that is available:

- Emit the event with `user_id = null` and `distinct_id = receipt_job_id`.
- Mark `attribution = "job_only"`.
- Do not invent a user ID or use the API key as a person identifier.

The subscription spec adds JWT authentication and quota accounting. Once implemented, pass the user ID into the job and use it as the PostHog `distinct_id`.

## 6. Provider instrumentation

### Gemini receipt extraction

`GeminiClient.analyze()` should return or attach:

- raw parsed result,
- model,
- provider,
- usage,
- cost metadata,
- latency,
- error information.

The worker emits the event after the call, not inside the API request.

### Jev classifier

The classifier worker emits a separate `$ai_generation` event using the same schema with:

- `$ai_span_name = receipt_classification`,
- the Jev model and provider,
- its own tokens/cost/latency.

A single receipt scan can therefore produce two model events with the same trace ID.

### Cost calculation

Preferred order:

1. LiteLLM response cost (`response_cost` / `_hidden_params` or `litellm.completion_cost`).
2. Local model price table keyed by model and token counts.
3. `null`/unknown; do not silently record zero cost.

For image inputs, record prompt tokens as reported by the provider. If the provider does not expose image-specific token counts, document that limitation.

## 7. Client changes

- The synthetic `$ai_generation` event was removed from `src/services/receiptAnalysis.ts`.
- Product-level events (`receipt_analysis_started/completed/failed`) remain.
- The client no longer fakes LLM input/output.
- The backend remains the source of truth for model cost.

## 8. Configuration

Add backend settings:

```text
POSTHOG_ENABLED=false
POSTHOG_PROJECT_API_KEY=<project api key>
POSTHOG_HOST=https://us.i.posthog.com
ENVIRONMENT=development
```

- `POSTHOG_ENABLED=false` or missing key → analytics client is a no-op. The backend default is
  `false`; set it to `true` with a project key to emit.
- `ENVIRONMENT` is copied into the event properties.
- The PostHog project key is server-only; never expose it as `EXPO_PUBLIC_*`.
- Tests default to disabled/no-network.

## 9. Failure isolation

PostHog must never affect receipt analysis:

- Wrap capture calls in a safe wrapper.
- Catch and log analytics exceptions at warning level.
- Do not retry a scan because analytics failed.
- Flush asynchronously; do not block the worker response path.
- Bound the PostHog client shutdown/flush time.

## 10. Testing

### Unit

- Usage extraction for prompt/completion/total tokens.
- Cost extraction from LiteLLM metadata.
- Pricing-table fallback when cost metadata is absent.
- Unknown cost remains `null`, not `0`.
- Error event has a sanitized code and no raw provider response.
- No image bytes or full receipt text in event properties.
- Disabled/no-key mode performs no network calls.
- PostHog exception does not change the job result.

### Integration

- Mock LiteLLM response with usage → assert exact PostHog event payload.
- Classifier and extractor produce two events with the same trace ID.
- A failed model call emits an error event with latency.

### Manual

- Run a receipt scan with a PostHog debug key.
- Confirm a `$ai_generation` event with tokens/cost appears.
- Compare reported cost with the provider dashboard for the same period.
- Confirm the receipt image and extracted values are absent from PostHog properties.

## 11. Dashboards and alerts

Track:

- cost per scan,
- cost per user,
- cost per subscription state (free/trial/Pro),
- token counts and latency by model,
- failure rate by provider,
- classifier + extractor combined cost per job.

Alert when:

- daily model cost exceeds a threshold,
- error rate rises sharply,
- average cost per scan changes materially,
- cost events stop arriving during active scans.

## 12. Rollout

1. Add the PostHog dependency and config.
2. Add safe capture and usage/cost extraction.
3. Instrument Gemini and Jev.
4. Add job/user attribution when Supabase JWT auth lands.
5. The frontend synthetic event was removed.
6. Verify with a small development rollout.
7. Enable production capture and build dashboards.
8. Use the data to validate free/trial/Pro pricing.

## 13. Out of scope

- Sending receipt images or extracted receipt content to PostHog.
- Using PostHog data for entitlement enforcement.
- Billing provider fees and Google Play commission.
- Per-request profitability prediction.
- Real-time budget enforcement.

## 14. Acceptance criteria

- Every Gemini and Jev call has a PostHog `$ai_generation` event.
- Events include real model, provider, token counts, cost, latency, and success/error.
- Cost is never silently reported as zero when unknown.
- Events are attributable to a receipt job; user attribution is present once JWT auth is available.
- No receipt image or extracted receipt content is sent to PostHog.
- PostHog failures cannot fail or delay a receipt scan materially.
- The frontend no longer fabricates LLM generation events.
- Cost per scan can be calculated from PostHog without reading provider billing consoles manually.

## 15. Implementation status

Implementation status: Backend instrumentation and frontend synthetic-event removal are implemented.
PostHog is disabled by default and requires `POSTHOG_ENABLED=true` plus a project API key. User
attribution remains job-only until JWT auth and `receipt_jobs.user_id` are available.

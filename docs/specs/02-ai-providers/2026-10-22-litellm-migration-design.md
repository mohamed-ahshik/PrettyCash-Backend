---
title: "Gemini and Jev via LiteLLM"
type: spec
status: implemented
date: 2026-10-22
section: ai-providers
tags:
  - prettycash
  - spec
  - ai
  - gemini
  - jev
  - litellm
---

# PrettyCash Backend — Migrate Gemini and Jev Calls to LiteLLM (Design)

**Date:** 2026-10-22
**Status:** Implemented
**Implementation status:** Implemented and verified against both providers

---

## Related

- Architecture: [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]], [[ARCHITECTURE#5. Layer Responsibilities and Dependency Rules|Layer Responsibilities]]
- Section: [[AI-PROVIDERS]]
- Supersedes: [[2026-09-13-prettycash-backend-receipt-analysis-design|Receipt Analysis Service]] Gemini client, [[2026-10-22-receipt-classification-design|Receipt Pre-Classification with Jev]] Jev client section
- Related plan: [[2026-10-22-receipt-classification|Classifier implementation]]
- Implementation plan: [[2026-10-22-litellm-migration|LiteLLM migration implementation]]

---

## Architecture Alignment

Read `docs/prettycash-backend-architecture/ARCHITECTURE.md` before implementing this spec.

- **Layers touched:** `app/services/gemini.py`, `app/services/jev.py`, `pyproject.toml`, and the two
  provider test modules.
- **New dependency:** `litellm`. No new layer, runtime service, queue, table, or API contract.
- **Boundaries preserved:** provider SDK calls stay inside `app/services/`; workers keep
  orchestrating; the API does not construct provider clients.
- **Current → target:** direct `httpx` provider calls → LiteLLM calls with the same models and keys.
- **After implementation:** move this change from "Approved Target" to "Current Runtime" in
  `ARCHITECTURE.md`, update the spec/plan index, and append the change log.

---

## 1. Overview & Objective

Replace the hand-rolled HTTP calls in the two AI clients with LiteLLM's Python SDK:

- `app/services/gemini.py` — receipt extraction
- `app/services/jev.py` — receipt/not-receipt classification

The Gemini model, Gemini API key, Jev model, OpenRouter key, prompts, JSON schema fields, API
contract, job statuses, and Supabase behavior stay the same. LiteLLM becomes the single provider
interface so future fallback models can be added without rewriting either client.

The current Gemini integration is **not** the Google SDK; it is a direct `httpx` REST client. The
current Jev integration is also direct `httpx` against OpenRouter's Decisions endpoint. Both are
replaced.

### 1.1 Decision on fallbacks

Fallback models are **deferred**. This spec only performs the migration and leaves a clean seam:

- Gemini can later use `litellm.completion(..., fallbacks=[...])`.
- Jev's `litellm.systemone` has no built-in fallback support; future Jev fallbacks require a
  LiteLLM Router or a custom wrapper. No Router or fallback configuration is added now.

---

## 2. Scope

**In scope**

- Add LiteLLM as a dependency.
- Rewrite `GeminiClient.analyze()` to call LiteLLM.
- Rewrite `JevClient.classify()` to call LiteLLM.
- Convert the receipt response schema to standard JSON Schema for Gemini 3.x.
- Update the Gemini and Jev unit tests to use injected fake LiteLLM callables.
- Update the classifier implementation plan's Jev task before implementation.

**Out of scope**

- Configuring fallback models or a LiteLLM Router.
- Running the LiteLLM proxy server.
- Changing models, API keys, prompts, schema fields, or response shapes.
- Changing the API, job statuses, queue topology, Supabase schema, or workers.
- Switching Jev from OpenRouter to TypeSafe direct.
- Removing `httpx` (still used by the API tests).
- Reworking the image classifier or its normalization.

---

## 3. Architecture

```
Gemini worker ──► GeminiClient ──► LiteLLM completion ──► Google AI Studio (gemini/)
Classifier worker ──► JevClient ──► LiteLLM systemone ──► OpenRouter Decisions (openrouter/)
```

Both clients remain the only place that knows the provider. Workers and the receipt analyzer keep
their existing interfaces.

### 3.1 Files touched

| File | Change |
|---|---|
| `pyproject.toml` | Add `litellm>=1.106.2` |
| `uv.lock` | Regenerate with `uv lock` |
| `app/services/gemini.py` | Replace `httpx` call with `litellm.completion`; standard JSON Schema |
| `app/services/jev.py` | Replace `httpx` call with `litellm.systemone` |
| `tests/test_services_gemini.py` | Fake `completion` callable instead of `respx` |
| `tests/test_services_jev.py` | Fake `systemone` callable instead of `respx` |
| `docs/plans/02-ai-providers/2026-10-22-receipt-classification.md` | Rewrite Jev client task before execution |
| `README.md` | Mention LiteLLM in the AI description |

`app/core/config.py`, `.env.example`, `docker/compose.yaml`, and the Dockerfile do not change.

---

## 4. Gemini Client

### 4.1 Call shape

`GeminiClient` keeps its constructor shape, with one optional test seam:

```python
class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        completion_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = _gemini_model(model)
        self._timeout = timeout
        self._completion = completion_fn or _default_completion
```

`_gemini_model("gemini-3.1-flash-lite")` returns `"gemini/gemini-3.1-flash-lite"`. If the value is
already prefixed with `gemini/`, it is left unchanged.

`_default_completion` imports LiteLLM lazily:

```python
def _default_completion(**kwargs: Any) -> Any:
    from litellm import completion

    return completion(**kwargs)
```

This keeps the API process from loading LiteLLM just because `app/api/v1/schemas.py` imports
`ReceiptDraft` through `app/services/receipt.py`.

The call:

```python
response = self._completion(
    model=self._model,
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_base64}",
                    },
                },
            ],
        }
    ],
    api_key=self._api_key,
    timeout=self._timeout,
    response_format={
        "type": "json_object",
        "response_schema": RECEIPT_RESPONSE_SCHEMA,
    },
)
```

The response is read from:

```python
response.choices[0].message.content
```

and parsed with `json.loads`, exactly as the receipt analyzer expects today.

### 4.2 Standard JSON Schema

LiteLLM's Gemini 3.x path sends `response_format.response_schema` through Gemini's
`responseJsonSchema`, which expects standard JSON Schema (lowercase types). Replace the current
OpenAPI-style uppercase/nullable schema with:

```python
RECEIPT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "merchant": {"type": "string"},
        "amount": {"type": "number"},
        "date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "time": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "note": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "price": {"type": "number"},
                },
                "required": ["name", "price"],
            },
        },
    },
    "required": ["merchant", "amount", "items"],
}
```

The fields, required keys, prompt, and Pydantic normalization in `ReceiptAnalyzer` are unchanged.

### 4.3 Error handling

- Any exception from `completion` → `InternalError("AI provider unavailable")`.
- Missing/empty content, malformed JSON, or an unexpected response object →
  `InternalError("Unexpected AI provider response")`.
- Provider errors, keys, and raw response bodies are never returned to clients.

The broad catch around the LiteLLM call is intentional: LiteLLM providers raise several exception
types (authentication, rate limit, timeout, connection, provider API errors), and this boundary
must collapse them all into the existing internal error contract.

---

## 5. Jev Client

### 5.1 Call shape

`JevClient` keeps `classify(image_base64) -> ClassificationResult` and its existing
`ClassifierUnavailable` / `ClassificationResult` types. Add the same optional test seam:

```python
class JevClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 5.0,
        systemone_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = _openrouter_model(model)
        self._timeout = timeout
        self._systemone = systemone_fn or _default_systemone
```

`_openrouter_model("typesafe/jev-1.14")` returns `"openrouter/typesafe/jev-1.14"`. If the value is
already prefixed with `openrouter/`, it is left unchanged.

`_default_systemone` imports LiteLLM lazily:

```python
def _default_systemone(**kwargs: Any) -> Any:
    from litellm import systemone

    return systemone(**kwargs)
```

The call:

```python
response = self._systemone(
    model=self._model,
    state=[
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_base64}",
            },
        }
    ],
    questions=IS_RECEIPT_QUESTION,
    api_key=self._api_key,
    timeout=self._timeout,
)
```

`IS_RECEIPT_QUESTION` is unchanged: one `noul` question named `is_receipt` with the existing
true/false criteria.

### 5.2 Image placement

The image is embedded directly in `state`, which is the OpenRouter/System One format that Jev 1.14
reads. Do **not** use LiteLLM's separate `images=[...]` parameter: LiteLLM's provider table marks
that parameter as unsupported for OpenRouter. The raw `state` array is forwarded to
`https://openrouter.ai/api/alpha/decisions` unchanged.

Jev 1.14's image rules still apply because they are enforced by the classifier's image
normalization step: JPEG, 256–1568 px per side, 78,400–2,458,624 total pixels. Images outside that
window skip Jev and fail open.

### 5.3 Response parsing

```python
answer = response.answers["is_receipt"]
noul = float(answer.noul)
model = str(response.model or self._model)
```

- `noul` must be finite and `0 <= noul <= 1`; otherwise `ClassifierUnavailable`.
- The response model string is returned for `classifier_model` persistence.
- A missing key, wrong answer shape, non-numeric score, or missing response attributes →
  `ClassifierUnavailable`.
- Any exception from `systemone` → `ClassifierUnavailable`.
- An empty API key → `ClassifierUnavailable` before any call.

`ClassifierUnavailable` keeps the existing classifier fail-open behavior: the worker forwards the
job to Gemini and leaves the classifier columns null.

### 5.4 Fallback limitation

`litellm.systemone` does not accept `fallbacks=[...]`. If Jev fallbacks are needed later, options
are a `litellm.Router` with a model group or a wrapper that tries the primary and fallback models.
Neither is implemented here.

---

## 6. Configuration and Dependencies

### 6.1 Dependencies

Add to `pyproject.toml`:

```toml
"litellm>=1.106.2",
```

Rationale: decisions routing requires LiteLLM `>=1.104.2`; `1.106.2` is the inspected version that
contains the OpenRouter decisions provider and TypeSafe image work. `uv.lock` pins the exact
resolved version for reproducibility.

`httpx` stays for the API test client and other tests. No Dockerfile or Compose change is needed
because the existing `uv sync` installs the new dependency.

### 6.2 Environment

No new variables:

- Gemini: existing `GEMINI_MODEL=gemini-3.1-flash-lite` and `GEMINI_API_KEY`.
- Jev: existing `OPENROUTER_JEV_MODEL=typesafe/jev-1.14` and `OPENROUTER_JEV_API_KEY`.

The provider prefixes are added in code. Keys are passed explicitly to LiteLLM, so the existing
`OPENROUTER_JEV_API_KEY` name is used instead of LiteLLM's default `OPENROUTER_API_KEY`.

---

## 7. Testing

### 7.1 Gemini tests

Replace `tests/test_services_gemini.py` with fake-callable tests:

- `FakeCompletion` records its kwargs and returns an object shaped like a LiteLLM `ModelResponse`
  whose `choices[0].message.content` is a JSON string.
- Assert the call receives:
  - `model == "gemini/gemini-3.1-flash-lite"`
  - `api_key == "key"`
  - `timeout == 60.0`
  - one user message with the prompt text and a `data:image/jpeg;base64,...` image part
  - `response_format.type == "json_object"`
  - a schema with lowercase `"object"` / `"string"` types and no `"nullable"` keys
- Assert the returned dict matches the JSON payload.
- Malformed JSON, empty content, and a fake completion that raises all produce `InternalError`.
- Remove the `respx` and direct Gemini URL assertions.

### 7.2 Jev tests

Replace `tests/test_services_jev.py` with fake-callable tests:

- `FakeSystemone` records its kwargs and returns an object with
  `answers={"is_receipt": SimpleNamespace(noul=0.92)}` and `model="openrouter/typesafe/jev-1.14"`.
- Assert the call receives:
  - `model == "openrouter/typesafe/jev-1.14"`
  - `api_key == "key"`
  - `timeout == 5.0`
  - `state` containing an `image_url` part with a JPEG data URL
  - the `is_receipt` `noul` question with true/false criteria
- Assert `ClassificationResult(noul=0.92, model=...)`.
- A fake systemone that raises, a missing answer, a non-numeric/out-of-range `noul`, and an empty
  API key all raise `ClassifierUnavailable`.
- Remove the `respx` and OpenRouter URL assertions.

### 7.3 Compatibility tests

- Existing `tests/test_services_receipt.py` continues to use `FakeGemini`; no change.
- Existing classifier worker tests continue to use `FakeClassifier`; no change.
- Full suite: `uv run pytest`.
- Lint: `uv run ruff check .`.

### 7.4 Manual verification

- Gemini: verified live with a synthetic receipt image; LiteLLM returned a parsed `ReceiptDraft`.
- Jev: verified live through the API:
  - receipt image → `completed` with `classifier_score=0.99`
  - non-receipt image → `rejected` with `classifier_score=0.01`
- The LiteLLM OpenRouter state pass-through worked as designed. The direct `httpx` fallback was not
  needed.

---

## 8. Impact on Existing Specs and Plans

This spec supersedes:

- `docs/specs/01-api/2026-09-13-prettycash-backend-receipt-analysis-design.md` §7 (Gemini client) and
  the Gemini-specific parts of §8 (testing).
- `docs/specs/02-ai-providers/2026-10-22-receipt-classification-design.md` §6 (Jev integration) and
  the Jev-client parts of §11.1 (testing).

The classifier plan was adjusted as follows:

- Task 4 (`Jev Decisions Client`) was implemented by this plan's Task 3 using
  `litellm.systemone` and fake callables.
- The LiteLLM dependency was added here.
- The classifier queue, worker, status, threshold, image normalization, and Supabase schema tasks
  were implemented unchanged.

No database migration, API contract change, or queue change is part of this spec.

---

## 9. Rollout

1. Add `litellm>=1.106.2` and run `uv lock`.
2. Rewrite `app/services/gemini.py` and `app/services/jev.py`.
3. Update the two service test files.
4. Run `uv run pytest` and `uv run ruff check .`.
5. Rebuild the Docker images and run a real Gemini extraction smoke test.
6. Keep the classifier fail-open path as a permanent policy; Jev was verified live.
7. The classifier plan's Task 4 was completed by this plan's Task 3.

No Supabase migration and no environment change are required.

---

## 10. Acceptance Criteria

1. `GeminiClient.analyze(image_bytes, mime_type)` calls LiteLLM with
   `gemini/gemini-3.1-flash-lite`, the existing `GEMINI_API_KEY`, the same prompt, and a standard
   JSON Schema, and returns the same parsed dict as before.
2. Malformed/empty Gemini responses and LiteLLM errors still map to `InternalError` without leaking
   provider details.
3. `JevClient.classify(image_base64)` calls LiteLLM with
   `openrouter/typesafe/jev-1.14`, the existing `OPENROUTER_JEV_API_KEY`, a 5s timeout, and the
   image embedded in `state`, and returns the same `ClassificationResult` as before.
4. All Jev failures still raise `ClassifierUnavailable`, preserving fail-open behavior.
5. No API contract, job status, queue, or Supabase schema changes.
6. `uv run pytest` and `uv run ruff check .` pass.
7. `litellm` is the only new runtime dependency; no new environment variables are required.
8. No fallback model behavior is introduced.

---

## 11. Risks and Open Items

- **OpenRouter credits:** resolved; Jev was verified live with credits.
- **Undocumented LiteLLM image path:** LiteLLM officially lists OpenRouter decision images as
  unsupported via the `images` parameter. This design uses the OpenRouter-native image-in-`state`
  format, which the LiteLLM source forwards unchanged. The live verification passed; keep the
  direct `httpx` fallback as a contingency only if a future LiteLLM upgrade breaks it.
- **LiteLLM version churn:** decisions support is relatively new. The lockfile pins the resolved
  version; upgrade deliberately and rerun the service tests.
- **Gemini schema conversion:** the schema representation changes from OpenAPI-style to standard
  JSON Schema. The fields and Pydantic validation are unchanged, but run the live Gemini smoke
  test to confirm Gemini 3.1 accepts the schema.
- **Jev fallback limitation:** `systemone` has no built-in fallbacks; future Jev fallback work needs
  a separate design.
- **Dependency weight:** LiteLLM brings more transitive dependencies than the direct `httpx` client.
  The Docker image will grow and the worker image build will take longer.

---

## 12. Out of Scope

- Fallback model lists, Router configuration, load balancing, retries, and cooldowns.
- Running the LiteLLM proxy or adding a new Compose service.
- Changing Gemini or Jev model versions, API keys, prompts, or response fields.
- API, job status, queue, worker, or Supabase changes.
- TypeSafe direct integration for Jev.
- Removing `httpx` or refactoring the image pipeline.

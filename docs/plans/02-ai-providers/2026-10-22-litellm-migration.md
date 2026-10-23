---
title: "Gemini and Jev via LiteLLM Implementation Plan"
type: plan
status: implemented
date: 2026-10-22
section: ai-providers
tags:
  - prettycash
  - plan
  - ai
  - gemini
  - jev
  - litellm
---

# Gemini and Jev via LiteLLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Related

- Spec: [[2026-10-22-litellm-migration-design|Gemini and Jev via LiteLLM]]
- Section: [[AI-PROVIDERS]]
- Plans: [[AI-PROVIDERS-PLANS]]
- Architecture: [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]]

## Architecture Alignment

Read `docs/prettycash-backend-architecture/ARCHITECTURE.md` before executing this plan.

- **Layers touched:** `app/services/gemini.py`, `app/services/jev.py`, `pyproject.toml`, and the two
  provider test modules.
- **New dependency:** `litellm`. No new layer, service, queue, table, or API contract.
- **Boundaries preserved:** provider SDK calls stay in `app/services/`; workers orchestrate; the API
  does not construct provider clients.
- **After implementation:** update the architecture current-state sections and change log.

## Global Constraints

- Keep the existing Gemini and Jev model names and API keys.
- Gemini model: `gemini/gemini-3.1-flash-lite` built from `GEMINI_MODEL`.
- Jev model: `openrouter/typesafe/jev-1.14` built from `OPENROUTER_JEV_MODEL`.
- Jev image is embedded in `state`, never passed via LiteLLM's `images` parameter.
- Provider errors map to `InternalError` (Gemini) or `ClassifierUnavailable` (Jev).
- Do not commit `.env` or secrets.
- Follow TDD. Do not commit unless the user asks.

---

### Task 1: Add LiteLLM

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Produces: an importable `litellm` package with decisions support.

- [ ] **Step 1: Add the dependency**

```bash
uv add 'litellm>=1.106.2'
```

- [ ] **Step 2: Verify the import and decisions API**

```bash
uv run python - <<'PY'
import litellm
assert hasattr(litellm, "completion")
assert hasattr(litellm, "systemone")
print(litellm.__version__)
PY
```

Expected: a version `1.106.2` or newer and no `AttributeError`.

---

### Task 2: Migrate the Gemini Client

**Files:**
- Modify: `app/services/gemini.py`
- Modify: `tests/test_services_gemini.py`

**Interfaces:**
- Consumes: `GEMINI_API_KEY`, `GEMINI_MODEL`, `MAX_IMAGE_DIMENSION` output.
- Produces: `GeminiClient(api_key, model, timeout=60.0, completion_fn=None)` and
  `GeminiClient.analyze(image_base64, mime_type) -> dict`.

- [ ] **Step 1: Replace the Gemini tests**

Replace `tests/test_services_gemini.py` with:

```python
import json
from types import SimpleNamespace

import pytest

from app.core.errors import InternalError
from app.services.gemini import RECEIPT_RESPONSE_SCHEMA, GeminiClient


class FakeCompletion:
    def __init__(self, content=None, response=None, error=None):
        self.content = content
        self.response = response
        self.error = error
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def test_analyze_calls_litellm_and_parses_json():
    payload = json.dumps({"merchant": "Whole Foods", "amount": 42.75})
    fake = FakeCompletion(content=payload)
    client = GeminiClient("key", "gemini-3.1-flash-lite", completion_fn=fake)

    result = client.analyze("aGVsbG8=", "image/jpeg")

    assert result == {"merchant": "Whole Foods", "amount": 42.75}
    assert fake.kwargs["model"] == "gemini/gemini-3.1-flash-lite"
    assert fake.kwargs["api_key"] == "key"
    assert fake.kwargs["timeout"] == 60.0
    content = fake.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert "receipt scanner" in content[0]["text"]
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="},
    }
    response_format = fake.kwargs["response_format"]
    assert response_format["type"] == "json_object"
    assert response_format["response_schema"] == RECEIPT_RESPONSE_SCHEMA
    assert response_format["response_schema"]["type"] == "object"
    assert "nullable" not in json.dumps(response_format["response_schema"])


def test_analyze_does_not_double_prefix_model():
    fake = FakeCompletion(content=json.dumps({"merchant": "X", "amount": 1.0}))
    client = GeminiClient("key", "gemini/gemini-3.1-flash-lite", completion_fn=fake)

    client.analyze("aGVsbG8=", "image/jpeg")

    assert fake.kwargs["model"] == "gemini/gemini-3.1-flash-lite"


@pytest.mark.parametrize("content", ["", "not-json", None])
def test_analyze_raises_internal_on_bad_content(content):
    client = GeminiClient("key", "gemini-3.1-flash-lite", completion_fn=FakeCompletion(content=content))
    with pytest.raises(InternalError):
        client.analyze("aGVsbG8=", "image/jpeg")


def test_analyze_raises_internal_on_empty_choices():
    fake = FakeCompletion(response=SimpleNamespace(choices=[]))
    client = GeminiClient("key", "gemini-3.1-flash-lite", completion_fn=fake)
    with pytest.raises(InternalError):
        client.analyze("aGVsbG8=", "image/jpeg")


def test_analyze_raises_internal_on_provider_error():
    fake = FakeCompletion(error=RuntimeError("provider down"))
    client = GeminiClient("key", "gemini-3.1-flash-lite", completion_fn=fake)
    with pytest.raises(InternalError):
        client.analyze("aGVsbG8=", "image/jpeg")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_services_gemini.py -v
```

Expected: FAIL because `GeminiClient` still uses `httpx` and has no `completion_fn`.

- [ ] **Step 3: Replace the Gemini client**

Replace `app/services/gemini.py` with:

```python
import json
from collections.abc import Callable
from typing import Any

from app.core.errors import InternalError

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

PROMPT = (
    "You are a receipt scanner. Extract the following fields from the receipt image and "
    "return them as JSON matching the requested schema:\n"
    "- merchant: the store or merchant name (empty string if unreadable)\n"
    "- amount: the receipt grand total as a positive number\n"
    "- date: the receipt date as YYYY-MM-DD if present, otherwise null\n"
    "- time: the receipt time as HH:mm in 24-hour format if present, otherwise null\n"
    "- note: a short note about the purchase, empty string if none\n"
    "- items: the line items; each item has name, quantity (if meaningful), and price "
    "(the line-item total)\n"
    "Return only JSON."
)


def _gemini_model(model: str) -> str:
    return model if model.startswith("gemini/") else f"gemini/{model}"


def _default_completion(**kwargs: Any) -> Any:
    from litellm import completion

    return completion(**kwargs)


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

    def analyze(self, image_base64: str, mime_type: str) -> dict:
        try:
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
        except Exception as exc:
            raise InternalError("AI provider unavailable") from exc

        try:
            content = response.choices[0].message.content
            if not content:
                raise ValueError("empty content")
            return json.loads(content)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise InternalError("Unexpected AI provider response") from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_services_gemini.py -v
```

Expected: PASS.

---

### Task 3: Create the Jev Client with LiteLLM

**Files:**
- Create: `app/services/jev.py`
- Create: `tests/test_services_jev.py`

**Interfaces:**
- Consumes: `OPENROUTER_JEV_API_KEY`, `OPENROUTER_JEV_MODEL`, `OPENROUTER_TIMEOUT_SECONDS`.
- Produces:
  - `ClassifierUnavailable`
  - `ClassificationResult(noul, model)`
  - `JevClient(api_key, model, timeout=5.0, systemone_fn=None)`
  - `JevClient.classify(image_base64) -> ClassificationResult`

- [ ] **Step 1: Write the failing Jev tests**

Create `tests/test_services_jev.py`:

```python
from types import SimpleNamespace

import pytest

from app.services.jev import (
    ClassificationResult,
    ClassifierUnavailable,
    JevClient,
)


class FakeSystemone:
    def __init__(self, noul=0.92, model="typesafe/jev-1.14", error=None):
        self.noul = noul
        self.model = model
        self.error = error
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            answers={"is_receipt": SimpleNamespace(noul=self.noul)},
            model=self.model,
        )


def test_classify_calls_litellm_and_parses_score():
    fake = FakeSystemone()
    client = JevClient("key", "typesafe/jev-1.14", systemone_fn=fake)

    result = client.classify("aGVsbG8=")

    assert result == ClassificationResult(noul=0.92, model="typesafe/jev-1.14")
    assert fake.kwargs["model"] == "openrouter/typesafe/jev-1.14"
    assert fake.kwargs["api_key"] == "key"
    assert fake.kwargs["timeout"] == 5.0
    assert fake.kwargs["state"] == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="},
        }
    ]
    question = fake.kwargs["questions"]["is_receipt"]
    assert question["type"] == "noul"
    assert question["criteria"]["true"]
    assert question["criteria"]["false"]


def test_classify_does_not_double_prefix_model():
    fake = FakeSystemone(noul=0.5)
    client = JevClient("key", "openrouter/typesafe/jev-1.14", systemone_fn=fake)

    client.classify("aGVsbG8=")

    assert fake.kwargs["model"] == "openrouter/typesafe/jev-1.14"


@pytest.mark.parametrize("noul", [-0.1, 1.5, float("nan")])
def test_classify_rejects_invalid_scores(noul):
    client = JevClient("key", "typesafe/jev-1.14", systemone_fn=FakeSystemone(noul=noul))
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")


def test_classify_raises_without_api_key():
    client = JevClient("", "typesafe/jev-1.14")
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")


def test_classify_raises_on_provider_error():
    client = JevClient(
        "key",
        "typesafe/jev-1.14",
        systemone_fn=FakeSystemone(error=RuntimeError("provider down")),
    )
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(answers={}, model="typesafe/jev-1.14"),
        SimpleNamespace(
            answers={"is_receipt": SimpleNamespace(noul="not-a-number")},
            model="typesafe/jev-1.14",
        ),
    ],
)
def test_classify_raises_on_malformed_response(response):
    def fake(**kwargs):
        return response

    client = JevClient("key", "typesafe/jev-1.14", systemone_fn=fake)
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_services_jev.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.jev'`.

- [ ] **Step 3: Create the Jev client**

Create `app/services/jev.py`:

```python
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

IS_RECEIPT_QUESTION = {
    "is_receipt": {
        "type": "noul",
        "instructions": (
            "The image shows a receipt, bill, or invoice containing merchant and amount "
            "information."
        ),
        "criteria": {
            "true": (
                "A photo, scan, or screenshot of a merchant receipt, bill, or invoice with a "
                "total amount and/or line items."
            ),
            "false": (
                "Any other image, including a selfie, landscape, product photo, unrelated "
                "screenshot, bank statement, order confirmation, or other document without a "
                "merchant receipt or invoice."
            ),
        },
    }
}


class ClassifierUnavailable(Exception):
    """Raised when Jev cannot produce a usable answer; callers fail open to Gemini."""


@dataclass(frozen=True)
class ClassificationResult:
    noul: float
    model: str


def _openrouter_model(model: str) -> str:
    return model if model.startswith("openrouter/") else f"openrouter/{model}"


def _default_systemone(**kwargs: Any) -> Any:
    from litellm import systemone

    return systemone(**kwargs)


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

    def classify(self, image_base64: str) -> ClassificationResult:
        if not self._api_key:
            raise ClassifierUnavailable("OpenRouter Jev API key is not configured")

        try:
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
        except Exception as exc:
            raise ClassifierUnavailable("Jev request failed") from exc

        try:
            answer = response.answers["is_receipt"]
            noul = float(answer.noul)
            model = str(getattr(response, "model", "") or self._model)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ClassifierUnavailable("Unexpected Jev response") from exc

        if not math.isfinite(noul) or not 0.0 <= noul <= 1.0:
            raise ClassifierUnavailable("Jev returned an invalid noul score")

        return ClassificationResult(noul=noul, model=model)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_services_jev.py -v
```

Expected: PASS.

---

### Task 4: Verify Provider Clients

- [ ] **Step 1: Run both provider test files**

```bash
uv run pytest tests/test_services_gemini.py tests/test_services_jev.py -v
```

Expected: PASS.

- [ ] **Step 2: Run lint on the changed files**

```bash
uv run ruff check app/services/gemini.py app/services/jev.py \
  tests/test_services_gemini.py tests/test_services_jev.py
```

Expected: no errors.

- [ ] **Step 3: Update the architecture**

Update `docs/prettycash-backend-architecture/ARCHITECTURE.md` after implementation:

- Move Gemini/Jev calls from "Approved Target" to "Current Runtime".
- Update the AI provider section to say LiteLLM is the transport.
- Update the testing section to say provider tests use injected fake callables.
- Update the spec/plan index and change log.

Do not commit unless the user asks.

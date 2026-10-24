---
title: "Auto-Categorize Receipts with Gemini"
type: plan
status: implemented
date: 2026-10-24
section: ai-providers
tags:
  - prettycash
  - plan
  - ai
  - gemini
  - categories
---

# PrettyCash Backend — Auto-Categorize Receipts with Gemini (Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the backend half of receipt auto-categorization: pass category options through the queue and Gemini analyzer, map the model’s key to the real category UUID, apply the confidence threshold, and document the result.

**Architecture:** The API, queue, and Gemini prompt/schema are already partially implemented. The remaining work is in `ReceiptAnalyzer`, the Gemini worker, tests, and architecture docs. No new queue, table, or dependency.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Redis, LiteLLM/Gemini, pytest, ruff.

**Spec:** [[2026-10-24-auto-categorization-design|Auto-Categorize Receipts with Gemini]]
**Architecture:** [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]]
**Section MOC:** [[AI-PROVIDERS-PLANS]]

**Implementation status:** Implemented — analyzer/worker complete; 87 backend tests and ruff pass; live verification is recorded in `ARCHITECTURE.md`. Frontend integration is implemented in the sibling repo.

## Global Constraints

- Preserve layer boundaries from `AGENT.md`.
- No new dependency; no backend DB migration.
- Old queued jobs must process with `auto_categorize=False` and `categories=[]`.
- Category names/descriptions are user data and must never be logged.
- `uv run pytest` and `uv run ruff check .` must pass after each task.

---

### Task 1: Complete ReceiptDraft and ReceiptAnalyzer

**Files:**
- Modify: `app/services/receipt.py`
- Modify: `tests/test_services_receipt.py` only if a needed assertion is missing.

**Interfaces:**
- `ReceiptAnalyzer(gemini, category_confidence_threshold=0.7)`
- `ReceiptAnalyzer.analyze(image_bytes, mime_type, auto_categorize=False, categories=None, job_id=None) -> ReceiptDraft`
- `ReceiptDraft.categoryId: str | None`, `ReceiptDraft.categoryConfidence: float | None`

- [ ] **Step 1: Add category fields to `ReceiptDraft`**

```python
class ReceiptDraft(BaseModel):
    merchant: str = ""
    amount: float = Field(gt=0)
    date: str | None = None
    time: str | None = None
    note: str = ""
    items: list[LineItem] = Field(default_factory=list)
    categoryId: str | None = None
    categoryConfidence: float | None = None
```

- [ ] **Step 2: Implement analyzer keying, mapping, threshold, and logging**

```python
import logging
import math

logger = logging.getLogger(__name__)

class ReceiptAnalyzer:
    def __init__(self, gemini: GeminiClient, category_confidence_threshold: float = 0.7) -> None:
        self._gemini = gemini
        self._threshold = category_confidence_threshold

    def analyze(
        self,
        image_bytes: bytes,
        mime_type: str,
        auto_categorize: bool = False,
        categories: list[dict[str, str]] | None = None,
        job_id: str | None = None,
    ) -> ReceiptDraft:
        image_base64 = base64.b64encode(image_bytes).decode()
        keyed = (
            [{"key": f"c{index}", **category} for index, category in enumerate(categories, start=1)]
            if auto_categorize and categories
            else []
        )
        raw = self._gemini.analyze(image_base64, mime_type, categories=keyed)
        return self._normalize(raw, keyed, auto_categorize, job_id=job_id)

    def _normalize(
        self,
        raw: dict[str, Any],
        keyed: list[dict[str, str]],
        auto_categorize: bool,
        job_id: str | None = None,
    ) -> ReceiptDraft:
        category_key = raw.pop("categoryKey", None)
        raw_confidence = raw.pop("categoryConfidence", None)
        confidence = (
            float(raw_confidence)
            if isinstance(raw_confidence, (int, float))
            and math.isfinite(raw_confidence)
            and 0 <= raw_confidence <= 1
            else None
        )
        match = next((c for c in keyed if c["key"] == category_key), None)

        requested = bool(auto_categorize and keyed)
        if requested and match and confidence is not None and confidence >= self._threshold:
            category_id = match["id"]
            decision = "accepted"
        elif requested and match and confidence is not None:
            category_id = None
            decision = "below_threshold"
        elif not requested:
            category_id = None
            decision = "not_requested"
        else:
            category_id = None
            decision = "no_match"

        logger.info(
            "Category decision job_id=%s category_key=%s category_confidence=%s "
            "threshold=%s category_decision=%s",
            job_id,
            category_key,
            confidence,
            self._threshold,
            decision,
        )

        try:
            draft = ReceiptDraft(**raw)
        except ValidationError as exc:
            raise UnprocessableError("Receipt data could not be parsed") from exc
        draft.categoryId = category_id
        draft.categoryConfidence = confidence if requested else None
        return draft
```

- [ ] **Step 3: Run the service tests**

```bash
uv run pytest tests/test_services_receipt.py -q
```

Expected: all pass, including the seven category tests.

---

### Task 2: Wire the Gemini worker and update worker tests

**Files:**
- Modify: `app/workers/worker.py`
- Modify: `tests/test_workers.py`

- [ ] **Step 1: Pass job fields and the threshold**

```python
draft = analyzer.analyze(
    image_bytes,
    job.mime_type,
    auto_categorize=job.auto_categorize,
    categories=job.categories,
    job_id=job.job_id,
)
```

In `main()`:

```python
analyzer = ReceiptAnalyzer(
    gemini,
    category_confidence_threshold=settings.receipt_category_confidence_threshold,
)
```

- [ ] **Step 2: Update the worker tests**

```python
class FakeAnalyzer:
    def __init__(self):
        self.kwargs = None

    def analyze(self, image_bytes: bytes, mime_type: str, **kwargs) -> ReceiptDraft:
        self.kwargs = kwargs
        return ReceiptDraft(merchant="X", amount=1.0)


def test_process_job_passes_category_fields(job_store):
    job = Job(
        job_id="job-1",
        image_base64="aGk=",
        mime_type="image/jpeg",
        auto_categorize=True,
        categories=[{"id": "cat-1", "name": "Food", "description": "Groceries"}],
    )
    analyzer = FakeAnalyzer()
    process_job(job, analyzer, job_store)
    assert analyzer.kwargs == {
        "auto_categorize": True,
        "categories": [{"id": "cat-1", "name": "Food", "description": "Groceries"}],
        "job_id": "job-1",
    }
```

Update `FailingAnalyzer.analyze` to accept `**kwargs`.

- [ ] **Step 3: Run worker tests**

```bash
uv run pytest tests/test_workers.py tests/test_workers_classifier.py -q
```

---

### Task 3: Config, docs, and final verification

**Files:**
- Modify: `.env.example`
- Modify: `docs/prettycash-backend-architecture/ARCHITECTURE.md`
- Modify: `docs/specs/SPECS.md`, `docs/specs/02-ai-providers/AI-PROVIDERS.md`
- Modify: `docs/plans/PLANS.md`, `docs/plans/02-ai-providers/AI-PROVIDERS-PLANS.md`
- Modify: `docs/specs/02-ai-providers/2026-10-24-auto-categorization-design.md`
- Modify: `docs/plans/02-ai-providers/2026-10-24-auto-categorization.md` (this file)

- [ ] **Step 1: Add the threshold to `.env.example`**

```dotenv
RECEIPT_CATEGORY_CONFIDENCE_THRESHOLD=0.7
```

- [ ] **Step 2: Update `ARCHITECTURE.md`**

- Move section 10.3 from “approved, not implemented” to the current runtime.
- Add `autoCategorize`/`categories` to the API request contract and `categoryId`/`categoryConfidence` to the completed result.
- Add the two fields to the job contract and queue serialization description.
- Add `RECEIPT_CATEGORY_CONFIDENCE_THRESHOLD` to the config table.
- Add a 2026-10-24 change-log row linking this plan.

- [ ] **Step 3: Update spec/plan indexes and statuses**

Add this plan to `docs/plans/PLANS.md` and `AI-PROVIDERS-PLANS.md`; set both auto-categorization documents to `status: implemented` and `**Implementation status:** Implemented`.

- [ ] **Step 4: Final verification**

```bash
uv run pytest
uv run ruff check .
docker compose -f docker/compose.yaml config -q
docker compose -f docker/compose.yaml up -d --build api classifier worker
docker compose -f docker/compose.yaml ps
```

Live check: enqueue a receipt with a seeded Food category and `autoCategorize: true`; confirm `completed` includes `categoryId`; enqueue an ambiguous image; confirm no `categoryId`.

**Implementation status:** Implemented.

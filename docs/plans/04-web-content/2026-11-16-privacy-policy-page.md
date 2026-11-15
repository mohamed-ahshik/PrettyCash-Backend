---
title: "Privacy Policy Page Implementation Plan"
type: plan
status: in-progress
date: 2026-11-16
section: web-content
tags:
  - prettycash
  - plan
  - web-content
  - privacy
  - http
---

# Privacy Policy Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve a public, self-contained HTML privacy policy at `GET /privacy` from the existing
FastAPI container, alongside the unchanged `/api/v1` API.

**Architecture:** A small `app/api/pages.py` router returns `app/static/privacy.html` through
`FileResponse`; `create_app` includes the router next to the API router. No new container, port,
dependency, or configuration. Cloudflare routes the apex `prettycash.app` to the existing service.

**Tech Stack:** FastAPI/Starlette `FileResponse`, pytest + `httpx.ASGITransport`, ruff.

**Spec:** `docs/specs/04-web-content/2026-11-15-privacy-policy-page-design.md`

## Related

- Architecture: [[ARCHITECTURE#8. API Contract|API Contract]], [[ARCHITECTURE#12. Deployment|Deployment]]
- Spec: [[2026-11-15-privacy-policy-page-design|Privacy Policy Page design]]
- Section: [[WEB-CONTENT]] / [[WEB-CONTENT-PLANS]]
- Related sections: [[API]], [[QUEUES-AND-WORKERS]]

## Global Constraints

- No new Compose service, published port, environment variable, dependency, table, or queue.
- `/api/v1/*` contract, authentication, and behavior do not change.
- `GET /privacy` is public, returns `text/html; charset=utf-8`, and is absent from OpenAPI.
- `Cache-Control: public, max-age=300`.
- The page is one self-contained file: no JavaScript, no external fonts/scripts/images.
- Do not merge or push the DRAFT template to `main`; deployment is automatic on push. The owner
  replaces every `[PLACEHOLDER]` and removes the DRAFT banner first.
- Keep `api.prettycash.app` routed to the same service until the mobile app ships
  `https://prettycash.app` as its base URL.

## Review Focus

1. A future global auth dependency could block the page → a request with no credentials must return
   `200`; covered by the public-page test in Task 1.
2. Trailing slash `/privacy/` → must reach the page, not `404`; test the `307` redirect in Task 1.
3. Non-ASCII copy (em dashes, accented names) → must decode as UTF-8; the charset assertion in
   Task 1 pins this.
4. Stale legal copy → corrections should appear within five minutes; the cache-header assertion in
   Task 1 pins this.
5. Missing or renamed HTML asset in the built image → the endpoint must be checked after the Docker
   build; manual step in Task 3.

---

### Task 0: Restore the ruff baseline

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/services/quota.py` (wrap two long lines; import order auto-fixed)
- Modify: `tests/conftest.py`, `tests/test_api_receipt.py` (import order auto-fixed)

**Interfaces:**
- Consumes: nothing.
- Produces: `uv run ruff check .` exits 0, so later tasks can meet `AGENT.md`'s definition of done.

- [ ] **Step 1: Ignore the FastAPI `B008` false positive**

Add to `pyproject.toml` under `[tool.ruff.lint]`:

```toml
# FastAPI dependency injection uses Depends() in argument defaults.
ignore = ["B008"]
```

- [ ] **Step 2: Auto-fix import ordering**

Run: `uv run ruff check . --fix`
Expected: `I001` findings in `app/services/quota.py`, `tests/conftest.py`, and
`tests/test_api_receipt.py` are fixed; the remaining output is the two `E501` lines in
`app/services/quota.py`.

- [ ] **Step 3: Wrap the two long lines**

In `app/services/quota.py`, replace the line-80 return with:

```python
        return Entitlement(
            False, True, days_left, scans_used, daily_limit, False, "daily_trial_limit"
        )
```

Replace the line-114 message with:

```python
            raise DailyTrialLimitError(
                f"You have used {scans_used}/{self._settings.trial_daily_scan_limit} "
                "AI scans today."
            )
```

- [ ] **Step 4: Verify**

Run: `uv run ruff check .`
Expected: `All checks passed!`

Run: `uv run pytest -q`
Expected: `120 passed`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/services/quota.py tests/conftest.py tests/test_api_receipt.py
git commit -m "chore: restore ruff baseline"
```

---

### Task 1: Public `/privacy` route

**Files:**
- Create: `app/api/pages.py`
- Create: `tests/test_api_privacy.py`
- Modify: `app/main.py`
- Existing asset: `app/static/privacy.html` (DRAFT template; the owner edits the copy separately)

**Interfaces:**
- Consumes: `create_app` from `app/main.py`.
- Produces: `router: APIRouter` in `app/api/pages.py`; `GET /privacy` → `FileResponse`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_privacy.py`:

```python
async def test_privacy_page_is_public_html(client):
    response = await client.get("/privacy")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "Privacy Policy" in response.text
    assert response.headers["cache-control"] == "public, max-age=300"


async def test_privacy_trailing_slash_redirects_to_canonical(client):
    response = await client.get("/privacy/")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/privacy")


async def test_privacy_page_not_in_openapi(client):
    response = await client.get("/openapi.json")
    assert "/privacy" not in response.json()["paths"]
```

- [ ] **Step 2: Run the tests to verify the page is missing**

Run: `uv run pytest tests/test_api_privacy.py -v`
Expected: FAIL — `/privacy` returns `404`. The OpenAPI test passes trivially and stays as a
regression guard.

- [ ] **Step 3: Add the router and include it**

Create `app/api/pages.py`:

```python
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

PRIVACY_PAGE = Path(__file__).resolve().parents[1] / "static" / "privacy.html"


@router.get("/privacy", include_in_schema=False)
async def privacy_policy() -> FileResponse:
    return FileResponse(
        PRIVACY_PAGE,
        media_type="text/html",
        headers={"Cache-Control": "public, max-age=300"},
    )
```

Modify `app/main.py`:

- Add `from app.api.pages import router as pages_router` above the existing
  `from app.api.v1.router import api_router` import.
- Add `app.include_router(pages_router)` immediately after `app.include_router(api_router)`.

- [ ] **Step 4: Run the tests and the full suite**

Run: `uv run pytest tests/test_api_privacy.py -v`
Expected: PASS (3 tests).

Run: `uv run pytest && uv run ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/pages.py app/main.py tests/test_api_privacy.py
git commit -m "feat: serve privacy policy at /privacy"
```

---

### Task 2: Documentation and indexes

**Files:**
- Modify: `docs/prettycash-backend-architecture/ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `docs/specs/04-web-content/2026-11-15-privacy-policy-page-design.md`
- Modify: `docs/plans/04-web-content/2026-11-16-privacy-policy-page.md`
- Modify: `docs/specs/04-web-content/WEB-CONTENT.md`
- Modify: `docs/plans/04-web-content/WEB-CONTENT-PLANS.md`

**Interfaces:**
- Consumes: the implementation from Task 1.
- Produces: documentation that matches the runtime.

- [ ] **Step 1: Add the route to the §8 API Contract table**

Add this row to `ARCHITECTURE.md`:

```markdown
| `GET /privacy` | No | Static HTML privacy policy (outside `/api/v1`; not in OpenAPI) |
```

- [ ] **Step 2: Record the deployment path in §12**

Add this bullet to `ARCHITECTURE.md`:

```markdown
- The API image also serves `GET /privacy` from `app/static/privacy.html`. Cloudflare routes
  `prettycash.app` to port 8000; `api.prettycash.app` stays routed to the same service until the
  mobile app ships the new base URL.
```

- [ ] **Step 3: Update the §17 index and §18 change log**

Add the spec and plan to the §17 Documents table. Append to the §18 change log:

```markdown
| 2026-11-16 | Added public `GET /privacy` serving the static privacy policy from the API image | `2026-11-15-privacy-policy-page-design.md` |
```

- [ ] **Step 4: Update `README.md`**

Add after the API section:

```markdown
## Privacy policy

Served by the API at `GET /privacy`, without authentication:
`https://prettycash.app/privacy` (or `http://localhost:8000/privacy` locally).
```

- [ ] **Step 5: Update document statuses**

Set the spec and plan frontmatter to `status: in-progress`, and update the status lines in
`WEB-CONTENT.md` and `WEB-CONTENT-PLANS.md` from "proposed" to "in progress". Task 3 marks them
implemented after the deploy checks pass.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/prettycash-backend-architecture/ARCHITECTURE.md \
  docs/specs/04-web-content docs/plans/04-web-content docs/specs/SPECS.md docs/plans/PLANS.md
git commit -m "docs: record privacy policy page in architecture"
```

---

### Task 3: Publish checklist (owner + deployment)

**Files:**
- Modify: `app/static/privacy.html` (owner-supplied copy only)

- [ ] **Step 1: Replace the copy**

Replace every `[PLACEHOLDER]` in `app/static/privacy.html`, set the effective and last-updated dates,
and remove the DRAFT banner and its HTML comment. Confirm the processor list matches production and
that retention/legal-entity/contact statements are true.

- [ ] **Step 2: Run the checks**

Run: `uv run pytest && uv run ruff check .`
Expected: PASS.

- [ ] **Step 3: Verify the built image locally**

Run:

```bash
docker compose build api
docker compose up -d api
curl -i http://localhost:8000/privacy
curl -i http://localhost:8000/
curl -s http://localhost:8000/api/v1/health
```

Expected: `/privacy` returns `200` with `content-type: text/html; charset=utf-8`; `/` returns
`200` with `text/plain; charset=utf-8` and `PrettyCash`; health returns `{"status":"ok"}`. A `500`
here means the HTML asset is missing from the image.

- [ ] **Step 4: Deploy and verify Cloudflare**

Commit and push only after the copy is final (`main` deploys automatically). Add the Cloudflare
public hostname: empty subdomain, domain `prettycash.app`, no path, service
`HTTP` → `localhost:8000`. Keep `api.prettycash.app` on the same service during the app migration.

Run:

```bash
curl -i https://prettycash.app/privacy
curl -i https://prettycash.app/
curl -s https://prettycash.app/api/v1/health
```

Expected: `200 text/html` for the page, `200 text/plain` with `PrettyCash` for the root, and
`{"status":"ok"}` for health.

- [ ] **Step 5: Submit the store URL**

Use `https://prettycash.app/privacy` in the App Store / Play Console listing after the endpoint
returns `200`.

- [ ] **Step 6: Mark the documents implemented**

After the deploy checks above pass, set the spec and plan frontmatter to `status: implemented` and
update the status lines in `WEB-CONTENT.md` and `WEB-CONTENT-PLANS.md` to "implemented".

---

### Task 4: Root plain-text placeholder (post-review addition)

**Files:**
- Modify: `app/api/pages.py`
- Modify: `tests/test_api_privacy.py`

**Interfaces:**
- Consumes: the existing `router` in `app/api/pages.py`.
- Produces: `GET /` → `PlainTextResponse("PrettyCash")`, with `include_in_schema=False`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_privacy.py`:

```python
async def test_root_shows_prettycash_text(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == "PrettyCash"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_api_privacy.py::test_root_shows_prettycash_text -v`
Expected: FAIL — `404` from the global JSON error handler.

- [ ] **Step 3: Implement the route**

In `app/api/pages.py`, import `PlainTextResponse` and add:

```python
@router.get("/", include_in_schema=False)
async def root() -> PlainTextResponse:
    return PlainTextResponse("PrettyCash")
```

- [ ] **Step 4: Run the checks**

Run: `uv run pytest tests/test_api_privacy.py -v && uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/pages.py tests/test_api_privacy.py
git commit -m "feat: show PrettyCash at root"
```

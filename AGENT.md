# Agent Instructions — PrettyCash Backend

**Applies to:** the entire repository
**Location:** repository root (this file)
**Mandatory reading order:** this file → [ARCHITECTURE.md](docs/prettycash-backend-architecture/ARCHITECTURE.md)
→ the relevant specification and implementation plan.

This file is not optional guidance. It defines the workflow every contributor and AI agent must
follow when creating, writing, or implementing a spec.

---

## 1. Architecture-First Rule

Before creating, writing, or implementing any specification:

1. Read `docs/prettycash-backend-architecture/ARCHITECTURE.md` in full.
2. Read the relevant existing spec/plan and identify whether it is current, approved, or superseded.
3. Add an **Architecture alignment** section to the new spec. It must state:
   - Which layers/components the change touches.
   - Which new dependencies, queues, tables, providers, or boundaries it introduces.
   - What changes for the API contract, data model, configuration, and deployment.
   - What is current behavior versus target behavior.
4. If the spec introduces a new component, dependency, queue, table, provider, or layer boundary,
   update `ARCHITECTURE.md` before implementation. Do not implement first and document later.
5. Only then write the implementation plan and code.

If a spec conflicts with `ARCHITECTURE.md`, stop and resolve the conflict in the architecture
document first. Do not silently diverge.

---

## 2. Clean Code and Separation Rules

The backend is layered. Keep each layer focused and keep dependency direction one-way.

| Layer | Directory | Allowed | Not allowed |
|---|---|---|---|
| HTTP | `app/api/` | Routes, auth, HTTP mapping, status codes | Provider SDKs, Redis queries, Supabase queries, business logic |
| Core | `app/core/` | Settings, error types, logging setup | Business rules, HTTP routes, provider calls |
| Services | `app/services/` | Image processing, prompts/schemas, provider clients, normalization, rate-limit logic with injected clients | FastAPI, creating Redis/Supabase clients, queue loops |
| Queue | `app/queue/` | Queue protocols and implementations | Business rules, provider calls, persistence |
| Store | `app/store/` | JobStore protocol and implementation | Business rules, HTTP, provider calls |
| Workers | `app/workers/` | Dequeue loops, status transitions, orchestration | HTTP handlers, request-level provider construction |

Rules:

1. Never import `app/api/` or `app/workers/` from a service, queue, or store.
2. Services receive collaborators through constructors. They do not read environment variables,
   create Redis clients, or create Supabase clients.
3. The API reads dependencies from `request.app.state`. It never constructs provider clients.
4. Workers construct provider clients and stores in `main()`, then pass them into testable
   functions.
5. Provider SDKs (LiteLLM included) belong only in `app/services/`.
6. Shared request/response models belong in a schema module, not in a provider client.
7. Configuration is loaded only through `app/core/config.py`. No `os.getenv()` elsewhere.
8. Prefer small, focused modules with one responsibility. Do not create god modules.
9. Use type hints. Keep functions and classes small enough to test in isolation.
10. Follow existing patterns before introducing a new abstraction. Do not add a framework or
    dependency unless the approved spec requires it.
11. Keep external provider calls behind the existing client interfaces:
    - `GeminiClient.analyze(...)`
    - `JevClient.classify(...)`
    Changing the provider implementation must not require changing workers or the receipt analyzer.
12. Preserve documented failure semantics. The classifier fail-open path and the Gemini
    `INTERNAL` error mapping must not change without a spec.

---

## 3. Architecture-Breaking Changes

A change is architecture-breaking if it adds or changes any of:

- A layer or directory responsibility.
- A runtime service or container.
- A queue name or message shape.
- A database table/column/status.
- A provider/SDK dependency.
- The API contract or job status contract.
- The direction of a dependency between layers.

Architecture-breaking changes require:

1. A spec with an **Architecture alignment** section.
2. An update to `ARCHITECTURE.md` before or with the implementation.
3. A change-log entry in `ARCHITECTURE.md`.
4. Tests at the affected layers.

Do not treat a new queue, status, or provider as an implementation detail.

---

## 4. Testing and Verification

- Test at the layer you changed.
- API tests use `httpx.AsyncClient` with `ASGITransport`; no real Redis/Supabase/providers.
- Worker tests use fake queues, stores, and services.
- Provider clients use injected fake callables; unit tests never call live models.
- Keep fakes aligned with the real interfaces.
- Run before claiming completion:

```bash
uv run pytest
uv run ruff check .
```

- Docker/Compose changes require `docker compose -f docker/compose.yaml config -q` and a rebuild.
- Manual live tests must be documented in the spec/plan and must not be represented as automated
  coverage.

---

## 5. Security Rules

- Never commit `.env` or real credentials.
- `.env.example` contains placeholders only.
- Never log API keys, image bytes, or raw provider response bodies.
- Provider errors returned to clients are generic (`INTERNAL`, `INVALID_IMAGE`, etc.).
- The Supabase service-role key is server-side only.
- Validate image type, size, and dimensions before sending data to a provider.
- Inbound endpoints require the documented Bearer credential and rate limit.

If a secret is found in the repository, stop, flag it, and rotate it. Do not copy it into new files
or documentation.

---

## 6. Documentation Rules

### Location

- `AGENT.md` lives at the repository root.
- Architecture: `docs/prettycash-backend-architecture/ARCHITECTURE.md`.
- Specs: `docs/specs/<NN-section>/`.
- Plans: `docs/plans/<NN-section>/`.
- Section folders use a two-digit ordinal starting at `01` so they sort cleanly. Specs and plans
  use the same ordinals. The current sections are:
  - `01-api`
  - `02-ai-providers`
  - `03-queues-and-workers`
- Do not create a folder for a section with no documents. Add the folder when the first document
  for that section is created, using the next ordinal.
- Renumbering a section folder is an architecture change: update the architecture map, both MOCs,
  and every path reference in the same change.
- Top-level maps of content: `docs/specs/SPECS.md` and `docs/plans/PLANS.md`.
- Section maps of content: `docs/specs/<NN-section>/<SECTION>.md` and
  `docs/plans/<NN-section>/<SECTION>-PLANS.md` (for example `API.md`, `AI-PROVIDERS.md`,
  `QUEUES-AND-WORKERS.md`).

### Obsidian compatibility

- Every spec, plan, and MOC starts with YAML frontmatter containing at least:
  `title`, `type` (`spec`, `plan`, or `moc`), `status`, `date`, `section`, and `tags`.
- Use `[[Wiki Links]]` for connections between notes, with aliases when useful
  (`[[note|Label]]`).
- Every spec/plan links to:
  - its architecture section,
  - its section MOC,
  - its plan/spec counterpart,
  - related sections.
- When adding or removing a document, update:
  - `docs/specs/SPECS.md` or `docs/plans/PLANS.md`,
  - the relevant section MOC(s),
  - the architecture spec/plan index.
- Keep note names unique. Avoid duplicate `INDEX.md` names; use section-specific MOC names.
- Do not create empty section folders.

### Status and architecture updates

- Use `status: approved`, `in-progress`, `implemented`, or `superseded`.
- Mark superseded documents clearly and link to the replacement.
- Every implementation must update `docs/prettycash-backend-architecture/ARCHITECTURE.md`:
  - Move approved changes into the current runtime.
  - Update diagrams, directory map, API contract, data model, config, deployment, and testing.
  - Update the spec/plan index.
  - Append to the architecture change log.
- Update `README.md` when user-facing setup, API behavior, or deployment changes.
- Do not leave contradictory documentation.

---

## 7. Definition of Done

A task is not complete until all applicable boxes are checked:

- [ ] `ARCHITECTURE.md` was read before the spec/plan was written.
- [ ] The spec contains an **Architecture alignment** section.
- [ ] The document is in the correct `docs/specs/<NN-section>/` or `docs/plans/<NN-section>/`
      folder.
- [ ] YAML frontmatter and Obsidian wiki-links are present.
- [ ] The relevant section MOC and `SPECS` / `PLANS` MOC are updated.
- [ ] No empty section folder was created.
- [ ] Layer boundaries and dependency direction are respected.
- [ ] No provider SDK leaked into API/workers/queue/store.
- [ ] No business logic leaked into queue/store/API.
- [ ] Configuration is read only through `app/core/config.py`.
- [ ] Tests cover the changed behavior at the correct layer.
- [ ] `uv run pytest` passes.
- [ ] `uv run ruff check .` passes.
- [ ] `ARCHITECTURE.md` is updated (current state, diagrams, contracts, index, change log).
- [ ] `README.md` is updated if user-facing behavior changed.
- [ ] No secrets, image bytes, or raw provider errors were added to code, logs, or docs.
- [ ] The spec/plan status is accurate (approved, in progress, implemented, or superseded).

---

## 8. Quick Reference

- Current runtime: `api`, `classifier`, `worker`, `redis`; Jev and Gemini via LiteLLM;
  `receipt:classify` and `receipt:queue`; `rejected` status.
- Receipt auto-categorization is implemented (backend verified live; frontend integrated). Fallback
  models are deferred.
- Read first: `docs/prettycash-backend-architecture/ARCHITECTURE.md`.
- Specs: `docs/specs/<NN-section>/` (MOC: [[SPECS]]).
- Plans: `docs/plans/<NN-section>/` (MOC: [[PLANS]]).
- Sections: [[API]], [[AI-PROVIDERS]], [[QUEUES-AND-WORKERS]].
- Update after implementation: `ARCHITECTURE.md` change log and current-state sections.
- Run: `uv run pytest`, `uv run ruff check .`.

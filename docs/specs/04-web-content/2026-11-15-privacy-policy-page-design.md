---
title: "Privacy Policy Page Served by the API"
type: spec
status: implemented
date: 2026-11-15
section: web-content
tags:
  - prettycash
  - spec
  - web-content
  - privacy
  - http
---

# PrettyCash Backend — Privacy Policy Page (Design)

**Date:** 2026-11-15
**Status:** Implemented 2026-11-16

---

## Related

- Architecture: [[ARCHITECTURE#8. API Contract|API Contract]], [[ARCHITECTURE#12. Deployment|Deployment]], [[ARCHITECTURE#17. Spec and Plan Index|Spec and Plan Index]]
- Section: [[WEB-CONTENT]]
- Plan: [[2026-11-16-privacy-policy-page|Privacy Policy Page implementation]]
- Receipt API contract: [[2026-09-13-prettycash-backend-receipt-analysis-design|Receipt Analysis Service]]

## Architecture Alignment

- **Layers touched:** HTTP (`app/api/`) and the app factory (`app/main.py`); one static asset under
  `app/static/`; API-layer tests.
- **New dependencies or boundaries:** none. No container, published port, queue, table, provider,
  environment variable, or layer responsibility is added.
- **API contract:** adds one public, unauthenticated `GET /privacy` that returns HTML. The
  `/api/v1/*` receipt and billing contracts do not change.
- **Deployment:** unchanged. The page ships inside the existing API image; no Compose, Dockerfile,
  or CI change is required.
- **Current vs target:** `GET /privacy` currently falls through to the JSON error handler (404);
  the target serves the privacy policy page.
- **Data/config:** no schema, queue, or configuration changes.
- **Docs:** this spec introduces section `04-web-content`; update `SPECS.md`, `ARCHITECTURE.md`
  (route table, index, change log), and `README.md` during implementation.

## Intent

The mobile app needs a publicly reachable privacy policy URL for app-store submission. The backend
already owns a public port, so serving the page at `GET /privacy` provides a stable URL
(`https://prettycash.app/privacy` publicly, or `localhost:8000/privacy` locally) with no new
container or port. Cloudflare Tunnel supplies the hostname and HTTPS.

## Goals

- Serve a self-contained HTML privacy policy at `GET /privacy`, without authentication.
- Keep the existing API reachable on the same origin at `https://prettycash.app/api/v1/*`; the
  `/api/v1` prefix and contract do not change.
- Return `text/html; charset=utf-8` and a short cache lifetime so wording corrections propagate.
- Render without JavaScript or external assets (no CDN fonts, scripts, or images), so the page works
  on restrictive networks and makes no third-party requests to visitors.
- Read cleanly on mobile and when printed/saved as PDF.
- Reuse the existing image and deployment pipeline; no new runtime service.

## Non-goals

- No nginx container, no new Compose service, and no use of port `8001`.
- No TLS termination in the backend; the existing domain proxy owns HTTPS.
- No CMS or admin editing; wording changes are commits.
- No analytics, cookies, or consent banner on the page.
- No changes to the `/api/v1` contract, auth, or rate limiting.

## Approaches considered

1. **Nginx container on `8001`** — clean separation and static hosting, but adds a second exposed
   port and requires the domain proxy to route by path or subdomain. Rejected: the extra moving
   parts buy nothing for one static page.
2. **Nginx in front of the API on `8000`** — single public port, but nginx becomes a dependency for
   every receipt call and requires upload-size, timeout, and forwarded-header configuration. A
   proxy mistake would break scanning, not just the page. Rejected: blast radius too large.
3. **Serve the page from FastAPI (chosen)** — one route in the existing app, same origin and port as
   the API, zero new containers or proxy rules. Trade-off accepted by the owner: the page's
   availability follows the API, and editing wording redeploys the API image (the existing deploy
   already rebuilds and restarts).

## Design

- Add `app/api/pages.py` with a module-level `APIRouter` (no prefix).
- `GET /privacy` returns `FileResponse(app/static/privacy.html, media_type="text/html")` with
  `Cache-Control: public, max-age=300`, and `include_in_schema=False` because it is not an API
  endpoint.
- No auth dependency and no rate limit. Auth is applied per route in this codebase, so a new route
  is public by default.
- Resolve the file path from `Path(__file__)`, not the process working directory, so tests and
  uvicorn work from any directory.
- Include the pages router in `create_app` alongside `api_router`.
- `app/static/privacy.html` is one self-contained document: inline `<style>`, semantic headings,
  viewport meta tag, visible "Last updated" date, and print styles. No external requests.
- The Docker image already runs `COPY app ./app`, so the asset is included without a Dockerfile
  change.
- Unknown paths and the existing JSON error envelope are unchanged.

### Edge routing (Cloudflare Tunnel, operational)

The backend does not know about hostnames. Public routing is Cloudflare's job. The owner requires
`https://prettycash.app/privacy` with no subdomain, and wants the API on the same origin at
`https://prettycash.app/api/v1/*`. The apex routes to the existing API service; FastAPI serves both
paths from the same container. No path rules are needed in Cloudflare.

```yaml
ingress:
  - hostname: prettycash.app
    service: http://localhost:8000
  - hostname: api.prettycash.app   # keep during the mobile-app base-URL migration
    service: http://localhost:8000
  - service: http_status:404
```

In the Zero Trust dashboard: add a Public Hostname with an empty subdomain, domain
`prettycash.app`, **no path**, and service `HTTP` → `localhost:8000`. The dashboard creates the
proxied apex DNS record pointing at the tunnel. Keep the existing `api.prettycash.app` hostname until
the mobile app has shipped a base URL of `https://prettycash.app`; removing it first breaks every
installed version that still calls the subdomain. Once old versions are retired, the `api.` hostname
can be deleted.

The API keeps its `/api/v1` prefix. `https://prettycash.app/api` itself is not given a new meaning;
clients call `https://prettycash.app/api/v1/...`.

Suggested page sections (owner supplies the final wording and may change the structure): who we are;
information we collect; how we use it; third-party processors; retention; security; children's
privacy; changes to the policy; contact.

## Content ownership

- The owner supplies the final policy text, effective date, and contact address.
- Do not merge placeholder copy to `main`: deployment is automatic on push. The route and page ship
  only with publishable copy.

## Testing

- New `tests/test_api_privacy.py`, using the existing `client` fixture:
  - `GET /privacy` with no credentials returns `200`, `text/html; charset=utf-8`, and a body that
    contains the expected title and heading.
  - The response includes `Cache-Control: public, max-age=300`.
  - `/privacy` is absent from `/openapi.json` paths.
- `uv run pytest` and `uv run ruff check .` pass.
- Manual verification: `curl -i localhost:8000/privacy`; browser check at phone width; after
  deployment, load `https://prettycash.app/privacy` and confirm
  `https://prettycash.app/api/v1/health` still returns `{"status":"ok"}`.

## Risks and open items

- Page availability is coupled to the API process (accepted).
- The apex hostname must resolve to the Cloudflare Tunnel. If the apex currently points at another
  origin, that record must be replaced by the tunnel public hostname. This is an operational check,
  not a code change.
- Removing `api.prettycash.app` before the mobile app ships the new base URL breaks installed
  clients. Keep both hostnames on the tunnel during the transition.
- The five-minute cache can delay wording corrections; lower `max-age` if needed.
- Owner must provide the final text, effective date, and contact email before the page is deployed.

---
title: API Specs
type: moc
status: active
section: api
tags:
  - prettycash
  - specs
  - api
  - moc
---

# API Specs

Architecture: [[ARCHITECTURE#8. API Contract|API Contract]] ·
Layers: [[ARCHITECTURE#5. Layer Responsibilities and Dependency Rules|Layer Responsibilities]]

This section owns the HTTP contract, inbound authentication, image validation, and the original
receipt-analysis endpoint contract.

## Specs

- [[2026-09-13-prettycash-backend-receipt-analysis-design|Receipt Analysis Service]] —
  `POST /api/v1/analyze-receipt`, polling, auth, image processing, and the original Gemini
  extraction contract. Implemented.
- [[2026-10-22-receipt-classification-design|Receipt Pre-Classification with Jev]] — adds the
  `rejected` terminal status and changes the API's enqueue target. Implemented.
- [[2026-10-24-receipt-analysis-idempotency-design|Receipt Analysis Idempotency]] — adds the
  optional `Idempotency-Key` header, `receipt_jobs.request_id`, and duplicate-job reuse. Implemented.

## Plans

- [[2026-09-13-prettycash-backend-receipt-analysis|Receipt Analysis implementation]] — implemented.
- [[2026-10-22-receipt-classification|Classifier implementation]] — implemented.
- [[2026-10-24-receipt-analysis-idempotency|Receipt Analysis Idempotency implementation]] —
  implemented.

## Related sections

- [[AI-PROVIDERS]]
- [[QUEUES-AND-WORKERS]]
- [[ARCHITECTURE#9. Data Storage|Data Storage]]
- [[API-PLANS]]

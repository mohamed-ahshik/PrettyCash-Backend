---
title: Queue and Worker Specs
type: moc
status: active
section: queues-and-workers
tags:
  - prettycash
  - specs
  - queue
  - workers
  - redis
  - moc
---

# Queue and Worker Specs

Architecture: [[ARCHITECTURE#7. Request and Data Flow|Request and Data Flow]] ·
Storage: [[ARCHITECTURE#9. Data Storage|Data Storage]] ·
Layers: [[ARCHITECTURE#5. Layer Responsibilities and Dependency Rules|Layer Responsibilities]]

This section owns Redis queue topology, worker lifecycles, job state transitions, and the Supabase
job store changes that accompany new workers.

## Specs

- [[2026-09-13-prettycash-backend-redis-queue-design|Redis Queue and Supabase Job Store]] —
  asynchronous jobs, `receipt:queue`, the worker, rate limiting, and `receipt_jobs`. Implemented.
- [[2026-10-22-receipt-classification-design|Receipt Pre-Classification with Jev]] — adds the
  `receipt:classify` queue, classifier worker, `rejected` status, and classifier columns.
  Implemented.

## Plans

- [[2026-09-13-prettycash-backend-redis-queue|Redis Queue implementation]] — implemented.
- [[2026-10-22-receipt-classification|Classifier implementation]] — implemented.

## Related sections

- [[API]]
- [[AI-PROVIDERS]]
- [[QUEUES-AND-WORKERS-PLANS]]

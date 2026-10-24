---
title: Plans
type: moc
status: active
tags:
  - prettycash
  - plans
  - moc
---

# Plans

Architecture: [[ARCHITECTURE]] · Agent rules: [[AGENT]] · Specs: [[SPECS]]

Plans are grouped by the same architecture section as the spec they implement. Folders use the
same `01-`, `02-`, `03-` order as specs. Execute plans in the order listed in [[ARCHITECTURE]].

## Sections

- `01-api/` — [[API-PLANS]] — receipt-analysis API implementation.
- `02-ai-providers/` — [[AI-PROVIDERS-PLANS]] — classifier, LiteLLM, and auto-categorization
  implementations.
- `03-queues-and-workers/` — [[QUEUES-AND-WORKERS-PLANS]] — Redis queue and classifier-worker
  implementation.

## Related

- [[SPECS]]
- [[ARCHITECTURE]]
- [[AGENT]]

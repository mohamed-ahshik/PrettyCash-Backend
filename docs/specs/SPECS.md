---
title: Specs
type: moc
status: active
tags:
  - prettycash
  - specs
  - moc
---

# Specs

Architecture: [[ARCHITECTURE]] · Agent rules: [[AGENT]] · Plans: [[PLANS]]

Specs are grouped by the architecture section they primarily change. Folders are numbered from
`01` so they sort in a stable order. Cross-cutting specs link to the other sections from their own
note and from the section MOC below.

## Sections

- `01-api/` — [[API]] — HTTP contract, inbound auth, image validation, initial receipt analysis.
- `02-ai-providers/` — [[AI-PROVIDERS]] — Gemini extraction, Jev classification, LiteLLM migration,
  and auto-categorization.
- `03-queues-and-workers/` — [[QUEUES-AND-WORKERS]] — Redis queues, worker topology, job lifecycle,
  and storage changes.

## Related

- [[PLANS]]
- [[ARCHITECTURE]]
- [[AGENT]]

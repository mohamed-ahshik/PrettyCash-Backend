---
title: AI Provider Specs
type: moc
status: active
section: ai-providers
tags:
  - prettycash
  - specs
  - ai
  - gemini
  - jev
  - litellm
  - moc
---

# AI Provider Specs

Architecture: [[ARCHITECTURE#10. AI Provider Integrations|AI Provider Integrations]] ·
Layers: [[ARCHITECTURE#5. Layer Responsibilities and Dependency Rules|Layer Responsibilities]]

This section owns Gemini extraction, Jev receipt classification, prompts, response schemas, and the
LiteLLM provider abstraction.

## Specs

- [[2026-10-22-receipt-classification-design|Receipt Pre-Classification with Jev]] — uses Jev to
  reject non-receipts before Gemini; adds classifier score persistence and a dedicated worker.
  Implemented and verified end-to-end.
- [[2026-10-22-litellm-migration-design|Gemini and Jev via LiteLLM]] — replaces the direct `httpx`
  provider clients with LiteLLM, keeping the same models and keys. Implemented and verified
  against both providers.
- [[2026-10-24-auto-categorization-design|Auto-Categorize Receipts with Gemini]] — sends the
  user’s expense categories with the scan, returns a category key + confidence, and maps it to the
  real category ID. Backend verified live; frontend integrated; on-device checks pending.
- [[2026-09-13-prettycash-backend-receipt-analysis-design|Receipt Analysis Service]] — original
  Gemini extraction contract. Implemented; its Gemini client section is superseded by the LiteLLM
  design.

## Plans

- [[2026-10-22-litellm-migration|LiteLLM migration implementation]] — implemented; migrates Gemini
  and Jev to LiteLLM.
- [[2026-10-22-receipt-classification|Classifier implementation]] — implemented; its Task 4 was
  superseded by the LiteLLM plan's Jev task.
- [[2026-09-13-prettycash-backend-receipt-analysis|Receipt Analysis implementation]] — implemented.
- [[2026-10-24-auto-categorization|Auto-categorization implementation]] — implemented; backend
  verified live and frontend integrated.

## Related sections

- [[API]]
- [[QUEUES-AND-WORKERS]]
- [[ARCHITECTURE#9. Data Storage|Data Storage]]
- [[AI-PROVIDERS-PLANS]]

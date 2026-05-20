---
type: research-artifact
task_id: 20260509195830-quality-preserv-p0-research-subscription-quota-signals
title: "Observable Subscription & Quota Signals per Platform"
authority_case: CASE-CAPACITY-ROUTING-001
created_at: 2026-05-20T18:15:00Z
vault_artifact: 30-areas/hapax/2026-05-20-observable-subscription-quota-signals-research.md
---

# Observable Subscription & Quota Signals per Platform

Research artifact for capacity routing. Full structured analysis at the vault
path above. Summary findings:

- **Claude Code:** Best observability. `anthropic-ratelimit-*` headers give
  per-request remaining tokens/requests. Monthly spend cap is NOT exposed.
- **Codex/OpenAI:** Good observability. `x-ratelimit-*` headers per request.
  Organization usage API (~5 min lag) for spend tracking.
- **Gemini CLI:** Weakest observability. No remaining-quota headers. Only
  signal is HTTP 429 / `RESOURCE_EXHAUSTED` when the wall is hit.

No platform exposes subscription tier via API — must be operator-configured.
No signal requires paid API spend to probe.

Recommendations: LiteLLM header passthrough, universal 429 circuit breaker,
pre-exhaustion alerting at 10% remaining for Claude/Codex, Gemini pessimism.

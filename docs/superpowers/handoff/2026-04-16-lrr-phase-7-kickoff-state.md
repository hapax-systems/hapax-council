---
title: LRR Phase 7 — kickoff state (pre-operator-signoff)
date: 2026-04-16
epic: lrr
phase: 7
status: kickoff-ready-pending-gov
author: beta (LRR single-session takeover)
---

# LRR Phase 7 — kickoff state

## Preconditions

Phase 7 plan (`docs/superpowers/plans/2026-04-15-lrr-phase-7-persona-spec-plan.md` §0) requires:

- [x] LRR UP-0 + UP-1 closed
- [x] LRR UP-7 substrate swap closed — **satisfied 2026-04-16** via scenario 1+2 ratification (OLMo-3 parallel backend + Qwen baseline); see `2026-04-16-lrr-phase-5-complete.md`
- [ ] LRR UP-8 governance finalization closed — **NOT yet.** Phase 6 spec + plan are on main (cherry-picked 2026-04-16) but the joint `hapax-constitution` PR has not been authored.
- [ ] Operator availability for review iterations

## Recommendation

**Do not open Phase 7 yet.** The substrate precondition is satisfied but UP-8 (Phase 6 governance) is not. The persona spec's constitutional grounding (`interpersonal_transparency` tightening, `it-irreversible-broadcast` recognition) depends on Phase 6 amendments merging first; writing the persona spec against a constitution that's about to change would waste review cycles.

**When to open:** after the joint `hapax-constitution` PR (bundling Phase 6's 4 implications + HSEA Phase 0's 1 precedent + 1 implication per §0.5.1 of Phase 6 spec) merges.

## Once open — execution path

Plan items 1-7 are a clean TDD chain:

1. Pydantic schema (`shared/persona_schema.py`) + tests — ~200 LOC
2. Draft persona YAML (`axioms/persona/hapax-livestream.yaml`) — verbatim from epic spec §Phase 7 item 1
3. Persona loader (`shared/persona_loader.py`) + frozen-file protocol — ~150 LOC
4. Integration with LLM call path (system-prompt injection) — ~100 LOC
5. Stream-mode axis interaction (from Phase 6) — ~80 LOC
6. VOLATILE-band injection → test
7. Sign-off commit once operator ratifies the draft

Estimated effort: ~800 LOC + 1-2 operator review iterations.

## What can happen in parallel

While Phase 6 governance PR is pending operator review:

- **Phase 8 scaffolding:** objectives data structure is substrate-agnostic AND persona-agnostic. Can begin now.
- **Phase 9 prep hooks:** see `2026-04-15-daimonion-code-narration-prep.md` — integration inventory is ready.
- **Phase 10 observability slicing:** per-condition Prometheus labels + stimmung dashboards can begin; they are not persona-dependent.

— beta, 2026-04-16

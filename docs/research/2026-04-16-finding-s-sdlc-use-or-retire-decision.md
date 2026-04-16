---
title: FINDING-S — SDLC pipeline use-or-retire decision
date: 2026-04-16
epic: lrr
phase: 10
decision: retire
author: beta (LRR single-session takeover)
---

# FINDING-S — SDLC pipeline use-or-retire decision

## Decision

**Retire.**

## Context

The Phase 6 SDLC pipeline audit (`docs/research/2026-04-13/round5-unblock-and-gaps/phase-6-sdlc-pipeline-audit.md`) established that `scripts/sdlc_{triage,plan,review,axiom_judge}.py` + their workflows have **never produced a non-dry-run event in production**. 324 dry runs across 3+ weeks, zero real invocations. Alpha ships fixes manually; beta ships fixes manually; the operator's workflow bypasses the pipeline entirely.

LRR epic spec §Phase 10 called for a "use-or-retire" decision with default-ship date 2026-04-22. This doc records the decision.

## Reasoning

### Why retire, not use

1. **Actual SDLC flow is already serving the operator's needs.** Manual alpha/beta/delta/epsilon branch-and-PR discipline, hook-enforced branch hygiene, existing lint/test/typecheck/security/freeze-check CI — all of this covers the operator's SDLC needs. The LLM pipeline would duplicate a flow that is already working.
2. **Pipeline output would need human review anyway.** The audit flagged adversarial-review rounds + axiom-gate as the pipeline's value-adds. In practice, alpha/beta's manual authoring already incorporates axiom context before code is written — the axiom gate is applied at authoring time, not after. Post-hoc LLM review would add latency without catching more.
3. **The single-operator axiom (`single_user`, weight 100) disfavors automation that introduces new review loops.** The pipeline was designed for a multi-author codebase where LLM triage + plan substitutes for a human code-review queue. Hapax does not have a queue.
4. **Freed constraints.** Retiring removes: (a) a broken workflow path that triggers on every PR but never advances, (b) 4 Python scripts + their test suite, (c) `.github/workflows/sdlc-*.yml` files, (d) `profiles/sdlc-events.jsonl` cold store. Reduces surface area without reducing capability.

### Why not delete vs retire

- **Retire** means: stop triggering, document the decision, leave scripts in place as reference code. Future operator or external contributor could re-enable if multi-author patterns emerge.
- **Delete** would require cross-checking `CLAUDE.md § SDLC Pipeline` references, hooks that may import scripts, LiteLLM callsites, etc. Too much surface for a decision that's primarily about "stop triggering the workflow."

## Actions

1. **Disable the trigger surfaces.** Remove `.github/workflows/sdlc-triage.yml` `on:` hook for `issues: [labeled]`. Without the trigger, the pipeline cannot fire.
2. **Remove the `agent-eligible` label from active circulation.** If the label exists, archive it in GitHub settings.
3. **Update `CLAUDE.md § SDLC Pipeline`** to record the retirement + reason, pointing future readers at this decision doc.
4. **Keep scripts + workflow YAML in the repo** as reference artifacts. A future reactivation is a 1-line edit to the trigger condition.

## Related

- Audit: `docs/research/2026-04-13/round5-unblock-and-gaps/phase-6-sdlc-pipeline-audit.md`
- Epic spec item: `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` § Phase 10
- Prior decision record: `docs/research/2026-04-15-finding-s-sdlc-decision-record.md` (framed the decision, this doc closes it)

— beta, 2026-04-16

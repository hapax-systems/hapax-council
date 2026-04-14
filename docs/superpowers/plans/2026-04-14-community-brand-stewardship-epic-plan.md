# Community + Brand Stewardship — Sister Epic Plan

**Epic:** Community + Brand Stewardship
**Owner:** Oudepode (operator)
**Design:** `docs/superpowers/specs/2026-04-14-community-brand-stewardship-epic-design.md`
**Beta working draft:** `~/.cache/hapax/relay/context/2026-04-14-sister-epic-community-brand-stewardship.md`

## Alpha-owned PR sequence (target ~1-2 PRs)

The sister epic is operator-owned. Alpha's PR scope is limited to scaffolding + coordination. The PR sequence below covers **only** the alpha-autonomous slice.

### PR #1 — Foundation + scaffolding (this PR)

**Files:**
- `docs/superpowers/specs/2026-04-14-community-brand-stewardship-epic-design.md` (design doc)
- `docs/superpowers/plans/2026-04-14-community-brand-stewardship-epic-plan.md` (this file)
- `config/sister-epic/discord-channels.yaml` — channel structure template, operator fills names + descriptions
- `config/sister-epic/patreon-tiers.yaml` — tier structure template per Bundle 7 §8.3, operator fills prices + perks
- `config/sister-epic/visual-signature.yaml` — visual identity slot schema, operator fills values
- `tests/test_sister_epic_config.py` — schema validation tests (YAML parses, required keys present, enum values in allowed sets)

**Goal:** get the design + plan + config scaffolding into git so the operator can start filling values. No operator value-judgments are required for this PR to land.

### PR #2 — LRR ↔ sister epic coupling hook

**Files:**
- `scripts/sister-epic-phase-s2-trigger.py` — dry-run CLI that reads `~/.cache/hapax/relay/lrr-state.yaml`, checks if LRR Phase 5 is closed, and prints the Phase S2 launch checklist + operator action items. Does not actually do anything; it's a coordination helper.
- `tests/test_sister_epic_phase_s2_trigger.py`

**Gate:** this PR is deferred until LRR Phase 5 is at least in-progress. Operator decides when to open it. Until then, no alpha work on this epic beyond PR #1.

## Everything else is operator-owned + beta-drafted

Per the epic design §Alpha's role:

- Phase S0 (brand identity, manifesto, taglines) → operator + beta drafting
- Phase S1 (inner ring, private streams) → operator
- Phase S2 (public launch tentpole) → operator, triggered by LRR Phase 5 close
- Phase S3 (derivative artifacts) → operator + Hapax reflection daemon (from LRR Phase 8)
- Phase S4 (community structure) → operator + beta drafting
- Phase S5 (monetization) → operator
- Phase S6 (cross-pollination) → operator
- Phase S7 (tentpole ops) → operator + beta drafting
- Phase S8 (year-2 planning) → operator

Beta ships drafts to `~/.cache/hapax/relay/context/` on request. Operator reviews + commits.

## Retirement note

This epic has a naturally small alpha scope. After PR #1 lands, the alpha session covering this epic should retire cleanly and hand off to the operator. The next alpha session that opens any of the LRR-coupled phases (e.g., Phase 5 handoff to S2) picks up from the handoff doc.

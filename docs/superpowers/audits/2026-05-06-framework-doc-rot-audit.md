# Framework Doc-Rot Audit

**Status:** current_authority
**Checked at:** 2026-05-06
**Scope:** segment prep framework, prompt-facing prep doctrine, anti-personification, layout responsibility, and prep-resumption gates.

## Classification Rules

Docs in this area are not authority by default. Use this order:

1. Current code and passing tests.
2. Current schemas/config.
3. Current authority docs with checked dates.
4. Revalidated historical docs.
5. Historical docs without revalidation.
6. Chat context: not authority.

Status labels:

- `current_authority`: safe to follow for current implementation.
- `current_with_code_check`: safe only after checking named code/test surfaces.
- `historical_context`: useful background, not a decision source.
- `superseded`: preserved for provenance, do not follow for new work.
- `stale_risk`: contains facts likely to have changed.
- `stale_do_not_use`: known contradiction with current doctrine.

## Current Authority

| Path | Status | Notes |
|---|---|---|
| `docs/superpowers/specs/2026-05-06-nonanthropomorphic-segment-prep-framework-stack.md` | current_authority | Canonical framework decision. |
| `docs/superpowers/framework-stack-matrix.md` | current_authority | Grep-friendly ownership matrix. |
| `docs/superpowers/specs/2026-05-06-one-segment-iteration-review-protocol.md` | current_authority | Canary and continued pool-release protocol. |
| `shared/resident_command_r.py` | current_authority | Command-R-only residency contract. |
| `shared/knowledge_recruitment_pressure.py` | current_authority | Domain-neutral source recruitment pressure. |
| `agents/hapax_daimonion/segment_layout_contract.py` | current_authority | Prepared layout proposal-only contract. |
| `shared/segment_iteration_review.py` | current_authority | Deterministic canary review gate. |
| `shared/segment_quality_actionability.py` | current_authority | Current heuristic quality/actionability/layout rubric after framework cleanup. |

## Current With Code Check

| Path | Status | Required check |
|---|---|---|
| `agents/programme_manager/prompts/programme_plan.md` | current_with_code_check | Must stay aligned with framework doc and planner schema. |
| `agents/hapax_daimonion/daily_segment_prep.py` | current_with_code_check | Must preserve Command-R residency, source/action/layout gates, and non-anthropomorphic prompt text. |
| `agents/hapax_daimonion/autonomous_narrative/segment_prompts.py` | current_with_code_check | Must not reintroduce human-host personality protocol during live segment composition. |
| `config/compositor-layouts/segment-*.json` | current_with_code_check | Layout assets exist, but success still requires runtime readback. |

## Historical Or Superseded

| Path | Status | Reason |
|---|---|---|
| `agents/hapax_daimonion/proofs/THEORETICAL-FOUNDATIONS.md` | historical_context | Valuable grounding literature review, but it predates the 2026-05-06 segment-prep framework stack and does not by itself govern content prep. |
| `docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md` | current_with_code_check | Linter design is still useful, but source counts, rollout stage language, and "2 live violations" are stale-risk. Follow current linter code/tests for enforcement status. |
| `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md` | historical_context | Preserve for provenance; do not use to relax the 2026-05-06 anti-anthropomorphic prep constraints. |
| `docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md` | stale_risk | Any "volitional" language must be rechecked against anti-personification before reuse. |
| `docs/superpowers/specs/2026-04-18-homage-framework-design.md` | historical_context | Visual/conceptual background, not segment-prep authority. |
| `docs/research/2026-05-06-segment-layout-control-loop-audit.md` | historical_context | Useful audit input; final authority now lives in framework and layout contract docs. |

## Known Rot Patterns To Keep Quarantined

- Source counts without retrieved/checked dates.
- Model names, provider routes, or "loaded model" assumptions not checked against current service state.
- "Hapax's voice", "Hapax has positions", "your show", "your opinions", "your affect", "operator-flavoured", or "operator-coloured" prompt language.
- Default/static layout described as successful in responsible live contexts.
- Camera presence, spoken-only fallback, or layout gauge success described as layout responsibility success.
- Theory names appearing in prompt-facing instructions where operational questions would be clearer.
- Old examples becoming anchor topics. Examples are non-selectable unless a current source packet justifies reusing the topic.

## Prep-Resumption Receipt

Before prep resumes:

- The current framework doc and matrix must exist.
- Active prep prompts must be checked for anthropomorphic language and layout laundering.
- Canary review remains blocking for continued pool release.
- Team critique receipts must bind to the canary artifact, programme id, and iteration id.
- Command-R residency must pass before and after prep.

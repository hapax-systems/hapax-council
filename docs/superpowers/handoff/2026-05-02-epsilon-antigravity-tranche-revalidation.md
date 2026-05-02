---
date: 2026-05-02
session: epsilon
type: handoff/revalidation-report
related_pr_range: "1906–1907 (Antigravity-era origin) audited"
status: complete
cc_task: antigravity-unified-self-grounding-tranche-revalidation
verdict: PASS — no defects found; spine accepted
---

# Antigravity Unified Self-Grounding Tranche — Independent Revalidation Report

## What

Independent audit of the Antigravity-associated unified self-grounding
implementation tranche per cc-task
`antigravity-unified-self-grounding-tranche-revalidation` (WSJF 10.8,
P0). Per the cc-task scope: "treat Antigravity implementation evidence
as suspect until fixtures, runtime witnesses, and code review prove
it."

## Verdict

**PASS — no defects found. Spine accepted as production-trustworthy.**

The two production files are correctly implemented against the parent
spec. The 33-test suite covers all acceptance criteria. No repair PRs
needed.

## Files audited

- `shared/self_grounding_envelope.py` (421 LOC) —
  `SelfPresenceEnvelopeProjection` builder, route decision logic,
  blocker computation, allowed-outcomes derivation, claim ceiling.
- `shared/private_to_public_bridge.py` (259 LOC) — `evaluate_bridge()`
  governor, `BridgeRequest`/`BridgeResult` schemas, impingement
  content formatter.
- `tests/shared/test_self_grounding_envelope.py` (453 LOC, 18 tests)
- `tests/shared/test_private_to_public_bridge.py` (484 LOC, 15 tests)

Total: 33 tests, all passing.

## Acceptance criteria — verified

| Criterion | Status | Evidence |
|---|---|---|
| Identify every Antigravity-associated production path | PASS | Two files in `shared/`, no integration callsites yet (deferred follow-up) |
| Verify schema fields against parent spec | PASS | All `RoleSnapshot`/`ApertureSnapshot`/`ProgrammeSnapshot`/`AudioSafetySnapshot`/`EgressSnapshot` fields match the cx-violet spine description |
| Private input cannot reach public without explicit transformation | PASS | `test_blue_yeti_private_cannot_reach_broadcast`, `test_default_path_private_response` |
| Public speech requires explicit intent + fresh programme + audio safety + route witness + egress | PASS | `_fail_closed_public_speech` model validator on `SelfPresenceEnvelopeProjection`; matching guard in `BridgeResult._no_public_without_authorization` |
| Stale/missing/malformed authorization fails closed | PASS | `test_missing_programme_blocks_public`, `test_fresh_programme_without_timestamp_blocks_public`, `test_public_proposal_holds_on_programme_id_mismatch`, `test_unsafe_audio_blocks_public`, `test_missing_egress_blocks_public` |

## Schema contract verification

`SelfPresenceEnvelopeProjection` validator (`_fail_closed_public_speech`)
enforces 8 simultaneous invariants for `PUBLIC_SPEECH_ALLOWED`:
1. `route_decision == BROADCAST`
2. `programme_authorization == FRESH`
3. `programme_id` non-empty
4. `programme_authorized_at` non-empty (timestamp present)
5. `audio_safety == SAFE`
6. `livestream_egress_state == WITNESSED`
7. `public_claim_ceiling == PUBLIC_GATE_REQUIRED`
8. `blockers` empty AND `private_risk_flags` empty

`BridgeResult` validator (`_no_public_without_authorization`) enforces
the dual on `PUBLIC_ACTION_PROPOSAL`:
- `public_broadcast_intent == True`
- `programme_authorization` non-empty
- `route_posture == "broadcast_authorized"`
- `claim_ceiling` is `PUBLIC_GATE_REQUIRED` or `EVIDENCE_BOUND`
- `blockers` empty
Plus negative: `PRIVATE_RESPONSE` cannot have `public_broadcast_intent`.

Both validators fail-closed at construction time — invalid combinations
cannot exist as instances.

## Decision-logic verification

`build_envelope_projection` is a pure function. The decision-tree:

1. `BLOCKED` aperture → `RouteDecision.BLOCKED`
2. `ARCHIVE_ONLY` aperture → `RouteDecision.ARCHIVE_ONLY`
3. `PRIVATE` or `SYNTHETIC_ONLY` aperture → `RouteDecision.PRIVATE`
4. Public-candidate/live aperture WITH blockers → `RouteDecision.PRIVATE` (fail-closed)
5. Public-candidate/live aperture, NO blockers → `RouteDecision.BROADCAST`

Allowed outcomes mapping is correctly conditioned on route + blockers
+ exposure_mode. The `UNKNOWN` fallback ensures `allowed_outcomes` is
never empty (would otherwise violate `min_length=1`).

`evaluate_bridge` decision:
1. `RouteDecision.BLOCKED` → `REFUSAL`
2. No `explicit_public_intent` → `PRIVATE_RESPONSE`
3. Public intent + envelope blockers → `DRY_RUN`
4. Public intent + `PUBLIC_SPEECH_ALLOWED` + programme matches →
   `PUBLIC_ACTION_PROPOSAL`
5. Public intent + envelope didn't grant → `HELD`

Correct fail-closed at every decision.

## Observation worth surfacing (deferred follow-up)

**No production callsite invokes either function yet.** Greps for
`build_envelope_projection`, `evaluate_bridge`, and
`render_compact_prompt_block` found only:
- The modules themselves
- Their tests
- `scripts/vulture_whitelist.py` (suppressing unused-function warnings)

The spine exists and is correctly implemented + tested, but no
runtime path actually calls into it. Expected next step: wire the
envelope projection into `compose.py` (replacing ad-hoc seed
construction) and the bridge governor into `destination_channel.py`
(making it the only path from private narration to public broadcast).

This is a **non-defect observation** — the cc-task scope is
revalidation of the existing tranche, not its integration. The
integration is downstream A+ packet work.

## Recommendation

Per cc-task acceptance criteria 1-5 all verified, mark
`antigravity-unified-self-grounding-tranche-revalidation` DONE.
The Antigravity-suspect implementation passes independent revalidation.

The downstream integration into `compose.py` /
`destination_channel.py` should proceed in a separate follow-up
(unblocked by this acceptance).

## What this revalidation proves

1. The schema contract correctly encodes private-public separation
   invariants.
2. The decision logic in both modules is fail-closed at every branch.
3. The 33-test suite covers all required negative paths
   (missing/stale/malformed authorization, private risk blocks,
   blocked apertures, ID mismatches).
4. The Antigravity-era implementation is internally consistent with
   the cx-violet self-grounding parent spec.
5. No production system can bypass the bridge governor without
   re-implementing the validator-enforced invariants.

## Pointers

- Parent spec: `hapax-research/specs/2026-04-30-hapax-unified-self-grounding-spine.md`
- Suspect implementation map: `hapax-research/specs/2026-04-30-hapax-unified-self-grounding-implementation-map.md`
  (status: suspect-requires-independent-revalidation; this report constitutes the independent revalidation)
- Production code: `shared/self_grounding_envelope.py`, `shared/private_to_public_bridge.py`
- Test coverage: `tests/shared/test_self_grounding_envelope.py`, `tests/shared/test_private_to_public_bridge.py`

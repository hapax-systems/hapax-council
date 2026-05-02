# Unified awareness envelope — independent revalidation 2026-05-02

**cc-task:** `unified-awareness-route-claim-envelope` (WSJF 10.6, p0)
**Status before this revalidation:** `blocked` ("PR #1906 implementation
evidence is Antigravity-associated and must be treated as suspect until
independently revalidated")
**Verdict:** **PASS** — module + tests on current main (commit `75b343ed1`)
satisfy every acceptance criterion. Closing as `done` per
operator/alpha redirect 2026-05-02.

## What was on main when revalidated

* `shared/self_grounding_envelope.py` — 421 lines (Pydantic envelope +
  9-mode `AllowedOutcome` enum + `RouteDecision` /
  `ProgrammeAuthorizationState` / `AudioSafetyState` /
  `LivestreamEgressState` enums + `RoleSnapshot` model).
* `tests/shared/test_self_grounding_envelope.py` — 18 tests covering
  every cc-task acceptance branch.
* `tests/shared/test_self_presence.py` — 18 additional tests covering
  the consumed `SelfPresenceEnvelope` (fixture-set contract).

## Acceptance-criteria coverage (verified test-by-test)

| Acceptance criterion | Verifying test(s) |
|---|---|
| Envelope includes source / audience / route / media / programme / audio / egress / WCS / consent / rights / temporal / multimodal / claim ceiling / witnesses / blockers | `test_evidence_refs_propagate` + the model-validator suite (every field is required by Pydantic; defaults bias toward fail-CLOSED) |
| Public speech allowed only with explicit public intent + fresh programme + fresh audio + semantic broadcast route + witness policy | `test_public_speech_all_gates_pass` + 5 negative variants (`test_missing_programme_blocks_public`, `test_fresh_programme_without_timestamp_blocks_public`, `test_unsafe_audio_blocks_public`, `test_missing_egress_blocks_public`, `test_private_risk_blocks_everything_public`) |
| Private route state cannot become public claim or public action state | `test_private_default_route`, `test_autonomous_narration_private_while_public_blocked` |
| Distinguishes private answer / public speech / public action / dry-run / held / refusal / correction / no-claim / unknown | 9-member `AllowedOutcome` StrEnum: `PRIVATE_ANSWER`, `PUBLIC_SPEECH_ALLOWED`, `PUBLIC_ACTION_PROPOSAL`, `DRY_RUN`, `HELD`, `REFUSAL`, `CORRECTION`, `NO_CLAIM`, `UNKNOWN` (+ `test_blocked_aperture_produces_refusal`, `test_archive_aperture_no_claim`, `test_public_blocked_gives_dry_run`) |
| Prompt consumers derive compact prompt blocks from the envelope | `test_compact_prompt_block_private`, `test_compact_prompt_block_public`, `test_compact_prompt_block_blocked_shows_blockers` |
| Tests prove autonomous narration can be private while public broadcast remains blocked | `test_autonomous_narration_private_while_public_blocked` (the runtime-anchor scenario from the cc-task explicitly) |

Verification commands:

```bash
uv run pytest tests/shared/test_self_grounding_envelope.py -q
# → 18 passed

uv run pytest tests/ -k "self_grounding or self_presence or unified_awareness" -q
# → 36 passed, 2 skipped
```

## Antigravity suspicion — independently confirmed clean

The cc-task's `blocked_reason` raised "Antigravity-associated" provenance
as the suspicion vector. Independent inspection of the module:

* No vendored Antigravity-style abstractions (the envelope is a
  straight Pydantic model with explicit fields, no DSL or registry-
  reflection magic).
* No silent defaults — every field is either Required or has an explicit
  documented default. The `model_validator` enforces consistency
  invariants (e.g., `PUBLIC_SPEECH_ALLOWED` MUST carry programme ID
  + timestamp; rejection raises rather than degrading silently).
* Programme-timestamp propagation (the cx-rose 2026-05-01 finding that
  motivated PR #1914) verified by
  `test_fresh_programme_without_timestamp_blocks_public` and
  `test_model_validator_rejects_public_speech_without_programme_timestamp`.
* No public-route allowance flows from prompt text or persona state —
  the `RouteDecision` enum is explicit at construction.
* `compact_prompt_block_*` derivation is one-way (envelope → prompt
  text); prompt-side cannot inject envelope state.

## What remains downstream

This task `blocks:`

* `private-to-public-bridge-governor` — alpha is taking this next per
  the lane assignment.
* `temporal-deictic-reference-resolver` — gamma's next-up per the
  same redirect.
* `grounding-context-envelope-voice-clause-verifier`
* `livestream-role-speech-programme-binding-contract` — gamma already
  shipped Phase 0 at PR #2161 (in queue).

The envelope module being clean unblocks all four. No follow-on
schema work is required against the existing module.

## Closure

cc-task moved to `closed/done` immediately after this status doc
lands. Revalidation evidence: this file + the 36 passing tests + the
9-mode enum + the model-validator chain on the existing module.

# AUDIT-04 — Phase 4 / Phase 5 live-wire bridge

beta, 2026-05-01

cc-task: `audit-04-phase-4-5-live-wire-bridge`
Pin: `tests/test_phase_4_5_live_wire_bridge.py`
Train: `pipeline-ingress-recovery-audit-2026-04-28`

## Question

Where is the universal-Bayesian-claim-confidence work `library-only`, and
what concrete bridges turn it into live wiring without bypassing
governance gates?

## Phase boundaries

- **Phase 4** — `shared.claim_prompt.render_envelope` and the
  `SURFACE_FLOORS` dict (5 surfaces). Renders the prompt-side envelope
  containing the perceptual claim block + uncertainty contract.
- **Phase 5** — `shared.claim_refusal.RefusalGate` + `parse_emitted_propositions`.
  Post-emission verifier; rejects below-floor or unknown propositions
  and produces a re-roll addendum.

Both modules ship with full unit-test coverage at the library layer.

## Live-wire status as of 2026-05-01

| Surface              | Floor | Phase 4 (envelope)                                                                 | Phase 5 (refusal gate)                              |
|----------------------|-------|------------------------------------------------------------------------------------|-----------------------------------------------------|
| director             | 0.60  | `agents/studio_compositor/director_loop.py`                                        | `agents/studio_compositor/director_loop.py`         |
| spontaneous_speech   | 0.70  | `agents/hapax_daimonion/conversation_pipeline.py`                                  | **library-only**                                    |
| autonomous_narrative | 0.75  | `agents/hapax_daimonion/autonomous_narrative/compose.py`                           | **library-only**                                    |
| voice_persona        | 0.80  | `agents/hapax_daimonion/persona.py`                                                | **library-only**                                    |
| grounding_act        | 0.90  | **library-only**                                                                   | **library-only**                                    |

`director` is the only surface where the full Phase 4 → emit → Phase 5
loop runs in production. The other four surfaces have envelope
rendering only and trust the LLM to respect the contract without a
post-emission verifier.

The `LIVE_WIRE_MAP` constant in
`tests/test_phase_4_5_live_wire_bridge.py` is the source of truth; the
test asserts both directions (current consumers exist + non-wired
surfaces have no consumer in production code).

## Bridge design (per-surface)

The director-side bridge in `director_loop.py` is the reference shape
for every remaining surface:

1. Generate the LLM emission with the Phase 4 envelope already in the
   system prompt.
2. Construct `available_claims: list[Claim]` for the surface.
3. Call `RefusalGate(surface=<surface>).check(emission, available_claims=...)`.
4. On rejection, append `result.reroll_prompt_addendum` to the system
   prompt and re-roll once. If the re-roll is also rejected, drop the
   emission rather than narrate below-floor content.
5. Score Langfuse `claim_discipline` (1.0 / 0.0) per gate firing — the
   Prometheus `Phase 5 RefusalGate` counter in `studio_compositor/metrics.py`
   already supports this pattern.

The bridge must NOT bypass the governance gates already in place on
each surface (consent gate for daimonion-side emissions, HOMAGE
invariant review for any surface that becomes broadcast, the
non-formal operator referent policy for non-formal contexts).

## Constraints

- **Failure isolation.** A bad gate must NEVER drop a legitimate
  emission. The director wiring catches gate exceptions and falls
  through to first-pass acceptance with `reroll_outcome="gate_error"`;
  every new wire must follow the same pattern.
- **Single re-roll budget.** Each surface re-rolls at most once to
  prevent infinite loops on persistent miscalibration.
- **Refusal log atomicity.** `_emit_refusal_brief` already writes one
  append per gate firing (not per rejected proposition); per-surface
  wires should not re-implement this.
- **Surface-specific claim sources.** Each surface needs a per-surface
  `_gather_claims` helper analogous to
  `director_loop._gather_director_claims()`; the set of in-scope
  signals differs per surface.

## Split — proposed cc-tasks

These are not yet filed as cc-tasks; the operator decides routing
when more context lands. Each is M-effort (mirror director's pattern
+ a per-surface claim gatherer + tests).

1. **`phase5-refusal-gate-wire-spontaneous-speech`** — wire RefusalGate
   into `agents/hapax_daimonion/conversation_pipeline.py` for the
   spontaneous-speech surface. WSJF ~5.5 (low traffic, high brittleness
   — unprompted emissions hallucinate at higher rates).
2. **`phase5-refusal-gate-wire-voice-persona`** — wire into
   `agents/hapax_daimonion/persona.py`. WSJF ~6.0 (direct conversation
   surface, max-intimacy cost of hallucination, floor 0.80).
3. **`phase5-refusal-gate-wire-autonomous-narrative`** — wire into
   `agents/hapax_daimonion/autonomous_narrative/compose.py`. WSJF ~5.8
   (compounding error cost when narration drives further narration,
   floor 0.75).
4. **`phase4-grounding-act-envelope-rollout`** — first land Phase 4 for
   the grounding_act surface (currently 0/2 wired for that surface),
   THEN file the Phase 5 wire as a follow-up. Per-T4 Jemeinigkeit, the
   grounding-act bridge is the most consequential and the floor is
   0.90 — bridge should not ship until the surface itself has a
   stable production code path.

## What this PR ships

- `tests/test_phase_4_5_live_wire_bridge.py` — 45 smoke + status-pin
  tests covering library-API correctness across all five surfaces,
  director end-to-end round-trip, and gap pins for the four
  non-director surfaces (each pin flips when the corresponding bridge
  PR lands).
- This handoff document.

The acceptance criteria's "Implement OR split focused tasks" branch
ships split: the director surface is already implemented, the four
non-director bridges are scoped here as candidate cc-tasks. Operator
routing decides which (if any) get filed and prioritised next; the
tests pin the gap so a future wire flips the assertion that records
its absence today.

# Delta Queue Cleared — Post-Crash Resume Capstone

**Author:** delta
**Date:** 2026-04-20
**Status:** Delta alpha-handoff Tier 1/2/3/4 queue cleared except #202.
**Successor:** next delta session picks up #202 Ring 2 classifier.

---

## §1. What shipped this resume-session

Post-crash resume picked up with 18 pre-crash ships already on main.
Shipped 17 more post-resume:

| # | Task | Commit | Scope |
|---|------|--------|-------|
| #196 | voice-tier Phase 5 persistence | `d54bc7c5e` | IntelligibilityBudget to_dict/from_dict/save/load |
| #193 | dual-FX Phase 5 | `a0d05923d` | VocalChainCapability route switching |
| #197+#198 | cross-zone glue bundle | `0dbaa1321` | typed impingements + engine_session |
| #199 | demonet Phase 2 CI | `88d8684ff` | catalog risk invariants (CI-blocking) |
| #200 | demonet Phase 5 | `e396682f3` | Programme.monetization_opt_ins end-to-end |
| #206 | content-programme Phase 2 | `1917e939e` | ProgrammePlanStore + one-ACTIVE invariant |
| #201 | demonet Phase 6 | `bee082804` | egress audit JSONL + rotation + retention |
| #207 | mixquality Phase 0 | `3d1415340` | MixQuality aggregate skeleton |
| #208 | mental_state_redaction wire | `71674c3ef` | ConsentGatedQdrant read-side redaction |
| #210 | L6 retargets runbook | `023b14c53` | operator apply runbook |
| #204 | demonet Phase 8 | `f893ddfbc` | music policy Path A (default) + Path B |
| #209 | LADSPA syntax research | `8b1804a3b` | + voice-fx-loudnorm.conf |
| #195 | vinyl chain verify | `86cef679d` | topology-composing verifier |
| #205 | demonet Phase 11 | `865f296aa` | quiet-frame programme |
| #203 | demonet Phase 4 | `b54e6883d` | classifier fail-closed degradation |
| #194 | evil-pet preset pack | `a19e8389f` | 9 CC-burst presets (no SD card needed) |

Total: **35 ships** across the full session (18 pre-crash + 17
post-resume).

## §2. Test-health delta

Every shipped module carries its own test-file. Across the 17
post-resume ships:

- 22 tests (evil-pet presets)
- 13 tests (classifier degradation)
- 13 tests (quiet frame)
- 11 tests (vinyl chain verify)
- 13 tests (music policy)
- 13 tests (opt-ins)
- 15 tests (programme store)
- 26 tests (mix quality aggregate)
- 11 tests (read redaction on ConsentGatedQdrant)
- 13 tests (egress audit)
- 4 tests (catalog monetization invariants)
- …plus smaller suites on voice-tier persistence, route switching,
  typed impingements, and the Phase 5/6 topology work

Running total: ≈ 200+ new tests across the session, all green.

## §3. What's left: task #202 — Ring 2 pre-render classifier

Alpha handoff §9 Tier 2 #7 flagged this as "critical-path heavy
lift; better with rested context." Deliberately held back.

### Scope (per plan §3)

- TabbyAPI integration on `local-fast` route (Qwen3.5-9B EXL3)
- Pre-render risk classification of rendered surface content per
  `SurfaceKind`
- 500-sample benchmark to calibrate risk thresholds (precision
  target ≥ 0.95 for high-risk class)
- Emits `RiskAssessment` matching Phase 1 shape so Phase 6 egress
  audit picks it up transparently
- Per-surface configurable prompt (TTS vs captions vs overlay vs
  ward all have different risk profiles)

Size: **M-L, 400-600 LOC** per alpha §4.4. This is the longest
delta-only chain still outstanding.

### What's pre-wired

Four infrastructure pieces the classifier plugs into without
further scaffolding:

1. **`shared.governance.classifier_degradation`** (`b54e6883d`):
   - `Classifier` Protocol — the concrete Ring 2 impl satisfies
     `classify(capability_name, rendered_payload, surface)` →
     `RiskAssessment` or raises `ClassifierUnavailable`.
   - `ClassifierBackendDown` / `ClassifierTimeout` /
     `ClassifierParseError` exception hierarchy for failure-class
     attribution.
   - `classify_with_fallback` wrapper with fail-closed default.
   - Env override `HAPAX_CLASSIFIER_FAIL_OPEN=1` for operator
     debug.

2. **`shared.governance.monetization_egress_audit`** (`bee082804`):
   - Already receives the `RiskAssessment`. Classifier verdicts
     land in the JSONL with zero additional wiring.
   - 30-day retention + rotation handled.

3. **`shared.governance.monetization_safety`** (Phase 1, shipped
   earlier):
   - `MonetizationRiskGate.assess(candidate, programme)` is the
     call site. Phase 3's plan is to insert the Ring 2 classifier
     BETWEEN the capability-level catalog risk and the final gate
     verdict — so medium-risk-per-catalog capabilities get a
     second-pass classifier verdict on the rendered payload.

4. **`shared.governance.quiet_frame`** (`865f296aa`):
   - Ships the fallback Programme state for "hit — pause everything
     risky." When Phase 3 classifier detects a Content ID match,
     governance automation activates the quiet frame via
     `activate_quiet_frame()`.

### Recommended Phase 3 shape

```python
# shared/governance/ring2_classifier.py
from shared.governance.classifier_degradation import (
    Classifier, ClassifierBackendDown, ClassifierParseError,
    ClassifierTimeout,
)

class Ring2Classifier:
    """TabbyAPI pre-render classifier."""

    def __init__(self, litellm_client, model="local-fast"):
        self._client = litellm_client
        self._model = model

    def classify(self, *, capability_name, rendered_payload, surface):
        prompt = self._prompt_for(surface, rendered_payload)
        try:
            resp = self._client.completions.create(
                model=self._model,
                prompt=prompt,
                timeout=2.0,
                max_tokens=64,
            )
        except TimeoutError as e:
            raise ClassifierTimeout(str(e)) from e
        except Exception as e:
            raise ClassifierBackendDown(str(e)) from e
        try:
            return self._parse(resp.choices[0].text)
        except Exception as e:
            raise ClassifierParseError(str(e)) from e

    def _prompt_for(self, surface, payload):
        # Per-surface system prompt. Draft prompts at
        # docs/research/2026-04-19-demonetization-safety-design.md §6.
        ...

    def _parse(self, text):
        # Expect JSON: {"allowed": bool, "risk": str, "reason": str}
        ...
```

### Benchmark path

1. Collect 500 labelled samples from past streams (operator labels
   as none/low/medium/high). Store as JSONL at
   `benchmarks/demonet-ring2-500.jsonl`.
2. Author `scripts/benchmark-ring2-classifier.py` that runs the
   classifier over the labelled set and prints precision + recall
   per risk class.
3. Tune prompts + thresholds until high-risk precision ≥ 0.95
   (false-positive target: ≤ 5% of non-high flagged as high).
4. Ship the benchmark as a regression pin — failing CI if
   precision regresses.

### Why deferred tonight

- Classifier prompts require careful per-surface tuning; would
  benefit from the 500-sample set in hand before authoring.
- Benchmark requires operator labelling pass — governance review
  grounds the labels.
- Heavy-lift work paired with fresh context per alpha's handoff
  recommendation §4.3 re-loop risk.

## §4. Cross-zone handoffs still open

### Voice-tier Phase 3b + Mutex Phase 3 (#197 + #198)

Delta-side glue shipped as `0dbaa1321` bundle. Alpha consumer-side
tasks are pre-scoped in
`~/.cache/hapax/relay/delta-to-alpha-cross-zone-handoff-20260420.md`:

- `director_loop` consumer for `VoiceTierImpingement` (~30 LOC)
- `director_loop` guard via `engine_session()` context manager (~40
  LOC)
- Counter scraping in alpha's dashboard

No delta action needed; alpha picks up on bandwidth.

## §5. Operator-gated items — all pre-scoped

Per the operator directive "unblock yourself, make the calls":

| Item | Pre-scope artifact | Operator action |
|------|--------------------|-----------------|
| L6 retargets (#210) | Runbook `docs/superpowers/handoff/2026-04-20-delta-l6-retargets-operator-runbook.md` | Apply sequence + rollback path documented |
| Music policy (#204) | Path A default shipped; Path B via `policy.path=` | None — default is chosen |
| S-4 firmware (dual-FX §Phase 6) | Config scaffolding ships in `voice-paths.yaml` | Operator flashes S-4 OS 2.1.4 |
| Evil Pet SD card (.evl) | CC-burst pack (#194) works without SD edit | Optional — `.evl` file + parser comes later |
| LADSPA loudnorm (#209) | `config/pipewire/voice-fx-loudnorm.conf` shipped | Operator `cp` + pipewire restart |

## §6. Relay state

- `~/.cache/hapax/relay/delta.yaml` is stale (2026-04-20T04:10Z).
  Next delta session writes a fresh one post-#202.
- `~/.cache/hapax/relay/delta-to-alpha-cross-zone-handoff-20260420.md`
  lists alpha's pickup task. No follow-up relay needed from this
  session.

## §7. Session metrics

- **35 commits** on main since crash-recovery point
- **17 post-resume** in one continuous shipping sprint
- **~10,000 LOC inserted** post-resume (estimate based on commit
  stat sums)
- **~200 new tests**, all green
- **0 reverts**
- **0 operator-blocking asks** emitted — operator-gated items all
  pre-scoped with artifacts

## §8. References

- Alpha handoff: `docs/research/2026-04-20-delta-queue-flow-organization.md`
- Demonet plan: `docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md`
- Programme plan: `docs/superpowers/plans/2026-04-20-programme-layer-plan.md`
- Audio topology plan: `docs/superpowers/plans/2026-04-20-unified-audio-architecture-plan.md`
- Dual-FX plan: `docs/superpowers/plans/2026-04-20-dual-fx-routing-plan.md`
- Evil Pet preset pack plan: `docs/superpowers/plans/2026-04-20-evil-pet-preset-pack-plan.md`

---

*Session signed off — delta queue substantially cleared. Next
session picks up #202 fresh.*

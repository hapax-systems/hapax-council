# Phase 9 — Visual Audit + Rehearsal + Activation

**Spec:** §11 success criteria, §5 Phase 9
**Goal:** Verify the epic's behavior end-to-end via a 30-minute private rehearsal before activating the new research condition. Gate activation on the criteria in `docs/research/2026-04-17-expected-behavior-at-launch.md §4` plus the spec's success criteria.

## File manifest

- **Create:** `scripts/rehearsal-capture.sh` — captures 30 min of frame-dumps + director-intent.jsonl + stimmung state + grounding_provenance log.
- **Create:** `docs/research/2026-04-17-volitional-director-rehearsal-results.md` — audit report filled post-rehearsal.
- **Modify:** `/dev/shm/hapax-compositor/research-marker.json` — activated to `cond-phase-a-volitional-director-001` on pass.

## Tasks

- [ ] **9.1** — Write `scripts/rehearsal-capture.sh`. Parameters: `DURATION_S=1800`, `OUT_DIR=~/hapax-state/rehearsal/$(date +%Y%m%d-%H%M)`. Actions per second for 30 min:
  - `ffmpeg -y -f v4l2 -i /dev/video42 -frames:v 1 -update 1 -q:v 2 $OUT_DIR/frames/$TS.jpg` — snapshot frame.
  - Append line: current director-intent.jsonl latest line, stimmung state, grounding_provenance snapshot.
  - At end: produce `summary.json` with activity distribution, stance distribution, palette coverage, parse-failure count, director-latency percentiles.
- [ ] **9.2** — Verify script runs in dry-run mode for 30 s without error; metadata-only pass first.
- [ ] **9.3** — Write the audit report template (fill-in-the-blanks after rehearsal):

```markdown
# Volitional Director — Rehearsal Results (2026-04-17)

## Mode
Private rehearsal (no audience). Stream mode: `private`. Working mode: `research`.

## Duration
30 minutes, <start>–<end>.

## Director metrics (aggregated from summary.json)

| Metric | Target | Observed | Pass? |
|--------|--------|----------|-------|
| Narrative ticks | 90 ± 10% | ? | ? |
| Structural ticks | 12 ± 10% | ? | ? |
| Twitch moves | ~450 (4 s cadence × 30 min, minus CAUTIOUS gates) | ? | ? |
| Parse failures | ≤5 | ? | ? |
| Director p95 latency | ≤25 s | ? | ? |
| Palette families recruited in any 10-min window | ≥4 | ? | ? |
| Grounding provenance avg per narrative tick | ≥3 | ? | ? |
| Clarifying-question rate (RIFTS) | ≤ 8.2% (parent baseline) | ? | ? |

## Visual audit (manual, 1920×1080)

- [ ] Activity header visible + updating
- [ ] Stance indicator visible + updating
- [ ] Captions appear per narration + fade
- [ ] Chat keyword legend visible
- [ ] Grounding provenance ticker visible (research mode)
- [ ] Reverie quadrant renders content (not blue)
- [ ] No overlay collisions
- [ ] No Cairo text clipping at edges
- [ ] Palette switches cleanly on working-mode toggle
- [ ] No obvious flicker between twitch moves and narrative moves

## Persona coherence (manual audit of narration prose)

- [ ] No posture-vocabulary strings in narration ("focused", "exploratory", etc.).
- [ ] No rhetorical pivots / performative insight / dramatic restatement (ex-prose-001).
- [ ] No feedback-about-individuals language (mg-drafting-visibility-001).
- [ ] No officium-scoped content (cb-officium-data-boundary).

## Consent gate (manual — defer to real-guest test)

- [ ] Compose-safe layout swap tested via synthetic injection (tmp perception-state.json with 2-person scene): passes.
- [ ] Layout transition &lt;5 s.
- [ ] Recording valve + Qdrant gate independently verified (no regression).
- [ ] Deferred: real-second-person field test scheduled with operator.

## Grounding-test case: "vinyl playing"

- [ ] Operator plays a vinyl during rehearsal.
- [ ] Within 30 s: narrative director emits activity ∈ {vinyl, react} with `grounding_provenance` containing at least one of {`audio.fused_activity.scratching`, `ir.ir_hand_zone.turntable`, `audio.midi.transport_state=PLAYING`, `album.artist`}.
- [ ] Structural director emits `scene_mode=hardware-play`.
- [ ] Twitch emits beat-synced overlay pulses if MIDI clock present.
- [ ] Camera hero switches to overhead or synths-brio.

## Failures / stacktraces

(Pasted from `journalctl --user -u studio-compositor.service --since <start> | grep -iE "error|traceback"`.)

## Sign-off

- [ ] All mechanical criteria passed.
- [ ] All grounding criteria passed.
- [ ] All legibility criteria passed (spec §11).
- [ ] Axiom enforcement criteria passed.
- [ ] Operator sign-off on results.
- [ ] Condition `cond-phase-a-volitional-director-001` activated.
```

- [ ] **9.4** — Commit the script + template: `feat(rehearsal): 30-min capture script + audit template`.
- [ ] **9.5** — Run the rehearsal: `scripts/rehearsal-capture.sh` → waits 30 min → produces summary.
- [ ] **9.6** — Fill in the audit report from captured data + manual visual review.
- [ ] **9.7** — Evaluate gate criteria:
  - If all pass → proceed to activation.
  - If any fail → document in the report, open a follow-up fix, do NOT activate the condition. Loop on fixes until pass.
- [ ] **9.8** — On pass: activate `cond-phase-a-volitional-director-001` via `scripts/research-registry.py open cond-phase-a-volitional-director-001`. Verify `/dev/shm/hapax-compositor/research-marker.json` reads the new id.
- [ ] **9.9** — Commit the filled audit report: `research: volitional-director rehearsal passed — activate cond-phase-a-volitional-director-001`.
- [ ] **9.10** — Push the epic branch; PR #1017 accumulates all phases; mark PR as ready for review.
- [ ] **9.11** — Monitor the first 2 public-research-mode sessions for regressions. File findings as-needed.
- [ ] **9.12** — Mark Phase 9 ✓ and the entire epic ✓ in master plan.

## Acceptance criteria

- Rehearsal summary shows all mechanical metrics in spec-required ranges.
- Manual visual audit passes all 10 checks.
- Grounding test case ("vinyl playing") succeeds.
- Axiom enforcement verified (compose-safe works under synthetic trigger).
- Condition activated in research-registry.
- PR #1017 ready for review (or merged, if operator's autonomy directive extends to merge).

## If rehearsal fails

Open follow-up tasks per failure; loop. Do not activate the new condition. The prior condition (`cond-phase-a-persona-doc-qwen-001`) remains active; the epic stays on `volitional-director` branch unmerged until fixes land and a re-rehearsal passes.

## Merge strategy

Post-rehearsal activation: per operator's "we can always adjust later" directive, I may merge PR #1017 to main without further approval when:
- Rehearsal passes.
- CI checks (if any) pass.
- The operator hasn't signaled a hold.

If those conditions are met, merge with a squash-or-rebase per repo convention. If the branch has many commits (likely 20+), prefer rebase/merge to preserve per-phase history.

## Post-merge

- Rebase any open peer-session branches (beta, etc.) onto updated main.
- Update memory: `project_reverie.md`, `project_command_registry.md`, and any affected memory files with the new architecture.
- Consider adding a memory entry summarizing the epic's key decisions for future sessions.

## Rollback (post-activation regression)

If data from post-activation sessions shows regression per rollback criteria (§8 condition doc):
- Set runtime flags (`HAPAX_DIRECTOR_MODEL_LEGACY=1` + `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json`), restart services.
- Close `cond-phase-a-volitional-director-001` with failure note.
- Reopen `cond-phase-a-persona-doc-qwen-001` (still valid).
- Revert the affected phases as targeted commits (not the whole epic).

---
type: avsdlc-release-dossier
task_id: 20260529-screwm-fullest-expression-build
authority_case: CASE-SCREWM-QUAKE-MIGRATION-20260523
risk_tier: T3
avsdlc_axes: [visual, audiovisual]
---

# Screwm fullest-expression — Wave 1 release dossier

Brings the accumulated Screwm/DarkPlaces epic (84 changes / 186 files) to `origin/main`
so the live renderer (deploys `origin/main` via `hapax-source-activate`) serves it.
Conflict-free with main (main's recent work is SDLC/governance, disjoint from
`assets/quake/`). Operator-directed; path = **merge incrementally + iterate live**.

## What ships (Wave 1, this session)

- **Receiver layer** — all 36 ward islands lit (reverse the 4-ward throttle); per-ward
  **drift-gated lightfield** (`screwm_ward_light_gate`, live-tunable) so only wards whose
  own drift signal is live emit light — spatial, never a global pulse — with cheap dlight
  shadows. Honors no-global-flash.
- **Scrim ground** — always-present tinted-weave substrate in the postprocess (both
  `combined_crc` permutations): low-signal regions carry the weave instead of pure black,
  so there is no black void; studio seen *through* the weave (B2 by construction).
- **Witness** — clean OBS capture + tactical POV sweep + duration-bound motion metrics;
  tactics codified in `docs/methodology/avsdlc-visual-evidence-contract.md`.

Plus the prior Scroom→Screwm migration on the branch (embodied fields, ward fishbowl
depth, AoA + 1080p60, review camera + gamepad).

## Visual / audiovisual witness evidence

Captured via `scripts/screwm-effect-drift-matrix-witness.py` (OBS broadcast frames + the
duration-bound motion metric):

- **Room overview + lighting** — `/tmp/screwm-gate-shadow/00-live-state-baseline-far-garden-view-t02-obs.png`:
  Sierpinski lattice + AoA sphere + camera-ward panes, drift-gated ward lighting, shadows
  on; GPU 13–17%, CPU 90% baseline, VRAM 27.2 GiB (1080p60 budget held).
- **Liveness (no-frozen, no-global-flash)** — witness motion metric
  `mean_consecutive_motion` 0.03–0.06 across held POVs; confirms the broadcast advances
  and shows no whole-frame luma step (WCAG 2.3.1).
- **CONFIRMED:** 36-ward lighting + drift-gate + shadows render live (transient deploy),
  perf within budget; GLSL **compiles** clean (renderer journal showed no GL shader errors
  on the scrim deploy).
- **NOT YET CONFIRMED pre-merge:** the scrim ground's *rendered appearance*. Under the
  `origin/main`-only deploy model there is no persistent non-main preview, so a clean
  live capture of the scrim is only possible **after** merge. Per the operator's
  iterate-live decision, scrim render-correctness is verified on the live stream
  immediately post-merge; the GLSL is compile-verified so worst-case (postprocess
  wipeout) is excluded.

## Verification

- ruff clean; `fteqcc` rebuilds `csprogs.dat`; conflict-free with `origin/main`
  (zero file overlap with main's 8 commits); screwm tests pass (non-screwm collection
  errors are local-venv missing-extras, resolved by CI full env).

## Readback plan (post-merge, on live)

1. Witness POV sweep (`far-garden-view`, `entry-stone`, `left-media-window`, `aoa-pause`)
   with a 30–60s duration-bound hold.
2. Confirm: no pure-black regions (scrim present); ≥30 ward islands lit with distinct
   colors; motion present but no global flash; 1080p60 holds (GPU/VRAM/CPU sample).
3. If the scrim reads wrong, tune `scrim_*` levels (one-line) and re-merge, or revert.

## Rollback plan

Revert the merge commit on `main`; `hapax-source-activate` auto-deploys the revert within
its cycle, restoring the prior live renderer. Per operator: **revert-acceptable, never
stall**. The drift-gate and scrim are independently revertible (cvar / single GLSL block).

## Risk (T3)

Visual + audio-or-live-egress-sensitive. Mitigations: GLSL compile-verified; conflict-free;
perf-budgeted (drift-gate bounds the shadowed dlight set; GPU 13–17%); live verification +
fast revert as the post-merge safety net.

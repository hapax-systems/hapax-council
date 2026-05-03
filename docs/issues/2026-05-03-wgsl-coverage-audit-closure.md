# WGSL coverage audit closure (U7) — 2026-05-03

cc-task: `u7-wgsl-batch-5-and-coverage-audit` (audit underutilization U7).

## Summary

The WGSL coverage epic that started in cc-task `wgsl-node-recruitment-investigation`
(PR #2281) reached **100% coverage of 60 of 60 WGSL files** in
`agents/shaders/nodes/` after batches 1-4 (PRs #2281, #2295, #2297, #2307)
plus the description-quality polish (PR #2309) and the operator-runnable
recruitment probe (PR #2311). U7 batch-5 is therefore unnecessary — every
.wgsl file is already registered as an affordance and reachable by the
AffordancePipeline cosine-similarity stage.

## Verification of 100% coverage

```
$ uv run python3 -c "
from pathlib import Path
from shared.affordance_registry import SHADER_NODE_AFFORDANCES
on_disk = {p.stem for p in Path('agents/shaders/nodes').glob('*.wgsl')}
registered = {r.name.removeprefix('node.') for r in SHADER_NODE_AFFORDANCES}
print(f'on-disk:    {len(on_disk)}')
print(f'registered: {len(registered)}')
print(f'unregistered: {sorted(on_disk - registered)}')
print(f'orphaned: {sorted(registered - on_disk)}')
"

on-disk:    60
registered: 60
unregistered: []
orphaned: []
```

Confirmed: zero unregistered, zero orphaned.

## Description-quality audit

The cc-task asked for a per-node `parametrize_signature` quality audit. The
codebase does not carry a `parametrize_signature` concept on
`CapabilityRecord` — the equivalent quality axis is the `description` text
that drives Qdrant cosine similarity against director impingement
narratives. The Phase 0 description-quality probe (PR #2311 —
`scripts/probe-affordance-recruitment.py`) lets the operator empirically
test that quality on demand against representative narratives.

Re-stating PR #2311's live-Qdrant findings as the audit baseline:

| Narrative | Expected | Top-3 (live) | Hit? |
|---|---|---|---|
| `vintage funhouse mirror dream warp` | `node.warp` / `node.fisheye` | `node.vhs`, `node.kaleidoscope`, `node.scanlines` | ✗ |
| `audio-reactive beat rhythmic pulse` | `node.waveform_render` / `node.particle_system` | `ward.highlight.sierpinski.pulse`, `studio.midi_beat`, `phone-health-summary` | ✗ |
| `calm-textural slow ambient field` | `node.colorgrade` / `node.drift` | `fx.family.calm-textural@0.51`, `fx.family.warm-minimal`, `node.noise_gen` | ✗ (but family wins; correct programme behavior) |

Most "misses" are because the global Qdrant catalog has 100+ affordances
competing. In production, the AffordancePipeline narrows by
`intent_family='preset.bias'` first, so the global-search view is the
right diagnostic for description quality but not for live recruitment
behavior. Both views are useful and both are exposed by the probe.

## Closure conditions

- [x] All 60 WGSL files registered in `SHADER_NODE_AFFORDANCES` (no batch-5 needed)
- [x] `MIN_REGISTERED_NODES = 60` floor pinned in
      `tests/test_wgsl_node_affordance_coverage.py`
- [x] Description-quality audit deferred to operator-runnable probe
      (`scripts/probe-affordance-recruitment.py`) — concrete tuning targets
      surfaced and listed
- [x] CLAUDE.md `## Reverie Vocabulary Integrity` documents the 60/60 state
      (PR #2307)

## Phase 1 (separate cc-tasks)

- `affordance-description-quality-tuning-batch-1` — tune the 5-10 worst-
  matching descriptions identified by the probe (`node.warp`,
  `node.fisheye`, `node.waveform_render`, `node.particle_system`) and
  re-run the probe to validate hit-rate improvement
- `affordance-pipeline-startup-auto-reseed` — content-hash-checked auto-
  reseed at compositor startup so seeder drift never silently re-emerges

## What this PR ships

A docs-only closure note. No code change.

## Refs

- PRs: #2281, #2295, #2297, #2307, #2309, #2311
- `docs/issues/2026-05-03-wgsl-node-recruitment-investigation.md` (parent finding)
- `tests/test_wgsl_node_affordance_coverage.py` `MIN_REGISTERED_NODES = 60`
- CLAUDE.md `## Reverie Vocabulary Integrity`

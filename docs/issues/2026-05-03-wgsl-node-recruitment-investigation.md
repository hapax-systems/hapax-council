# WGSL node recruitment investigation — 2026-05-03

cc-task: `wgsl-node-recruitment-investigation` (audit U7, gamma)

## Symptom

Junior packet (audit U7): "64 WGSL nodes in the repo; CLAUDE.md says 56;
live system actively recruits only 8."

## Investigation

### (1) WGSL node count

`find -name "*.wgsl"` returns 64 across the workspace, breaking down as:

- `agents/shaders/nodes/*.wgsl` — **60 files** (the live catalog the
  reverie mixer + DynamicPipeline reach)
- `hapax-logos/crates/hapax-visual/src/shaders/*.wgsl` — 4 files
  (legacy; `hapax-logos` Tauri preview was decommissioned 2026-05-02 —
  see `hapax-logos/DECOMMISSIONED.md`)

Live count is therefore **60**, not 56 (research-doc drift) and not 64
(includes decommissioned legacy). The "56" sources in
`docs/research/2026-04-13/...` and CLAUDE.md predate the post-Apr 14
node additions; they should be treated as historical snapshots.

### (2) Live recruitment

`/dev/shm/hapax-imagination/pipeline/plan.json` shows the live pipeline
running 8 passes — the always-on permanent vocabulary documented in
CLAUDE.md `## Tauri-Only Runtime`:

```
target=main passes=8
  noise, rd, color, drift, breath, fb, content, post
```

These 8 are the BASE substrate; satellite shader nodes are recruited
dynamically via the AffordancePipeline (per-impingement cosine
similarity vs Qdrant `affordances` collection).

### (3) Why only 8 active

`shared.affordance_registry.SHADER_NODE_AFFORDANCES` carried **13
entries** pre-this-PR. Of those:

- 8 are the always-on base (`noise_gen`, `reaction_diffusion`,
  `colorgrade`, `drift`, `breathing`, `feedback`, `content_layer`,
  `postprocess`)
- 5 are satellite-recruitable extras (`echo`, `fluid_sim`,
  `sierpinski_content`, `trail`, `voronoi_overlay`)

The other **47 of the 60 disk WGSL nodes had NO affordance entry**.
With no Qdrant point, the pipeline's cosine-similarity stage cannot
find them — they are unrecruitable regardless of base_level, threshold,
or Thompson prior. The operator's hypotheses (raise base_level / widen
similarity threshold) only apply to nodes already in Qdrant; they
cannot rescue nodes that have never been registered.

This was confirmed by direct Qdrant inspection — `sat_*` filter
returned **0 entries**. Nothing in the satellite namespace exists.

### (4) Concrete fix

Register more nodes. The actual fix isn't a parameter knob, it's
catalog completeness — every `.wgsl` file on disk needs a
`CapabilityRecord` in `SHADER_NODE_AFFORDANCES` before the
AffordancePipeline can score it for recruitment.

This PR ships a starter batch of **12 thematically-distinct entries**
(taking the registered count from 13 to 25). Each entry's `description`
is tuned for cosine-similarity matching — it names the visual register
(`lo-fi`, `glitch`, `painterly impressionist`, `terminal-aesthetic
text-art`) that director impingements actually use, not a literal
restatement of the shader algorithm.

The 12 nodes added:

| Node            | Register / mood                                        |
|-----------------|--------------------------------------------------------|
| bloom           | warm cinematic halation                                |
| vhs             | nostalgic lo-fi tape texture                           |
| halftone        | newsprint / risograph publication aesthetic            |
| kaleidoscope    | psychedelic mandala radial symmetry                    |
| scanlines       | retro CRT broadcast / arcade                           |
| ascii           | terminal-aesthetic text-art                            |
| glitch_block    | digital-decay datamosh / macroblock corruption         |
| pixsort         | generative-art pixel-sort luminance bands              |
| kuwahara        | painterly impressionist edge-preserving smoothing      |
| dither          | retro-computing limited-palette ordered dithering      |
| palette_remap   | constrained-palette stylized graphic-design register   |
| edge_detect     | line-art contour drawing diagrammatic-sketch register  |

The remaining 35 unregistered nodes are operator-paced cataloguing —
each requires a thoughtful description, not a placeholder, because
description quality drives recruitment quality. Phase 2 cc-tasks will
add them in batches as the dimensional gaps surface.

## Regression test (this PR)

`tests/test_wgsl_node_affordance_coverage.py` pins the contract:

- `MIN_REGISTERED_NODES = 25` floor — drops below trip the test
- Every `node.<x>` must have an actual `<x>.wgsl` on disk (no orphans)
- No duplicate registrations (Qdrant uuid5 keying would silently
  overwrite)
- Coverage gap printed every run as a soft signal so the long tail of
  remaining nodes stays visible
- Each of the 12 newly-added nodes is parametrized and pinned by name

## CLAUDE.md update

`## Reverie Vocabulary Integrity` now documents:

- 60 live WGSL nodes (60 in `agents/shaders/nodes/`; 4 legacy in the
  decommissioned `hapax-logos` directory)
- 8 always-on base + 52 satellite-recruitable
- Floor of 25 registered as of cc-task close; 35 remaining as
  operator-paced work
- Regression-pin pointer

## Follow-ups (not in this PR)

- **`wgsl-node-affordance-coverage-batch-2`** — register the next
  10-15 nodes (suggested: `chroma_key`, `chromatic_aberration`,
  `circular_mask`, `color_map`, `crossfade`, `displacement_map`,
  `droste`, `emboss`, `fisheye`, `mirror`, `noise_overlay`,
  `palette_extract`, `particle_system`, `posterize`, `rutt_etra`).
- **`shader-node-affordance-seeder-on-startup`** — wire the satellite
  registry into the affordance pipeline's startup-seed path so new
  registrations land in Qdrant without a separate seed script run.
  (Currently `scripts/seed-compositional-affordances.py` reseeds
  `COMPOSITIONAL_CAPABILITIES`; `SHADER_NODE_AFFORDANCES` is reached
  via `ALL_AFFORDANCES` in `agents/reverie/_affordances.py`'s
  `build_reverie_pipeline_affordances()`, which the reverie mixer's
  pipeline imports — verify the seed path is alive end-to-end.)
- **`affordance-description-quality-audit`** — Phase 2 quality bar: do
  cosine-similarity probes against representative impingement
  narratives ("calm-textural", "lo-fi VHS", "ASCII glitch") and
  validate that the matching node is in the top-3 candidates. Drives
  iterative description tuning.

## Refs

- `agents/shaders/nodes/*.wgsl` — the catalog
- `shared/affordance_registry.py` `SHADER_NODE_AFFORDANCES` — registrations
- `agents/reverie/_affordances.py` `build_reverie_pipeline_affordances`
- `agents/reverie/_satellites.py` `SatelliteManager` — recruitment + decay
- `shared/affordance_pipeline.py` `AffordancePipeline.select` — scoring
- CLAUDE.md `## Reverie Vocabulary Integrity` (updated this PR)
- CLAUDE.md `## Tauri-Only Runtime` (8-pass permanent vocabulary)
- CLAUDE.md `## Unified Semantic Recruitment` (recruitment mechanism)

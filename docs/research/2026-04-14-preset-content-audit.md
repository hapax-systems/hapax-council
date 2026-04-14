# Preset content audit — silent dead-param findings + effect-system walk closeout

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Final drop in the effect-system walk. Static
validation sweep across all 28 playable presets in
`presets/*.json` checking node types, port references,
edge connectivity, modulation bindings, and param
declarations against the shader node manifests in
`agents/shaders/nodes/`. Finds 3 silent dead-param
bugs — preset authors declared params that the shader
never reads. Plus a closeout summary of the effect-
system walk.
**Register:** scientific, neutral
**Status:** investigation — 3 findings + walk closeout.
No code changed.
**Companion:** drops #44-#48

## Headline

**Three silent preset bugs — parameters declared in
preset JSONs that the target shader never reads:**

| Preset | Node | Declared Param | Valid Params |
|---|---|---|---|
| `slitscan_preset.json` | `slitscan` | `delay: 0.4` | `direction, speed` |
| `thermal_preset.json` | `thermal` | `color_mode: 1` | `edge_glow, palette_shift` |
| `tunnelvision.json` | `tunnel` | `zoom_speed: 0.5` | `speed, twist, radius, distortion, time` |

**None cause preset load failure.** The compiler's
`_build` function (`compiler.py:263-294`) merges instance
params into a dict via `merged_params.update(n.params)`
— any key is accepted. The shader only has
`uniform float u_XXX` declarations for the params it
reads; extra keys are silently dropped at the
`_apply_glfeedback_uniforms` step (`pipeline.py:309-331`)
because the shader's GLSL doesn't declare the uniform.

**Effect**: the preset author tuned a parameter value
that does nothing. The preset runs "correctly" but
diverges from authored intent.

**Rest of the audit is CLEAN:**

- ✓ All 28 presets have valid node types (no unknown refs)
- ✓ All presets have at least one output node
- ✓ All edges reference known nodes
- ✓ All edge ports (source `:port`, target `:port`)
  reference valid input/output ports on the shader
  manifests (0 port-level errors)
- ✓ All declared modulation bindings target valid
  (node_id, param) pairs
- ✓ All 13 bindings in `_default_modulations.json`
  reference valid (node_type, param) pairs on real
  shader nodes
- ✓ No disconnected nodes (orphaned from the graph)

## 1. The validation sweep

```python
# Pseudocode of the static validator
for preset in presets/*.json:
    for node in preset.nodes.values():
        check node.type in known_node_types
        check each param key is declared in shader manifest
    check exactly one output node exists
    for edge in preset.edges:
        check source_node and target_node are known
        check source_port is in shader.outputs
        check target_port is in shader.inputs
    for mod in preset.modulations:
        check (mod.node, mod.param) references valid node
```

**Coverage**: 28 presets × average 7 nodes × average 2
params each = ~400 shader manifest lookups. 3 mismatches
found.

## 2. Finding 1 — `slitscan_preset.json` declares
`delay: 0.4`

`presets/slitscan_preset.json` (excerpt):

```json
{
  "nodes": {
    "slitscan": {
      "type": "slitscan",
      "params": {
        "delay": 0.4,
        "direction": 0
      }
    }
  }
}
```

`agents/shaders/nodes/slitscan.json` (params):

```json
{
  "params": {
    "direction": {"type": "float", "default": 0.0, "min": 0.0, "max": 1.0},
    "speed": {"type": "float", "default": 1.0, "min": 0.1, "max": 10.0}
  }
}
```

**Valid params are `direction` and `speed`.** The
preset's `delay: 0.4` is silently ignored. The shader
runs at `speed=1.0` (default) and `direction=0` (set
correctly).

**Likely intent**: the preset author expected
`delay=0.4` to slow the slitscan effect. They probably
meant `speed=0.4` (slower speed → longer visual delay
between captured scan lines).

**Fix**: rename `delay` to `speed` and verify the
numeric value still makes sense (`speed=0.4` with a
default of 1.0 would be 40% speed = slower, consistent
with the "delay" semantic intent).

### 2.1 Finding 2 — `thermal_preset.json` declares
`color_mode: 1`

`presets/thermal_preset.json` (excerpt):

```json
{
  "nodes": {
    "thermal": {
      "type": "thermal",
      "params": {
        "edge_glow": 0.6,
        "color_mode": 1
      }
    }
  }
}
```

`agents/shaders/nodes/thermal.json` (params):

```json
{
  "params": {
    "edge_glow": {...},
    "palette_shift": {...}
  }
}
```

**Valid params are `edge_glow` and `palette_shift`.**
The preset's `color_mode: 1` is silently ignored.

**Likely intent**: the preset author expected multiple
thermal palette modes selectable via `color_mode`
(0=iron, 1=rainbow, 2=grayscale etc.). The actual
shader has `palette_shift` which is probably a
continuous float offset into a single palette.

**Fix options**:

- **Rename**: change `color_mode` to `palette_shift`
  and map the integer value (0, 1, 2...) to
  corresponding float offsets
- **Extend shader**: add a `color_mode` param to
  `thermal.frag` if multiple palettes are genuinely
  wanted
- **Remove**: just delete the `color_mode` key from the
  preset

**Recommendation**: remove the key. If the operator
wants multi-palette thermal, it's a feature request on
the shader, not a fixable preset typo.

### 2.2 Finding 3 — `tunnelvision.json` declares
`zoom_speed: 0.5`

`presets/tunnelvision.json` (excerpt):

```json
{
  "nodes": {
    "tunnel": {
      "type": "tunnel",
      "params": {
        "speed": 1.5,
        "twist": 0.4,
        "radius": 0.5,
        "zoom_speed": 0.5
      }
    }
  }
}
```

`agents/shaders/nodes/tunnel.json` (params):

```json
{
  "params": {
    "speed": {...},
    "twist": {...},
    "radius": {...},
    "distortion": {...},
    "time": {...}
  }
}
```

**Valid params are `speed, twist, radius, distortion, time`.**
The preset already sets `speed=1.5` directly, so the
`zoom_speed: 0.5` is redundant AND unknown.

**Likely intent**: the preset author may have copied
from another shader that had a `zoom_speed` param, or
was experimenting with a per-dimension speed split that
the shader never implemented.

**Fix**: remove the `zoom_speed` key. The preset
already has `speed=1.5` which is the real knob.

**Also per drop #44 finding 3**: this is the preset
that has the "tunnel_vision" / "tunnelvision" filename
typo in `_GENRE_BIAS`. So `tunnelvision.json` is doubly
unreachable — governance genre bias can't find it, AND
its `zoom_speed` param is a dead reference.

## 3. Ring summary

### Ring 1 — preset content corrections

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **PRC-1** | `slitscan_preset.json`: rename `delay` → `speed` | `presets/slitscan_preset.json` | 1 | Preset author's intent actually runs |
| **PRC-2** | `thermal_preset.json`: remove `color_mode` key | `presets/thermal_preset.json` | 1 | Dead key removed |
| **PRC-3** | `tunnelvision.json`: remove `zoom_speed` key | `presets/tunnelvision.json` | 1 | Dead key removed |

**Risk profile**: zero for all three. They're already
no-ops at runtime; removing them doesn't change visual
output. PRC-1 is the only one that changes visual
output (it activates the author's intent) — needs
operator verification that the `speed=0.4` slitscan
looks right.

### Ring 2 — validator tooling

| # | Fix | Scope |
|---|---|---|
| **PRC-4** | Add a `check-presets.py` script that runs the validation sweep from this drop as a pre-commit hook | New script, integrates with existing hook infrastructure |
| **PRC-5** | Add preset validation to the `_build_keyword_index` path in `chat_reactor.py` — log warnings at startup for any preset that has dead params | Startup-time detection, minimal surface |
| **PRC-6** | Have `GraphCompiler._validate` (already runs at `load_graph`) also warn on unknown params | Runtime warning, catches dynamically-constructed graphs |

**Risk profile**: PRC-4 is a new script (~50 lines of
code, mostly the logic from this drop). PRC-5 and PRC-6
add logging only. All three are zero-risk additions.

**Recommendation**: PRC-4 is the minimum viable
validator. Ship it alongside PRC-1/2/3.

## 4. Effect-system walk closeout

**Six drops, 25+ findings across the effect system** —
the walk is now complete for meaningful surface area.

| Drop | Focus | Key findings |
|---|---|---|
| #44 | Preset + layer + governance | 9 findings — 3 dead features (LayerPalette, PresetInput, temporal), 1 silent typo (tunnelvision genre bias), naming inconsistency |
| #45 | Shader complexity + temporal slot | 4 findings — 2 dead (temporal_slot.py, temporal_buffers), bloom/thermal 5×5 kernel hot spots |
| #46 | Mutation bus + module organization | 4 findings — random_mode polling undersampling, module mixed concerns (Reverie + compositor) |
| #47 | Dead feature inventory | 7 consolidated dead features (~350 LOC) + 624 LOC Reverie-only |
| #48 | Studio effects API routes | 4 findings — double-apply bug, dead API endpoint for LayerPalette, thread race, prior-art observability |
| #49 (this) | Preset content audit | 3 silent dead-param bugs |

**What's still unexplored after this walk**:

- **Individual shader source correctness** (55 `.frag`
  files) — a full line-by-line shader audit would find
  GLSL-level bugs, but the 3 hot shaders are covered in
  drop #45 and the branch-heavy ones are documented
- **Reverie-side wgsl_compiler / wgsl_transpiler** —
  out of scope for the compositor effect system (drop
  #46 finding 3)
- **Chain builder Logos UI** — frontend code, not
  compositor
- **The `logos_effect_graph` → WGSL pipeline** — bridges
  compositor and Reverie via the same shader definitions
  but runs in Reverie

**None of these are compositor effect-system hot paths.**
The effect system walk is as complete as the camera
pipeline walk now was.

### 4.1 Cumulative effect-system findings rollup

**Dead features that can ship as one cleanup PR**:

1. `LayerPalette` (drop #44 FX-5, drop #47 DR-1)
2. `PresetInput` + source-registry binding path
   (drop #44 FX-6, drop #47 DR-7)
3. `temporal_slot.py` (drop #45 FXS-1, drop #47 DR-2)
4. `temporal_buffers` schema field (drop #45 FXS-2,
   drop #47 DR-3)
5. `find_slot_for_node` prefix-match path (drop #47 DR-4)
6. `merge_default_modulations` type-to-ids dict
   (drop #47 DR-5)
7. `needs_dedicated_fbo` field (drop #47 DR-6)
8. `PATCH /studio/layer/{layer}/palette` API endpoint
   (drop #48 API-4)
9. `GET /studio/layer/status` API endpoint (drop #48,
   same dead feature chain)

**Bugs to fix**:

- `_GENRE_BIAS` typo `"tunnel_vision"` → `"tunnelvision"`
  (drop #44 FX-1)
- `slitscan_preset.delay` → `speed` (this drop PRC-1)
- `thermal_preset.color_mode` dead key (this drop PRC-2)
- `tunnelvision.zoom_speed` dead key (this drop PRC-3)
- `replace_effect_graph` double-apply (drop #48 API-1
  or API-2)
- `replace_modulations` thread race (drop #48 API-7)
- `merge_default_modulations` reads disk on every call
  (drop #44 FX-2)
- `copy.deepcopy` in `load_graph` (drop #44 FX-3)
- `random_mode` fade undersampled by state_reader
  polling (drop #46 MB-1)
- `chat_reactor` / `random_mode` exclusion-list drift
  (drop #46 MB-7)

**Observability to add**:

- Per-timer latency histograms for
  `fx_tick_callback`, `tick_governance`, `tick_modulator`,
  `tick_slot_pipeline` (drop #43 FXT-4)
- `compositor_fx_passthrough_slots` gauge (drop #38)
- Preset-load duration histogram (drop #44 FX-9)
- Log warning when `merge_default_modulations` finds
  multiple nodes of same type (drop #44 FX-4)
- `compositor_process_fd_count` gauge (drop #41 BT-5)

**Architectural decisions needed**:

- Ship or retire PresetInput / source-registry bindings
  (drop #44 FX-6, drop #47 DR-7)
- Move Reverie-only files out of `effect_graph/`
  (drop #46 MB-4, drop #47 DR-8)
- Bloom kernel 5×5 → 3×3 (FXS-3) OR separable Gaussian
  (FXS-4) OR downsample (FXS-5) — all optional

## 5. Cross-references

- `presets/slitscan_preset.json` — PRC-1
- `presets/thermal_preset.json` — PRC-2
- `presets/tunnelvision.json` — PRC-3
- `agents/shaders/nodes/slitscan.json` — valid params
- `agents/shaders/nodes/thermal.json` — valid params
- `agents/shaders/nodes/tunnel.json` — valid params
- `agents/effect_graph/compiler.py:263-294` — `_build`
  function (where params are merged without validation)
- `agents/effect_graph/pipeline.py:309-331` —
  `_apply_glfeedback_uniforms` (where unknown keys are
  silently dropped because the shader has no matching
  `u_XXX` uniform)
- Drop #44 — preset + governance walk (includes
  `_GENRE_BIAS` tunnelvision typo)
- Drops #45-#48 — rest of the effect-system walk
- Drop #38 — SlotPipeline architecture (context for
  how params flow into glfeedback)

## 6. End of the effect-system walk

**Effect-system walk complete.** 6 drops (#44-#49),
~2500 lines of research documentation, ~2800 lines
of compositor effect code audited, 25+ actionable
findings.

**Combined with the cam-pipeline walk** (drops #28-#43,
16 drops), this session has produced a comprehensive
audit of the compositor's hot path + control plane +
effect system: ~4500+ lines of research documentation,
total ~5300 lines of compositor code audited,
~50 Ring 1 fixes identified, ~30 Ring 2/3 architectural
items documented, and ~9 drops' worth of findings
already shipped to main by alpha.

**The compositor is now as thoroughly audited as a single
session can achieve.** Further research on this codebase
would have diminishing returns relative to shipping the
existing findings.

**Recommendation to alpha**: the dead-feature
consolidation PR (drops #44 FX-5, #45 FXS-1/FXS-2,
#47 DR-1 through DR-6, #48 API-4) is the highest-leverage
single cleanup available — ~500+ lines of dead code
removal in one coordinated removal, with zero runtime
risk.

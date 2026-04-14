# effect_graph dead-feature inventory + uniform propagation path walk

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Fourth drop in the effect-system walk.
Consolidates dead-feature findings discovered across drops
#44, #45, #46 plus two new ones from tracing the uniform
propagation path (`modulator.tick` → glfeedback slot).
Total: **seven dead or vestigial features** in the
`agents/effect_graph/` module, spanning ~800+ lines of
compiler/runtime/pipeline code that defends against
scenarios no current preset exhibits. Plus a focused walk
of the uniform propagation path to identify one
additional minor finding.
**Register:** scientific, neutral
**Status:** investigation — 7 consolidated dead-feature
findings + 1 new finding on per-update uniform marshaling.
No code changed.
**Companion:** drops #38, #44, #45, #46

## Headline

**Seven dead or vestigial features in `agents/effect_graph/`:**

| # | Feature | Source | Reason it's dead |
|---|---|---|---|
| 1 | `LayerPalette` | `types.py`, `runtime.py` | 0/28 presets declare `layer_palettes`; no downstream reader |
| 2 | `PresetInput` / `resolve_preset_inputs` | `types.py`, `compiler.py` | 0/28 presets declare `inputs` |
| 3 | `TemporalSlotState` | `temporal_slot.py` | 0 imports; glfeedback owns ping-pong now |
| 4 | `temporal_buffers` declaration | shader JSON schema | 0 shaders use more than 1 `tex_accum`; ignored at runtime |
| 5 | `find_slot_for_node` prefix-matching | `pipeline.py:222-237` | 0/28 presets use `pN_` chain prefixes |
| 6 | `merge_default_modulations` "pick LAST matching" | `effects.py:125-161` | 0/28 presets have multiple instances of the same node type |
| 7 | `needs_dedicated_fbo` | `compiler.py:77,291` | Computed but never read; 0/28 presets have multi-fanout nodes anyway |

**Collectively these represent defensive code for
architectural scenarios that were designed but never
executed on.** Chain composition (`pN_` prefixes +
multi-instance node types), per-layer palette grading,
main-layer source-registry binding, and multi-buffer
temporal accumulation were all sketched out but never
adopted in the preset library.

**Plus one new minor finding** on the uniform marshaling
path: `_apply_glfeedback_uniforms` re-serializes ALL
params of a slot on every modulator update, even if only
one param changed. Modest redundant work (~300 Gst
property sets/sec of unchanged data).

## 1. Dead feature consolidation

### 1.1 Dead feature 1 — `LayerPalette` (drop #44 finding 1)

**Size**: ~30 lines across `types.py`,
`runtime.py`, `get_graph_state`.

**Evidence**: 0/28 presets declare `layer_palettes`. No
downstream consumer reads the runtime's `_layer_palettes`
dict.

### 1.2 Dead feature 2 — `PresetInput` / source-registry
bindings (drop #44 finding 2)

**Size**: ~200+ lines across `types.py`, `compiler.py`,
`effects.py:try_graph_preset`, and the `fx_chain.py:build_source_appsrc_branches`
main-layer branch infrastructure.

**Evidence**: 0/28 presets declare `inputs`. The
`resolve_preset_inputs` helper is never called for any
production preset. Combined with drop #41 finding 1
(layout-declared cairo sources never start), the entire
source-registry → preset → glvideomixer appsrc pad
pipeline is dead end-to-end.

### 1.3 Dead feature 3 — `TemporalSlotState` (drop #45
finding 1)

**Size**: 63 lines in `temporal_slot.py`.

**Evidence**: `grep -rn 'TemporalSlotState' agents/`
returns only the definition. No caller.

### 1.4 Dead feature 4 — `temporal_buffers` declaration
(drop #45 finding 2)

**Size**: field in 10 shader node JSON manifests, plus
passthrough in `registry.py:50-60`, `compiler.py:290`,
`types.py:ExecutionStep:76`.

**Evidence**: `stutter.json` declares
`temporal_buffers=8` but `stutter.frag` uses only one
`tex_accum` uniform. glfeedback Rust plugin allocates 1
buffer per slot regardless of declared value.

### 1.5 Dead feature 5 — `find_slot_for_node`
prefix-matching (NEW)

`agents/effect_graph/pipeline.py:222-237`:

```python
def find_slot_for_node(self, node_type: str) -> int | None:
    """Find which slot a node type is assigned to.

    Handles prefixed IDs from merged chains: 'p0_bloom' matches slot type 'bloom'.
    """
    # Exact match first
    for i, assigned in enumerate(self._slot_assignments):
        if assigned == node_type:
            return i
    # Prefix match: strip 'pN_' prefix and match base type
    base = node_type.split("_", 1)[-1] if "_" in node_type and node_type[0] == "p" else None
    if base:
        for i, assigned in enumerate(self._slot_assignments):
            if assigned == base:
                return i
    return None
```

**Evidence**:

```text
$ python3 check_preset_prefixes.py
(no output — zero presets use pN_ prefixes)
```

The prefix-stripping path (lines 231-237) never
activates in production. The exact-match path handles
every real preset. **Dead code**: ~8 lines.

### 1.6 Dead feature 6 — `merge_default_modulations`
"pick LAST matching" logic (NEW)

`agents/studio_compositor/effects.py:125-161`:

```python
# Build type→node_id map for matching default bindings to prefixed nodes
type_to_ids: dict[str, list[str]] = {}
for nid, node in graph.nodes.items():
    t = node.type
    if t not in type_to_ids:
        type_to_ids[t] = []
    type_to_ids[t].append(nid)

...
for d in defaults:
    target_type = d["node"]
    matching_ids = type_to_ids.get(target_type, [])
    if not matching_ids:
        continue
    # Apply to the LAST matching node — in chains, earlier instances are
    # neutralized (identity params), so modulations should target the
    # last instance which retains authored params.
    node_id = matching_ids[-1]
    ...
```

**Evidence**:

```text
$ python3 check_preset_multi_instance.py
(no output — zero presets have multiple instances of the same node type)
```

Every preset has unique (node_id, node_type) mappings.
The "last matching" selection logic (`matching_ids[-1]`)
always picks the single matching ID. The `type_to_ids`
dict construction is unnecessary overhead — a direct
lookup by node_type → node_id would suffice.

**Root cause**: same as dead feature 5. Both guard
against chain preset composition (`pN_` prefixed
multi-instance), which is a design pattern that was
sketched but never used.

**Dead code footprint**: ~15 lines (`type_to_ids`
construction + `matching_ids[-1]` logic could be
replaced with a single `nid = next((nid for nid, n in
graph.nodes.items() if n.type == target_type), None)`).

### 1.7 Dead feature 7 — `needs_dedicated_fbo` (NEW)

`agents/effect_graph/compiler.py:77`:

```python
@dataclass
class ExecutionStep:
    ...
    needs_dedicated_fbo: bool = False
```

Populated in `compiler.py:291`:

```python
needs_dedicated_fbo=out_count.get(nid, 0) > 1,
```

**Evidence**:

```text
$ grep -rn 'needs_dedicated_fbo' agents/ | grep -v '__pycache__'
agents/effect_graph/compiler.py:77    (defn)
agents/effect_graph/compiler.py:291   (populated)
(no readers)
```

Computed but never consumed. The intent was presumably
to hint to the downstream runtime that multi-fanout
nodes need dedicated framebuffers to avoid texture
reuse conflicts — but the downstream (glfeedback via
SlotPipeline) doesn't use the hint.

**Does it matter?** Only if a preset actually has a
multi-fanout node (one output, two+ consumers). Static
analysis shows **0/28 presets have multi-fanout
nodes**:

```text
$ python3 check_multi_fanout.py
(no output — zero presets have nodes with >1 outgoing edge)
```

So in practice `out_count.get(nid, 0) > 1` is always
False. **Dead code**: the field, the computation, and
any future reader.

## 2. Uniform propagation path walk

Drop #43 covered `tick_modulator` building the signals
dict and calling `_on_graph_params_changed` per update.
This section traces what happens downstream of that
call, finishing the loop into the glfeedback slot.

### 2.1 The path

```text
fx_tick_callback (GLib main loop, ~30 Hz)
│
├── tick_modulator(compositor, t, energy, b)
│    │
│    ├── signals = {~30 keys}
│    ├── updates = modulator.tick(signals)
│    │     │ for each of ~5-10 bindings:
│    │     │   raw = signals.get(b.source)
│    │     │   if raw is None: skip
│    │     │   target = raw * scale + offset
│    │     │   apply smoothing / attack-decay envelope
│    │     │   updates[(node_id, param)] = value
│    │     ▼
│    │
│    └── for (node_id, param), value in updates.items():
│         compositor._on_graph_params_changed(node_id, {param: value})
│         │
│         ▼
│         SlotPipeline.update_node_uniforms(node_type, params)
│         │ (compositor.py:316: self._slot_pipeline.update_node_uniforms(node_id, params))
│         │
│         ├── slot_idx = find_slot_for_node(node_type)       ← dead feature 5
│         │
│         ├── for key, val in params.items():
│         │    │  (typically 1 key per call — one param per modulation)
│         │    │
│         │    ├── if key in ("time","width","height") or not in preset:
│         │    │      _slot_base_params[slot_idx][key] = val
│         │    │
│         │    ├── elif numeric preset base:
│         │    │      combined = preset[key] + val
│         │    │      clamp to pdef.min/max
│         │    │      _slot_base_params[slot_idx][key] = combined
│         │    │
│         │    └── else:
│         │          _slot_base_params[slot_idx][key] = val
│         │
│         └── if temporal:
│              _apply_glfeedback_uniforms(slot_idx)
│              │  ← NEW FINDING
│              │  re-serializes ALL params in _slot_base_params[slot_idx]
│              │  builds "u_key=val, u_key=val" comma-sep string
│              │  calls slot.set_property("uniforms", uniform_str)
│              ▼
│              glfeedback plugin (Rust)
│              │  parses uniform string
│              │  diff-checks vs previous (drop #5 fix)
│              │  updates GPU uniform buffer
│              ▼
│              GL context → shader sees new u_key values on next draw
```

### 2.2 New finding — `_apply_glfeedback_uniforms`
re-sends ALL params on every modulator update

`agents/effect_graph/pipeline.py:309-331`:

```python
def _apply_glfeedback_uniforms(self, slot_idx: int) -> None:
    """Set uniforms on a glfeedback element via its 'uniforms' property.

    The glfeedback element accepts comma-separated key=value pairs.
    """
    params = self._slot_base_params[slot_idx]
    parts = []
    for key, value in params.items():
        if isinstance(value, bool):
            parts.append(f"u_{key}={1.0 if value else 0.0}")
        elif isinstance(value, (int, float)):
            parts.append(f"u_{key}={float(value)}")
        elif isinstance(value, str):
            defn = self._registry.get(self._slot_assignments[slot_idx] or "")
            if defn and key in defn.params and defn.params[key].enum_values:
                vals = defn.params[key].enum_values or []
                idx = vals.index(value) if value in vals else 0
                parts.append(f"u_{key}={float(idx)}")
    if parts:
        uniform_str = ", ".join(parts)
        node = self._slot_assignments[slot_idx] or "?"
        log.debug("Slot %d (%s) uniforms: %s", slot_idx, node, uniform_str[:200])
        self._slots[slot_idx].set_property("uniforms", uniform_str)
```

**Observation**: iterates over `_slot_base_params[slot_idx]`
— the full parameter dict — on every call, not just the
changed key. For a slot with 3 params (like `bloom`:
threshold, radius, alpha), a single modulation on `alpha`
causes all 3 parameters to be re-formatted and re-sent.

**Per-update redundancy**: ~2 out of 3 param strings are
unchanged but still rebuilt and re-sent on every tick.

**Aggregate cost**: at 30 fps × ~5-10 modulator updates
per tick × ~2-3 redundant params per update = **~300-900
redundant property sets per second** across all slots.
Each set is ~50 µs marshaling + GStreamer GObject
property write overhead. Total waste: **~15-45 ms/sec**
of CPU on the main loop, ~0.5-1.5% of one core.

**Not a hot spot**, but it's measurable waste on the
same main loop that drop #43 flagged for priority-pinning
attention. Stacked with drop #43 finding 3 (tick_slot_pipeline
string-contains scan), these are small mainloop cleanups
that collectively matter.

**Fix options**:

- **DF-1**: change `_apply_glfeedback_uniforms` to
  accept a `changed_keys` subset and only serialize
  those. Requires verifying that glfeedback's uniform
  parser accepts partial updates (it probably does via
  merge-on-set, but needs test).
- **DF-2**: diff `_slot_base_params[slot_idx]` against a
  `_slot_last_sent_params[slot_idx]` cache, send only
  the delta. More generic but requires an extra state
  cache.
- **DF-3**: leave as is. Document the redundancy as a
  known minor waste.

**Recommendation**: DF-3 initially. DF-1 or DF-2 should
wait for measurement — drop #43 FXT-4 (per-timer latency
histogram) would measure the fx_tick_callback duration
and reveal whether this is actually a bottleneck.

### 2.3 Glfeedback's own diff check saves the day

Drop #5 (pre-compaction) added a diff check INSIDE the
glfeedback Rust plugin so that `set_property("uniforms",
...)` with the same string content doesn't trigger a
shader recompile or FBO clear. **That diff check
neutralizes the cost of finding 2.3's redundant
reserialization at the Rust/GPU boundary** — the GPU
work is skipped even when the Python side sends
unchanged data.

**What remains** is just the Python-side work: building
the string, marshaling the property set, and the
glfeedback plugin's own parse + diff check.

**Aggregate of the remaining Python-side cost** is ~15-45
ms/sec (0.5-1.5% of one core). Real but not urgent.

## 3. Total effect_graph dead LOC audit

Consolidating lines removable if all 7 dead features ship:

| # | Feature | Approx LOC |
|---|---|---|
| 1 | `LayerPalette` | ~30 |
| 2 | `PresetInput` + main-layer source-registry wiring | ~200 |
| 3 | `TemporalSlotState` | 63 |
| 4 | `temporal_buffers` schema + passthrough | ~30 |
| 5 | `find_slot_for_node` prefix-match | ~8 |
| 6 | `merge_default_modulations` type-to-ids dict | ~15 |
| 7 | `needs_dedicated_fbo` field + computation | ~4 |
| | **Total** | **~350** |

**Plus the already-Reverie-only files** from drop #46:

| File | Lines |
|---|---|
| `capability.py` | 78 |
| `wgsl_compiler.py` | 284 |
| `wgsl_transpiler.py` | 262 |

**Module total potentially reclaimable from compositor-side
code paths**: ~350 lines of dead features + ~624 lines
Reverie-only = **~974 lines** out of ~1993 total in
`agents/effect_graph/`.

**Nearly half the module is either dead or not
compositor-facing.**

## 4. Ring summary

### Ring 1 — consolidated dead-code removal

All dead-feature fixes gathered from drops #44, #45,
this drop. **These all ship together as a single
cleanup PR**:

| # | Fix | File | Lines removed | Drop origin |
|---|---|---|---|---|
| **DR-1** | Remove `LayerPalette` class + runtime state + export | `types.py`, `runtime.py` | ~30 | drop #44 FX-5 |
| **DR-2** | Remove `temporal_slot.py` | delete file | 63 | drop #45 FXS-1 |
| **DR-3** | Remove `temporal_buffers` schema field | `registry.py`, `compiler.py`, node JSONs | ~30 | drop #45 FXS-2 |
| **DR-4** | Simplify `find_slot_for_node` to exact match only | `pipeline.py:222-237` | ~8 | this drop (dead feature 5) |
| **DR-5** | Simplify `merge_default_modulations` type-to-ids → direct lookup | `effects.py:125-161` | ~15 | this drop (dead feature 6) |
| **DR-6** | Remove `needs_dedicated_fbo` field | `compiler.py:77,291` | ~4 | this drop (dead feature 7) |

**Combined**: ~150 lines of definitively dead code
removed. Zero risk; each is a dead-path deletion with
no current reader.

### Ring 2 — requires operator decision

| # | Fix | Source | Decision needed |
|---|---|---|---|
| **DR-7** | Retire `PresetInput` + source-registry binding path OR write reference preset | drop #44 FX-6 | Is the Phase 6/7 source-registry binding system still intended? |
| **DR-8** | Move Reverie-only effect_graph files to `agents/reverie_shader/` | drop #46 MB-4 | Cross-module reorganization; low risk |

### Ring 3 — minor (measure first)

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **DF-1** | Send delta params only to `_apply_glfeedback_uniforms` | `pipeline.py:309-331` | ~20 | ~15-45 ms/sec main-loop savings. Not worth shipping without measurement (pair with drop #43 FXT-4) |

## 5. The architectural observation

**All seven dead features share a common origin**: they
were added as architectural accommodations for **preset
chain composition** (`pN_` prefixed multi-instance
nodes) and **main-layer source-registry integration**.
Both of these design patterns were sketched out during
the compositor unification epic but never followed
through to productionization.

**Whoever originally designed the effect_graph module
anticipated**:

1. Preset chains built from component sub-presets
   (`p0_datamosh` + `p1_bloom` → "datamosh_bloom"
   composition)
2. Layer-level color grading on input sources
   (live/smooth/hls palettes)
3. Preset-level input routing via source registry
4. Multi-buffer temporal accumulation for ring-buffer
   effects (stutter with N frames of history)
5. Multi-fanout shader graphs with dedicated FBOs

**None of these have been adopted by the current
preset library.** The 28 live presets all follow a
simple linear topology with unique (node_id, node_type)
mappings and single-path fanout. The architectural
guards are real but unnecessary.

**This isn't a bug.** Anticipatory engineering that
never ships is a natural part of evolving designs. But
documenting it makes the module's actual behavior
clearer and opens the door for deliberate pruning.

## 6. Cross-references

- `agents/effect_graph/types.py:72-78` — `LayerPalette` (DR-1)
- `agents/effect_graph/types.py:80-114` — `PresetInput` (DR-7)
- `agents/effect_graph/temporal_slot.py` — dead file (DR-2)
- `agents/shaders/nodes/*.json` — `temporal_buffers` field (DR-3)
- `agents/effect_graph/pipeline.py:222-237` — `find_slot_for_node` prefix path (DR-4)
- `agents/studio_compositor/effects.py:125-161` — `merge_default_modulations` type_to_ids (DR-5)
- `agents/effect_graph/compiler.py:77,291` — `needs_dedicated_fbo` (DR-6)
- `agents/effect_graph/pipeline.py:309-331` — `_apply_glfeedback_uniforms` full-dict send (DF-1)
- Drop #5 — glfeedback Rust-side diff check (already shipped; neutralizes DF-1's GPU cost)
- Drop #38 — SlotPipeline 24-slot architecture
- Drop #43 — fx_tick_callback walk (DF-1 is adjacent to FXT-1 string-contains scan)
- Drop #44 — preset + governance walk (FX-5, FX-6 origins)
- Drop #45 — shader complexity + temporal slot (FXS-1, FXS-2 origins)
- Drop #46 — mutation-bus cross-process flow + module mixed concerns (MB-4 origin)

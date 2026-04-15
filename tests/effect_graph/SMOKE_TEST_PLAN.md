# Effect Graph System — Backend Smoke Test Plan

Systematic test plan exercising all major and minor backend features.
Tests are grouped by layer, ordered from foundational to integration.
All tests are backend-only — no frontend/browser required.

**Prerequisites**: `logos-api` running on `:8051`, `studio-compositor` running.
**Tool**: `curl` for API tests, `pytest` for unit tests.

---

## Layer 1: Type System & Registry (foundational, no API needed)

```bash
uv run pytest tests/effect_graph/test_smoke.py -v -q
```

Covers:
- [ ] ParamDef: float, int, bool, enum, vec2 types
- [ ] PortType: FRAME, SCALAR, COLOR values
- [ ] EdgeDef: simple, with ports, layer sources (@live/@smooth/@hls)
- [ ] NodeInstance: with params, empty, nested
- [ ] ModulationBinding: defaults, custom scale/offset/smoothing, bounds enforcement
- [ ] EffectGraph: minimal, parsed_edges, modulations, transition_ms
- [ ] GraphPatch: empty, add nodes/edges, remove nodes/edges
- [ ] Registry: loads all 54 node types, sorted, unknown returns None
- [ ] Registry: all node categories (35 processing, 6 temporal, 5 compositing, 3 generative, 2 meta)
- [ ] Registry: all non-output/palette nodes have GLSL source with `main()` and `gl_FragColor`
- [ ] Registry: all schemas JSON-serializable
- [ ] Registry: param completeness (colorgrade has 5 params, trail has 5, bloom has 3, vhs has 1, blend has 2)

**Expected**: 167+ tests pass, 0 failures.

---

## Layer 2: Compiler Validation

```bash
uv run pytest tests/effect_graph/test_smoke.py -k "Compiler" -v
```

- [ ] Rejects graph with no output node
- [ ] Rejects graph with unknown node type
- [ ] Rejects graph with cycle (A→B→A)
- [ ] Rejects graph with disconnected nodes
- [ ] Rejects invalid layer source (@invalid)
- [ ] Accepts valid layer sources (@live, @smooth, @hls)
- [ ] Topological sort: linear chain produces correct order
- [ ] Topological sort: diamond dependency resolves correctly
- [ ] Topological sort: multi-source inputs handled
- [ ] Execution plan: steps have shader_source, params, edges
- [ ] Execution plan: layer_sources set populated
- [ ] Execution plan: transition_ms preserved

---

## Layer 3: Runtime Mutations

```bash
uv run pytest tests/effect_graph/test_smoke.py -k "Runtime" -v
```

- [ ] Initial state: current_graph is None, current_plan is None
- [ ] load_graph: stores graph, compiles plan, fires _on_plan_changed
- [ ] Level 1 (param patch): updates params without recompile, fires _on_params_changed
- [ ] Level 2 (topology): apply_patch adds/removes nodes, recompiles, fires _on_plan_changed
- [ ] Level 3 (full replace): load_graph replaces everything
- [ ] remove_node: deletes node and connected edges
- [ ] Layer palettes: set, get, defaults to neutral
- [ ] State export: get_graph_state returns full state dict

---

## Layer 4: Modulator Signal Processing

```bash
uv run pytest tests/effect_graph/test_smoke.py -k "Modulator" -v
```

- [ ] add_binding: adds new, replaces existing (same node+param)
- [ ] remove_binding: removes and clears smoothed cache
- [ ] replace_all: atomic clear and reload
- [ ] tick: processes signals, returns (node, param) → value updates
- [ ] tick: missing signal source silently skipped
- [ ] tick: scale/offset applied (target = raw × scale + offset)
- [ ] Smoothing: 0.0 = direct, 0.85 = EMA, first frame = no smoothing
- [ ] Smoothing bounds: [0.0, 1.0] enforced by Pydantic

---

## Layer 5: Pipeline Slot Assignment

```bash
uv run pytest tests/effect_graph/test_pipeline.py -v
```

- [ ] 8 slots created by default
- [ ] activate_plan assigns nodes in topological order
- [ ] activate_plan skips output node
- [ ] activate_plan truncates with warning if >8 nodes
- [ ] activate_plan clears unused slots to passthrough
- [ ] find_slot_for_node returns correct index
- [ ] find_slot_for_node returns None for unassigned type
- [ ] update_node_uniforms routes to correct slot
- [ ] Uniform encoding: bool→float, int→float, enum→index

---

## Layer 6: Preset Loading & Compilation

```bash
uv run pytest tests/effect_graph/test_smoke.py -k "Preset" -v
```

Then verify all 28 presets load and compile:

```bash
uv run python3 -c "
from pathlib import Path
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.types import EffectGraph
import json

registry = ShaderRegistry(Path('agents/shaders/nodes'))
compiler = GraphCompiler(registry)
presets_dir = Path('presets')
failed = []
for p in sorted(presets_dir.glob('*.json')):
    if p.name.startswith('_'): continue
    try:
        graph = EffectGraph(**json.loads(p.read_text()))
        plan = compiler.compile(graph)
        nodes = len(plan.steps)
        print(f'  OK  {p.stem:30s}  ({nodes} nodes, {len(graph.modulations)} modulations)')
    except Exception as e:
        failed.append((p.stem, str(e)))
        print(f'  FAIL {p.stem}: {e}')
if failed:
    print(f'\n{len(failed)} FAILED')
else:
    print(f'\nAll {len(list(presets_dir.glob(\"*.json\")))-1} presets compile OK')
"
```

- [ ] All 28 presets parse as valid EffectGraph
- [ ] All 28 presets compile to ExecutionPlan without errors
- [ ] Each preset has at least one non-output node
- [ ] Presets with modulations reference valid node IDs in their graph

---

## Layer 7: Default Modulation Merge

```bash
uv run python3 -c "
import json
from pathlib import Path
from agents.effect_graph.types import EffectGraph

defaults = json.loads(Path('presets/_default_modulations.json').read_text())
print(f'Default modulation template: {len(defaults)} bindings')
for b in defaults:
    print(f'  {b[\"node\"]}.{b[\"param\"]} ← {b[\"source\"]} (scale={b.get(\"scale\",1)}, smooth={b.get(\"smoothing\",0.85)})')

# Test merge: ghost has trail+bloom, should get defaults for those
ghost = EffectGraph(**json.loads(Path('presets/ghost.json').read_text()))
ghost_nodes = set(ghost.nodes.keys())
applicable = [b for b in defaults if b['node'] in ghost_nodes]
print(f'\nGhost has nodes: {sorted(ghost_nodes)}')
print(f'Applicable defaults: {len(applicable)}')
for b in applicable:
    print(f'  {b[\"node\"]}.{b[\"param\"]} ← {b[\"source\"]}')
"
```

- [ ] `_default_modulations.json` exists and parses
- [ ] Defaults only merge for nodes present in graph
- [ ] Graph's own modulations take precedence over defaults

---

## Layer 8: API Routes — Graph Management

Requires `logos-api` running on `:8051`.

```bash
# 8.1 Get current graph (may be null initially)
curl -s localhost:8051/api/studio/effect/graph | python3 -m json.tool | head -5

# 8.2 Load a preset via API
curl -s -X POST localhost:8051/api/studio/presets/ghost/activate | python3 -m json.tool

# 8.3 Get graph after activation
curl -s localhost:8051/api/studio/effect/graph | python3 -m json.tool | head -10

# 8.4 Patch node params (no recompile)
curl -s -X PATCH localhost:8051/api/studio/effect/graph/node/trail/params \
  -H 'Content-Type: application/json' \
  -d '{"fade": 0.02, "opacity": 0.6}' | python3 -m json.tool

# 8.5 Delete a node (triggers recompile)
curl -s -X DELETE localhost:8051/api/studio/effect/graph/node/bloom | python3 -m json.tool

# 8.6 Apply topology patch (add node back)
curl -s -X PATCH localhost:8051/api/studio/effect/graph \
  -H 'Content-Type: application/json' \
  -d '{"add_nodes": {"bloom2": {"type": "bloom", "params": {"threshold": 0.3}}}, "add_edges": [["trail", "bloom2"], ["bloom2", "out"]]}' | python3 -m json.tool
```

- [ ] GET graph returns null or current state
- [ ] POST activate loads and compiles preset
- [ ] GET graph after activation returns full graph
- [ ] PATCH params updates without recompile
- [ ] DELETE node removes node and edges, recompiles
- [ ] PATCH topology adds nodes/edges, recompiles

---

## Layer 9: API Routes — Modulations

```bash
# 9.1 Get current modulations
curl -s localhost:8051/api/studio/effect/graph/modulations | python3 -m json.tool

# 9.2 Replace all modulations
curl -s -X PUT localhost:8051/api/studio/effect/graph/modulations \
  -H 'Content-Type: application/json' \
  -d '[{"node":"trail","param":"opacity","source":"audio_rms","scale":0.3,"offset":0.2,"smoothing":0.85}]' | python3 -m json.tool

# 9.3 Verify replacement
curl -s localhost:8051/api/studio/effect/graph/modulations | python3 -m json.tool
```

- [ ] GET modulations returns current bindings list
- [ ] PUT modulations replaces all atomically
- [ ] Replaced bindings visible on subsequent GET

---

## Layer 10: API Routes — Layer Control

```bash
# 10.1 Enable/disable layer
curl -s -X PATCH localhost:8051/api/studio/layer/smooth/enabled \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true}' | python3 -m json.tool

# 10.2 Verify flag file created
cat /dev/shm/hapax-compositor/layer-smooth-enabled.txt

# 10.3 Set smooth delay
curl -s -X PATCH localhost:8051/api/studio/layer/smooth/delay \
  -H 'Content-Type: application/json' \
  -d '{"delay_seconds": 3.0}' | python3 -m json.tool

# 10.4 Verify delay file
cat /dev/shm/hapax-compositor/smooth-delay.txt

# 10.5 Invalid layer name → 400
curl -s -X PATCH localhost:8051/api/studio/layer/invalid/enabled \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true}' -w "\n%{http_code}"

# 10.6 Invalid delay value → 400
curl -s -X PATCH localhost:8051/api/studio/layer/smooth/delay \
  -H 'Content-Type: application/json' \
  -d '{"delay_seconds": 50}' -w "\n%{http_code}"
```

- [ ] PATCH enabled writes flag file to /dev/shm
- [ ] PATCH delay writes seconds to /dev/shm
- [ ] Invalid layer name returns 400
- [ ] Out-of-range delay returns 400

---

## Layer 11: API Routes — Preset CRUD

```bash
# 11.1 List all presets
curl -s localhost:8051/api/studio/presets | python3 -m json.tool | head -20

# 11.2 Get specific preset
curl -s localhost:8051/api/studio/presets/ghost | python3 -m json.tool | head -10

# 11.3 Save user preset
curl -s -X PUT localhost:8051/api/studio/presets/test_smoke \
  -H 'Content-Type: application/json' \
  -d '{"name":"smoke test","description":"test","transition_ms":500,"nodes":{"cg":{"type":"colorgrade","params":{"saturation":1.5}},"out":{"type":"output","params":{}}},"edges":[["@live","cg"],["cg","out"]],"modulations":[]}' | python3 -m json.tool

# 11.4 Verify saved preset appears in list
curl -s localhost:8051/api/studio/presets | python3 -c "import sys,json; d=json.load(sys.stdin); print([p['name'] for p in d['presets'] if p['name']=='test_smoke'])"

# 11.5 Activate user preset
curl -s -X POST localhost:8051/api/studio/presets/test_smoke/activate | python3 -m json.tool

# 11.6 Delete user preset
curl -s -X DELETE localhost:8051/api/studio/presets/test_smoke | python3 -m json.tool

# 11.7 Delete builtin preset → 403
curl -s -X DELETE localhost:8051/api/studio/presets/ghost -w "\n%{http_code}"

# 11.8 Get nonexistent preset → 404
curl -s localhost:8051/api/studio/presets/nonexistent -w "\n%{http_code}"
```

- [ ] GET presets lists 28+ presets with name, display_name, description
- [ ] GET preset returns full graph JSON
- [ ] PUT preset saves to user directory
- [ ] Saved preset appears in subsequent list
- [ ] POST activate loads user preset
- [ ] DELETE user preset succeeds
- [ ] DELETE builtin preset returns 403
- [ ] GET nonexistent preset returns 404

---

## Layer 12: API Routes — Node Registry

```bash
# 12.1 List all node types
curl -s localhost:8051/api/studio/effect/nodes | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d[\"nodes\"])} node types')"

# 12.2 Get specific node schema
curl -s localhost:8051/api/studio/effect/nodes/colorgrade | python3 -m json.tool

# 12.3 Get temporal node
curl -s localhost:8051/api/studio/effect/nodes/trail | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'temporal={d.get(\"temporal\")}, buffers={d.get(\"temporal_buffers\")}')"

# 12.4 Unknown node → 404
curl -s localhost:8051/api/studio/effect/nodes/nonexistent -w "\n%{http_code}"
```

- [ ] Returns 54 node types
- [ ] Each schema has node_type, inputs, outputs, params
- [ ] Temporal nodes marked with temporal=true, temporal_buffers≥1
- [ ] Unknown node type returns 404

---

## Layer 13: API Routes — Camera Control

```bash
# 13.1 List cameras
curl -s localhost:8051/api/studio/cameras | python3 -m json.tool

# 13.2 Select hero camera
curl -s -X POST localhost:8051/api/studio/camera/select \
  -H 'Content-Type: application/json' \
  -d '{"role": "brio-operator"}' | python3 -m json.tool

# 13.3 Verify flag file
cat /dev/shm/hapax-compositor/hero-camera.txt

# 13.4 Invalid request → 400
curl -s -X POST localhost:8051/api/studio/camera/select \
  -H 'Content-Type: application/json' \
  -d '{}' -w "\n%{http_code}"
```

- [ ] GET cameras returns camera list from status.json
- [ ] POST select writes role to hero-camera.txt
- [ ] Missing role returns 400

---

## Layer 14: Compositor Integration (requires running compositor)

```bash
# 14.1 Verify graph runtime initialized
curl -s localhost:8051/api/studio/effect/nodes | python3 -c "import sys,json; n=len(json.load(sys.stdin)['nodes']); print(f'Registry: {n} nodes'); assert n==54"

# 14.2 Activate preset via shm (compositor polling)
echo "ghost" > /dev/shm/hapax-compositor/fx-request.txt
sleep 2
cat /dev/shm/hapax-compositor/fx-current.txt

# 14.3 Verify alias resolution
echo "vhs" > /dev/shm/hapax-compositor/fx-request.txt
sleep 2
cat /dev/shm/hapax-compositor/fx-current.txt

# 14.4 Check FX snapshot produced
ls -la /dev/shm/hapax-compositor/fx-snapshot.jpg

# 14.5 Check smooth snapshot produced
ls -la /dev/shm/hapax-compositor/smooth-snapshot.jpg
```

- [ ] Graph runtime initializes with 54 node types
- [ ] fx-request.txt triggers preset switch
- [ ] Alias resolution (vhs → vhs_preset) works
- [ ] FX snapshot JPEG produced in /dev/shm
- [ ] Smooth snapshot JPEG produced in /dev/shm

---

## Layer 15: Error Handling & Edge Cases

```bash
# 15.1 Empty graph → validation error
curl -s -X PUT localhost:8051/api/studio/effect/graph \
  -H 'Content-Type: application/json' \
  -d '{"name":"empty","nodes":{},"edges":[]}' -w "\n%{http_code}"

# 15.2 Cycle detection
curl -s -X PUT localhost:8051/api/studio/effect/graph \
  -H 'Content-Type: application/json' \
  -d '{"name":"cycle","nodes":{"a":{"type":"colorgrade"},"b":{"type":"bloom"},"out":{"type":"output"}},"edges":[["@live","a"],["a","b"],["b","a"],["a","out"]]}' -w "\n%{http_code}"

# 15.3 Unknown node type
curl -s -X PUT localhost:8051/api/studio/effect/graph \
  -H 'Content-Type: application/json' \
  -d '{"name":"bad","nodes":{"x":{"type":"nonexistent"},"out":{"type":"output"}},"edges":[["@live","x"],["x","out"]]}' -w "\n%{http_code}"

# 15.4 Rapid preset switching (stress test)
for p in ghost trails neon vhs_preset clean screwed trap; do
  curl -s -X POST localhost:8051/api/studio/presets/$p/activate > /dev/null
  sleep 0.1
done
echo "Rapid switching complete"

# 15.5 Modulation with missing signal (should not crash)
curl -s -X PUT localhost:8051/api/studio/effect/graph/modulations \
  -H 'Content-Type: application/json' \
  -d '[{"node":"trail","param":"opacity","source":"nonexistent_signal","scale":1}]'
sleep 1
curl -s localhost:8051/api/studio/effect/graph | python3 -c "import sys,json; print('Graph still active:', json.load(sys.stdin).get('name','none'))"
```

- [ ] Empty graph returns 400 (no output node)
- [ ] Cyclic graph returns 400
- [ ] Unknown node type returns 400
- [ ] Rapid preset switching doesn't crash
- [ ] Missing modulation signal doesn't crash (silently skipped)

---

## Execution Summary

| Layer | Tests | Method | Requires |
|-------|-------|--------|----------|
| 1. Types & Registry | ~90 | pytest | Nothing |
| 2. Compiler | ~15 | pytest | Nothing |
| 3. Runtime | ~30 | pytest | Nothing |
| 4. Modulator | ~20 | pytest | Nothing |
| 5. Pipeline | ~9 | pytest | Nothing |
| 6. Presets | ~28 | python script | Nothing |
| 7. Default Modulations | ~3 | python script | Nothing |
| 8. API: Graph | 6 | curl | logos-api |
| 9. API: Modulations | 3 | curl | logos-api |
| 10. API: Layers | 8 | curl | logos-api |
| 11. API: Presets | 8 | curl | logos-api |
| 12. API: Nodes | 4 | curl | logos-api |
| 13. API: Cameras | 4 | curl | logos-api |
| 14. Compositor | 5 | shm files | compositor |
| 15. Edge Cases | 5 | curl | logos-api |
| **Total** | **~238** | | |

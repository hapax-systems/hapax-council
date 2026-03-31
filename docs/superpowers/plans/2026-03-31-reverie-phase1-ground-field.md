# Phase 1: Expand the Ground Field — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `reaction_diffusion` node to the Reverie core graph, making the surface a living, self-organizing ground field instead of static procedural noise.

**Architecture:** Insert R-D between `noise` and `colorgrade` in the vocabulary graph. R-D is temporal (`@accum_rd`) — it reads its own previous output each frame, enabling self-organizing pattern evolution. The visual chain already has R-D parameter bindings defined (`rd.f_delta`, `rd.da_delta`) but they currently target an absent node. This phase activates them.

**Tech Stack:** Python (visual chain, tests), JSON (vocabulary preset), Rust (already handles temporal nodes — no Rust changes needed thanks to PR #483 temporal texture fix)

**Spec:** `docs/superpowers/specs/2026-03-31-reverie-adaptive-compositor-design.md` §2 (Core nodes), §7 (Phase 1)

---

### Task 1: Test that R-D node compiles into the plan

**Files:**
- Modify: `tests/effect_graph/test_wgsl_compiler.py`

- [ ] **Step 1: Write the failing test**

Add to the `TestCompileToWgslPlan` class:

```python
def test_reaction_diffusion_is_temporal(self):
    """reaction_diffusion should compile as a temporal render pass with @accum_ input."""
    graph = EffectGraph(
        name="test-rd",
        nodes={
            "rd": {"type": "reaction_diffusion", "params": {"feed_rate": 0.055, "kill_rate": 0.062}},
            "out": {"type": "output"},
        },
        edges=[["@live", "rd"], ["rd", "out"]],
    )
    plan = compile_to_wgsl_plan(graph)
    assert len(plan["passes"]) == 1
    p = plan["passes"][0]
    assert p["node_id"] == "rd"
    assert p["shader"] == "reaction_diffusion.wgsl"
    assert p["type"] == "render"
    assert p.get("temporal") is True
    assert "@accum_rd" in p["inputs"]

def test_reaction_diffusion_params(self):
    """R-D pass should include feed_rate and kill_rate in uniforms."""
    graph = EffectGraph(
        name="test-rd-params",
        nodes={
            "rd": {
                "type": "reaction_diffusion",
                "params": {"feed_rate": 0.04, "kill_rate": 0.06, "diffusion_a": 1.0, "diffusion_b": 0.5, "speed": 1.5},
            },
            "out": {"type": "output"},
        },
        edges=[["@live", "rd"], ["rd", "out"]],
    )
    plan = compile_to_wgsl_plan(graph)
    u = plan["passes"][0]["uniforms"]
    assert u["feed_rate"] == 0.04
    assert u["kill_rate"] == 0.06
    assert u["speed"] == 1.5
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/effect_graph/test_wgsl_compiler.py::TestCompileToWgslPlan::test_reaction_diffusion_is_temporal tests/effect_graph/test_wgsl_compiler.py::TestCompileToWgslPlan::test_reaction_diffusion_params -v`

Expected: PASS — the compiler already handles temporal nodes generically via the registry's `temporal: true` flag. `reaction_diffusion.json` already has this flag. These tests confirm the existing path works for R-D specifically.

- [ ] **Step 3: Commit**

```bash
git add tests/effect_graph/test_wgsl_compiler.py
git commit -m "test: verify reaction_diffusion compiles as temporal render pass"
```

---

### Task 2: Add R-D to the vocabulary graph

**Files:**
- Modify: `presets/reverie_vocabulary.json`

- [ ] **Step 1: Write test for vocabulary graph structure**

Create `tests/test_reverie_vocabulary.py`:

```python
"""Tests for reverie_vocabulary.json structural integrity."""

import json
from pathlib import Path

VOCAB_PATH = Path(__file__).resolve().parents[1] / "presets" / "reverie_vocabulary.json"


def _load_vocab() -> dict:
    return json.loads(VOCAB_PATH.read_text())


def test_vocabulary_has_rd_node():
    vocab = _load_vocab()
    assert "rd" in vocab["nodes"], "reaction_diffusion node missing from vocabulary"
    assert vocab["nodes"]["rd"]["type"] == "reaction_diffusion"


def test_rd_has_required_params():
    vocab = _load_vocab()
    params = vocab["nodes"]["rd"]["params"]
    assert "feed_rate" in params
    assert "kill_rate" in params
    assert "diffusion_a" in params
    assert "diffusion_b" in params
    assert "speed" in params


def test_rd_is_between_noise_and_colorgrade():
    """R-D should receive noise output and feed into colorgrade."""
    vocab = _load_vocab()
    edges = vocab["edges"]
    assert ["noise", "rd"] in edges, "noise→rd edge missing"
    assert ["rd", "color"] in edges, "rd→color edge missing"
    # noise should NOT connect directly to color anymore
    assert ["noise", "color"] not in edges, "stale noise→color edge still present"


def test_vocabulary_has_8_core_passes():
    """Core graph: noise→rd→color→drift→breath→fb→content→post→out = 9 nodes, 8 edges."""
    vocab = _load_vocab()
    assert len(vocab["edges"]) == 8


def test_all_edges_reference_existing_nodes():
    vocab = _load_vocab()
    node_ids = set(vocab["nodes"].keys())
    for src, dst in vocab["edges"]:
        assert src in node_ids, f"edge source '{src}' not in nodes"
        assert dst in node_ids, f"edge target '{dst}' not in nodes"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_reverie_vocabulary.py -v`

Expected: FAIL — `rd` node doesn't exist in vocabulary yet.

- [ ] **Step 3: Add R-D node and rewire edges**

In `presets/reverie_vocabulary.json`, add the `rd` node after `noise` and rewire the `noise→color` edge to `noise→rd→color`:

Replace the `noise` node's closing brace through the `color` node's opening with:

```json
"noise": {
    "type": "noise_gen",
    "params": {
        "frequency_x": 3.0,
        "frequency_y": 2.0,
        "octaves": 4,
        "amplitude": 0.5,
        "speed": 0.15
    }
},
"rd": {
    "type": "reaction_diffusion",
    "params": {
        "feed_rate": 0.055,
        "kill_rate": 0.062,
        "diffusion_a": 1.0,
        "diffusion_b": 0.5,
        "speed": 1.0
    }
},
"color": {
```

Update edges from:
```json
"edges": [
    ["noise", "color"],
    ["color", "drift"],
    ...
]
```

To:
```json
"edges": [
    ["noise", "rd"],
    ["rd", "color"],
    ["color", "drift"],
    ["drift", "breath"],
    ["breath", "fb"],
    ["fb", "content"],
    ["content", "post"],
    ["post", "out"]
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_reverie_vocabulary.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add presets/reverie_vocabulary.json tests/test_reverie_vocabulary.py
git commit -m "feat: add reaction_diffusion to reverie core graph

Insert R-D as temporal node between noise and colorgrade. The ground
field is now self-organizing — patterns emerge from feed/kill rates
rather than static FBM noise. 8-pass core: noise→rd→color→drift→
breath→fb→content→post."
```

---

### Task 3: Fix visual chain R-D param names to match WGSL

**Files:**
- Modify: `agents/visual_chain.py:73,82,128`
- Modify: `tests/test_visual_chain.py`

The visual chain defines R-D parameter mappings using delta names (`rd.f_delta`, `rd.da_delta`) but the Rust per-node param bridge matches against WGSL Params struct field names (`u_feed_rate`, `u_diffusion_a`). The keys must match or the overrides are silently dropped. The R-D shader's WGSL Params struct has: `u_feed_rate`, `u_kill_rate`, `u_diffusion_a`, `u_diffusion_b`, `u_speed`.

- [ ] **Step 1: Write failing tests for correct param key names**

Add to `tests/test_visual_chain.py`:

```python
def test_tension_produces_rd_feed_rate():
    """Tension dimension should produce rd.u_feed_rate override."""
    cap = VisualChainCapability()
    imp = Impingement(
        source="test",
        type=ImpingementType.SIGNAL,
        strength=0.8,
        content={"metric": "visual_modulation"},
    )
    cap.activate_dimension("visual_chain.tension", imp, 0.7)
    deltas = cap.compute_param_deltas()
    assert "rd.u_feed_rate" in deltas
    assert deltas["rd.u_feed_rate"] > 0.0


def test_diffusion_produces_rd_diffusion_a():
    """Diffusion dimension should produce rd.u_diffusion_a override."""
    cap = VisualChainCapability()
    imp = Impingement(
        source="test",
        type=ImpingementType.SIGNAL,
        strength=0.8,
        content={"metric": "visual_modulation"},
    )
    cap.activate_dimension("visual_chain.diffusion", imp, 0.5)
    deltas = cap.compute_param_deltas()
    assert "rd.u_diffusion_a" in deltas
    assert deltas["rd.u_diffusion_a"] > 0.0


def test_coherence_produces_rd_feed_rate_negative():
    """Coherence dimension should produce negative rd.u_feed_rate (reduces reaction)."""
    cap = VisualChainCapability()
    imp = Impingement(
        source="test",
        type=ImpingementType.SIGNAL,
        strength=0.8,
        content={"metric": "visual_modulation"},
    )
    cap.activate_dimension("visual_chain.coherence", imp, 0.8)
    deltas = cap.compute_param_deltas()
    assert "rd.u_feed_rate" in deltas
    assert deltas["rd.u_feed_rate"] < 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py::test_tension_produces_rd_feed_rate tests/test_visual_chain.py::test_diffusion_produces_rd_diffusion_a tests/test_visual_chain.py::test_coherence_produces_rd_feed_rate_negative -v`

Expected: FAIL — visual chain currently uses `f_delta` and `da_delta` as param names, not `u_feed_rate` and `u_diffusion_a`.

- [ ] **Step 3: Fix param names in visual_chain.py**

In `agents/visual_chain.py`, change the three R-D ParameterMapping entries:

Line 73 — tension:
```python
_PM("rd", "u_feed_rate", [(0.0, 0.0), (0.5, 0.005), (1.0, 0.015)]),
```

Line 82 — diffusion:
```python
_PM("rd", "u_diffusion_a", [(0.0, 0.0), (0.5, 0.05), (1.0, 0.2)]),
```

Line 128 — coherence:
```python
_PM("rd", "u_feed_rate", [(0.0, 0.0), (0.5, -0.005), (1.0, -0.015)]),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`

Expected: All tests PASS (including the existing tests — the old `f_delta`/`da_delta` names are not tested by existing tests since those use `"gradient"` as the technique name in test fixtures).

- [ ] **Step 5: Commit**

```bash
git add agents/visual_chain.py tests/test_visual_chain.py
git commit -m "fix: align visual chain R-D param names with WGSL Params struct

f_delta→u_feed_rate, da_delta→u_diffusion_a. The per-node param
bridge matches keys against WGSL param_order. Old delta names were
silently dropped because they didn't match any param in the R-D
shader's Params struct."
```

---

### Task 4: Rebuild and deploy

**Files:**
- No file changes — build and service restart only.

- [ ] **Step 1: Compile the vocabulary to plan.json**

The vocabulary needs to be compiled to `/dev/shm/hapax-imagination/pipeline/plan.json` for the Rust binary. The effect graph compiler does this. Verify the compilation path:

Run: `cd ~/projects/hapax-council--beta && uv run python -c "
from agents.effect_graph.types import EffectGraph
from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan, write_wgsl_pipeline
import json
from pathlib import Path

vocab = json.loads(Path('presets/reverie_vocabulary.json').read_text())
graph = EffectGraph(name=vocab['name'], nodes=vocab['nodes'], edges=vocab['edges'])
plan = compile_to_wgsl_plan(graph)
print(f'Passes: {len(plan[\"passes\"])}')
for p in plan['passes']:
    temporal = ' (temporal)' if p.get('temporal') else ''
    print(f'  {p[\"node_id\"]}: {p[\"shader\"]}{temporal} inputs={p[\"inputs\"]}')
"`

Expected output should show 8 passes with `rd` as a temporal pass reading `@accum_rd`.

- [ ] **Step 2: Write the compiled plan to shm**

Run: `cd ~/projects/hapax-council--beta && uv run python -c "
from agents.effect_graph.types import EffectGraph
from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan, write_wgsl_pipeline
import json
from pathlib import Path

vocab = json.loads(Path('presets/reverie_vocabulary.json').read_text())
graph = EffectGraph(name=vocab['name'], nodes=vocab['nodes'], edges=vocab['edges'])
plan = compile_to_wgsl_plan(graph)
write_wgsl_pipeline(plan)
print('Written to /dev/shm/hapax-imagination/pipeline/')
"`

- [ ] **Step 3: Restart hapax-imagination service**

Run: `systemctl --user restart hapax-imagination && sleep 2 && systemctl --user status hapax-imagination --no-pager | head -10`

Expected: Active (running), logs should show `loaded 8 passes`.

- [ ] **Step 4: Verify frame output**

Run: `stat /dev/shm/hapax-visual/frame.jpg | grep Modify`

Expected: Timestamp within last few seconds. The surface should now show R-D self-organizing patterns modulated by the noise substrate.

- [ ] **Step 5: Verify temporal accumulation**

Run: `journalctl --user -u hapax-imagination --since "30 sec ago" --no-pager | grep -i "loaded\|error\|panic"`

Expected: `loaded 8 passes`, no errors or panics. The R-D node should accumulate via `@accum_rd` (temporal texture initialized by PR #483 fix).

---

### Task 5: Run full test suite

**Files:**
- No changes.

- [ ] **Step 1: Run all visual/effect tests**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py tests/test_reverie_vocabulary.py tests/effect_graph/ -v`

Expected: All tests pass.

- [ ] **Step 2: Run ruff lint and format**

Run: `cd ~/projects/hapax-council--beta && uv run ruff check tests/test_reverie_vocabulary.py tests/test_visual_chain.py && uv run ruff format --check tests/test_reverie_vocabulary.py tests/test_visual_chain.py`

Expected: No issues.

- [ ] **Step 3: Create PR**

```bash
git push -u origin HEAD
gh pr create --title "feat: add reaction_diffusion to reverie core graph" --body "$(cat <<'EOF'
## Summary

- Inserts `reaction_diffusion` as a temporal node between `noise` and `colorgrade` in `reverie_vocabulary.json`
- Core graph goes from 7 to 8 passes: noise → **rd** → color → drift → breath → fb → content → post
- R-D is self-organizing — patterns emerge from feed/kill rates. The ground field is alive.
- Visual chain R-D parameter bindings (tension→f_delta, diffusion→da_delta, coherence→f_delta) now target a real shader pass
- Phase 1 of the Reverie Adaptive Compositor spec

## Test plan

- [x] R-D compiles as temporal render pass with @accum_rd input
- [x] Vocabulary has 8 edges, R-D between noise and colorgrade
- [x] Visual chain tension/diffusion/coherence produce R-D parameter deltas
- [x] Plan compiles to 8 passes, service runs, frame output fresh
- [ ] CI pipeline

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Monitor CI, merge when green**

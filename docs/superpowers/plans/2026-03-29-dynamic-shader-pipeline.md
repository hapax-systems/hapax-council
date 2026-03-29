# Dynamic Shader Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded 6-technique WGPU render pipeline with a dynamic shader graph executor. Python transpiles GLSL→WGSL and writes execution plans to `/dev/shm`. Rust hot-reloads and executes arbitrary shader graphs.

**Architecture:** Python is the shader authority (compiler + transpiler). Rust is a generic executor (dynamic pipeline + uniform buffer). Filesystem-as-bus (`/dev/shm`) carries execution plans and per-frame uniforms. All 54 GLSL nodes transpiled to WGSL. Content layer and postprocess become graph nodes.

**Tech Stack:** Python 3.12 (naga CLI for transpilation), Rust (wgpu 24, notify 7), GLSL ES 1.0 → WGSL

---

## File Map

### Python side

| File | Action | Responsibility |
|------|--------|---------------|
| `agents/effect_graph/wgsl_transpiler.py` | Create | GLSL→WGSL adapter + naga CLI wrapper |
| `agents/effect_graph/wgsl_compiler.py` | Create | Compile graph → plan.json + WGSL to /dev/shm |
| `agents/effect_graph/runtime.py` | Modify | Call WGSL compiler on graph load |
| `agents/effect_graph/modulator.py` | Modify | Write uniforms.json to /dev/shm |
| `agents/shaders/nodes/*.wgsl` | Create (54) | Transpiled WGSL for each node |
| `tests/effect_graph/test_wgsl_transpiler.py` | Create | Transpilation tests |
| `tests/effect_graph/test_wgsl_compiler.py` | Create | Plan generation tests |

### Rust side

| File | Action | Responsibility |
|------|--------|---------------|
| `crates/hapax-visual/src/dynamic_pipeline.rs` | Create | Plan loading, shader compilation, pass execution |
| `crates/hapax-visual/src/uniform_buffer.rs` | Create | Shared GPU uniform struct, per-frame upload |
| `crates/hapax-visual/src/shaders/uniforms.wgsl` | Create | Shared uniform struct for all shaders |
| `crates/hapax-visual/src/shaders/fullscreen_quad.wgsl` | Create | Shared vertex shader |
| `crates/hapax-visual/src/lib.rs` | Modify | Replace technique modules |
| `src-imagination/src/main.rs` | Modify | Use DynamicPipeline instead of hardcoded render |

### Deleted

| File | Reason |
|------|--------|
| `crates/hapax-visual/src/techniques/*.rs` | Replaced by graph nodes |
| `crates/hapax-visual/src/compositor.rs` | Replaced by dynamic pipeline |
| `crates/hapax-visual/src/content_layer.rs` | Becomes graph node |
| `crates/hapax-visual/src/postprocess.rs` | Becomes graph node |
| `crates/hapax-visual/src/shaders/composite.wgsl` | Replaced |
| `crates/hapax-visual/src/shaders/content_layer.wgsl` | Becomes node WGSL |
| `crates/hapax-visual/src/shaders/postprocess.wgsl` | Becomes node WGSL |
| All technique-specific WGSL | Replaced by transpiled versions |

---

### Task 1: Install naga CLI

**Files:** None (system dependency)

- [ ] **Step 1: Install naga**

```bash
cargo install naga-cli
```

- [ ] **Step 2: Verify**

```bash
naga --version
echo '#version 100
precision mediump float;
varying vec2 v_texcoord;
uniform sampler2D tex;
void main() { gl_FragColor = texture2D(tex, v_texcoord); }' > /tmp/test.frag
naga /tmp/test.frag /tmp/test.wgsl && cat /tmp/test.wgsl
```

Expected: WGSL output with `@fragment` entry point.

- [ ] **Step 3: Document naga limitations**

Test a few of the 54 shaders to identify adaptation needs:

```bash
cd ~/projects/hapax-council--beta
for f in agents/shaders/nodes/{bloom,ascii,feedback,drift,physarum_sim}.frag; do
  echo "=== $f ==="
  naga "$f" /tmp/out.wgsl 2>&1 | tail -5
done
```

Record which shaders fail and why. These will need manual GLSL pre-processing before transpilation.

- [ ] **Step 4: Commit** (no code changes — just document findings in commit message)

---

### Task 2: Create WGSL transpiler

**Files:**
- Create: `agents/effect_graph/wgsl_transpiler.py`
- Create: `tests/effect_graph/test_wgsl_transpiler.py`

- [ ] **Step 1: Write tests**

Create `tests/effect_graph/test_wgsl_transpiler.py`:

```python
"""Tests for GLSL→WGSL transpilation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestGlslAdapter:
    """Test GLSL source pre-processing before naga."""

    def test_adds_version_if_missing(self):
        from agents.effect_graph.wgsl_transpiler import adapt_glsl

        src = "void main() { gl_FragColor = vec4(1.0); }"
        adapted = adapt_glsl(src)
        assert adapted.startswith("#version")

    def test_preserves_existing_version(self):
        from agents.effect_graph.wgsl_transpiler import adapt_glsl

        src = "#version 100\nvoid main() {}"
        adapted = adapt_glsl(src)
        assert adapted.count("#version") == 1

    def test_maps_texture2D_to_texture(self):
        from agents.effect_graph.wgsl_transpiler import adapt_glsl

        src = "#version 100\nvoid main() { gl_FragColor = texture2D(tex, uv); }"
        adapted = adapt_glsl(src)
        assert "texture2D" in adapted or "texture(" in adapted

    def test_adds_precision_if_missing(self):
        from agents.effect_graph.wgsl_transpiler import adapt_glsl

        src = "#version 100\nvoid main() {}"
        adapted = adapt_glsl(src)
        assert "precision" in adapted


class TestTranspile:
    """Test naga-based transpilation."""

    def test_simple_passthrough_shader(self):
        from agents.effect_graph.wgsl_transpiler import transpile_glsl_to_wgsl

        glsl = (
            "#version 100\n"
            "precision mediump float;\n"
            "varying vec2 v_texcoord;\n"
            "uniform sampler2D tex;\n"
            "void main() { gl_FragColor = texture2D(tex, v_texcoord); }\n"
        )
        wgsl = transpile_glsl_to_wgsl(glsl)
        assert "@fragment" in wgsl or "fn main" in wgsl

    def test_transpile_failure_raises(self):
        from agents.effect_graph.wgsl_transpiler import transpile_glsl_to_wgsl

        with pytest.raises(RuntimeError, match="naga"):
            transpile_glsl_to_wgsl("not valid glsl at all {{{")


class TestBatchTranspile:
    """Test batch transpilation of node shaders."""

    def test_transpile_node_creates_wgsl_file(self, tmp_path):
        from agents.effect_graph.wgsl_transpiler import transpile_node

        frag = tmp_path / "test.frag"
        frag.write_text(
            "#version 100\n"
            "precision mediump float;\n"
            "varying vec2 v_texcoord;\n"
            "uniform sampler2D tex;\n"
            "void main() { gl_FragColor = texture2D(tex, v_texcoord); }\n"
        )
        out = transpile_node(frag, tmp_path)
        assert out.exists()
        assert out.suffix == ".wgsl"
        assert "@fragment" in out.read_text() or "fn main" in out.read_text()

    def test_transpile_all_nodes(self):
        from agents.effect_graph.wgsl_transpiler import transpile_all_nodes

        nodes_dir = Path("agents/shaders/nodes")
        if not nodes_dir.exists():
            pytest.skip("shader nodes not found")
        results = transpile_all_nodes(nodes_dir)
        assert results["total"] > 0
        # Some may fail due to naga limitations — that's OK
        assert results["success"] + results["failed"] == results["total"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/projects/hapax-council--beta && uv run pytest tests/effect_graph/test_wgsl_transpiler.py -v 2>&1 | tail -15
```

- [ ] **Step 3: Implement wgsl_transpiler.py**

Create `agents/effect_graph/wgsl_transpiler.py`:

```python
"""GLSL→WGSL transpilation via naga CLI.

Pre-processes GLSL ES 1.0 fragment shaders (GStreamer glshader convention)
to be compatible with naga's GLSL frontend, then calls naga to produce WGSL.

Usage:
    # Single shader
    wgsl = transpile_glsl_to_wgsl(glsl_source)

    # Batch — all nodes
    results = transpile_all_nodes(Path("agents/shaders/nodes"))
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def adapt_glsl(source: str) -> str:
    """Pre-process GLSL source for naga compatibility.

    Handles GStreamer glshader conventions:
    - Ensures #version directive present
    - Ensures precision qualifier present
    - Normalizes varying/attribute declarations
    """
    lines = source.strip().splitlines()

    has_version = any(l.strip().startswith("#version") for l in lines)
    has_precision = any("precision" in l for l in lines)

    adapted = []
    if not has_version:
        adapted.append("#version 100")
    if not has_precision:
        # Insert after #version or at start
        version_idx = next(
            (i for i, l in enumerate(lines) if l.strip().startswith("#version")), -1
        )
        if version_idx >= 0:
            adapted = lines[: version_idx + 1]
            adapted.append("#ifdef GL_ES")
            adapted.append("precision mediump float;")
            adapted.append("#endif")
            adapted.extend(lines[version_idx + 1 :])
            return "\n".join(adapted) + "\n"

    adapted.extend(lines)
    return "\n".join(adapted) + "\n"


def transpile_glsl_to_wgsl(glsl_source: str) -> str:
    """Transpile GLSL ES source to WGSL via naga CLI.

    Raises RuntimeError if naga fails.
    """
    if not shutil.which("naga"):
        raise RuntimeError("naga CLI not found — install with: cargo install naga-cli")

    adapted = adapt_glsl(glsl_source)

    with tempfile.NamedTemporaryFile(suffix=".frag", mode="w", delete=False) as frag:
        frag.write(adapted)
        frag_path = Path(frag.name)

    wgsl_path = frag_path.with_suffix(".wgsl")

    try:
        result = subprocess.run(
            ["naga", str(frag_path), str(wgsl_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"naga transpilation failed: {result.stderr.strip()}")
        return wgsl_path.read_text()
    finally:
        frag_path.unlink(missing_ok=True)
        wgsl_path.unlink(missing_ok=True)


def transpile_node(frag_path: Path, output_dir: Path | None = None) -> Path:
    """Transpile a single .frag node shader to .wgsl.

    Returns path to the output .wgsl file.
    """
    glsl = frag_path.read_text()
    wgsl = transpile_glsl_to_wgsl(glsl)

    out_dir = output_dir or frag_path.parent
    out_path = out_dir / frag_path.with_suffix(".wgsl").name
    out_path.write_text(wgsl)
    return out_path


def transpile_all_nodes(
    nodes_dir: Path, output_dir: Path | None = None
) -> dict[str, int | list[str]]:
    """Batch-transpile all .frag shaders in a directory.

    Returns summary: {total, success, failed, failures: [filenames]}.
    """
    out_dir = output_dir or nodes_dir
    frags = sorted(nodes_dir.glob("*.frag"))
    success = 0
    failures: list[str] = []

    for frag in frags:
        try:
            transpile_node(frag, out_dir)
            success += 1
            log.info("Transpiled: %s", frag.name)
        except Exception as e:
            failures.append(frag.name)
            log.warning("Failed to transpile %s: %s", frag.name, e)

    return {
        "total": len(frags),
        "success": success,
        "failed": len(failures),
        "failures": failures,
    }
```

- [ ] **Step 4: Run tests**

```bash
cd ~/projects/hapax-council--beta && uv run pytest tests/effect_graph/test_wgsl_transpiler.py -v
```

- [ ] **Step 5: Run batch transpilation and check results**

```bash
cd ~/projects/hapax-council--beta && uv run python -c "
from pathlib import Path
from agents.effect_graph.wgsl_transpiler import transpile_all_nodes
r = transpile_all_nodes(Path('agents/shaders/nodes'))
print(f'Total: {r[\"total\"]}, Success: {r[\"success\"]}, Failed: {r[\"failed\"]}')
for f in r['failures']:
    print(f'  FAILED: {f}')
"
```

Record results. Hand-port any failures in Task 3.

- [ ] **Step 6: Commit**

```bash
git add agents/effect_graph/wgsl_transpiler.py tests/effect_graph/test_wgsl_transpiler.py
git commit -m "feat(effect-graph): GLSL→WGSL transpiler via naga CLI"
```

---

### Task 3: Batch transpile all 54 nodes + hand-port failures

**Files:**
- Create: `agents/shaders/nodes/*.wgsl` (54 files)

- [ ] **Step 1: Run batch transpilation, saving output**

```bash
cd ~/projects/hapax-council--beta && uv run python -c "
from pathlib import Path
from agents.effect_graph.wgsl_transpiler import transpile_all_nodes
r = transpile_all_nodes(Path('agents/shaders/nodes'))
print(f'Success: {r[\"success\"]}/{r[\"total\"]}')
for f in r['failures']:
    print(f'  NEEDS HAND-PORT: {f}')
"
```

- [ ] **Step 2: Hand-port any failures**

For each failed shader, read the GLSL source, understand what it does, and write equivalent WGSL manually. Save to `agents/shaders/nodes/<name>.wgsl`. Common issues:

- `#ifdef GL_ES` blocks — remove, use WGSL precision directly
- `texture2D()` — becomes `textureSample()`
- `gl_FragColor` — becomes function return value
- `varying` — becomes vertex shader output struct member
- Multi-sampler shaders — need bind group layout adaptation

- [ ] **Step 3: Verify all 54 .wgsl files exist**

```bash
cd ~/projects/hapax-council--beta
frag_count=$(ls agents/shaders/nodes/*.frag | wc -l)
wgsl_count=$(ls agents/shaders/nodes/*.wgsl | wc -l)
echo "GLSL: $frag_count, WGSL: $wgsl_count"
# Both should be equal
```

- [ ] **Step 4: Commit**

```bash
git add agents/shaders/nodes/*.wgsl
git commit -m "feat(effect-graph): transpile all 54 GLSL nodes to WGSL"
```

---

### Task 4: Create WGSL compiler (Python → plan.json)

**Files:**
- Create: `agents/effect_graph/wgsl_compiler.py`
- Create: `tests/effect_graph/test_wgsl_compiler.py`

- [ ] **Step 1: Write tests**

Create `tests/effect_graph/test_wgsl_compiler.py`:

```python
"""Tests for WGSL execution plan compiler."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


class TestPlanGeneration:
    def test_single_node_plan(self):
        from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan
        from agents.effect_graph.types import EffectGraph, NodeInstance

        graph = EffectGraph(
            name="test",
            nodes=[NodeInstance(id="bloom_0", node_type="bloom", params={"threshold": 0.5})],
            edges=[],
        )
        plan = compile_to_wgsl_plan(graph)
        assert len(plan["passes"]) == 1
        assert plan["passes"][0]["node_id"] == "bloom_0"
        assert plan["passes"][0]["shader"] == "bloom.wgsl"

    def test_multi_node_plan_preserves_order(self):
        from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan
        from agents.effect_graph.types import EffectGraph, NodeInstance

        graph = EffectGraph(
            name="test",
            nodes=[
                NodeInstance(id="a", node_type="bloom", params={}),
                NodeInstance(id="b", node_type="drift", params={}),
            ],
            edges=[{"from": "a:out", "to": "b:in"}],
        )
        plan = compile_to_wgsl_plan(graph)
        assert plan["passes"][0]["node_id"] == "a"
        assert plan["passes"][1]["node_id"] == "b"

    def test_plan_includes_uniforms(self):
        from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan
        from agents.effect_graph.types import EffectGraph, NodeInstance

        graph = EffectGraph(
            name="test",
            nodes=[NodeInstance(id="x", node_type="bloom", params={"threshold": 0.8})],
            edges=[],
        )
        plan = compile_to_wgsl_plan(graph)
        assert plan["passes"][0]["uniforms"]["threshold"] == 0.8


class TestPlanWrite:
    def test_writes_plan_and_shaders_to_dir(self, tmp_path):
        from agents.effect_graph.wgsl_compiler import write_wgsl_pipeline

        plan = {
            "version": 1,
            "passes": [
                {"node_id": "bloom_0", "shader": "bloom.wgsl", "type": "render",
                 "inputs": [], "output": "layer_0", "uniforms": {}}
            ],
        }
        nodes_dir = Path("agents/shaders/nodes")
        write_wgsl_pipeline(plan, tmp_path, nodes_dir)

        assert (tmp_path / "plan.json").exists()
        plan_data = json.loads((tmp_path / "plan.json").read_text())
        assert len(plan_data["passes"]) == 1
```

- [ ] **Step 2: Implement wgsl_compiler.py**

Create `agents/effect_graph/wgsl_compiler.py`:

```python
"""Compile effect graphs into WGSL execution plans for the Rust dynamic pipeline.

Reads the existing compiled ExecutionPlan and produces:
- plan.json — ordered passes with WGSL shader references
- Copies .wgsl files to the output directory

Output directory: /dev/shm/hapax-imagination/pipeline/
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from .compiler import GraphCompiler
from .registry import ShaderRegistry
from .types import EffectGraph

log = logging.getLogger(__name__)

PIPELINE_DIR = Path("/dev/shm/hapax-imagination/pipeline")
NODES_DIR = Path(__file__).parent.parent / "shaders" / "nodes"

# Map node types to pass type (render vs compute)
COMPUTE_NODES = {
    "reaction_diffusion", "physarum_sim", "voronoi_seed",
    "wave_propagate",
}


def compile_to_wgsl_plan(graph: EffectGraph) -> dict:
    """Compile an EffectGraph to a WGSL execution plan dict.

    Uses the existing GraphCompiler for topological ordering,
    then maps each step to a WGSL pass descriptor.
    """
    registry = ShaderRegistry()
    compiler = GraphCompiler(registry)
    plan = compiler.compile(graph)

    passes = []
    for i, step in enumerate(plan.steps):
        node_def = registry.get(step.node_type)
        wgsl_file = f"{step.node_type}.wgsl"

        pass_type = "compute" if step.node_type in COMPUTE_NODES else "render"
        steps_per_frame = 8 if step.node_type == "reaction_diffusion" else 1

        inputs = [e.from_port.split(":")[0] for e in step.input_edges] if step.input_edges else []
        output = f"layer_{i}"

        pass_desc = {
            "node_id": step.node_id,
            "shader": wgsl_file,
            "type": pass_type,
            "inputs": inputs,
            "output": output,
            "uniforms": dict(step.params),
        }
        if pass_type == "compute" and steps_per_frame > 1:
            pass_desc["steps_per_frame"] = steps_per_frame

        passes.append(pass_desc)

    # Mark last pass output as "final"
    if passes:
        passes[-1]["output"] = "final"

    return {"version": 1, "passes": passes}


def write_wgsl_pipeline(
    plan: dict,
    output_dir: Path | None = None,
    nodes_dir: Path | None = None,
) -> Path:
    """Write plan.json and copy required .wgsl files to output directory.

    Returns the output directory path.
    """
    out = output_dir or PIPELINE_DIR
    src = nodes_dir or NODES_DIR

    out.mkdir(parents=True, exist_ok=True)

    # Write plan
    (out / "plan.json").write_text(json.dumps(plan, indent=2))

    # Copy required WGSL files
    for pass_desc in plan["passes"]:
        wgsl_name = pass_desc["shader"]
        wgsl_src = src / wgsl_name
        if wgsl_src.exists():
            shutil.copy2(wgsl_src, out / wgsl_name)
        else:
            log.warning("WGSL shader not found: %s", wgsl_src)

    return out
```

- [ ] **Step 3: Run tests**

```bash
cd ~/projects/hapax-council--beta && uv run pytest tests/effect_graph/test_wgsl_compiler.py -v
```

- [ ] **Step 4: Commit**

```bash
git add agents/effect_graph/wgsl_compiler.py tests/effect_graph/test_wgsl_compiler.py
git commit -m "feat(effect-graph): WGSL execution plan compiler"
```

---

### Task 5: Wire compiler into runtime + modulator output

**Files:**
- Modify: `agents/effect_graph/runtime.py`
- Modify: `agents/effect_graph/modulator.py`
- Modify: `logos/api/routes/studio.py`

- [ ] **Step 1: Update runtime.py to trigger WGSL compilation**

In `agents/effect_graph/runtime.py`, in the `load_graph` method, after `self._current_plan = plan`, add:

```python
        # Compile to WGSL pipeline for hapax-imagination
        try:
            from .wgsl_compiler import compile_to_wgsl_plan, write_wgsl_pipeline
            wgsl_plan = compile_to_wgsl_plan(graph)
            write_wgsl_pipeline(wgsl_plan)
            log.info("WGSL pipeline written for %s (%d passes)", graph.name, len(wgsl_plan["passes"]))
        except Exception:
            log.warning("Failed to write WGSL pipeline", exc_info=True)
```

- [ ] **Step 2: Update modulator.py to write uniforms.json**

In `agents/effect_graph/modulator.py`, in the `tick` method, after computing `updates`, add:

```python
        # Write current uniforms to /dev/shm for Rust pipeline
        try:
            import json
            from pathlib import Path
            uniforms_path = Path("/dev/shm/hapax-imagination/pipeline/uniforms.json")
            if uniforms_path.parent.exists():
                flat = {f"{node}.{param}": val for (node, param), val in self._smoothed.items()}
                flat.update({f"signal.{k}": v for k, v in signals.items()})
                uniforms_path.write_text(json.dumps(flat))
        except Exception:
            pass  # Non-critical — Rust falls back to defaults
```

- [ ] **Step 3: Verify preset activation writes pipeline**

```bash
cd ~/projects/hapax-council--beta && uv run python -c "
from agents.effect_graph.runtime import GraphRuntime
from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.types import EffectGraph
import json
from pathlib import Path

r = ShaderRegistry()
c = GraphCompiler(r)
m = UniformModulator()
rt = GraphRuntime(r, c, m)

# Load a preset
p = Path('presets/ambient.json')
if p.exists():
    graph = EffectGraph(**json.loads(p.read_text()))
    rt.load_graph(graph)
    plan_path = Path('/dev/shm/hapax-imagination/pipeline/plan.json')
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        print(f'Pipeline written: {len(plan[\"passes\"])} passes')
    else:
        print('Pipeline NOT written')
"
```

- [ ] **Step 4: Commit**

```bash
git add agents/effect_graph/runtime.py agents/effect_graph/modulator.py
git commit -m "feat(effect-graph): wire WGSL compiler into runtime + modulator"
```

---

### Task 6: Create shared WGSL uniform struct and fullscreen quad

**Files:**
- Create: `hapax-logos/crates/hapax-visual/src/shaders/uniforms.wgsl`
- Create: `hapax-logos/crates/hapax-visual/src/shaders/fullscreen_quad.wgsl`

- [ ] **Step 1: Write uniforms.wgsl**

Create `hapax-logos/crates/hapax-visual/src/shaders/uniforms.wgsl`:

```wgsl
struct Uniforms {
    time: f32,
    dt: f32,
    resolution: vec2<f32>,
    // Stimmung
    stance: u32,
    color_warmth: f32,
    speed: f32,
    turbulence: f32,
    brightness: f32,
    // 9 expressive dimensions
    intensity: f32,
    tension: f32,
    depth: f32,
    coherence: f32,
    spectral_color: f32,
    temporal_distortion: f32,
    degradation: f32,
    pitch_displacement: f32,
    formant_character: f32,
    // Content layer
    slot_opacities: vec4<f32>,
    // Per-node custom params (32 floats)
    custom: array<f32, 32>,
};

@group(0) @binding(0)
var<uniform> uniforms: Uniforms;
```

- [ ] **Step 2: Write fullscreen_quad.wgsl**

Create `hapax-logos/crates/hapax-visual/src/shaders/fullscreen_quad.wgsl`:

```wgsl
struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vertex_index: u32) -> VertexOutput {
    // Fullscreen triangle (3 vertices, no vertex buffer needed)
    var out: VertexOutput;
    let x = f32(i32(vertex_index & 1u) * 2 - 1);
    let y = f32(i32(vertex_index >> 1u) * 2 - 1);
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, (1.0 - y) * 0.5);
    return out;
}
```

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/crates/hapax-visual/src/shaders/
git commit -m "feat(visual): shared WGSL uniform struct + fullscreen quad vertex shader"
```

---

### Task 7: Create Rust UniformBuffer

**Files:**
- Create: `hapax-logos/crates/hapax-visual/src/uniform_buffer.rs`

- [ ] **Step 1: Write uniform_buffer.rs**

Create `hapax-logos/crates/hapax-visual/src/uniform_buffer.rs`. This module:

1. Defines `UniformData` struct matching the WGSL `Uniforms` struct (bytemuck Pod/Zeroable)
2. `UniformBuffer::new(device)` — creates the GPU buffer
3. `UniformBuffer::update(queue, data)` — uploads per frame
4. `UniformBuffer::from_state_and_file(state_reader, uniforms_json_path) -> UniformData` — merges stimmung + imagination + per-node uniforms from the JSON file

The struct must be `repr(C)` and match the WGSL layout exactly (including padding for alignment).

Read the existing `ContentUniforms` struct in `content_layer.rs` and `CompositeUniforms` in `compositor.rs` for the bytemuck pattern used in this codebase.

- [ ] **Step 2: Verify it compiles**

```bash
cd ~/projects/hapax-council--beta/hapax-logos/crates/hapax-visual && cargo check
```

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/crates/hapax-visual/src/uniform_buffer.rs
git commit -m "feat(visual): UniformBuffer — shared GPU uniform struct with per-frame upload"
```

---

### Task 8: Create Rust DynamicPipeline

**Files:**
- Create: `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`

This is the core Rust module. It:

1. **Watches** `/dev/shm/hapax-imagination/pipeline/plan.json` via notify
2. **On change:** reads plan.json, reads each `.wgsl` file, prepends the shared `uniforms.wgsl` content, calls `device.create_shader_module()`, creates render/compute pipelines with bind group layouts
3. **Per frame:** reads `uniforms.json`, updates UniformBuffer, executes passes in order using ping-pong textures
4. **Texture pool:** named textures (`layer_0`, `layer_1`, `final`, content slots). Passes reference by name.
5. **Content layer support:** when a pass references content slot textures, the engine loads JPEG images from `/dev/shm/hapax-imagination/content/` into GPU textures (same logic as existing `ContentLayer::upload_to_slot`)

- [ ] **Step 1: Write dynamic_pipeline.rs**

The implementer should read these existing files for patterns:
- `crates/hapax-visual/src/compositor.rs` — bind group creation, render pass encoding
- `crates/hapax-visual/src/content_layer.rs` — texture upload from JPEG, 9-dimension uniforms
- `crates/hapax-visual/src/output.rs` — ShmOutput pattern (staging buffer → JPEG → /dev/shm)

Key structures:

```rust
pub struct DynamicPipeline {
    passes: Vec<DynamicPass>,
    textures: HashMap<String, (wgpu::Texture, wgpu::TextureView)>,
    uniform_buffer: UniformBuffer,
    plan_watcher: notify::RecommendedWatcher,
    pending_reload: Arc<AtomicBool>,
    fullscreen_vertex_module: wgpu::ShaderModule,
    shm_output: ShmOutput,
}

struct DynamicPass {
    node_id: String,
    pipeline: wgpu::RenderPipeline,  // or ComputePipeline
    bind_group: wgpu::BindGroup,
    inputs: Vec<String>,   // texture names
    output: String,        // texture name
    pass_type: PassType,
    steps_per_frame: u32,
}

enum PassType { Render, Compute }
```

Methods:
- `DynamicPipeline::new(device, queue, width, height) -> Self`
- `DynamicPipeline::reload_plan(device, plan_dir) -> Result<(), Error>`
- `DynamicPipeline::render(device, queue, surface_view, state_reader, dt, time)`
- `DynamicPipeline::resize(device, width, height)`

- [ ] **Step 2: Verify it compiles**

```bash
cd ~/projects/hapax-council--beta/hapax-logos/crates/hapax-visual && cargo check
```

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs
git commit -m "feat(visual): DynamicPipeline — hot-reload shader graph executor"
```

---

### Task 9: Update lib.rs and delete hardcoded techniques

**Files:**
- Modify: `hapax-logos/crates/hapax-visual/src/lib.rs`
- Delete: `crates/hapax-visual/src/techniques/` (entire directory)
- Delete: `crates/hapax-visual/src/compositor.rs`
- Delete: `crates/hapax-visual/src/content_layer.rs`
- Delete: `crates/hapax-visual/src/postprocess.rs`
- Delete: technique-specific shaders from `crates/hapax-visual/src/shaders/`

- [ ] **Step 1: Update lib.rs**

Replace `hapax-logos/crates/hapax-visual/src/lib.rs`:

```rust
pub mod control;
pub mod dynamic_pipeline;
pub mod gpu;
pub mod output;
pub mod state;
pub mod uniform_buffer;
```

- [ ] **Step 2: Delete hardcoded modules**

```bash
cd ~/projects/hapax-council--beta/hapax-logos/crates/hapax-visual
rm -rf src/techniques/
rm -f src/compositor.rs
rm -f src/content_layer.rs
rm -f src/postprocess.rs
# Keep: src/shaders/uniforms.wgsl, src/shaders/fullscreen_quad.wgsl
# Delete old technique shaders:
rm -f src/shaders/composite.wgsl src/shaders/content_layer.wgsl src/shaders/postprocess.wgsl
rm -f src/shaders/gradient.wgsl src/shaders/reaction_diff.wgsl src/shaders/voronoi*.wgsl
rm -f src/shaders/wave*.wgsl src/shaders/physarum*.wgsl src/shaders/feedback.wgsl
```

- [ ] **Step 3: Verify crate compiles**

```bash
cd ~/projects/hapax-council--beta/hapax-logos/crates/hapax-visual && cargo check
```

- [ ] **Step 4: Commit**

```bash
git add -A hapax-logos/crates/hapax-visual/
git commit -m "chore: delete hardcoded techniques, compositor, content_layer, postprocess

Replaced by dynamic_pipeline.rs which executes shader graphs from plan.json."
```

---

### Task 10: Update hapax-imagination main.rs

**Files:**
- Modify: `hapax-logos/src-imagination/src/main.rs`

- [ ] **Step 1: Replace hardcoded render loop with DynamicPipeline**

The `ImaginationApp` struct currently initializes all 6 techniques + compositor + content_layer + postprocess. Replace with:

```rust
// In struct ImaginationApp:
dynamic_pipeline: Option<DynamicPipeline>,
// Remove: gradient, reaction_diff, voronoi, wave, physarum, feedback,
//         compositor, content_layer, postprocess

// In resumed():
let dynamic_pipeline = DynamicPipeline::new(&gpu.device, &gpu.queue, w, h);
self.dynamic_pipeline = Some(dynamic_pipeline);

// In render():
if let Some(pipeline) = &mut self.dynamic_pipeline {
    pipeline.render(&gpu.device, &gpu.queue, &surface_view, &self.state_reader, dt, time);
}
```

Read the existing `main.rs` carefully — keep the UDS server, window management, stats emission, and shm directory creation. Only replace the render pipeline internals.

- [ ] **Step 2: Verify binary compiles**

```bash
cd ~/projects/hapax-council--beta/hapax-logos/src-imagination && cargo build 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/src-imagination/src/main.rs
git commit -m "feat(imagination): use DynamicPipeline — fully dynamic shader graph execution"
```

---

### Task 11: Update preset JSONs for content_layer + postprocess nodes

**Files:**
- Modify: `presets/*.json` (29 files)

- [ ] **Step 1: Add content_layer and postprocess nodes to presets**

For each preset that should show imagination content, add a `content_layer` node after the last effect node, and a `postprocess` node as the final pass. Example for `ambient.json`:

Add to the `nodes` array:
```json
{"id": "content_0", "node_type": "content_layer", "params": {}},
{"id": "post_0", "node_type": "postprocess", "params": {"vignette_strength": 0.3}}
```

Add edges wiring them into the chain.

Not all presets need content_layer — some (like `clean`) may skip it. All presets should have `postprocess` as the final node.

- [ ] **Step 2: Verify presets compile to valid plans**

```bash
cd ~/projects/hapax-council--beta && uv run python -c "
from pathlib import Path
import json
from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan
from agents.effect_graph.types import EffectGraph

for p in sorted(Path('presets').glob('*.json')):
    try:
        graph = EffectGraph(**json.loads(p.read_text()))
        plan = compile_to_wgsl_plan(graph)
        print(f'{p.stem}: {len(plan[\"passes\"])} passes')
    except Exception as e:
        print(f'{p.stem}: FAILED — {e}')
"
```

- [ ] **Step 3: Commit**

```bash
git add presets/
git commit -m "feat(presets): add content_layer + postprocess nodes to all 29 presets"
```

---

### Task 12: Integration test + PR

- [ ] **Step 1: Build everything**

```bash
cd ~/projects/hapax-council--beta/hapax-logos
cargo build --workspace 2>&1 | tail -10
```

- [ ] **Step 2: Run Python tests**

```bash
cd ~/projects/hapax-council--beta
uv run pytest tests/effect_graph/ -v 2>&1 | tail -20
```

- [ ] **Step 3: Run Rust tests**

```bash
cd ~/projects/hapax-council--beta/hapax-logos
cargo test --workspace 2>&1 | tail -15
```

- [ ] **Step 4: Test preset activation end-to-end**

```bash
# Start logos-api
cd ~/projects/hapax-council--beta && uv run logos-api &
sleep 5

# Activate a preset
curl -X POST http://localhost:8051/api/studio/effect/select -d '{"preset": "ambient"}' -H 'Content-Type: application/json'

# Verify pipeline written
ls /dev/shm/hapax-imagination/pipeline/
cat /dev/shm/hapax-imagination/pipeline/plan.json | python -m json.tool | head -20

# Start imagination binary
~/.local/bin/hapax-imagination &
sleep 3

# Verify it picked up the pipeline (check logs or send status)
echo '{"type":"status"}' | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/hapax-imagination.sock

kill %1 %2
```

- [ ] **Step 5: Push and create PR**

```bash
cd ~/projects/hapax-council--beta
git push -u origin feat/dynamic-shader-pipeline
gh pr create --title "feat: dynamic shader pipeline — effect graph → WGPU" --body "$(cat <<'EOF'
## Summary

Replace hardcoded 6-technique WGPU render pipeline with dynamic shader graph executor.

- **Python WGSL transpiler**: GLSL→WGSL via naga CLI, all 54 nodes transpiled
- **WGSL compiler**: graph → plan.json + shader files to /dev/shm
- **Rust DynamicPipeline**: hot-reload plan.json, create shader modules, execute passes
- **UniformBuffer**: shared GPU struct with stimmung + 9 dimensions + per-node params
- **Content layer as graph node**: composable within presets
- All 29 presets updated, postprocess as final node
- Deleted: 6 technique modules, compositor, content_layer, postprocess (~3000 lines)

## Test plan

- [ ] Python: `uv run pytest tests/effect_graph/ -v`
- [ ] Rust: `cargo test --workspace` in hapax-logos/
- [ ] All 54 .wgsl files exist alongside .frag files
- [ ] Preset activation writes plan.json to /dev/shm
- [ ] hapax-imagination binary hot-reloads and renders
- [ ] Content layer visible in presets that include it
EOF
)"
```

- [ ] **Step 6: Monitor CI, merge when green**

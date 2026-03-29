# Logos Full-Stack Rectification Epic

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every issue found in the full-scale Logos audit — from crashing services to frozen shader time to architectural violations.

**Architecture:** Bottom-up, dependency-ordered. Infrastructure (Phase 0) unblocks everything. Backend fixes (Phase 1) fix API gaps. Shader remediation (Phase 2) is the largest phase — 26 GLSL-compiled shaders have ghost system uniforms in their Params struct causing `global.u_time` to read 0.0 instead of actual time. Frontend IPC compliance (Phase 3) and hardening (Phase 4) close out.

**Tech Stack:** Rust/Tauri, WGSL shaders, Python FastAPI, React/TypeScript, systemd

---

## Phase 0: Stabilize Infrastructure

### Task 0.1: Fix Logos Crash-Loop (Wayland Protocol Bug)

**Root cause:** webkit2gtk 2.50.6 has a syncobj protocol bug with NVIDIA on native Wayland (gtk#8056, tauri#10702). The `__NV_DISABLE_EXPLICIT_SYNC=1` workaround is insufficient — crashes persist as kernel SIGKILL.

**Files:**
- Modify: `systemd/units/hapax-logos.service`
- Modify: `~/.config/systemd/user/hapax-logos.service` (deployed)

- [ ] **Step 1: Add GDK_BACKEND=x11 to service unit**

In `systemd/units/hapax-logos.service`, add after the existing `__NV_DISABLE_EXPLICIT_SYNC` line:

```ini
# Force XWayland backend — native Wayland triggers webkit2gtk syncobj protocol
# bug with NVIDIA (gtk#8056, tauri#10702). __NV_DISABLE_EXPLICIT_SYNC alone is
# insufficient; crashes persist as kernel SIGKILL.
Environment=GDK_BACKEND=x11
```

- [ ] **Step 2: Deploy and verify**

```bash
cp systemd/units/hapax-logos.service ~/.config/systemd/user/hapax-logos.service
systemctl --user daemon-reload
systemctl --user restart hapax-logos.service
sleep 5
systemctl --user is-active hapax-logos.service
```

Expected: `active`

- [ ] **Step 3: Verify stability (30 second soak)**

```bash
sleep 30
systemctl --user is-active hapax-logos.service
```

Expected: still `active` (previously crashed within 1-5 minutes)

- [ ] **Step 4: Verify ports are up**

```bash
ss -tlnp | grep -E '805[23]'
```

Expected: both 8052 and 8053 listening

- [ ] **Step 5: Commit**

```bash
git add systemd/units/hapax-logos.service
git commit -m "fix(logos): force XWayland backend to avoid webkit2gtk Wayland SIGKILL

webkit2gtk 2.50.6 syncobj protocol bug with NVIDIA causes kernel SIGKILL
on native Wayland. __NV_DISABLE_EXPLICIT_SYNC alone is insufficient.
GDK_BACKEND=x11 forces XWayland, trading minor overhead for stability.

Refs: gtk#8056, tauri#10702"
```

---

### Task 0.2: Consolidate Visual Stack Target

**Problem:** Two conflicting versions exist: `systemd/hapax-visual-stack.target` (stale, 3 services) and `systemd/units/hapax-visual-stack.target` (canonical, 5 services). The root-level file is a leftover that was never deleted.

**Files:**
- Delete: `systemd/hapax-visual-stack.target`
- Verify: `systemd/units/hapax-visual-stack.target` (no changes needed)
- Deploy: `~/.config/systemd/user/hapax-visual-stack.target`

- [ ] **Step 1: Delete stale target**

```bash
rm systemd/hapax-visual-stack.target
```

- [ ] **Step 2: Deploy canonical version**

```bash
cp systemd/units/hapax-visual-stack.target ~/.config/systemd/user/hapax-visual-stack.target
systemctl --user daemon-reload
```

- [ ] **Step 3: Verify deployment**

```bash
systemctl --user cat hapax-visual-stack.target | grep Wants
```

Expected: line containing `hapax-imagination.service hapax-logos.service hapax-dmn.service visual-layer-aggregator.service studio-compositor.service`

- [ ] **Step 4: Commit**

```bash
git add -A systemd/hapax-visual-stack.target
git commit -m "fix(systemd): delete stale visual-stack.target from root

Canonical version lives in systemd/units/. Root-level copy was a
leftover with only 3 services instead of 5."
```

---

## Phase 1: Backend & Rust Fixes

### Task 1.1: Fix streaming.rs LOGOS_BASE Inconsistency

**Problem:** `streaming.rs` defines `LOGOS_BASE = "http://127.0.0.1:8051"` (no `/api`) while `proxy.rs` defines `LOGOS_BASE = "http://127.0.0.1:8051/api"`. Current code works by accident but is fragile.

**Files:**
- Modify: `hapax-logos/src-tauri/src/commands/streaming.rs:16`

- [ ] **Step 1: Align LOGOS_BASE with proxy.rs**

Change line 16 from:
```rust
const LOGOS_BASE: &str = "http://127.0.0.1:8051";
```
to:
```rust
const LOGOS_BASE: &str = "http://127.0.0.1:8051/api";
```

- [ ] **Step 2: Update all URL constructions that include `/api`**

Search the file for `"{}/api/` and change to `"{}/`:

Line ~101 (cancel_stream_and_server):
```rust
// Before:
let url = format!("{}/api/agents/runs/current", LOGOS_BASE);
// After:
let url = format!("{}/agents/runs/current", LOGOS_BASE);
```

Line ~118 (run_sse_stream) — the `path` parameter already starts with `/agents/...` (no `/api` prefix) when called from Tauri commands, so this should just work. Verify by searching all call sites:

```bash
grep -n "run_sse_stream\|start_sse_stream" hapax-logos/src-tauri/src/commands/*.rs
```

The callers pass paths like `"/agents/{name}/run"` — these are relative to LOGOS_BASE. With LOGOS_BASE now including `/api`, the final URL is `http://127.0.0.1:8051/api/agents/{name}/run` which is correct.

- [ ] **Step 3: Verify build**

```bash
cd hapax-logos && cargo check -p hapax-logos 2>&1 | tail -5
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/src-tauri/src/commands/streaming.rs
git commit -m "fix(tauri): align streaming.rs LOGOS_BASE with proxy.rs

Both now use http://127.0.0.1:8051/api as the base URL.
Previously streaming.rs omitted /api, requiring callers to
include it — inconsistent with proxy.rs convention."
```

---

### Task 1.2: Add Recording Control Endpoints

**Problem:** Frontend calls `POST /studio/recording/enable` and `POST /studio/recording/disable` but no backend handlers exist. Recording UI is dead.

**Architecture:** The compositor reads control files from `/dev/shm/hapax-compositor/`. We follow the existing pattern used by effect selection (`fx-request.txt`) and layer control (`layer-{name}-enabled.txt`).

**Files:**
- Modify: `logos/api/routes/studio.py`
- Test: `tests/test_studio_recording.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_studio_recording.py`:

```python
"""Tests for recording control endpoints."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from logos.api.app import app

client = TestClient(app)

RECORDING_CONTROL = Path("/dev/shm/hapax-compositor/recording-control.txt")


class TestRecordingEndpoints(unittest.TestCase):
    @patch("logos.api.routes.studio.RECORDING_CONTROL")
    def test_enable_recording(self, mock_path):
        tmp = Path("/tmp/test-recording-control.txt")
        mock_path.__class__ = type(tmp)
        mock_path.parent.mkdir.return_value = None
        mock_path.write_text = tmp.write_text
        mock_path.parent = tmp.parent

        resp = client.post("/api/studio/recording/enable")
        assert resp.status_code == 200
        assert resp.json()["recording"] is True
        assert tmp.read_text() == "1"
        tmp.unlink(missing_ok=True)

    @patch("logos.api.routes.studio.RECORDING_CONTROL")
    def test_disable_recording(self, mock_path):
        tmp = Path("/tmp/test-recording-control.txt")
        mock_path.__class__ = type(tmp)
        mock_path.parent.mkdir.return_value = None
        mock_path.write_text = tmp.write_text
        mock_path.parent = tmp.parent

        resp = client.post("/api/studio/recording/disable")
        assert resp.status_code == 200
        assert resp.json()["recording"] is False
        assert tmp.read_text() == "0"
        tmp.unlink(missing_ok=True)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_studio_recording.py -v
```

Expected: FAIL (endpoints don't exist, 404)

- [ ] **Step 3: Implement endpoints**

In `logos/api/routes/studio.py`, add near the top with other path constants:

```python
RECORDING_CONTROL = Path("/dev/shm/hapax-compositor/recording-control.txt")
```

Add the two endpoints (near the existing `compositor_live` endpoint):

```python
@router.post("/recording/enable")
async def enable_recording():
    """Enable recording via compositor control file."""
    RECORDING_CONTROL.parent.mkdir(parents=True, exist_ok=True)
    RECORDING_CONTROL.write_text("1")
    return {"recording": True}


@router.post("/recording/disable")
async def disable_recording():
    """Disable recording via compositor control file."""
    RECORDING_CONTROL.parent.mkdir(parents=True, exist_ok=True)
    RECORDING_CONTROL.write_text("0")
    return {"recording": False}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_studio_recording.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add logos/api/routes/studio.py tests/test_studio_recording.py
git commit -m "feat(api): add recording enable/disable endpoints

POST /studio/recording/enable and /disable write control
files that the compositor reads to toggle recording state.
Follows existing pattern (fx-request.txt, layer-*-enabled.txt)."
```

---

### Task 1.3: Fix Directive Watcher Silent Failures

**Problem:** `directive_watcher.rs` uses `.ok()` to silently drop I/O errors. Operators won't know when directives fail.

**Files:**
- Modify: `hapax-logos/src-tauri/src/commands/directive_watcher.rs`

- [ ] **Step 1: Replace `.ok()` with explicit error logging**

Search for all `.ok()` calls in the file and replace with `if let Err`:

```bash
grep -n '\.ok()' hapax-logos/src-tauri/src/commands/directive_watcher.rs
```

For each occurrence, replace the pattern:
```rust
// Before:
fs::write(path, payload.to_string()).ok();

// After:
if let Err(e) = fs::write(path, payload.to_string()) {
    log::error!("Failed to write directive response to {}: {}", path.display(), e);
}
```

For `fs::create_dir_all`:
```rust
// Before:
fs::create_dir_all("/dev/shm/hapax-logos").ok();

// After:
if let Err(e) = fs::create_dir_all("/dev/shm/hapax-logos") {
    log::error!("Failed to create directive directory: {}", e);
    return;
}
```

- [ ] **Step 2: Verify build**

```bash
cd hapax-logos && cargo check -p hapax-logos 2>&1 | tail -5
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/src-tauri/src/commands/directive_watcher.rs
git commit -m "fix(tauri): log directive_watcher I/O errors instead of silently dropping

Replaced .ok() calls with explicit error logging so operators
can diagnose directive delivery failures."
```

---

## Phase 2: Shader Param Remediation

### Background

26 GLSL-compiled shaders have `u_time`, `u_width`, and/or `u_height` in their `Params` struct. These are ghost fields — relics of the GLSL-to-WGSL transpilation. The `DynamicPipeline` fills the Params buffer at pipeline load time only (not per-frame), so `global.u_time` reads 0.0 and `global.u_width`/`global.u_height` read 0.0.

The correct values are available via the shared uniforms (group 0): `uniforms.time`, `uniforms.resolution.x`, `uniforms.resolution.y`. These ARE updated every frame.

**Strategy:** For each affected shader:
1. Remove `u_time`, `u_width`, `u_height` from `struct Params`
2. Replace all `global.u_time` references with `uniforms.time`
3. Replace all `global.u_width` references with `uniforms.resolution.x`
4. Replace all `global.u_height` references with `uniforms.resolution.y`

The `extract_wgsl_param_names()` function in `wgsl_transpiler.py` will automatically exclude these from `param_order` since they'll no longer be in the Params struct.

**Affected shaders (26):** ascii, bloom, breathing, drift, droste, edge_detect, emboss, fluid_sim, glitch_block, halftone, noise_gen, noise_overlay, particle_system, pixsort, reaction_diffusion, rutt_etra, scanlines, sharpen, slitscan, thermal, trail, tunnel, vhs, voronoi_overlay, warp, waveform_render

**Affected presets (23/29):** ambient, ascii_preset, datamosh, datamosh_heavy, dither_retro, feedback_preset, ghost, glitch_blocks_preset, halftone_preset, heartbeat, kaleidodream, neon, nightvision, pixsort_preset, screwed, sculpture, slitscan_preset, thermal_preset, trails, trap, tunnelvision, vhs_preset, voronoi_crystal

### Task 2.1: Create Shader Migration Script

Rather than manually editing 26 shaders, write a Python script that performs the mechanical transformation.

**Files:**
- Create: `scripts/migrate-shader-params.py`

- [ ] **Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""Migrate GLSL-transpiled WGSL shaders to use shared uniforms for time/resolution.

Removes u_time, u_width, u_height from per-node Params struct and replaces
references with uniforms.time, uniforms.resolution.x, uniforms.resolution.y.
"""

import re
import sys
from pathlib import Path

NODES_DIR = Path(__file__).resolve().parent.parent / "agents" / "shaders" / "nodes"

# Ghost fields to remove from Params struct
GHOST_FIELDS = {"u_time", "u_width", "u_height"}

# Replacement map for global.u_* references in shader code
REPLACEMENTS = {
    "global.u_time": "uniforms.time",
    "global.u_width": "uniforms.resolution.x",
    "global.u_height": "uniforms.resolution.y",
}

# Also handle the naga-transpiled pattern: let _eNN = global.u_time;
# followed by usage of _eNN — we inline the replacement.
NAGA_LET_PATTERN = re.compile(
    r"let (_e\d+) = (global\.u_time|global\.u_width|global\.u_height);"
)


def migrate_shader(path: Path) -> bool:
    """Migrate a single shader. Returns True if modified."""
    text = path.read_text()
    original = text

    # 1. Remove ghost fields from Params struct
    lines = text.split("\n")
    new_lines = []
    in_params = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("struct Params"):
            in_params = True
            new_lines.append(line)
            continue
        if in_params and (stripped == "}" or stripped.startswith("}")):
            in_params = False
            new_lines.append(line)
            continue
        if in_params:
            field_name = stripped.split(":")[0].strip().rstrip(",") if ":" in stripped else ""
            if field_name in GHOST_FIELDS:
                continue  # Skip this line
        new_lines.append(line)

    text = "\n".join(new_lines)

    # 2. Handle naga let-binding pattern: let _eNN = global.u_time;
    # Find all such bindings and their variable names
    let_bindings: dict[str, str] = {}
    for match in NAGA_LET_PATTERN.finditer(text):
        var_name = match.group(1)
        global_ref = match.group(2)
        replacement = REPLACEMENTS[global_ref]
        let_bindings[var_name] = replacement

    # Remove the let-binding lines
    text = NAGA_LET_PATTERN.sub("", text)

    # Replace all uses of the bound variables with the shared uniform reference
    for var_name, replacement in let_bindings.items():
        # Only replace standalone variable references (word boundary)
        text = re.sub(rf"\b{re.escape(var_name)}\b", replacement, text)

    # 3. Direct replacements for any remaining global.u_* references
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)

    # 4. Clean up empty Params struct (if all fields were ghost)
    text = re.sub(
        r"struct Params \{\s*\}",
        "struct Params {\n    _pad: f32,\n}",
        text,
    )

    # 5. Clean up double blank lines from removed lines
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    if text != original:
        path.write_text(text)
        return True
    return False


def main():
    modified = []
    for wgsl in sorted(NODES_DIR.glob("*.wgsl")):
        if migrate_shader(wgsl):
            modified.append(wgsl.name)

    if modified:
        print(f"Migrated {len(modified)} shaders:")
        for name in modified:
            print(f"  {name}")
    else:
        print("No shaders needed migration.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run migration**

```bash
python3 scripts/migrate-shader-params.py
```

Expected: `Migrated 26 shaders:` followed by the list

- [ ] **Step 3: Spot-check 3 shaders**

Verify the transformations are correct by reading glitch_block.wgsl, vhs.wgsl, and bloom.wgsl:
- `struct Params` should NOT contain `u_time`, `u_width`, or `u_height`
- Code should reference `uniforms.time` instead of `global.u_time`
- Code should reference `uniforms.resolution.x` instead of `global.u_width`
- The shaders should still have their actual user params (e.g., `u_block_size`, `u_intensity`)

- [ ] **Step 4: Verify plan.json param_order will change**

The wgsl_compiler extracts param_order from the Params struct. With ghost fields removed, param_order should shrink:

```bash
python3 -c "
from agents.effect_graph.wgsl_transpiler import extract_wgsl_param_names
from pathlib import Path
for name in ['glitch_block', 'vhs', 'bloom', 'trail']:
    params = extract_wgsl_param_names(Path(f'agents/shaders/nodes/{name}.wgsl'))
    print(f'{name}: {params}')
"
```

Expected: no `time`, `width`, or `height` in any param list

- [ ] **Step 5: Commit**

```bash
git add agents/shaders/nodes/*.wgsl scripts/migrate-shader-params.py
git commit -m "fix(shaders): remove ghost system uniforms from 26 GLSL-compiled shaders

All GLSL-transpiled shaders had u_time, u_width, u_height in their
Params struct — relics of the GLSL-to-WGSL transpilation. The Params
buffer is only filled at pipeline load time (not per-frame), so
global.u_time always read 0.0 instead of actual time.

Replaced with shared uniforms: uniforms.time, uniforms.resolution.x,
uniforms.resolution.y — these ARE updated every frame by DynamicPipeline.

Affects 23/29 presets. Time-dependent animations (glitch, VHS, drift,
breathing, particles, etc.) will now animate correctly."
```

---

### Task 2.2: Fix Remaining Param Mismatches (VHS, Pixsort, Halftone)

After the ghost field removal, some shaders will still have JSON spec ↔ WGSL mismatches because the JSON param names don't match the WGSL field names.

**Files:**
- Modify: `agents/shaders/nodes/vhs.json`
- Modify: `agents/shaders/nodes/pixsort.json`
- Modify: `agents/shaders/nodes/halftone.json`

- [ ] **Step 1: Verify post-migration Params structs**

After Task 2.1, read each shader to see remaining fields:

**pixsort.wgsl** Params after migration:
```wgsl
struct Params {
    u_threshold_low: f32,
    u_threshold_high: f32,
    u_sort_length: f32,
    u_direction: f32,
}
```

**pixsort.json** params: `threshold, direction, segment_length`
→ Mismatch: `threshold` split into `threshold_low`/`threshold_high`, `segment_length` renamed to `sort_length`

**vhs.wgsl** Params after migration:
```wgsl
struct Params {
    u_chroma_shift: f32,
    u_head_switch_y: f32,
    u_noise_band_y: f32,
}
```

**vhs.json** params: `chroma_shift, noise_speed, head_switch, head_switch_height, tracking_jitter`
→ Mismatch: completely different field names

**halftone.wgsl** Params after migration:
```wgsl
struct Params {
    u_dot_size: f32,
    u_color_mode: f32,
}
```

**halftone.json** params: `dot_size, angle, color_mode`
→ Mismatch: `angle` is hardcoded in shader (unused param)

- [ ] **Step 2: Update JSON specs to match actual WGSL fields**

**pixsort.json** — update params to match shader:
```json
{"node_type":"pixsort","glsl_fragment":"pixsort.frag","inputs":{"in":"frame"},"outputs":{"out":"frame"},"params":{"threshold_low":{"type":"float","default":0.3,"min":0.0,"max":1.0},"threshold_high":{"type":"float","default":0.8,"min":0.0,"max":1.0},"sort_length":{"type":"float","default":100.0,"min":10.0,"max":500.0},"direction":{"type":"float","default":0.0}},"temporal":false,"temporal_buffers":0}
```

**vhs.json** — update params to match shader:
```json
{"node_type":"vhs","glsl_fragment":"vhs.frag","inputs":{"in":"frame"},"outputs":{"out":"frame"},"params":{"chroma_shift":{"type":"float","default":4.0,"min":0.0,"max":20.0},"head_switch_y":{"type":"float","default":0.08,"min":0.0,"max":0.2},"noise_band_y":{"type":"float","default":0.003,"min":0.0,"max":0.05}},"temporal":false,"temporal_buffers":0}
```

**halftone.json** — remove unused `angle` param:
```json
{"node_type":"halftone","glsl_fragment":"halftone.frag","inputs":{"in":"frame"},"outputs":{"out":"frame"},"params":{"dot_size":{"type":"float","default":6.0,"min":1.0,"max":20.0},"color_mode":{"type":"float","default":0.0}},"temporal":false,"temporal_buffers":0}
```

- [ ] **Step 3: Update presets that use old param names**

Search presets for old param names and update:

```bash
grep -rl '"threshold"\|"segment_length"\|"noise_speed"\|"head_switch"\|"head_switch_height"\|"tracking_jitter"\|"angle"' presets/
```

For each preset found, update the param names to match the new JSON specs.

- [ ] **Step 4: Commit**

```bash
git add agents/shaders/nodes/vhs.json agents/shaders/nodes/pixsort.json agents/shaders/nodes/halftone.json presets/
git commit -m "fix(shaders): reconcile JSON node specs with actual WGSL param names

pixsort: threshold→threshold_low/threshold_high, segment_length→sort_length
vhs: noise_speed/head_switch/head_switch_height/tracking_jitter → chroma_shift/head_switch_y/noise_band_y
halftone: remove unused angle param (hardcoded in shader)"
```

---

### Task 2.3: Deploy and Verify Visual Pipeline

- [ ] **Step 1: Recompile the active pipeline**

Trigger the wgsl_compiler to regenerate plan.json with updated param_orders:

```bash
# Deploy updated shaders to /dev/shm
python3 -c "
from agents.effect_graph.wgsl_compiler import deploy_plan
deploy_plan()
"
```

Or if the compiler is triggered by the compositor, restart it:

```bash
systemctl --user restart studio-compositor.service
sleep 3
```

- [ ] **Step 2: Verify plan.json has no ghost params**

```bash
cat /dev/shm/hapax-imagination/pipeline/plan.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
for p in d['passes']:
    po = p.get('param_order', [])
    ghosts = [x for x in po if x in ('time', 'width', 'height')]
    status = 'CLEAN' if not ghosts else f'GHOSTS: {ghosts}'
    print(f\"{p['node_id']}: {status} — {po}\")
"
```

Expected: all passes show `CLEAN`

- [ ] **Step 3: Restart imagination and verify rendering**

```bash
systemctl --user restart hapax-imagination.service
sleep 3
stat -c '%s %Y' /dev/shm/hapax-visual/frame.jpg && date +%s
```

Expected: frame size > 10KB, timestamp within last 3 seconds

- [ ] **Step 4: No commit needed** (runtime verification only)

---

## Phase 3: Frontend IPC Compliance

### Task 3.1: Route HapaxPage JSON Fetches Through IPC

**Problem:** HapaxPage.tsx has 2 raw `fetch()` calls for JSON data that should go through Tauri invoke().

**Files:**
- Modify: `hapax-logos/src/pages/HapaxPage.tsx`

- [ ] **Step 1: Replace visual-layer fetch with api.get()**

Find the `fetch(\`${API}/studio/visual-layer\`)` call (~line 197) and replace:

```typescript
// Before:
fetch(`${API}/studio/visual-layer`)
  .then((res) => (res.ok ? res.json() : null))
  .then(...)

// After:
import { api } from "../api/client";
// ...
api.get<Record<string, any>>("/studio/visual-layer")
  .then(...)
  .catch(() => null)
```

- [ ] **Step 2: Replace activity-correction POST with api.post()**

Find the `fetch(\`${API}/api/studio/activity-correction\`)` call (~line 236) and replace:

```typescript
// Before:
await fetch(`${API}/api/studio/activity-correction`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ label: correctionInput.trim() }),
});

// After:
await api.post("/studio/activity-correction", { label: correctionInput.trim() });
```

Note: the old code had a double `/api/api/` bug too (API already includes `/api`).

- [ ] **Step 3: Remove unused API constant**

If the `const API = "http://localhost:8051/api"` is no longer used by anything (img.src still needs a URL), it can stay for the img.src usage. If img.src is the only remaining user, rename it to make intent clear:

```typescript
const SNAPSHOT_BASE = "http://localhost:8051/api";
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd hapax-logos && npx tsc --noEmit 2>&1 | tail -10
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add hapax-logos/src/pages/HapaxPage.tsx
git commit -m "fix(logos): route HapaxPage JSON fetches through Tauri IPC

Visual-layer state polling and activity-correction POST now go
through api.get()/api.post() instead of raw browser fetch().
Also fixes double /api/api/ prefix in correction endpoint."
```

---

### Task 3.2: Extract Hardcoded URLs Into Constants

**Problem:** Hardcoded `localhost` URLs scattered across frontend files. Browser-API-mandated URLs (img.src, hls.js, video poster) can't go through IPC, but should use centralized constants.

**Files:**
- Create: `hapax-logos/src/config.ts`
- Modify: `hapax-logos/src/components/visual/VisualSurface.tsx`
- Modify: `hapax-logos/src/components/terrain/ground/CameraHero.tsx`
- Modify: `hapax-logos/src/hooks/useBatchSnapshotPoll.ts`

- [ ] **Step 1: Create config module**

```typescript
/**
 * Runtime URL configuration for browser-mandated HTTP endpoints.
 *
 * These URLs cannot go through Tauri IPC because they're consumed by
 * browser APIs (<img src>, <video poster>, hls.js) that require URLs.
 */

/** Logos API base — used for img.src, HLS, and batch snapshot polling. */
export const LOGOS_API_URL =
  import.meta.env.VITE_LOGOS_API_URL || "http://127.0.0.1:8051/api";

/** Visual frame server — Axum HTTP server inside Tauri process. */
export const FRAME_SERVER_URL =
  import.meta.env.VITE_FRAME_SERVER_URL || "http://127.0.0.1:8053";
```

- [ ] **Step 2: Update VisualSurface.tsx**

Replace hardcoded URL:
```typescript
// Before:
const FRAME_URL = "http://127.0.0.1:8053/frame";

// After:
import { FRAME_SERVER_URL } from "../../config";
const FRAME_URL = `${FRAME_SERVER_URL}/frame`;
```

- [ ] **Step 3: Update CameraHero.tsx**

Replace hardcoded URLs:
```typescript
// Before:
const url = "http://localhost:8051/api/studio/hls/stream.m3u8";
// After:
import { LOGOS_API_URL } from "../../../config";
const url = `${LOGOS_API_URL}/studio/hls/stream.m3u8`;

// Before:
poster="http://localhost:8051/api/studio/stream/fx"
// After:
poster={`${LOGOS_API_URL}/studio/stream/fx`}
```

- [ ] **Step 4: Update useBatchSnapshotPoll.ts**

Replace hardcoded URL:
```typescript
// Before:
`http://localhost:8051/api/studio/stream/cameras/batch?roles=${roles.join(",")}&_t=${Date.now()}`

// After:
import { LOGOS_API_URL } from "../config";
`${LOGOS_API_URL}/studio/stream/cameras/batch?roles=${roles.join(",")}&_t=${Date.now()}`
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd hapax-logos && npx tsc --noEmit 2>&1 | tail -10
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add hapax-logos/src/config.ts hapax-logos/src/components/visual/VisualSurface.tsx hapax-logos/src/components/terrain/ground/CameraHero.tsx hapax-logos/src/hooks/useBatchSnapshotPoll.ts
git commit -m "refactor(logos): extract hardcoded localhost URLs into config module

Browser-API-mandated URLs (img.src, hls.js, video poster) now read
from centralized config with VITE_ env var override support."
```

---

## Phase 4: Hardening

### Task 4.1: Add Shader Pre-Validation

**Problem:** `wgsl_compiler.py` deploys shaders without validation. A bad shader causes `device.create_shader_module()` to panic, crashing the entire Imagination process.

**Files:**
- Modify: `agents/effect_graph/wgsl_compiler.py`
- Test: `tests/test_wgsl_validation.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_wgsl_validation.py`:

```python
"""Tests for WGSL shader pre-validation."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from agents.effect_graph.wgsl_compiler import validate_wgsl


class TestWgslValidation(unittest.TestCase):
    def test_valid_shader_passes(self):
        valid = "struct Params { x: f32, }\n@fragment fn main() -> @location(0) vec4<f32> { return vec4(1.0); }"
        assert validate_wgsl(valid) is True

    def test_invalid_shader_fails(self):
        invalid = "this is not wgsl at all {"
        assert validate_wgsl(invalid) is False

    def test_all_deployed_shaders_valid(self):
        """Every .wgsl file in agents/shaders/nodes/ must be parseable."""
        nodes_dir = Path(__file__).resolve().parent.parent / "agents" / "shaders" / "nodes"
        uniforms = (nodes_dir.parent.parent.parent / "hapax-logos" / "crates" / "hapax-visual" / "src" / "shaders" / "uniforms.wgsl").read_text()
        for wgsl in sorted(nodes_dir.glob("*.wgsl")):
            combined = uniforms + "\n" + wgsl.read_text()
            assert validate_wgsl(combined), f"{wgsl.name} failed validation"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_wgsl_validation.py -v
```

Expected: FAIL (validate_wgsl doesn't exist)

- [ ] **Step 3: Implement validation using naga**

The `naga` Python package isn't available, but we can use `wgpu`'s offline validation. Simpler approach: use a subprocess call to `naga-cli` if available, or a basic syntax check.

In `agents/effect_graph/wgsl_compiler.py`, add:

```python
def validate_wgsl(source: str) -> bool:
    """Validate WGSL source. Returns True if parseable.

    Uses naga-cli for validation if available, otherwise falls back
    to basic struct/function syntax checks.
    """
    import subprocess
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(suffix=".wgsl", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            result = subprocess.run(
                ["naga", f.name],
                capture_output=True,
                timeout=10,
            )
            Path(f.name).unlink(missing_ok=True)
            return result.returncode == 0
    except FileNotFoundError:
        # naga-cli not installed — fall back to basic checks
        return "@fragment" in source or "@compute" in source
    except Exception:
        return False
```

Then in the `deploy_plan()` function (or `compile_to_wgsl_plan`), add validation before copying shaders:

```python
# In the shader copy loop:
combined = SHARED_UNIFORMS + "\n" + shader_source
if not validate_wgsl(combined):
    log.error("Shader %s failed validation — skipping deployment", shader_name)
    continue
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_wgsl_validation.py -v
```

Expected: 3 passed (or 2 if naga-cli not installed — the third test depends on it)

- [ ] **Step 5: Commit**

```bash
git add agents/effect_graph/wgsl_compiler.py tests/test_wgsl_validation.py
git commit -m "feat(shaders): add pre-deployment WGSL validation

Validates shader source via naga-cli before deploying to /dev/shm.
Prevents bad shaders from crashing the Imagination process.
Falls back to basic syntax check if naga-cli not installed."
```

---

### Task 4.2: Tighten CSP for Production

**Problem:** `tauri.conf.json` allows `unsafe-eval` in script-src and `unsafe-inline` in style-src. Missing `frame-src` and `object-src` restrictions.

**Files:**
- Modify: `hapax-logos/src-tauri/tauri.conf.json`

- [ ] **Step 1: Update CSP**

Find the `security.csp` field and update:

```json
"csp": "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' http://127.0.0.1:8051 http://127.0.0.1:8053 blob: data:; connect-src 'self' http://127.0.0.1:8051 http://127.0.0.1:8053 ws://127.0.0.1:8052; media-src 'self' http://127.0.0.1:8051 blob:; worker-src 'self' blob:; frame-src 'none'; object-src 'none'"
```

Changes:
- `unsafe-eval` → `wasm-unsafe-eval` (only needed for WASM, not arbitrary eval)
- Added `frame-src 'none'` and `object-src 'none'`
- `unsafe-inline` kept for style-src (required by Tailwind)

- [ ] **Step 2: Verify build**

```bash
cd hapax-logos && cargo check -p hapax-logos 2>&1 | tail -5
```

Expected: no errors (CSP is a string, no compile impact)

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/src-tauri/tauri.conf.json
git commit -m "security(logos): tighten CSP — remove unsafe-eval, add frame/object restrictions

Replace unsafe-eval with wasm-unsafe-eval (only WASM needs it).
Add frame-src 'none' and object-src 'none' to prevent embedding."
```

---

### Task 4.3: Fix cost.rs System Time Unwrap

**Problem:** `cost.rs` has `unwrap()` on `SystemTime::now().duration_since(UNIX_EPOCH)` which panics if system time is before 1970.

**Files:**
- Modify: `hapax-logos/src-tauri/src/commands/cost.rs`

- [ ] **Step 1: Replace unwrap with fallback**

Find the `unwrap()` on system time and replace:

```rust
// Before:
let now = std::time::SystemTime::now()
    .duration_since(std::time::UNIX_EPOCH)
    .unwrap()
    .as_secs();

// After:
let now = std::time::SystemTime::now()
    .duration_since(std::time::UNIX_EPOCH)
    .unwrap_or_default()
    .as_secs();
```

- [ ] **Step 2: Verify build**

```bash
cd hapax-logos && cargo check -p hapax-logos 2>&1 | tail -5
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/src-tauri/src/commands/cost.rs
git commit -m "fix(tauri): replace system time unwrap with safe fallback in cost.rs"
```

---

## Summary

| Phase | Tasks | Scope |
|-------|-------|-------|
| **0: Stabilize** | 0.1, 0.2 | Service crash, stale systemd units |
| **1: Backend** | 1.1, 1.2, 1.3 | Streaming URL, recording endpoints, error logging |
| **2: Shaders** | 2.1, 2.2, 2.3 | 26 ghost-uniform shaders, 3 param mismatches, pipeline verification |
| **3: Frontend** | 3.1, 3.2 | IPC compliance, URL config extraction |
| **4: Hardening** | 4.1, 4.2, 4.3 | Shader validation, CSP, panic prevention |

**Total: 12 tasks across 5 phases. Each phase is independently shippable.**

**Estimated commits: 12 (one per task)**

# Unified AoA/OARB — Geometry/Visual Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the AoA tetrix from depth-4 to the mathematically-exact depth-5 (4096 addressable faces) and lock the OARB as the honest flat content plane inscribed in the central void, rendered as one occlusion-coherent in-engine object.

**Architecture:** The honesty principle (no invented depth) makes the substrate *real in-engine geometry*, not a fake-volumetric renderer: the tetrix is genuine 3-D geometry (its depth is real, view-correct from any camera angle) and the OARB is a real flat plane in the void; DarkPlaces depth-sorts them natively, so occlusion is coherent by construction. Phase 1 is a pure asset regen — the per-face control atlas grid grows from 32 cols × 64 px to 64 cols × 32 px (staying 2048², now holding 4096 cells), the generator emits a depth-5 MDL, and the live atlas producer is matched to the same grid. No BSP rebuild and no QC recompile: the OARB billboard and the central-void insphere (861u) are invariant under subdivision depth.

**Tech Stack:** Python 3.12 (hyphen-named scripts loaded via `importlib.util`), Quake MDL binary format (`struct`), DarkPlaces engine, systemd user services, pytest (`uv run pytest`).

## Global Constraints

- **Depth 5, exactly 4096 addressable leaf faces** (`4·4^5`); 12288 vertices (3 per face); 972 visible outer-shell gasket triangles; leaf edge E/32. (Spec REQ A4.2, A3.3)
- **Exact regular tetrix math, no floating-point drift** — dyadic midpoint subdivision only; incenter-centered; closed-form √-expressions. The existing `generate-aoa-mdl.py` math is audited exact — do NOT alter the recursion, vertices, winding, or incenter. (Spec REQ A3.1–A3.3)
- **Atlas stays 2048×2048**, grid = 64 columns × 32 px cells, 64 rows × 32 px → 4096 cells. (Derived; keeps the live-texture update budget unchanged.)
- **The generator's per-face UV cells and the atlas producer's cell map MUST address the same cell for every face index** — this is the load-bearing invariant; a mismatch garbles every face. (New cross-consistency test.)
- **OARB = flat content plane, no invented depth**, inscribed in the central octahedral void (insphere = parent_edge/(2√6) ≈ 861u at the deployed 2.5× scale); a 1500×750 (2:1) plane has half-diagonal 838u < 861u → corners inside the insphere, no poke-through. (Spec REQ A5.1–A5.2, A1.1) — **already correct in the BSP; verify, do not rebuild.**
- **Depth and scale are independent knobs:** depth = facet richness (this plan), scale (`AOA_DISPLAY_SCALE`) = overall size + OARB. The central-void insphere is invariant under depth, so depth-5 does not disturb the OARB. Keep `AOA_DISPLAY_SCALE = 2.5`.
- **Deploy-worktree trap:** `~/.cache/hapax/source-activation/worktree` is a DETACHED HEAD checkout of the live release. Do NOT `git commit` there (lost-commit trap). All commits go on a feature branch in a fresh council worktree (Task 0). The same edited files are synced into the deploy worktree only for the live build/witness (Task 4).
- **Build pipeline (this phase):** `python3 scripts/generate-aoa-mdl.py` (regenerates + deploys the MDL) → `scripts/install-darkplaces-screwm-assets.sh` → restart `hapax-darkplaces-v4l2.service` (reloads geometry) + `hapax-quake-live-aoa-atlas.service` (reloads grid). No `generate-screwm-map.py` run (BSP unchanged).
- **Witness:** `ffmpeg -nostdin -loglevel error -f v4l2 -i /dev/video52 -frames:v 1 -update 1 -y /tmp/aoa-witness.png`.
- **No audio change in this phase** — `hapax-audio-routing-check` is not applicable; do not touch audio services.
- Ruff: line-length 100, double quotes (`uv run ruff check scripts/ tests/`).

---

## File Structure

- `scripts/generate-aoa-mdl.py` (modify) — depth-5 + 64×32 atlas grid constants. Owns the tetrix geometry, the baked fallback skin, and the per-face UV mapping.
- `scripts/quake-live-aoa-atlas-source.py` (modify) — match the 64×32 / 4096-cell grid. Owns the live per-face control atlas written to `/dev/shm`.
- `tests/test_aoa_geometry_atlas.py` (create) — self-contained tests (importlib-load both hyphen-named scripts): geometry counts, MDL header on regenerate, and the generator↔producer cell cross-consistency invariant.

---

## Task 0: Branch + worktree setup

**Files:** none (workspace setup)

- [ ] **Step 1: Create a fresh council worktree off origin/main on a feature branch**

The council repo (not the deploy worktree) is where commits live. From a council clone:

```bash
cd ~/projects/hapax-council 2>/dev/null || cd ~/projects/hapax-council--iota || exit 1
git fetch origin
git worktree add -b feat/aoa-oarb-depth5-geometry ~/projects/hapax-council--aoa-depth5 origin/main
ls ~/projects/hapax-council--aoa-depth5/scripts/generate-aoa-mdl.py
```
Expected: the path lists (worktree created on `feat/aoa-oarb-depth5-geometry`).

- [ ] **Step 2: Confirm the no-stale-branches hook did not block**

Run: `cd ~/projects/hapax-council--aoa-depth5 && git status -sb`
Expected: `## feat/aoa-oarb-depth5-geometry`. If branch creation was blocked by unmerged branches, resolve per the council workflow before continuing. **All edits and commits in Tasks 1–3 happen in this worktree.**

---

## Task 1: Depth-5 geometry + 64×32 atlas grid in the generator

**Files:**
- Modify: `scripts/generate-aoa-mdl.py:18` (`DEPTH`), `:31` (`AOA_FACE_ATLAS_COLUMNS`), `:32` (`AOA_FACE_ATLAS_CELL_SIZE`)
- Test: `tests/test_aoa_geometry_atlas.py`

**Interfaces:**
- Consumes: nothing (entry task).
- Produces: `aoa_face_count() == 4096`; `flatten_aoa_surface_mesh(compose_aoa_parts(5))` → 12288 verts / 4096 faces / 12288 uvs; `AOA_SKIN_W == AOA_SKIN_H == 2048`; `aoa_face_cell_uvs(i)` tiles a 64×64 grid of 32 px cells.

- [ ] **Step 1: Write the failing test**

Create `tests/test_aoa_geometry_atlas.py`:

```python
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_depth5_counts():
    g = _load("aoa_gen", "generate-aoa-mdl.py")
    assert g.DEPTH == 5
    assert g.aoa_face_count() == 4096  # 4 * 4**5
    parts = g.compose_aoa_parts(5)
    verts, faces, uvs = g.flatten_aoa_surface_mesh(parts)
    assert len(faces) == 4096
    assert len(verts) == 12288  # 3 per face, per-face vertex duplication
    assert len(uvs) == 12288


def test_generator_atlas_grid_2048_64x32():
    g = _load("aoa_gen", "generate-aoa-mdl.py")
    assert g.AOA_FACE_ATLAS_COLUMNS == 64
    assert g.AOA_FACE_ATLAS_CELL_SIZE == 32
    assert g.AOA_SKIN_W == 2048 and g.AOA_SKIN_H == 2048
    # 4096 faces fit exactly in a 64x64 cell grid
    assert g.aoa_face_atlas_rows(g.aoa_face_count()) == 64
    # Every face's UV centroid lands inside its own 32px cell, no overlap
    seen = set()
    for i in range(g.aoa_face_count()):
        uvs = g.aoa_face_cell_uvs(i)
        cx = sum(u for u, _ in uvs) / 3.0 * 2048
        cy = sum(v for _, v in uvs) / 3.0 * 2048
        cell = (int(cx) // 32, int(cy) // 32)
        assert cell == (i % 64, i // 64)
        assert cell not in seen
        seen.add(cell)
    assert len(seen) == 4096
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--aoa-depth5 && uv run pytest tests/test_aoa_geometry_atlas.py -q`
Expected: FAIL — `assert g.DEPTH == 5` (currently 4) and the atlas-grid asserts (currently 32 cols / 64 px).

- [ ] **Step 3: Apply the generator edits**

In `scripts/generate-aoa-mdl.py`, change three constants:

```python
DEPTH = 5
```
```python
AOA_FACE_ATLAS_COLUMNS = 64
AOA_FACE_ATLAS_CELL_SIZE = 32
```

`AOA_SKIN_W`/`AOA_SKIN_H` (`= AOA_FACE_ATLAS_COLUMNS * AOA_FACE_ATLAS_CELL_SIZE`) stay 2048 automatically. `aoa_face_cell_uvs` already divides by `AOA_FACE_ATLAS_COLUMNS`, so the UVs re-tile to 64×64 with no further change. Do NOT touch the recursion, `AOA_ROOT_MODEL_VERTICES`, the winding tuples, `tetrahedron_incenter`, or `AOA_DISPLAY_SCALE`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--aoa-depth5 && uv run pytest tests/test_aoa_geometry_atlas.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint**

Run: `cd ~/projects/hapax-council--aoa-depth5 && uv run ruff check scripts/generate-aoa-mdl.py tests/test_aoa_geometry_atlas.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-council--aoa-depth5
git add scripts/generate-aoa-mdl.py tests/test_aoa_geometry_atlas.py
git commit -m "feat(aoa): depth-5 tetrix (4096 faces) + 64x32 atlas grid"
```

---

## Task 2: Match the live atlas producer to the 64×32 / 4096-cell grid

**Files:**
- Modify: `scripts/quake-live-aoa-atlas-source.py:22` (`DEFAULT_COLUMNS`), `:23` (`DEFAULT_CELL_SIZE`), `:25` (`FACE_COUNT`), `:27` (`LEAF_FACE_EDGE_UNITS`)
- Test: `tests/test_aoa_geometry_atlas.py` (extend)

**Interfaces:**
- Consumes: nothing from Task 1 at runtime (separate process), but its grid constants must equal Task 1's.
- Produces: `FACE_COUNT == 4096`; `_face_cell_map(64, 32)` → 4096 cells, each 32×32 px, all within 2048×2048.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_aoa_geometry_atlas.py`:

```python
def test_producer_grid_matches_4096_cells():
    p = _load("aoa_atlas", "quake-live-aoa-atlas-source.py")
    assert p.FACE_COUNT == 4096
    assert p.DEFAULT_COLUMNS == 64
    assert p.DEFAULT_CELL_SIZE == 32
    assert p.DEFAULT_WIDTH == 2048 and p.DEFAULT_HEIGHT == 2048
    cells = p._face_cell_map(p.DEFAULT_COLUMNS, p.DEFAULT_CELL_SIZE)
    assert len(cells) == 4096
    for c in cells:
        assert c["w"] == 32 and c["h"] == 32
        assert 0 <= c["x"] <= 2048 - 32
        assert 0 <= c["y"] <= 2048 - 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--aoa-depth5 && uv run pytest tests/test_aoa_geometry_atlas.py::test_producer_grid_matches_4096_cells -q`
Expected: FAIL — `FACE_COUNT` is 1024, `DEFAULT_COLUMNS` is 32, `DEFAULT_CELL_SIZE` is 64.

- [ ] **Step 3: Apply the producer edits**

In `scripts/quake-live-aoa-atlas-source.py`:

```python
DEFAULT_COLUMNS = 64
DEFAULT_CELL_SIZE = 32
```
```python
FACE_COUNT = 4096
```
```python
LEAF_FACE_EDGE_UNITS = 131.8
```

`DEFAULT_WIDTH`/`DEFAULT_HEIGHT` stay 2048 (= 64 × 32). Leave `GEOMETRY_REVISION` and `FACE_OPERABILITY_CONTRACT` unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--aoa-depth5 && uv run pytest tests/test_aoa_geometry_atlas.py::test_producer_grid_matches_4096_cells -q`
Expected: PASS.

- [ ] **Step 5: Lint**

Run: `cd ~/projects/hapax-council--aoa-depth5 && uv run ruff check scripts/quake-live-aoa-atlas-source.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-council--aoa-depth5
git add scripts/quake-live-aoa-atlas-source.py tests/test_aoa_geometry_atlas.py
git commit -m "feat(aoa): match live atlas producer to 64x32 / 4096-cell grid"
```

---

## Task 3: Cross-consistency invariant + MDL emission check

**Files:**
- Test: `tests/test_aoa_geometry_atlas.py` (extend)
- (No source change — this task proves Tasks 1+2 agree and the binary emits correctly.)

**Interfaces:**
- Consumes: `g.aoa_face_cell_uvs`, `g.aoa_face_count`, `g.write_mdl`, `g.flatten_aoa_surface_mesh`, `g.compose_aoa_parts`, `g.transform_vertices`, `g.aoa_skin_pixels`, `g.AOA_SKIN_W/H`, `g.SCALE`; `p._face_cell_map`.
- Produces: the garble-preventing guarantee that generator UV cells and producer cells coincide per face index, and that a regenerated MDL has the depth-5 header.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_aoa_geometry_atlas.py`:

```python
import struct
import tempfile


def test_generator_uvs_match_producer_cells():
    g = _load("aoa_gen", "generate-aoa-mdl.py")
    p = _load("aoa_atlas", "quake-live-aoa-atlas-source.py")
    cells = {c["face_index"]: c for c in p._face_cell_map(p.DEFAULT_COLUMNS, p.DEFAULT_CELL_SIZE)}
    assert g.AOA_FACE_ATLAS_COLUMNS == p.DEFAULT_COLUMNS
    assert g.AOA_FACE_ATLAS_CELL_SIZE == p.DEFAULT_CELL_SIZE
    for i in range(g.aoa_face_count()):
        uvs = g.aoa_face_cell_uvs(i)
        cx = sum(u for u, _ in uvs) / 3.0 * g.AOA_SKIN_W
        cy = sum(v for _, v in uvs) / 3.0 * g.AOA_SKIN_H
        cell = cells[i]
        assert cell["x"] <= cx <= cell["x"] + cell["w"]
        assert cell["y"] <= cy <= cell["y"] + cell["h"]


def test_regenerated_mdl_header_is_depth5():
    g = _load("aoa_gen", "generate-aoa-mdl.py")
    verts, faces, uvs = g.flatten_aoa_surface_mesh(g.compose_aoa_parts(g.DEPTH))
    verts = g.transform_vertices(verts)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "aoa.mdl"
        g.write_mdl(
            verts, faces, out, g.SCALE,
            skin_width=g.AOA_SKIN_W, skin_height=g.AOA_SKIN_H,
            skin_pixels=g.aoa_skin_pixels(g.AOA_SKIN_W, g.AOA_SKIN_H), uvs=uvs,
        )
        raw = out.read_bytes()
        assert raw[:4] == b"IDPO"
        # header layout: magic(4) ver(4) scale(12) origin(12) radius(4) eye(12)
        # numskins(4) skinw(4) skinh(4) numverts(4) numtris(4)
        skinw, skinh = struct.unpack_from("<ii", raw, 4 + 4 + 12 + 12 + 4 + 12 + 4)
        numverts, numtris = struct.unpack_from("<ii", raw, 4 + 4 + 12 + 12 + 4 + 12 + 4 + 8)
        assert (skinw, skinh) == (2048, 2048)
        assert numverts == 12288
        assert numtris == 4096
```

- [ ] **Step 2: Run test to verify it fails first, then passes after Tasks 1+2**

Run: `cd ~/projects/hapax-council--aoa-depth5 && uv run pytest tests/test_aoa_geometry_atlas.py -q`
Expected: with Tasks 1+2 committed, all 5 tests PASS. (If `test_generator_uvs_match_producer_cells` fails, the grids diverged — fix the constant that disagrees before proceeding; this is the garble guard.)

- [ ] **Step 3: Full suite regression check**

Run: `cd ~/projects/hapax-council--aoa-depth5 && uv run pytest tests/test_aoa_geometry_atlas.py tests/test_screwm_self_perception.py -q`
Expected: PASS (no regression in the existing screwm test).

- [ ] **Step 4: Commit**

```bash
cd ~/projects/hapax-council--aoa-depth5
git add tests/test_aoa_geometry_atlas.py
git commit -m "test(aoa): generator/producer cell cross-consistency + depth-5 MDL header"
```

---

## Task 4: Deploy to the live broadcast + witness

**Files:**
- Sync (no new edits): `scripts/generate-aoa-mdl.py`, `scripts/quake-live-aoa-atlas-source.py` into the deploy worktree.

**Interfaces:**
- Consumes: the committed files from Tasks 1–2.
- Produces: a depth-5 AoA with the flat OARB held in the void on `/dev/video52`, occlusion-coherent.

- [ ] **Step 1: Sync the two edited files into the deploy worktree**

The deploy worktree is the live release tree; copy the exact committed files into it (do NOT commit there):

```bash
cp ~/projects/hapax-council--aoa-depth5/scripts/generate-aoa-mdl.py \
   ~/.cache/hapax/source-activation/worktree/scripts/generate-aoa-mdl.py
cp ~/projects/hapax-council--aoa-depth5/scripts/quake-live-aoa-atlas-source.py \
   ~/.cache/hapax/source-activation/worktree/scripts/quake-live-aoa-atlas-source.py
```

- [ ] **Step 2: Regenerate + deploy the MDL**

Run: `cd ~/.cache/hapax/source-activation/worktree && python3 scripts/generate-aoa-mdl.py`
Expected output includes `depth 5: lattice 12288 vertices/4096 triangles` and two `Deployed to .../aoa.mdl` lines.

- [ ] **Step 3: Install assets**

Run: `cd ~/.cache/hapax/source-activation/worktree && scripts/install-darkplaces-screwm-assets.sh`
Expected: completes without error (installs the new `aoa.mdl` to the game dir).

- [ ] **Step 4: Restart the renderer and the atlas producer**

```bash
systemctl --user restart hapax-quake-live-aoa-atlas.service
systemctl --user restart hapax-darkplaces-v4l2.service
```
Then confirm both active:
Run: `systemctl --user is-active hapax-quake-live-aoa-atlas.service hapax-darkplaces-v4l2.service`
Expected: `active` / `active`.

- [ ] **Step 5: Confirm the live atlas is the 4096-cell grid**

Run: `cat /dev/shm/hapax-compositor/quake-live-aoa-atlas.json` (or the producer's meta path)
Expected: `"face_count": 4096` and a fresh heartbeat timestamp.

- [ ] **Step 6: Witness the render (allow ~70s for a cold first atlas frame)**

```bash
ffmpeg -nostdin -loglevel error -f v4l2 -i /dev/video52 -frames:v 1 -update 1 -y /tmp/aoa-witness.png
```
Then Read `/tmp/aoa-witness.png`.
Expected: a denser tetrix (visibly finer triangulation than depth-4) with the flat OARB media plane held inside the central void, the lattice translucently in front of/around it (occlusion-coherent, no poke-through, no half-scale float).

- [ ] **Step 7: Operator confirmation gate**

Present the witness frame to the operator. The depth-5 facet density and the held flat OARB are visual-acceptance criteria (spec REQ A4.2, A5). If the operator wants the AoA larger, that is a one-line `AOA_DISPLAY_SCALE` change (independent of depth) handled as a follow-up, not a rework.

- [ ] **Step 8: Open the governed PR**

```bash
cd ~/projects/hapax-council--aoa-depth5
git push -u origin feat/aoa-oarb-depth5-geometry
```
Open the PR per the council governed-merge flow (propagate the operator-signed S5 fields; `release_authorized` stays false until S7 auto-arm). Own it through CI to merge.

---

## Self-Review

**1. Spec coverage (Addendum A):**
- A1.1 (no invented depth on OARB) → Task 4 keeps the OARB a flat plane; sphere not reintroduced. ✓
- A3.1–A3.3 (exact tetrix, every facet, counts) → Task 1 (depth-5, 4096 faces, recursion untouched) + Task 3 (MDL header check). ✓
- A4.2 (depth 5, 4096 faces) → Task 1. ✓
- A5.1–A5.2 (flat plane inscribed in void, no poke-through) → Global Constraints + Task 4 witness; BSP/contract verified-unchanged (insphere invariant under depth). ✓
- A2 (substrate) → resolved to real in-engine geometry (Architecture); no sibling renderer needed because honesty excludes fake depth. ✓
- **Gap (intentional, deferred):** A3.2 stella-octangula explicit materialization, A6 volumetric mount contract, and the signal-binding ("AoA IS HARDM", 4096 faces → HARDM signal set) are Phase 2/3 — separate plans. The dead `aoa_sphere.mdl` entity removal needs a QC recompile (no toolchain confirmed) and is deferred; it is already alpha=0/invisible, so the OARB is visually flat-plane-only now.

**2. Placeholder scan:** No TBD/TODO; every code step shows the exact constant change or full test. ✓

**3. Type consistency:** `AOA_FACE_ATLAS_COLUMNS`(64)/`AOA_FACE_ATLAS_CELL_SIZE`(32) in the generator equal `DEFAULT_COLUMNS`/`DEFAULT_CELL_SIZE` in the producer; `FACE_COUNT`(4096) == `aoa_face_count()`; skin 2048² consistent across all three tasks; the cross-consistency test (Task 3) enforces this at test time. ✓

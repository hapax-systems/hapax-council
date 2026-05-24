# Screwm-Quake Phase 1 Audit

**Branch:** `alpha/self-grounding-aperture-awareness`
**Commits audited:** 11 (from `16a023807` through `f232196f8`)
**Spec:** `docs/superpowers/specs/2026-05-23-screwm-quake-hybrid-isap.md`
**Date:** 2026-05-23

---

## 1. Spec-vs-Implementation Gaps

### 1.1 CRITICAL: v4l2 Device Number Mismatch

The spec references `/dev/video70` in 6 places (architecture diagram, deliverables D6, evidence gates). The implementation uses `/dev/video52`:

- `pipeline.py:37` — `DARKPLACES_V4L2_DEVICE = "/dev/video52"`
- Commit `869018fba` explicitly changed from video70 to video52

But the docstring on `_add_darkplaces_background()` still says "Falls back to black background if /dev/video70 is not available." The constant and docstring contradict each other, and both contradict the spec.

**Action required:** Reconcile. Either update the spec to say video52 (if that's the correct device after MAX_DEVICES=8 constraint) or fix the code. Update the docstring regardless.

### 1.2 CRITICAL: QuakeHomage Not Registered

`agents/studio_compositor/homage/quake.py` defines `QUAKE_PACKAGE` but it is never imported or registered in `homage/__init__.py`. The `__init__.py` registers BitchX (3 variants) and Enlightenment-Moksha (2 variants) but has zero references to quake/Quake.

The package cannot be activated at runtime. This blocks spec §8 ("QuakeHomage registered as third HomagePackage") and any ward rendering in Quake aesthetic.

**Action required:** Add `from .quake import QUAKE_PACKAGE` and `register_package(QUAKE_PACKAGE)` to `homage/__init__.py`.

### 1.3 HIGH: BSP Textures Not Found

The BSP compile log shows 4 missing texture warnings:
```
WARNING: unable to find texture ground1_6
WARNING: unable to find texture sky4
WARNING: unable to find texture city4_2
WARNING: unable to find texture metal5_2
```

These are stock Quake 1 texture names. LibreQuake pak0/pak1 may provide them, but the build log confirms they were NOT available at compile time. The BSP will render with purple/missing checkerboard textures until the WAD or replacement textures are properly referenced.

Spec §4 D3 ("CC0 Texture Pipeline") lists this as "IN PROGRESS — epsilon lane," but the committed BSP was compiled without any textures available. The BSP itself is checked in as a binary artifact — recompilation after texture availability requires regenerating it.

**Action required:** Either provide the textures (WAD file or TGA replacements in `textures/`) before BSP compilation, or regenerate the BSP once textures are available. Current BSP will show missing texture patterns.

### 1.4 MEDIUM: Geometry Mismatch — Rectangular Not Octagonal

Spec §5 says "Tower BSP (8 octagonal walls, ramps, floor, ceiling)." The actual `screwm.map` is a **rectangular** box:
- 2 axis-aligned wall pairs (4 walls total)
- Floor slab + ceiling slab = 6 structural brushes
- 4 internal ramp brushes (flat platforms, not ramps)
- Total: 10 brushes

The geometry is an axis-aligned rectangular room 594×594×496 Quake units, not an octagonal tower. This is cosmetically significant but functionally acceptable as Phase 0 scaffolding.

### 1.5 MEDIUM: Compositor Layout JSON Not Updated

Spec §5 D7 says "Layout JSON update: DarkPlaces as background layer." No changes to `config/compositor-layouts/default.json` appear in the branch diff. The DarkPlaces source integration is code-level only (`_add_darkplaces_background()` in pipeline.py), not reflected in the layout configuration system.

### 1.6 MEDIUM: Ambient Sound Fully Commented Out

All `sound()` and `precache_sound()` calls in `world.qc` are commented out:
```c
// sound(snd, 1, "ambient/perception_rumble.ogg", 0.6, 3);
// precache_sound("ambient/perception_rumble.ogg");
```

Sound entities are spawned at correct positions but produce no audio. Spec §6.2 ("Sound Implementation") describes a detailed 5-zone system that is entirely unimplemented.

### 1.7 MEDIUM: No Cognitive Coupling Implementation

Spec §7 describes QuakeC reading `/dev/shm` state files via `fopen`/`fgets` for stimmung-driven camera speed, working mode map swaps, voice activity, and content density coupling. None of this is implemented:

- No `coupling.qc` file exists (spec D4 lists it as part of the QuakeC mod)
- `camera.qc` uses a hardcoded `CAMERA_PERIOD = 135` instead of stimmung-driven period
- No `/dev/shm` file reading anywhere in the QC code
- No working mode detection or map switching logic

The `fopen` builtin is declared in `defs.qc` (#110, verified correct) but never called.

### 1.8 LOW: Spec Claims 5 Texture Types, Map Uses 4

Spec §6.1 describes 5 distinct texture themes per tower level. The map uses only 4 unique textures: `ground1_6` (floor), `sky4` (ceiling), `city4_2` (walls), `metal5_2` (ramps). No per-level texture differentiation exists.

### 1.9 LOW: Map Has Leak Portals

`screwm.leak.prt` exists with 3 portal entries, suggesting the BSP compiler detected potential leak paths. While the compile log doesn't explicitly say "LEAK," the presence of this file warrants verification that the map is fully sealed.

---

## 2. Code Quality Issues

### 2.1 HIGH: Docstring / Constant Contradiction (pipeline.py)

```python
DARKPLACES_V4L2_DEVICE = "/dev/video52"  # line 37

def _add_darkplaces_background(...):
    """...Falls back to black background if /dev/video70 is not available."""  # line 48
```

The constant says video52; the docstring says video70. One is wrong.

### 2.2 MEDIUM: No Error Recovery for Partial Pipeline Linkage (pipeline.py)

`_add_darkplaces_background()` adds 4 elements to the pipeline (`src`, `caps`, `convert`, `queue`), links them, then requests a compositor sink pad. If the sink pad request or pad link fails, the function returns `False` but leaves orphaned elements in the pipeline. These orphans will cause state transition warnings when the pipeline starts.

Should either remove the elements on failure or use a try/finally pattern.

### 2.3 MEDIUM: Camera Pitch Calculation Is Approximate (camera.qc)

```c
ang_x = 0 - (look_dir_y / hdist) * 45.0;
```

This approximates pitch using a linear ratio scaled by 45 degrees instead of `atan2`. For the tower's geometry (Y range -32 to 352, camera radius ~60-120 units), this produces significant pitch error at steep angles — up to ~15° off at the top/bottom of the tower. Should use proper inverse tangent or at minimum scale by a more appropriate factor.

### 2.4 LOW: `avelocity` Redundant with Think Function (world.qc)

`aoa_entity.avelocity = '0 15 0'` sets engine-level angular velocity, but `aoa_think()` also manually rotates `self.angles_y += frametime * 15`. These will compound, rotating at double speed. Either remove `avelocity` or remove the manual rotation in `aoa_think`.

### 2.5 LOW: Hardcoded FPS in QuakeC (camera.qc)

```c
self.nextthink = time + 0.033; // ~30fps
```

Should reference a constant or match the engine's tick rate. DarkPlaces server runs at `sys_ticrate` (default 1/72 = 0.01389s). A 0.033s think interval means the camera updates at 30Hz while the engine renders at potentially 72Hz+, causing visible stutter in camera motion.

### 2.6 LOW: Missing `WatchdogSec` in Systemd Unit

Spec says "WatchdogSec=60s" but the committed `hapax-darkplaces.service` has no `WatchdogSec` directive. DarkPlaces has no sd_notify integration anyway, so watchdog would require a sidecar health check. The spec promise is currently undeliverable.

---

## 3. Architectural Concerns

### 3.1 obs-glcapture Dependency Chain

The systemd unit uses `obs-glcapture` (from `obs-vkcapture` package) to wrap DarkPlaces for OpenGL frame capture. This adds a runtime dependency on the OBS capture infrastructure even when OBS itself isn't running. The capture path is:

```
DarkPlaces (GL) → obs-glcapture (LD_PRELOAD GL intercept) → ??? → /dev/video52
```

The intermediate step is unclear — `obs-glcapture` captures frames for OBS's game capture source, not for v4l2loopback output. How do captured frames reach `/dev/video52`? This may require a separate OBS instance or a custom capture pipeline that isn't documented.

**Concern:** The capture architecture may not work as designed. `obs-glcapture` is an LD_PRELOAD hook that injects into GL calls and shares textures with OBS via shared memory. Without OBS running to consume those shared textures, the frames may go nowhere. The spec's original approach (DarkPlaces → window → v4l2loopback) via screen capture may be more reliable.

### 3.2 GPU Contention on 5060 Ti

The systemd unit pins DarkPlaces to GPU 1 (5060 Ti, 16GB). This GPU also hosts:
- hapax-daimonion STT (~5GB)
- hapax-imagination (~0.8GB, will retire but currently running)

DarkPlaces VRAM is estimated at 200-500MB. Total: ~6-6.3GB of 16GB. Within budget, but the 5060 Ti is also the daimonion's exclusive GPU — adding a real-time 3D renderer could cause scheduling contention on the GPU compute queue, potentially affecting STT latency.

### 3.3 Binary Artifacts in Git

The branch commits binary files directly:
- `assets/quake/maps/screwm.bsp` (18.6KB)
- `assets/quake/maps/screwm.lit` (24.7KB)
- `assets/quake/models/aoa.mdl` (8.3KB)

These are generated artifacts from `scripts/generate-screwm-map.py` and `scripts/generate-aoa-mdl.py`. They should be `.gitignore`d and regenerated at build/deploy time, not tracked in git. The systemd unit's `ExecStartPre` already copies these from the repo — if they're regenerated at deploy time instead, the copy step can pull from the build output.

### 3.4 DarkPlaces Depends on hapax-secrets.service

The unit declares `After=hapax-secrets.service` and `Requires=hapax-secrets.service`. DarkPlaces is a standalone Quake engine that doesn't need any secrets. This dependency adds an unnecessary failure mode — if hapax-secrets fails, DarkPlaces won't start either. Should use `After=graphical-session.target` or similar.

### 3.5 Wayland Capture Uncertainty

DarkPlaces on Wayland cannot be captured via traditional X11 screen capture. The `obs-glcapture` approach intercepts OpenGL calls, but DarkPlaces compiled with SDL2 on Wayland may use Vulkan or EGL rather than GLX. The `__GLX_VENDOR_LIBRARY_NAME=nvidia` environment variable in the unit file suggests X11/GLX is expected, but the unit also sets `WAYLAND_DISPLAY=wayland-1`. These may conflict — if DarkPlaces opens a Wayland window, GLX vendor library settings are irrelevant.

---

## 4. Evidence Gate Status

| Gate | Status | Notes |
|------|--------|-------|
| DarkPlaces renders tower BSP with textures at 1280×720 | **FAILING** | BSP compiled without textures; all 4 texture names missing from build. Will render checkerboard. |
| v4l2loopback /dev/video70 captures DarkPlaces output | **FAILING** | Device is video52 not video70. obs-glcapture → v4l2 capture path is architecturally uncertain. |
| Compositor accepts DarkPlaces as background source with wards overlay | **UNTESTED** | Code exists (`_add_darkplaces_background`) but device mismatch + capture uncertainty block testing. |
| QuakeC pendulum camera traverses tower smoothly (120-150s period) | **PARTIAL** | Camera spline code exists and is mathematically sound. Hardcoded 135s period (spec says stimmung-driven 120-150s). Pitch approximation causes visible error at steep angles. Double-speed AoA rotation bug. |
| AoA Sierpinski tetrahedron visible and rotating at tower center | **PARTIAL** | Model exists (8.3KB MDL). `setmodel()` call present. Double rotation bug (avelocity + think). |
| 5 ambient sound zones audible | **FAILING** | All sound calls commented out. Entities spawned at correct positions but silent. |
| Working mode switch changes fog/textures | **NOT STARTED** | No coupling.qc, no /dev/shm reading, no map swap logic. |
| Stimmung energy modulates camera speed | **NOT STARTED** | Hardcoded CAMERA_PERIOD, no stimmung integration. |
| Textures CC0/BSD licensed | **PASSING** | LICENSES.md present, only LibreQuake (BSD) + project-authored assets. No proprietary id Software content. |
| Systemd unit starts/stops/restarts cleanly | **PARTIAL** | Unit exists, structurally valid. WatchdogSec missing per spec. hapax-secrets dependency unnecessary. |
| 1-hour stability test | **NOT TESTED** | |
| 39 shader nodes ported (Phase 4) | **NOT STARTED** | Phase 4 scope. |
| hapax-imagination disabled (Phase 6) | **NOT STARTED** | Phase 6 scope. |
| OBS screenshot verification | **NOT TESTED** | |

**Summary:** 1/14 gates passing, 3 partial, 5 failing, 5 not started/not tested.

---

## 5. Recommendations

1. **Fix video device mismatch** — pick one device number, update code constant + docstring + spec.
2. **Register QuakeHomage** — add import + `register_package(QUAKE_PACKAGE)` in `homage/__init__.py`.
3. **Fix double AoA rotation** — remove `avelocity` line (manual think rotation is more controllable).
4. **Fix camera pitch** — use `atan2` equivalent or at minimum correct the scaling factor.
5. **Resolve obs-glcapture architecture** — verify the capture chain actually works end-to-end, or switch to a window-capture approach.
6. **Provide textures before BSP compile** — either embed WAD reference or provide TGA overrides.
7. **Remove hapax-secrets dependency** from the DarkPlaces systemd unit.
8. **Gitignore binary artifacts** — regenerate BSP/LIT/MDL at deploy time.
9. **Uncomment sound calls** or defer sound evidence gate to Phase 2.
10. **Add coupling.qc** with at minimum stimmung-driven camera period to unblock the cognitive coupling evidence gate.

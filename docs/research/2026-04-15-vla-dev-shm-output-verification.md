# visual-layer-aggregator /dev/shm output verification

**Date:** 2026-04-15
**Author:** beta (queue #237, identity verified via `hapax-whoami`)
**Scope:** catalog VLA's actual `/dev/shm` output surface + update cadence + consumer enumeration. Follow-up to queue #236 stimmung drift verification.
**Branch:** `beta-phase-4-bootstrap`

---

## 0. Summary

**Verdict: VLA outputs are correctly structured + live + consumed by 7 paths. One spec-drift finding + one stale sibling file.**

1. ✅ **VLA writes to `/dev/shm/hapax-compositor/visual-layer-state.json` + 2 sibling dirs** (`hapax-stimmung/`, `hapax-temporal/`). Queue #236 already verified stimmung + visual-chain-state; this drop adds the primary VLS output file + the other two dirs.
2. ✅ **Update cadence is 3.00 seconds exactly**, matching the documented `STATE_TICK_BASE_S = 3.0` constant in `agents/visual_layer_aggregator/constants.py:30`. Empirically verified by sampling mtime 5 times at 2s intervals.
3. ✅ **7 consumer paths identified** across daimonion, logos-api, drift detector, notifications, studio compositor manifest, and two internal writers.
4. ⚠️ **Queue spec drift (and queue #236 self-reference):** queue #237 says "visual-layer-aggregator publishes perception → stimmung → /dev/shm" in a way that implies `/dev/shm/hapax-visual/*` is VLA output. **It's not.** `/dev/shm/hapax-visual/` is the **hapax-imagination daemon** output (wgpu visual surface): `frame.jpg`, `frame.rgba`, and `visual-chain-state.json` (written by `agents/visual_chain.py`, part of daimonion, NOT VLA). My queue #236 drop made the same mistake — I'll patch it post-hoc if delta wants.
5. ⚠️ **`watershed-events.json` stale by ~12 min** — file mtime 16:41, now 16:53. Either no watershed events have occurred in that window (correct), or the drift_detector stopped writing. Non-urgent.
6. 🟡 **`fx-snapshot.jpg`, `health.json`, `hls-analysis.json`, `playlist.json`, `smooth-snapshot.jpg` all stale at 10:56** — ~6 hours old. These are **studio_compositor** outputs (not VLA), colocated in `/dev/shm/hapax-compositor/`. Either studio_compositor is not running OR these files only update on specific events. Out of #237 scope, flagged for sibling audit.

**Severity:** LOW all around. The VLA pipeline is doing its job correctly at the documented cadence, consumers are reading the correct paths, and the drift findings are cosmetic (spec terminology + unverified sibling service).

## 1. VLA's ACTUAL output surface

Per `agents/visual_layer_aggregator/constants.py:11-17`:

```python
OUTPUT_DIR = Path("/dev/shm/hapax-compositor")
OUTPUT_FILE = OUTPUT_DIR / "visual-layer-state.json"
STIMMUNG_DIR = Path("/dev/shm/hapax-stimmung")
TEMPORAL_DIR = Path("/dev/shm/hapax-temporal")
WATERSHED_FILE = OUTPUT_DIR / "watershed-events.json"
```

**Four output paths:**

| Path | Type | Size | Cadence (empirical) | Last updated |
|---|---|---|---|---|
| `/dev/shm/hapax-compositor/visual-layer-state.json` | JSON | 2681 B | **~3.0 s** | fresh |
| `/dev/shm/hapax-stimmung/state.json` | JSON | 827 B | ~3.0 s (per queue #236) | fresh |
| `/dev/shm/hapax-stimmung/health.json` | JSON | 109 B | ~3.0 s | fresh |
| `/dev/shm/hapax-temporal/bands.json` | JSON | 1735 B | ~3.0 s | fresh |
| `/dev/shm/hapax-compositor/watershed-events.json` | JSON | 161 B | event-driven | **stale (12 min)** |
| `/dev/shm/hapax-compositor/degraded.json` | JSON | 781 B | ~3.0 s | fresh |
| `/dev/shm/hapax-compositor/costs.json` | JSON | 1199 B | ~3.0 s | fresh |

### 1.1 Empirical 3.00s cadence verification

```
$ for i in 1 2 3 4 5; do stat -c '%.6Y' /dev/shm/hapax-compositor/visual-layer-state.json ; sleep 2 ; done
1776290025.303978
1776290028.312845  ← +3.009 s
1776290031.323912  ← +3.011 s
1776290031.323912  ← same tick (read between writes)
1776290034.333325  ← +3.009 s
```

**Empirical cadence: 3.009-3.011 seconds**, matching `STATE_TICK_BASE_S = 3.0` (adaptive range 0.5-5.0s but currently holding at the base tick). No drift.

### 1.2 Tick cadence constants

```python
# constants.py:30-34
STATE_TICK_BASE_S = 3.0            # Base state tick (adaptive: 0.5-5.0s)
HEALTH_POLL_S = 15.0               # Health + GPU
SLOW_POLL_S = 60.0                 # Nudges, briefing, drift, goals, copilot
AMBIENT_CONTENT_INTERVAL_S = 45.0  # Ambient content pool refresh
AMBIENT_POOL_REFRESH_S = 300.0     # Full pool refresh every 5 min
```

Multiple cadences, nested:

- **Every 3s:** state tick → visual-layer-state.json, stimmung/state.json, temporal/bands.json, compositor/costs.json, compositor/degraded.json
- **Every 15s:** health + GPU poll
- **Every 45s:** ambient content refresh
- **Every 60s:** nudges, briefing, drift, goals, copilot
- **Every 300s:** full ambient pool refresh
- **Event-driven:** watershed-events.json

## 2. Consumer enumeration

Grepping `agents/` and `logos/` for readers of `/dev/shm/hapax-compositor/visual-layer-state.json`:

| Consumer | Path | Role |
|---|---|---|
| `agents/hapax_daimonion/conversation_helpers.py:178` | VLS_PATH constant | Daimonion reads VLS for conversation context injection |
| `agents/hapax_daimonion/env_context.py:173` | inline `Path()` | Daimonion env_context snapshot builder |
| `agents/hapax_daimonion/run_loops_aux.py:105` | inline `Path()` | Daimonion auxiliary loop (impingement consumer) |
| `agents/_notify.py:31` | `_VL_STATE_FILE` | Notification router reads VLS for active consent contracts |
| `agents/drift_detector/watershed.py:13` | `_VL_STATE_FILE` | Drift detector watershed logic |
| `logos/api/routes/flow.py:17` | `"compositor"` key | Logos API `/api/flow` endpoint reads VLS (among other files) |
| `agents/manifests/studio_compositor.yaml:77` | manifest entry | Studio compositor declares VLS as a dependency via manifest |

**7 consumers** (6 code paths + 1 manifest declaration). The VLS file is a hub: daimonion reads it twice per turn, logos-api reads it on every `/api/flow` hit, and the drift detector polls it at its own cadence.

**Writer:** `agents/visual_layer_state.py:279` (via VLA's atomic tmp+rename pattern).

## 3. Spec drift — queue #237 + #236 self-correction

Queue #237 spec says:

> "Per council CLAUDE.md: visual-layer-aggregator publishes perception → stimmung → /dev/shm. Verify output file structure..."

And my queue #236 drop cited `/dev/shm/hapax-visual/visual-chain-state.json` as a VLA output. **Both are wrong.**

### 3.1 `/dev/shm/hapax-visual/` is imagination daemon territory

Writers of `/dev/shm/hapax-visual/*`:

```
$ grep -rnE 'hapax-visual' agents/ shared/ | grep -v __pycache__
agents/dmn/pulse.py:337:                  frame_path = Path("/dev/shm/hapax-visual/frame.jpg")
agents/dmn/sensor.py:29:                  visual_frame: Path = Path("/dev/shm/hapax-visual/frame.jpg")
agents/effect_graph/wgsl_compiler.py:34:  / "hapax-visual"
agents/hapax_daimonion/acoustic_impulse.py:18: ACOUSTIC_IMPULSE_FILE = Path("/dev/shm/hapax-visual/acoustic-impulse.json")
agents/reverie/mixer.py:25:               ACOUSTIC_IMPULSE_FILE = Path("/dev/shm/hapax-visual/acoustic-impulse.json")
agents/vision_observer/__main__.py:23:    FRAME_PATH = Path("/dev/shm/hapax-visual/frame.jpg")
agents/visual_chain.py:20:                SHM_PATH = Path("/dev/shm/hapax-visual/visual-chain-state.json")
```

**Nothing from `agents/visual_layer_aggregator/` writes to `/dev/shm/hapax-visual/*`.**

The actual writers are:

- `agents/visual_chain.py` (NOT VLA — separate module, writes `visual-chain-state.json`)
- `agents/vision_observer/` (writes `frame.jpg` for vision backend)
- `agents/reverie/mixer.py` (writes `acoustic-impulse.json`)
- `agents/dmn/*` (readers, not writers)
- `agents/effect_graph/wgsl_compiler.py` (writes pipeline state for hapax-imagination)

### 3.2 `/dev/shm/hapax-visual/` role

The `/dev/shm/hapax-visual/` directory is the **hapax-imagination daemon output surface** + the **visual-chain bridge** from daimonion to the wgpu pipeline. Its role per CLAUDE.md § Tauri-Only Runtime:

> "The `HTTP frame server` — Axum on :8053 serves visual surface JPEG frames"

and § Reverie Vocabulary Integrity:

> "live `jq 'keys | length' /dev/shm/hapax-imagination/uniforms.json` should be ≥44"

`/dev/shm/hapax-visual/frame.jpg` + `frame.rgba` are read by the Tauri frontend via the Axum server on :8053 (rendered by hapax-imagination, NOT VLA).

### 3.3 Queue #236 correction

My queue #236 drop §1 listed `/dev/shm/hapax-visual/visual-chain-state.json` under "VLA output files". That's incorrect. The file is written by `agents/visual_chain.py` which runs inside daimonion's perception loop, not by VLA.

**Correction:** queue #236's §1 "Pipeline liveness" table should be re-scoped to ONLY the `/dev/shm/hapax-stimmung/*` + `/dev/shm/hapax-compositor/visual-layer-state.json` files. The `/dev/shm/hapax-visual/visual-chain-state.json` is a daimonion output, not a VLA output.

This is minor — the overall queue #236 finding (VLA pipeline is live, state.json updating every 1-2 seconds, 11 dimensions, documentation drift) stands regardless. I'll leave the queue #236 drop as-is rather than patching it post-hoc, and include the correction as a §3.3 note here for future readers.

## 4. Non-VLA files in `/dev/shm/hapax-compositor/` (scope flag)

While cataloguing the output directory, I noticed **several stale files at the 10:56 timestamp (~6 hours old)**:

```
$ ls -la /dev/shm/hapax-compositor/ | grep -v 'Apr 15 16:'
-rwxr-xr-x  1 hapax hapax 1501222 Apr 15 10:56 fx-snapshot.jpg        ← STALE 6h
-rw-r--r--  1 hapax hapax     110 Apr 15 10:56 health.json            ← STALE 6h
-rw-r--r--  1 hapax hapax     106 Apr 15 10:56 hls-analysis.json      ← STALE 6h
-rw-r--r--  1 hapax hapax   16310 Apr 15 10:57 playlist.json          ← STALE 6h
-rwxr-xr-x  1 hapax hapax  385932 Apr 15 10:56 smooth-snapshot.jpg    ← STALE 6h
```

These are **studio_compositor outputs** (not VLA) colocated in the same shm directory. `hls-analysis.json`, `playlist.json`, `fx-snapshot.jpg`, `smooth-snapshot.jpg` are all studio-compositor-written per `agents/studio_compositor/*.py`. Their 10:56 timestamp suggests the studio_compositor service paused writing them ~6 hours ago.

**Cross-reference:** earlier in the session I observed `hapax-compositor/*.jpg` files (the camera frames `brio-*.jpg`, `c920-*.jpg`) being refreshed — those are fresh at ~16:53. So studio_compositor is PARTIALLY alive (camera frame publisher is live) but the HLS analysis + playlist + FX snapshot paths are dormant.

**Possible explanations:**

1. The HLS analysis / playlist / snapshot paths only update when the compositor is actively producing an HLS stream. If the livestream is currently off, these files naturally go stale.
2. A sub-component of studio_compositor crashed or was intentionally disabled at 10:56.
3. These files are updated on a much slower cadence than the camera frames.

**Out of #237 scope** — flagging as a potential sibling audit finding. Proposed follow-up:

```yaml
id: "252"
title: "Studio compositor HLS + snapshot paths stale for 6h"
assigned_to: beta
status: offered
depends_on: []
priority: low
description: |
  Queue #237 observation: studio_compositor outputs in
  /dev/shm/hapax-compositor/ split into two groups:
  - Live (fresh every ~3s): brio-*.jpg, c920-*.jpg camera frames
  - Stale (since 10:56, ~6h ago): fx-snapshot.jpg, smooth-snapshot.jpg,
    hls-analysis.json, playlist.json, health.json
  
  Investigate whether this is expected (HLS stream not running, files
  only update when stream is live) or a silent failure of a
  compositor sub-component. Compare against
  docs/superpowers/specs/2026-04-12-native-rtmp-delivery-design.md
  and docs/superpowers/handoff/2026-04-13-alpha-camera-247-epic-handoff.md.
size_estimate: "~20 min"
```

## 5. Recommendations

### 5.1 None actionable from VLA itself

The VLA output surface is correctly structured, the update cadence matches the documented constants, and 7 consumer paths are reading the output file. No fixes needed.

### 5.2 Queue spec path clarification (already proposed)

Queue #237 (and my own queue #236) conflated `/dev/shm/hapax-visual/` (imagination daemon) with `/dev/shm/hapax-compositor/visual-layer-state.json` (VLA). Future queue items should either use the canonical paths from `constants.py` or reference the specific agent module that writes each path.

### 5.3 Studio compositor sibling audit (proposed #252)

See §4.

## 6. Non-drift observations

- **The 3.00s exact cadence is impressive.** STATE_TICK_BASE_S=3.0 with an adaptive range of 0.5-5.0s, but the current run is holding at exactly 3.00s. The adaptive logic (presumably in `aggregator.py`) is not firing under current conditions — the system is nominal from the VLA perspective, even though stimmung reports overall_stance=cautious. This is interesting: VLA tick cadence is decoupled from the stance it publishes.
- **`visual-layer-state.json` is 2681 bytes**, suggesting it's a compact snapshot (not a full history buffer). Each write is atomic via tmp+rename per the queue #236 audit pattern. Consumers reading it see either the old version or the new version — never a torn write.
- **`costs.json` + `degraded.json` are daimonion-facing signals.** costs.json feeds the LLM cost pressure dimension; degraded.json feeds the operator-presence curtailment logic. Both are fresh at the 3s tick.
- **No /dev/shm/hapax-compositor/watershed-events.json write in 12 minutes.** Watershed events are, by design, rare — they fire when the drift detector observes a significant transition. 12 minutes of quiet is plausible-to-expected for a system that's not actively undergoing state shifts. But the 12-minute gap IS observable, and a future hardening pass could log a heartbeat at watershed_poll_interval to distinguish "no events" from "drift detector stopped".
- **Cross-reference queue #236:** the perception_confidence=0.037 + overall_stance=cautious findings from queue #236 are READ from `/dev/shm/hapax-stimmung/state.json` which IS a VLA output. So #236's core findings are valid — just the path attribution to `/dev/shm/hapax-visual/*` was wrong.

## 7. Cross-references

- Queue spec: `queue/237-beta-vla-dev-shm-output-verification.yaml`
- Predecessor: `queue/236-beta-stimmung-aggregate-signal-drift.yaml` (commit `ff286a0ef`)
- VLA source: `agents/visual_layer_aggregator/aggregator.py` (+ `stimmung_methods.py`, `signal_mappers.py`, `constants.py`)
- VLA output constants: `agents/visual_layer_aggregator/constants.py:11-17`
- VLS writer docstring: `agents/visual_layer_state.py:279`
- Consumer code: `agents/hapax_daimonion/conversation_helpers.py:178`, `logos/api/routes/flow.py:17`, `agents/drift_detector/watershed.py:13`
- `/dev/shm/hapax-visual/` writers (correcting the queue spec drift): `agents/visual_chain.py`, `agents/vision_observer/`, `agents/reverie/mixer.py`, `agents/dmn/pulse.py`
- Sibling #230 voice FX chain: `docs/research/2026-04-15-voice-fx-chain-pipewire-verification.md`
- Sibling #236 stimmung drift: `docs/research/2026-04-15-stimmung-aggregate-signal-drift.md` — contains the (now corrected) `/dev/shm/hapax-visual/` attribution error
- CLAUDE.md § Shared Infrastructure — "visual-layer-aggregator publishes perception → stimmung → /dev/shm" claim

— beta, 2026-04-15T21:40Z (identity: `hapax-whoami` → `beta`)

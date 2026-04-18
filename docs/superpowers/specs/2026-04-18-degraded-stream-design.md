# DEGRADED-STREAM Mode (Safe Compositor Fallback) — Design

**Status:** 🟣 SPEC (provisionally approved 2026-04-18)
**Last updated:** 2026-04-18
**Source:** [`docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md`](../research/2026-04-18-homage-follow-on-dossier.md) §2 — Task #122
**Index:** [active-work-index](../plans/2026-04-18-active-work-index.md)
**Priority:** HIGH (live-deploy viewer protection)

---

## 1. Goal

Display a coherent, BitchX-authentic fallback surface during live code deploys (hapax-rebuild-services.timer cascade) so that mid-update glitches — partial ward rendering, shader-reload artifacts, ShmRgbaReader races — never reach viewers.

---

## 2. Current Risk Surface

- `hapax-rebuild-services.timer` fires every 5 minutes, checks per-service watch paths, restarts services whose sources changed.
- Restart sequence: systemd stops unit → ~200 ms gap → unit restarts → ~1–3 s before first valid frame.
- During the gap, the compositor keeps running but downstream wards may show stale/partial textures, ShmRgbaReader may return stale Reverie frames, or MIDI-driven wards may freeze.
- Broadcast tees (RTMP/HLS/recording) capture all of this unfiltered.

**Viewer impact today:** flicker, partial black frames, text snapping between fonts, stance-mismatched shaders.

---

## 3. Architecture

### 3.1 Signal

Systemd per-service `ExecStartPre` writes a flag:

```ini
ExecStartPre=/bin/sh -c 'echo "{\"reason\":\"rebuild\",\"service\":\"%n\",\"ts\":$(date +%s)}" > /dev/shm/hapax-compositor/degraded.flag'
ExecStartPost=/bin/rm -f /dev/shm/hapax-compositor/degraded.flag
```

(`%n` is the systemd unit name.)

Compositor main loop polls `degraded.flag` once per frame (16 ms @ 60 fps).

### 3.2 Ward: `degraded_stream_ward`

- Inherits `HomageTransitionalSource`.
- Activates on flag presence: all other wards transition to `absent`, `degraded_stream_ward` transitions to `entering` → `hold`.
- Deactivates on flag removal: `degraded_stream_ward` transitions to `exiting` → `absent`, other wards resume.
- Fade timing: 300 ms in / 500 ms out (slightly longer fade-out to hide any residual rebuild artifacts).

### 3.3 Visual grammar (BitchX-authentic)

Centered on canvas, Px437 IBM VGA 8×16:

```
*** hapax rebuilding • #hapax :+v operator
[----------------------------------------]  55% complete
-:- restart in progress: studio-compositor
```

- Line 1: mIRC bright-grey (package-grey idle + bright identity on `hapax` and `operator`).
- Line 2: IRC-style ASCII progress bar; progress derived from rebuild start time + heuristic ETA.
- Line 3: BitchX `-:-` status-message prefix + currently-rebuilding service name.
- Background: Gruvbox-dark solid with subtle CP437 noise pattern (matches BitchX netsplit aesthetic).

### 3.4 Scope of coverage

`degraded_stream_ward` overrides the full 1920×1080 canvas. Reverie substrate continues to run behind it (substrate-invariant from #124) but is fully occluded.

---

## 4. File-Level Plan

### New files
- `agents/studio_compositor/degraded_stream_ward.py` — HomageTransitionalSource subclass, renders the BitchX netsplit surface.
- `systemd/hapax-degraded-stream-signal.sh` — helper script invoked by `ExecStartPre`/`ExecStartPost` in all managed services.
- `tests/studio_compositor/test_degraded_stream.py` — flag-on/flag-off transition tests.

### Modified files
- `agents/studio_compositor/compositor.py` — main loop polls flag, dispatches to ward override.
- `agents/studio_compositor/legibility_sources.py` OR `ward_registry.py` — register `degraded_stream_ward`.
- `systemd/user/hapax-*.service` — every managed service gets `ExecStartPre`/`ExecStartPost` lines pointing at the helper script.
- `shared/director_observability.py` — `hapax_compositor_degraded_active{reason, service}` gauge + transition counter.

---

## 5. Observability

- `hapax_compositor_degraded_active{reason, service}` — Gauge (0 or 1).
- `hapax_compositor_degraded_activation_total{reason, service}` — Counter on each activation.
- `hapax_compositor_degraded_duration_seconds` — Histogram on exit.

Grafana panel: count of degraded activations per hour (alert if > 20/hour — suggests rebuild storm).

---

## 6. Interaction with HOMAGE Choreographer

- `degraded_stream_ward` is a **privileged override** — it bypasses the concurrency-limit enforcement of the choreographer.
- Choreographer treats the degraded ward as a "netsplit event" in BitchX vocabulary: it triggers mass-`absent` transition for all other wards as a side effect of its own `entering` transition.
- Metric `hapax_choreographer_rejection_total{reason="degraded_override"}` counts the skipped rejections (for audit).

---

## 7. Test Strategy

1. **Unit:** flag-file parser, ward state transition on flag change.
2. **Integration:** start compositor, touch flag, assert ward becomes visible within 500 ms.
3. **E2E:** trigger `systemctl --user restart hapax-daimonion.service`, capture RTMP stream, assert no partial-frame artifacts visible in the 3-second restart window.
4. **Negative:** simulate flag-write-race (write flag twice within 50 ms) — assert idempotent.

---

## 8. Open Questions

Q1. ETA heuristic: use rolling-mean-of-last-5-restart-durations or fixed 3-second estimate? Default: rolling mean, fallback to 3 s if no history.

Q2. Should `hapax-watch-receiver` and `hapax-phone-receiver` restarts trigger degraded mode? They don't affect visual surface. Default: NO, only visual-surface-adjacent services.

---

## 9. Implementation Order

1. Helper script + systemd unit drop-ins (no code change yet).
2. `degraded_stream_ward.py` + unit tests.
3. Wire into compositor main loop.
4. Prometheus metrics.
5. E2E test against live systemd restart.
6. Audit which services should trigger (answer Q2).
7. Ship.

---

## 10. Related

- **Dossier §2 #122** (source)
- **Rebuild timer:** `systemd/user/hapax-rebuild-services.timer`
- **HOMAGE substrate exemption:** `docs/superpowers/specs/2026-04-18-reverie-substrate-preservation-design.md` (Reverie keeps running behind degraded ward)
- **Stream mode governance:** `shared/stream_mode_intent.py` (degraded is *not* a stream mode; it's a compositor-layer override)

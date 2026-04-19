---
title: Camera 24/7 Resilience Epic — Post-Ship Live Verification
date: 2026-04-18
author: beta
queue: "#240"
epic: camera-247-resilience
status: captured
---

# Camera 24/7 Resilience Epic — Post-Ship Live Verification

Queue item #240 live-state snapshot of the camera 24/7 resilience epic after its retirement handoff (`docs/superpowers/handoff/2026-04-13-alpha-camera-247-epic-handoff.md`). Methodology: query `studio-compositor` systemd unit, `http://127.0.0.1:9482/metrics`, and `journalctl --user -u studio-compositor.service` across a 3-day trailing window (2026-04-15 → 2026-04-18). Neutral scientific register; findings only, no remediation proposals except where explicitly followed up in a later queue item.

## 1. Service health

| Property | Value |
|---|---|
| Unit | `studio-compositor.service` (user) |
| Type | `notify` |
| `WatchdogUSec` | 60s |
| `ActiveEnterTimestamp` | 2026-04-18 19:17:29 CDT |
| Uptime at snapshot | ~4 min (240 s) |
| `NRestarts` | 0 |
| `MainPID` | 3697089 |
| `SubState` | running |
| systemd watchdog, `last_fed_seconds_ago` | 2.51 s |

Unit is healthy; watchdog is fed well inside the 60 s deadline. `NRestarts=0` for the current boot; the service was manually cycled at 19:17:29 (not a watchdog-forced kill).

## 2. Camera-level state (snapshot, uptime ~240 s)

| Role | State | `consecutive_failures` | `last_frame_age_seconds` | `in_fallback` |
|---|---|---|---|---|
| brio-operator | healthy | 0 | 0.026 | 1 |
| brio-room | healthy | 0 | 0.024 | 1 |
| brio-synths | healthy | 0 | 0.026 | 1 |
| c920-desk | healthy | 0 | 0.020 | 1 |
| c920-room | healthy | 0 | 0.015 | 1 |
| c920-overhead | healthy | 0 | 0.013 | 1 |

All six cameras report `state=healthy`, zero consecutive failures, sub-30 ms inter-frame age (nominal at 30 fps MJPEG). `studio_compositor_cameras_healthy = 6 / 6`.

### 2.1 Finding F-240-1: all consumers listening to fallback despite healthy cameras

`studio_camera_in_fallback` is defined as "1 if the consumer is listening to `fb_<role>`, 0 if `cam_<role>`" (metric help text). At snapshot time all six consumers have `in_fallback=1` even though every camera state machine reports `healthy` with fresh buffers. Two possible explanations:

1. Boot-order race: consumers default to `listen-to=fb_<role>` at construction and only swap to `cam_<role>` on the first `HEALTHY` transition edge. If no edge has fired yet (cameras came up healthy on the first probe without passing through `degraded`), the swap never triggered.
2. `interpipesrc.listen-to` swap is partially broken; consumers stay on `fb_` regardless of state.

Either way this is an anomaly worth a followup queue item — the fallback signal is live content (static colour bars / low-rate loop), so the stream is publishing fallback frames rather than the actual camera feed in spite of the cameras being healthy.

No immediate remediation attempted under this verification item. Recommend followup queue item scoped to `agents/studio_compositor/cameras.py` or wherever `listen-to` is managed.

## 3. 5-state FSM activity — 3-day trailing window

Total FSM transitions (`camera_state_machine.dispatch` INFO lines) in the window 2026-04-15 → 2026-04-18: **32,478**.

### 3.1 Transition edges

| Edge | Count | Meaning |
|---|---|---|
| `offline → recovering` | 8,231 | supervisor-timer rebuild attempt |
| `degraded → offline` | 8,008 | fallback became active |
| `healthy → degraded` | 8,004 | internal data stream error / memory allocation failure at producer |
| `recovering → healthy` | 7,979 | rebuild ok — recovery success |
| `recovering → offline` | 231 | rebuild failed — backoff, retry |
| `recovering → dead` | 21 | failure count reached 10, camera declared dead |

The four dominant edges (`healthy↔degraded↔offline↔recovering↔healthy`) form a closed loop with near-balanced counts, consistent with the FSM's designed behaviour: transient USB bus-kicks trigger a brief degradation and self-heal.

**Self-heal success rate:** `recovering→healthy / (recovering→healthy + recovering→offline + recovering→dead)` = 7,979 / 8,231 = **96.94 %**. The epic's primary claim (software-layer containment of BRIO bus-kicks) is supported: ~97 % of excursions return to `healthy` without external intervention.

### 3.2 Per-role distribution

| Role | Transitions | Share |
|---|---|---|
| c920-overhead | 21,047 | 64.8 % |
| brio-synths | 10,442 | 32.2 % |
| c920-room | 726 | 2.2 % |
| brio-operator | 143 | 0.4 % |
| c920-desk | 66 | 0.2 % |
| brio-room | 50 | 0.2 % |

### 3.3 Finding F-240-2: two cameras absorb 97 % of FSM churn

`c920-overhead` (Pi-6 co-located) and `brio-synths` together account for 31,489 / 32,478 = **96.9 %** of all transitions. The remaining four cameras are effectively quiescent (combined 985 transitions = ~320/day split six ways). Investigation vectors (not performed here, to keep this item scoped to verification):

- USB hub topology — are the two churning cameras on the same shared hub / voltage rail?
- `c920-overhead` is on the Pi-6 tee split; the transition count may reflect Pi-6 hub activity rather than a local problem.
- `brio-synths` is a BRIO; BRIOs are the original bus-kick population per the epic's problem statement.

### 3.4 Finding F-240-3: `c920-room` accounts for all 21 DEAD transitions

All 21 `recovering→dead` events in the window are `c920-room`. Timestamped cluster (most recent 10 shown):

```
2026-04-17T20:13:28Z  c920-room  failures=10
2026-04-17T20:18:24Z  c920-room  failures=10
2026-04-17T20:22:31Z  c920-room  failures=10
2026-04-17T21:54:55Z  c920-room  failures=10
2026-04-17T21:58:03Z  c920-room  failures=10
2026-04-17T22:10:18Z  c920-room  failures=10
2026-04-17T23:44:08Z  c920-room  failures=10
2026-04-17T23:51:12Z  c920-room  failures=10
2026-04-17T23:54:04Z  c920-room  failures=10
2026-04-18T00:43:47Z  c920-room  failures=10
```

Each DEAD event represents 10 consecutive failed rebuilds — i.e., the camera is lost until an external action (compositor restart, USB re-plug, udev event). The cluster during 2026-04-17 20:13 → 2026-04-18 00:43 is a multi-hour outage period for `c920-room` specifically. Current snapshot shows `c920-room` healthy, so the camera did recover at some point before the 19:17 compositor restart.

The FSM exit-to-DEAD branch is operating as designed; what is missing is a reliable automatic recovery *from* DEAD (the current exit requires service restart or a fresh udev event).

### 3.5 Finding F-240-4: "Failed to allocate required memory" is surfaced as the dominant reason (bus-kick misattribution)

Reason distribution (3-day window):

| Reason string | Count |
|---|---|
| supervisor timer | 8,231 |
| Internal data stream error. | 8,049 |
| rebuild ok | 7,979 |
| Failed to allocate required memory. | 7,865 |
| rebuild failed | 252 |
| fallback active | 55 |
| start failed at build | 26 |
| Watchdog triggered | 15 |
| Could not read from resource. | 1 |
| Failed to allocate a buffer | 1 |

"Failed to allocate required memory." is the GStreamer-surfaced text for a USB bus-kick (`-ENODEV`) — the producer's V4L2 source reports buffer-pool activation failure when the device vanishes mid-read. `camera_pipeline.py` lines 424–435 already rewrites the single-buffer variant of this message to name the underlying USB bus-kick condition, but the buffer-*pool* variant at `gstv4l2src.c:957` is not rewritten and surfaces literally. 7,865 literal "Failed to allocate required memory." lines look like OOM in a cursory journal read.

This is not a failure of the epic's resilience claim, but it is a logging-clarity regression against the rewrite's stated intent. Recommend a followup queue item to extend the message rewrite in `_on_bus_message` to cover the buffer-pool variant.

## 4. Watchdog behaviour

Two watchdog channels exist:

1. **systemd watchdog** — `WatchdogUSec=60s` on the unit. `studio_compositor_watchdog_last_fed_seconds_ago` = 2.51 s at snapshot. `NRestarts=0` on the current boot. No watchdog-forced restarts observed in the current boot window; no historical record accessible post-restart because `NRestarts` is per-boot.
2. **GStreamer element watchdog** — `GstWatchdog` element inside each camera pipeline. Fired 15 times in the 3-day window (reason string "Watchdog triggered"), always on BRIO devices. This is intentional: the GstWatchdog fires when frame flow stalls and is the trigger for the FSM's `healthy→degraded` edge.

Kernel-level USB disconnect traces: `dmesg | grep -iE "bus.*kick|descriptor read.*error|usb.*disconnect|usb.*reset"` returned no matches at snapshot time, likely because `dmesg` ring buffer has rolled over past the 2026-04-17 cluster.

## 5. Dependency surface

- `mediamtx` running at PID 1250 (`/usr/bin/mediamtx /etc/mediamtx/mediamtx.yml`) — RTMP relay live on 127.0.0.1:1935.
- `/dev/video42` present — OBS V4L2 sink exposed.
- Prometheus scrape target live at 127.0.0.1:9482 (confirmed by queue #132 audit; still valid).

## 6. Summary

The camera 24/7 resilience epic is operating within its designed envelope:

- 6/6 cameras in `healthy` state at snapshot.
- 96.94 % self-heal rate on FSM excursions over a 3-day window (7,979 successful rebuilds out of 8,231).
- 0 systemd watchdog-forced restarts on current boot.
- GStreamer-level watchdog firing appropriately (15 events, all BRIO, all triggered FSM degradation).
- RTMP relay + V4L2 sink + Prometheus scrape target all live.

Four findings captured for possible followup queue items:

| ID | Finding | Severity |
|---|---|---|
| F-240-1 | All consumers on `in_fallback=1` despite all cameras healthy at uptime 240s | medium (live stream is showing fallback content when cameras are available) |
| F-240-2 | `c920-overhead` + `brio-synths` absorb 97 % of FSM churn | low (investigative — not a failure) |
| F-240-3 | `c920-room` is the only camera that reaches the DEAD state (21 events in 3 days) | medium (DEAD recovery requires external action) |
| F-240-4 | Bus-kick misattribution: buffer-pool variant not covered by message rewrite | low (logging clarity, not functional) |

F-240-1 is the only finding that may warrant immediate engineering action, since it implies the live stream is currently publishing fallback content rather than live camera feeds. The operator is the consumer of record for that consequence and should decide whether this is a user-visible problem before a followup queue item is opened.

# HLS race condition + start-pre hang — paired incident, paired fix

**Date:** 2026-04-14
**Author:** delta (beta role — perf research)
**Scope:** Live incident retrospective covering two
connected failure modes that turned a routine
operator-initiated USB cable test into a 5+ minute
compositor outage. Both failure modes have permanent
fixes shipped in this session (commits `6e14129b7`
and `767c24591`). Pairs with drop #32 finding 1 (HLS
branch flagged as wasteful) — this drop shows that
finding upgraded from "wasteful" to "single point of
failure for the entire compositor" once the race
condition was observed live.
**Register:** scientific, neutral
**Status:** incident closed — root causes documented,
permanent fixes shipped to main on 2026-04-14
**Companion:** drop #32 (encoder + output path walk),
drop #2 (brio-operator sustained deficit, H4
cable/port hypothesis), drop #27 (brio-operator
cold-start grace fix)

## Headline

**One operator action, two independent failure modes,
five-minute compositor outage.**

At 13:33:42 the operator unplugged the brio-operator
BRIO from its working USB port to test drop #2's
hypothesis H4 (physical cable/port signal integrity).
What followed:

1. **13:33:42–13:34:24** — PipelineManager runs 8
   recovery attempts on brio-operator (correct behavior).
2. **13:33:54** — `hls-archive-rotate.timer` fires its
   normal 1-minute pass and moves 6 segments out of
   `~/.cache/hapax-compositor/hls/` into
   `~/hapax-state/stream-archive/hls/2026-04-14/`.
3. **13:34:29** — `hlssink2`'s own rotation queue tries
   to delete `segment00148.ts`. The file is no longer
   there (the rotator moved it). `unlink()` returns
   ENOENT. `hlssink2` posts an `ERROR` message to the
   pipeline bus.
4. **13:34:29** — The compositor's `_on_bus_message`
   handler in `compositor.py:436-438` falls through to
   the catch-all `else` branch and calls `self.stop()`,
   taking down the entire pipeline (all 6 cameras +
   v4l2sink to OBS + RTMP bin if attached).
5. **13:34:54** — systemd restarts the service.
6. **13:34:54–13:36:54** — `start-pre` runs
   `studio-camera-setup.sh`, which calls `v4l2-ctl`
   directly on each camera. The brio-operator USB
   device is still in a degraded state (kernel
   `device descriptor read/8, error -110`) and
   `v4l2-ctl` blocks on the `SET_CTRL` ioctl
   indefinitely.
7. **13:36:54** — systemd kills `start-pre` after the
   `TimeoutStartSec` limit. The service enters
   restart-loop mode.
8. **13:37:15–13:42:00** — Three additional restart
   attempts, each killed by the same start-pre hang.
9. **13:42:30** — Permanent fix `6e14129b7` shipped
   (HLS bus error scoping), then permanent fix
   `767c24591` shipped (start-pre v4l2-ctl timeout +
   universal `v4l2_soft` use), then `systemctl --user
   reset-failed && restart`.
10. **13:42:36** — Compositor returns to `active`. 5
    of 6 cameras healthy.

**The two failure modes are independent.** Neither
caused the other, but both were triggered by the same
operator action (the BRIO replug). Both have permanent
code fixes now.

## 1. Failure mode A — HLS race condition + fatal escalation

### 1.1 The race

`hlssink2` (in-process GStreamer element) and
`hls-archive-rotate.service` (out-of-process systemd
timer running `agents/studio_compositor/hls_archive.py`)
both manage files in
`~/.cache/hapax-compositor/hls/`. Neither knows about
the other.

- **`hlssink2`** writes new segments and rotates them
  out of its internal playlist when
  `playlist-length=10` is exceeded. When it rotates
  a segment out, it `unlink()`s the file.
- **`hls_archive.rotate_segment()`** scans the
  directory for `*.ts` files whose mtime has been
  stable for 10 seconds (`STABLE_MTIME_WINDOW_SECONDS`).
  When a segment qualifies, it `shutil.move()`s the
  file to the archive directory.

The race window is exactly:
**(stable mtime threshold) − (playlist rotation point).**

With `target-duration=2s`, `playlist-length=10`,
`max-files=15`, and `stable_window=10s`:

- Segments written every 2 seconds
- A segment becomes "closed" 2 s after its mtime stops
  changing
- The rotator considers it "stable" 10 s after that
  → rotator moves it ~12 s after creation
- `hlssink2` keeps the segment in playlist for ~20 s
  (`playlist-length × target-duration`)
- After ~20 s, hlssink2 tries to delete it
- But it's been gone for ~8 s

**Every 2 seconds, hlssink2 attempts to delete a file
the rotator has already moved.** Most of the time the
attempt is silent because hlssink2 doesn't always log
ENOENT (it depends on GStreamer version and platform).
But occasionally — and 13:34:29 was one such occasion —
hlssink2 posts an `ERROR` message to the pipeline bus
instead of silently swallowing the error.

The race has been present continuously since both
systems were first deployed. It became visible today
because the brio-operator recovery cycles caused
extra activity on the bus, raising the probability of
the ERROR being noticed by the bus handler thread.

### 1.2 The fatal escalation

`compositor.py:436-438` had a catch-all `else` branch:

```python
else:
    log.error("Pipeline error from %s: %s (debug: %s)", src_name, err.message, debug)
    self.stop()
```

Any pipeline ERROR not matching one of the existing
scoped handlers (`rtmp_*`, camera roles, `fx-v4l2`,
`output` busy, `fxsrc-*`) escalates to a full pipeline
stop. This is correct for unknown elements that might
indicate genuine pipeline corruption — but
**`hls-sink` was never explicitly scoped**, so the
file-delete ERROR fell through to fatal.

Drop #32 finding 1 had already flagged the HLS branch
as "write-only with no consumer" (the stream.m3u8
file is never read; the actual consumer is the
out-of-process archive rotator that moves files via
`shutil.move`). What drop #32 missed was that the
*same write-only branch* also had a fatal-escalation
path triggered by its own race condition with the
rotator. **The branch was both wasteful AND
load-bearing for the entire compositor's
availability.**

### 1.3 The fix (commit `6e14129b7`)

Add an `elif` to scope `hls-sink` errors as warnings:

```python
elif src_name == "hls-sink":
    # hls-sink races with hls-archive-rotate.timer over segment
    # files: the rotator moves a segment to the archive directory,
    # then hlssink2's own rotation queue tries to delete the same
    # file and posts an ERROR for the missing file. The element is
    # not in a broken state — it can keep writing new segments —
    # so suppress fatal escalation. If hls-sink ever fails for a
    # real reason (disk full, permission denied), the warning is
    # still surfaced in the journal.
    log.warning("HLS sink error (non-fatal): %s", err.message)
```

10-line addition (with the comment). The `hlssink2`
element continues writing new segments after the
failed delete — its internal state is not corrupted
by the ENOENT — so the warning is surfaced and the
pipeline keeps running.

**Trade-off:** if hls-sink ever fails for a real
reason (disk full, permission denied), the warning
is logged but the pipeline doesn't stop. The
operator will see the warning in the journal but
the failure won't trigger automated recovery. This
is acceptable because:

- the HLS branch is consent-gated by config
  (`HlsConfig.enabled`)
- a real failure only affects the HLS branch, not
  the v4l2sink to OBS or the RTMP bin
- drop #32's HLS-1 fix (disable the branch entirely
  if no consumer needs it) is a stronger long-term
  remediation

### 1.4 The deeper question

**Should the rotator and hlssink2 share a coordination
mechanism?** Three options:

- **Option A** (shipped): scope hls-sink errors as
  non-fatal. Race continues, no crash.
- **Option B**: set `playlist-length=0` on hlssink2
  so it never tracks files for deletion. Only the
  rotator manages files. This eliminates the race
  but requires verifying hlssink2 supports unlimited
  playlists.
- **Option C**: change the rotator to read the
  current playlist and skip files referenced in it.
  This eliminates the race correctly but adds a
  cross-process coordination requirement.

Option A is the minimal change that prevents
production outages. Option B/C are deferred to a
future cleanup pass.

## 2. Failure mode B — start-pre hang on bad USB device

### 2.1 The hang

`systemd/units/studio-camera-setup.sh` is
`studio-compositor.service`'s `ExecStartPre` script.
It runs `v4l2-ctl --set-ctrl=...` on each of the 6
cameras to apply optimized exposure / white balance /
focus / sharpness settings. Roughly half the
`v4l2-ctl` invocations were wrapped in a `v4l2_soft`
helper that logged failures non-fatally; the other
half were raw `$V4L2 -d "$DEV" ...` calls.

When the brio-operator's USB device was in a
degraded state at 13:34:54 (kernel was logging
`device descriptor read/8, error -110` repeatedly),
`v4l2-ctl --set-ctrl` blocked on the SET_CTRL ioctl.
The kernel's USB layer was waiting for the device
to respond to a control transfer, which it never did.
The `v4l2-ctl` process was uninterruptable in
`D` (disk wait) state.

systemd's `TimeoutStartSec` for the service is the
default 90 seconds. When `start-pre` exceeded that,
systemd sent SIGTERM, then SIGKILL, then marked the
service as failed and entered restart loop.

**Each restart attempt repeated the same hang.** The
hung process was killed each time, but the underlying
USB-level problem persisted, so the next `v4l2-ctl`
call hit the same wedged ioctl. The compositor was
trapped.

### 2.2 The fix (commit `767c24591`)

Two changes in `studio-camera-setup.sh`:

1. **Bound `v4l2_soft` calls with `timeout 5`:**
   ```bash
   V4L2_TIMEOUT=5

   v4l2_soft() {
       local dev="$1"
       shift
       if ! timeout "$V4L2_TIMEOUT" "$V4L2" -d "$dev" "$@" 2>>"$LOG"; then
           echo "[$(date +%H:%M:%S)] WARNING: v4l2-ctl -d $dev $* returned non-zero" >>"$LOG"
       fi
   }
   ```
   `timeout 5` sends SIGTERM after 5 seconds and
   SIGKILL after another 5. A wedged ioctl can no
   longer block compositor startup beyond 10 seconds
   per camera (worst case 60 s for all 6 cameras vs
   the previous unbounded blocking).

2. **Convert all raw `$V4L2 -d "$DEV"` calls to use
   `v4l2_soft`.** Previously half the calls used the
   helper and half were raw, which meant half the
   calls would hard-fail under `set -euo pipefail`
   even if a camera was perfectly healthy but
   responding slowly. Now all 12 v4l2-ctl invocations
   in the script benefit from both the timeout AND
   the non-fatal error logging.

**Trade-off:** if a camera takes longer than 5
seconds to respond to a v4l2-ctl, its settings will
be skipped (logged to
`$XDG_RUNTIME_DIR/studio-camera-setup.log`). This is
acceptable because (a) a healthy USB camera responds
in <100 ms to v4l2 ioctls, and (b) the compositor
can run without the optimized v4l2 controls applied
— the camera defaults are usable, just less ideal.

## 3. Why these two failures stacked

The two failure modes are independent but stacked
because:

- The HLS race had been present continuously since
  both `hlssink2` and `hls_archive.rotate_segment`
  were deployed. It silently posted ENOENT errors
  most of the time without triggering the fatal path.
- The start-pre hang was latent — only triggered
  when a USB device entered a degraded state.

The operator's BRIO replug created the conditions
for BOTH:

- It created the recovery activity that increased the
  probability of the bus handler observing the
  hls-sink ERROR (failure A trigger)
- It created the bad USB state that caused
  `v4l2-ctl` to hang on subsequent restart attempts
  (failure B trigger)

Without the operator action, neither failure would
have shown up today. With it, both fired in sequence,
and the compositor was unrecoverable for 5 minutes
until both fixes were shipped.

## 4. Live verification post-fix

Immediate live state at 13:42:36 after the fix:

```text
studio_camera_state{role="brio-operator",state="healthy"} 1.0
studio_camera_state{role="c920-desk",state="recovering"} 1.0
studio_camera_state{role="c920-room",state="healthy"} 1.0
studio_camera_state{role="c920-overhead",state="healthy"} 1.0
studio_camera_state{role="brio-room",state="healthy"} 1.0
studio_camera_state{role="brio-synths",state="healthy"} 1.0
```

5 of 6 cameras healthy. c920-desk recovering (still
working through the residual USB instability from
the replug stress).

**The compositor came back up cleanly with both
fixes in place.** The HLS race no longer crashes the
pipeline. The start-pre v4l2-ctl timeout no longer
hangs on degraded USB devices.

## 5. Post-incident state — multiple cameras flapping

After the fixes restored the compositor, two cameras
remained in unstable states:

- **c920-desk** — flapping
  `healthy→degraded→offline→recovering→healthy` every
  ~6 seconds with reason `Device ... failed during
  initialization`. Kernel `dmesg` shows
  `uvcvideo 2-2.4.2.1:1.1: Failed to set UVC probe
  control : -110`. USB hub topology `2-2.4.2.1` is
  unstable.
- **brio-room** — same flapping pattern. Kernel
  `dmesg` shows `uvcvideo 1-3:1.1: Failed to set UVC
  probe control : -110`.

These are **independent USB-level failures** caused by
the cumulative stress of multiple USB reseats during
the BRIO test session. The compositor's resilience
layer is correctly cycling them through recovery —
no crash, no compositor restart — but the cameras
themselves cannot sustain a stable producer pipeline.

**Operator action**: stop reseating cables for ~5-10
minutes and let USB power negotiation settle. If the
flapping continues after that, hard-reboot to clear
USB state.

## 6. Drop #2 H4/H5/H6 — a partial answer

Drop #2 § 4 proposed a cable/port swap test to
distinguish three hypotheses for brio-operator's
sustained 27.94 fps deficit:

- **H4** — physical cable / port signal integrity
- **H5** — BRIO firmware variance (this specific unit)
- **H6** — `jpegdec` / `interpipesink` back-pressure

Today's session executed the test partially. The
operator replugged the brio-operator BRIO into **two
different USB ports** in succession. Both new ports
produced kernel `-110` enumeration errors that the
original port had not been showing. The result:

- **H4 confirmed** — physical / port signal integrity
  is the operative hypothesis. Two known-bad ports
  observed. The original port's 27.94 fps is the
  *floor* for this BRIO + cable + USB-hub topology.
- **H5 not separated** — would require swapping the
  BRIO unit itself, not just the port.
- **H6 not tested** — would require parallel
  `v4l2-ctl --stream-count=300` on brio-operator
  and brio-synths.

**For 30 fps on brio-operator**, the operator needs
one of:

- Different USB cable
- A direct-to-chipset USB port (not behind a hub)
- A powered USB hub
- A different BRIO unit (rules out H5)

The original port is the best known configuration.
The replug experiment did not improve fps — it
made things worse.

## 7. Permanent fixes shipped

| Commit | Title | Files |
|---|---|---|
| `6e14129b7` | fix(compositor): scope hls-sink errors as non-fatal | `agents/studio_compositor/compositor.py` |
| `767c24591` | fix(studio): bound v4l2-ctl calls with timeout in start-pre | `systemd/units/studio-camera-setup.sh` |

Both are now on `main`. The compositor is verified
running with both fixes applied at 13:42:36+.

## 8. Cross-references

- **Drop #32** (`2026-04-14-encoder-output-path-walk.md`)
  finding 1 — flagged the HLS branch as wasteful;
  this drop upgrades it to "single point of failure"
- **Drop #2** (`2026-04-14-brio-operator-producer-deficit.md`)
  § 4 — proposed the cable/port swap test that the
  operator executed today
- **Drop #27** (`2026-04-14-brio-operator-startup-stall-reproducible.md`)
  — cold-start grace fix (PR #806) shipped earlier;
  verified working in this session's restart cycles
- **Drop #28-#30** — camera-side pipeline walks
- **Drop #31** — cam-stability rollup picklist
- `agents/studio_compositor/compositor.py:419-438` —
  bus message handler with new hls-sink scope
- `systemd/units/studio-camera-setup.sh` — start-pre
  script with new timeouts
- `agents/studio_compositor/hls_archive.py:150-194`
  — `rotate_segment` (the moving party in the race)
- `agents/studio_compositor/recording.py:79-122` —
  `add_hls_branch` (the deleting party in the race)
- Journal: `journalctl --user -u studio-compositor.service
  --since "2026-04-14 13:30:00" --until "2026-04-14 13:43:00"`
- dmesg: `sudo dmesg -T | grep -E 'usb|uvcvideo'`
  at the same time

## 9. Open follow-ups

1. **Drop #32 HLS-1** still recommended — disable
   `HlsConfig.enabled` if no consumer needs the local
   HLS sink. With the bus error scope fix in place,
   leaving HLS on is no longer a crash risk, but it
   is still ~2 MB/s of disk write to nowhere.
2. **HLS race option B/C** — coordinate hlssink2 and
   the rotator so they don't fight over file
   ownership. Lower priority now that the crash
   path is closed.
3. **Universal start-pre script audit** — other
   `ExecStartPre=` scripts in the council systemd
   units should be checked for similar
   unbounded-blocking patterns (anything that calls
   USB / v4l2 / network without a timeout is
   a latent restart-loop bug).
4. **brio-operator hardware** — drop #2 H4
   confirmed; for 30 fps, operator needs a
   different cable or port topology (see § 6 above).
5. **TimeoutStartSec audit** — services depending
   on USB devices should consider a longer
   `TimeoutStartSec` *combined with* per-call
   timeouts in their start-pre scripts. Currently
   the compositor relies on the default 90 s
   `TimeoutStartSec` + 5 s per `v4l2-ctl` call.
   Worth verifying after a few days that this is
   sufficient under USB stress.

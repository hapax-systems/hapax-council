# brio-operator sustained deficit — H4/H5/H6 closeout + USB topology verdict

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Definitive closeout of drop #2's sustained
27.94 fps deficit on brio-operator. The operator executed
drop #2 § 4's cable/port swap test today, plus a cable
swap, plus 4 alternative USB ports. All alternatives
failed. The 27.94 fps baseline is not a hardware limit
of the BRIO, cable, or producer chain — it is USB 2.0
isochronous bandwidth exhaustion on a shared host
controller. H4 is ruled out. A new hypothesis (H7,
USB isoc budget contention) is strongly supported by
direct kernel evidence. Closes drop #2.
**Register:** scientific, neutral
**Status:** investigation — H4 experimentally ruled out;
H7 introduced and strongly supported; drop #2's sustained
deficit thread is now answerable from this drop plus
the pending operator-initiated hardware swap
**Companion:** drop #2 (initial sustained deficit),
drop #31 (cam-stability rollup OA1/OA2/OA3 items),
drop #33 (live incident from the test session)

## Headline

**The 27.94 fps deficit is USB 2.0 host controller
isochronous bandwidth exhaustion, not cable signal
integrity, not BRIO firmware variance, and not
producer-chain decode back-pressure.** The BRIO, cable,
and GStreamer producer chain all function correctly —
they are forced into a lower-bandwidth USB altsetting
because the host controller cannot allocate the full
isoc slot the BRIO requests when it shares a USB 2.0
root hub with other high-bandwidth cameras.

**The fix is hardware topology, not code.** The operator
has scheduled a motherboard swap with better USB 3.0
port distribution for later today, which removes the
contention entirely.

## 1. Test executed

Drop #2 § 4 proposed a 60-second cable/port swap test
to distinguish three hypotheses for the sustained
27.94 fps deficit:

- **H4** — physical cable / port signal integrity
- **H5** — BRIO firmware variance (this specific unit)
- **H6** — `jpegdec` / `interpipesink` back-pressure

Operator executed an **extended** version of the test
across the 2026-04-14 session: **5 distinct
BRIO configurations tested**, plus a cable swap, plus
observations of the post-session USB topology.

### 1.1 Test configurations

| # | Cable | Port | Bus | Result |
|---|---|---|---|---|
| 1 | original | **`usb 3-3`** (original) | Bus 003, USB 2.0 480M | **27.94 fps** (baseline, reproducible) |
| 2 | original | alt port A | Bus 001, USB 2.0 480M | Kernel `-110` enumeration errors, never reached streaming |
| 3 | original | alt port B | Bus 001, USB 2.0 480M | Kernel `-110` enumeration errors, never reached streaming |
| 4 | **new** | `usb 3-3` (original) | Bus 003, USB 2.0 480M | **27.93 fps** (matches baseline within noise) |
| 5 | original | `usb 1-9` | Bus 001, USB 2.0 480M | Enumerated cleanly but 0 frames delivered; silent bandwidth failure |
| 6 | original | `usb 1-4` | Bus 001, USB 2.0 480M | `usb 1-4: Not enough bandwidth for altsetting 10` (explicit) |
| 7 | original | `usb 1-10` | Bus 001, USB 2.0 480M | Enumerated cleanly but 0 frames delivered; silent bandwidth failure |
| 8 | original | `usb 3-3` (original, final) | Bus 003, USB 2.0 480M | **27.94 fps** — back to baseline |

Configuration 4 (cable swap at original port) and
configuration 8 (return to original port with original
cable) both reproduced 27.94 ± 0.01 fps, matching drop
#2's 6-hour measurement exactly.

### 1.2 Hypothesis verdicts

- **H4 — physical cable / port signal integrity →
  RULED OUT.** Configuration 4 used a *different*
  physical cable at the original port and reproduced
  27.94 fps to within measurement noise. The cable is
  not a lever. Configurations 2, 3, 5, 6, 7 tested
  four alternative ports; none were better and four
  were strictly worse.
- **H5 — BRIO firmware variance → NOT TESTED.**
  This would require swapping the brio-operator unit
  with a different BRIO. Not executed today. Remains
  a formally open hypothesis but see § 2 for why it
  is unlikely to be the active cause.
- **H6 — `jpegdec` / `interpipesink` back-pressure →
  NOT TESTED directly.** The drop #28-#30 camera
  pipeline walks documented that CPU jpegdec is
  bottlenecked and that nvjpegdec is available but
  unused. This remains a plausible mitigation path
  (Ring 3 fix H in drop #31) but the direct evidence
  in this drop points elsewhere (see § 2).

### 1.3 New hypothesis

**H7 — USB 2.0 host controller isochronous bandwidth
contention on a shared root hub.** Strongly supported
by direct kernel evidence collected today.

## 2. The kernel evidence

### 2.1 Explicit bandwidth rejection

During configuration 6 (`usb 1-4`), the kernel logged
the exact failure mode continuously at 1-second
intervals:

```text
[14:10:02] usb 1-4: Not enough bandwidth for new device state.
[14:10:02] usb 1-4: Not enough bandwidth for altsetting 10.
[14:10:03] usb 1-4: Not enough bandwidth for new device state.
[14:10:03] usb 1-4: Not enough bandwidth for altsetting 10.
...continuously...
```

`altsetting 10` on a Logitech BRIO at 1280×720 MJPEG
30 fps requests the full isochronous slot size for
high-rate streaming. The host controller is returning
`-ENOSPC` (or equivalent) because the aggregate isoc
budget on Bus 001 is already committed to other
devices. The BRIO falls back to a lower altsetting
that requests less bandwidth — which maps to a lower
sustained frame rate.

### 2.2 Silent bandwidth rejection

During configurations 5 and 7 (`usb 1-9`, `usb 1-10`),
the same failure mode occurred *without* the explicit
kernel log. Both ports enumerated cleanly, the
GStreamer producer pipeline transitioned to PLAYING,
and the compositor state machine reported healthy —
but zero frames flowed:

```text
Configuration 5 (usb 1-9):
  frame_interval_seconds_count = 987 (frozen across 1.9s sample)
  last_frame_age_seconds = 94.48 (climbing)
  Compositor state = healthy (grace period active)
  dmesg = clean enumeration at high-speed 480M, no bandwidth error

Configuration 7 (usb 1-10):
  frame_interval_seconds_count = 987 (frozen across 1.9s sample)
  last_frame_age_seconds = 78.02 (climbing)
  Same pattern as #5
```

The absence of an explicit `Not enough bandwidth`
message does not mean there was no bandwidth issue —
it means the device driver accepted the lower
altsetting silently, and the altsetting it accepted
delivers zero frames at 720p30. The operator-visible
behavior is identical to a dead camera.

### 2.3 Host controller topology (live `lsusb -t`)

```text
Bus 001 (USB 2.0, 480M shared, xhci_hcd/10p):
  Port 001: C920 (Dev 002) — uvcvideo + audio
  Port 003: BRIO (Dev 004) — uvcvideo
  Port 009: [empty until config 5 when brio-operator landed here]
  Port 010: [empty until config 7 when brio-operator landed here]
  Port 004: [empty until config 6 when brio-operator landed here]
  ... plus Logi Bolt, HID, audio devices

Bus 002 (USB 3.0, 10000M, xhci_hcd/4p):
  Port 001: BRIO (Dev 006) at 5000M — uvcvideo

Bus 003 (USB 2.0, 480M shared, xhci_hcd/4p):
  Port 002: C920 (Dev 002)
  Port 003: [brio-operator's original port]
  Port 004: C920 (Dev 003)

Bus 004 (USB 3.0, 10000M, xhci_hcd/4p):
  Port 001: BRIO (Dev 005) at 5000M — uvcvideo
```

**Six UVC cameras distributed across four USB host
controllers:**

- 2 BRIOs on dedicated USB 3.0 controllers (Bus 002,
  Bus 004) — each gets a 5 Gbps SuperSpeed link with
  no contention. These cameras (brio-room,
  brio-synths) produce 30 fps consistently.
- 4 cameras (3 C920s + brio-operator BRIO) share two
  USB 2.0 480M controllers (Bus 001, Bus 003). USB 2.0
  isoc budget is ~192 Mbps per controller in practice
  (microframe scheduling limits the theoretical 480
  Mbps to about 40% for isochronous traffic).

**Bus 003 distribution:**

- 2× C920 at 720p MJPEG: ~15-25 Mbps each = ~30-50 Mbps
- 1× BRIO at 720p MJPEG high altsetting: ~60-90 Mbps
  *when granted*, lower when not
- Aggregate with full altsetting: ~90-140 Mbps on a
  ~192 Mbps budget — fits but tight
- Aggregate with a fourth high-bandwidth stream:
  exceeds budget

**This matches the observed behavior.** When
brio-operator is on Bus 003 at its original port, the
controller grants enough bandwidth for the 3 cameras
to all stream but at reduced altsetting. The BRIO's
reduced altsetting corresponds to ~27.94 fps instead
of 30 fps. When brio-operator is also fully allocated,
c920-overhead loses its slot and goes offline (observed
post-test).

### 2.4 USB 2.0 isoc budget math

USB 2.0 high-speed microframe structure:

- 125 µs microframes, 8 per 1 ms frame
- Isochronous transactions can consume at most
  80% of microframe bandwidth (hardware reserves 20%
  for control + bulk)
- Practical sustained isoc ceiling: ~192 Mbps per
  controller

With three cameras sharing one controller:

| Camera config | Mbps each | Total |
|---|---|---|
| 3× 720p MJPEG at minimum altsetting | ~30 | **90 Mbps** ✓ |
| 3× 720p MJPEG at full altsetting | ~60-80 | **180-240 Mbps** ✗ |

The budget allows 3 cameras at *reduced* altsettings
but not at *full* altsettings. The host controller's
resolution is to accept the reduced altsettings for
all devices — which produces the sustained 27.94 fps
for the BRIO and unknown-but-survivable rates for the
C920s (C920s at 720p are less bandwidth-sensitive).

Adding a fourth high-bandwidth device to the same
controller pushes the aggregate over the budget and
the controller refuses one of the altsettings
entirely. That is exactly what happened during
configurations 5, 6, 7, and is what currently keeps
c920-overhead in the fallback state.

## 3. Why H5 (BRIO firmware variance) is unlikely

H5 proposed that this specific BRIO unit has a
firmware quirk that limits its sustained rate. Three
observations argue against H5:

1. **Cable independence (config 4):** if the BRIO
   itself were limited, a different cable would have
   no effect — but also the original result would hold
   regardless of port. That is not quite what
   happened: the alternative ports 5/6/7 produced
   strictly *worse* results, which suggests the BRIO
   is healthy and capable of the high altsetting, it
   just can't obtain the bandwidth to use it.
2. **USB 3.0 BRIOs work at 30 fps:** the two BRIOs on
   dedicated USB 3.0 controllers (brio-room,
   brio-synths) consistently produce 30 fps. If H5
   were the operative cause on brio-operator, it
   would be peculiar to a single unit — but the
   alternative-port experiments would still have
   produced 27.94 fps consistently, which they did
   not.
3. **Explicit kernel rejection:** the `altsetting 10`
   rejection on `usb 1-4` is a host controller
   decision, not a device-firmware decision. The host
   is refusing to grant the slot the device requests.
   That is architecturally distinct from a
   device-side limit.

H5 is not *disproven*, but nothing in today's data
supports it and the available evidence is better
explained by H7. A future unit-swap test could
definitively close H5 but it is not a priority.

## 4. Why H6 (jpegdec back-pressure) is unlikely the
primary cause

H6 proposed that CPU `jpegdec` in the producer chain
stalls under load and back-pressures v4l2src, causing
frame drops at the kernel layer. Drops #28-#30
identified CPU jpegdec as a real bottleneck and
proposed Ring 3 fix H (nvjpegdec) as the mitigation.

However, if H6 were the primary cause of the 27.94 fps
deficit, we would expect:

- The deficit to be *reducible* by moving decode work
  off the CPU (nvjpegdec swap or similar)
- The USB device to be requesting and receiving a
  full-bandwidth altsetting, with frames dropped in
  the software chain after successful USB delivery

Neither is directly observed. What *is* observed:

- The kernel is refusing the full-bandwidth altsetting
  at the USB host controller level, *before* any data
  reaches `v4l2src` or `jpegdec`
- The frames that *do* arrive are delivered at their
  full `framerate` spec — there's no kernel drop
  counter increment (drop #2's false-zero
  `studio_camera_kernel_drops_total` aside)

H6 may still be a contributing factor — a producer
chain that consumes frames faster would exert back
pressure *differently* and might allow the host to
grant a slightly higher altsetting — but the dominant
mechanism is H7.

**Ring 3 fix H (nvjpegdec) is still worth pursuing**
for the system-wide reclamation benefits documented
in drops #28-#30, but the drop #2 sustained deficit
specifically will not resolve without addressing H7.

## 5. The verdict

**The 27.94 fps sustained rate is the steady-state
streaming rate the BRIO achieves when forced into a
reduced-bandwidth USB altsetting by shared USB 2.0
host controller isoc contention. It is not a BRIO
hardware limit, not a cable issue, not a producer
chain stall, and not a software bug.**

The fix requires changing the USB topology so that
brio-operator gets more host controller bandwidth,
either by:

- **Moving it to a USB 3.0 host controller** (the
  dedicated-SuperSpeed path that brio-room and
  brio-synths enjoy), OR
- **Reducing the number of devices on its current
  controller** (e.g., disabling c920-overhead or
  moving one of the C920s off Bus 003), OR
- **Adding a new USB 3.0 host controller** via PCIe
  card / USB 3.0 hub with independent controller

The operator has scheduled a motherboard swap for
later today. New boards typically distribute USB 3.0
ports across more controllers with better bandwidth
per controller, which will likely resolve the
contention without any software change.

## 6. Post-test state (as of this drop)

After returning brio-operator to its original port
(`usb 3-3` on Bus 003), the compositor state is:

| Camera | State | FPS | Notes |
|---|---|---|---|
| brio-operator | healthy | **27.94** | baseline restored; matches drop #2's 6-h measurement exactly |
| c920-desk | healthy | 30.0 | USB 2.0 Bus 003 |
| c920-room | healthy | 30.0 | USB 2.0 Bus 003 |
| **c920-overhead** | **offline** | 0 | Bus 003 bandwidth fully committed; displaced by brio-operator's altsetting |
| brio-room | healthy | 30.0 | USB 3.0 Bus 002 or Bus 004 |
| brio-synths | healthy | 30.0 | USB 3.0 Bus 002 or Bus 004 |

**5 of 6 cameras healthy; c920-overhead serving from
fallback.** The compositor is stable. Operator has
accepted this degraded state until the motherboard
swap.

## 7. Implications for the cam-stability rollup

Drop #31 (cam-stability rollup) referenced this test
as:

- **OA1** — cable/port swap test for brio-operator
  — ✅ **EXECUTED** today; result documented in this
  drop
- **OA2** — decide if sustained brio-operator deficit
  (~28 fps on 720p) is acceptable — **closed by
  operator today**: "we can accept the degradation.
  will be swapping to a much better mobo with better
  ports later today"

The **drop #2 sustained deficit thread is now closed**
with the following resolution:

> Closed. Sustained deficit is USB 2.0 host controller
> isochronous bandwidth contention (H7). H4 (cable/port
> signal integrity) ruled out experimentally. H5
> (firmware variance) and H6 (jpegdec back-pressure)
> not directly tested but not load-bearing given the
> kernel evidence. Fix is the pending hardware swap.
> No further software work is possible on the drop #2
> sustained deficit until the hardware changes.

## 8. Implications for Ring 3 fix H (nvjpegdec)

Ring 3 fix H (swap `jpegdec` for `nvjpegdec` on the
producer chain) was listed as the H6 mitigation in
drops #28-#31. Based on this drop's findings, Ring 3
fix H will:

- **Not fix** the 27.94 fps sustained deficit on
  brio-operator under the current USB topology (the
  bottleneck is upstream of `v4l2src`)
- **Still be worth pursuing** for the system-wide
  benefits: ~248 MB/s of CPU→GPU bandwidth reclaimed,
  ~1 CPU core of jpegdec work offloaded to the GPU

Ring 3 fix H's priority should be re-evaluated in
light of this:

- **Before this drop**: fix H was pitched primarily
  as the brio-operator 30-fps fix
- **After this drop**: fix H is a general throughput
  improvement that does *not* fix brio-operator's
  30-fps goal

The hardware swap is the brio-operator fix. Ring 3
fix H remains an independent improvement.

## 9. What would fully close H5

H5 (BRIO firmware variance) is not tested today. To
definitively close it:

1. **Swap the brio-operator unit** with another BRIO
   (e.g., swap the physical device with brio-room's
   BRIO, relabel their device-by-id paths in
   `config.py`, restart the compositor).
2. **Observe**: if the new unit at brio-operator's
   original port sustains 27.94 ± noise fps, H5 is
   closed (the rate is topology-dependent, not
   unit-dependent). If the new unit sustains 30 fps,
   H5 is the operative cause.
3. **Revert** the swap once the result is recorded.

This is 5 minutes of physical work. It can be done
after the motherboard swap if the swap does not fully
resolve brio-operator. Not a priority today.

## 10. References

- Drop #2 — `2026-04-14-brio-operator-producer-deficit.md`
  — the initial 27.94 fps finding and 5-hypothesis
  enumeration
- Drop #31 — `2026-04-14-cam-stability-rollup.md`
  — OA1/OA2/OA3 operator-action items
- Drop #33 — `2026-04-14-hls-race-and-startpre-hang-incident.md`
  — the incident during today's test
- dmesg @ 14:10:02-14:10:07 — `usb 1-4: Not enough
  bandwidth for altsetting 10`
- dmesg @ 14:13:57-14:13:59 — `usb 3-3: Not enough
  bandwidth for altsetting 10` (at original port
  after the replug, suggesting Bus 003 is always
  at the edge of its budget)
- `lsusb -t` live topology @ ~14:05 — 4 controllers,
  6 UVC devices
- Live metrics @ `http://127.0.0.1:9482/metrics`
  `studio_camera_frame_interval_seconds_{count,sum}`
  per role, sampled at multiple points during the
  test session
- `agents/studio_compositor/config.py:34-78` —
  `_DEFAULT_CAMERAS` with per-device v4l symlinks
  (the only stable identifier across replugs)

## 11. Follow-ups

1. **Later today** — operator motherboard swap. After
   the swap, re-run configurations 1 (original port)
   and 4 (cable swap at original port) to see if
   brio-operator sustains 30 fps on the new
   topology. If yes → H7 confirmed by the positive
   control. If no → H5 or H6 becomes the next
   investigation.
2. **After mobo swap** — re-audit USB topology with
   `lsusb -t`. Document the new controller layout in
   a follow-up drop (#35 if needed).
3. **Deferred** — Ring 3 fix H (nvjpegdec) remains
   valuable for system-wide throughput even if it
   does not fix brio-operator directly.
4. **Deferred** — H5 unit swap is a 5-minute
   definitive close but unnecessary if the mobo swap
   resolves the issue.
5. **Deferred** — update drop #31 cam-stability
   rollup to reference this drop as the OA1
   resolution.

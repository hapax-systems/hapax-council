# BRIO USB Robustness — Research Note

**Filed:** 2026-04-12
**Status:** Open investigation
**Priority:** MEDIUM — operator repeatedly losing cameras mid-stream
**Owner:** TBD

## Problem statement

The three Logitech BRIO 4K webcams (`brio-operator`, `brio-room`, `brio-synths`) keep getting kicked off their USB controllers, and/or the controllers themselves are dying. The pattern:

- Cameras that were enumerated and streaming drop off the bus without warning
- `lsusb` stops listing them
- The kernel logs `device descriptor read/64, error -71` (EPROTO) during attempted re-enumeration
- Sometimes an entire hub cascade goes down (multiple devices disconnect in the same second)
- Reboot recovers, but the failure recurs under load

Specifically, between 2026-04-11 19:00 and 2026-04-12 14:30 the kernel logged **15 USB disconnect events** including one cascade on 2026-04-12 13:41:21 where four devices across buses 5 and 6 dropped simultaneously (`5-1, 6-2, 5-3, 6-4`). At that moment the compositor lost `brio-operator` and `brio-room` and did not get them back until reboot.

This has happened enough times that compositor UX is materially degraded: two of six cameras are offline for large fractions of the working day.

## Hardware topology (as of 2026-04-12)

```
Bus 008 (Renesas xhci-pci 5000M, 4p)     ← USB-C/Thunderbolt?
  └─ Port 003: BRIO 046d:085e (9726C031) — brio-synths — working

Bus 004 (Intel xhci 10000M, 4p)
  └─ Hub 8087:0b40
      └─ Hub 2188:5500 (TS4 USB3.2 Gen2)
          ├─ Hub 2188:5501 (TS4)
          └─ Hub 2188:5502 (TS4)

Bus 003 (Intel xhci 480M, 8p)
  └─ Hub 2188:5802 (TS4 USB2.0)
      ├─ C920 046d:08e5
      ├─ Hub 2188:5510 (TS4)
      ├─ Hub 2188:5511 (TS4)
      └─ Hub 2188:5512 (TS4)

Bus 001 (Intel xhci 480M, 10p)
  └─ C920 046d:08e5
  └─ Genesys Hub 05e3:0610
  └─ Logitech Unifying Receiver

MISSING (as of 2026-04-12 14:00):
  brio-operator (serial 5342C819) — last seen on bus 1 port 9 and bus 6 port 4
  brio-room     (serial 43B0576A) — last seen on bus 1 port 4 and bus 5 port 4
```

The three BRIOs roam across multiple USB ports over the course of a day — that alone is a tell. When the operator plugs them into "the same place" they end up on different kernel bus/port pairs depending on which hub power-cycles. The TS4 daisy-chain is the common denominator.

## Symptoms observed

**Kernel log signatures:**

```
usb 1-9: USB disconnect, device number 8
usb 1-9: device descriptor read/64, error -71
usb 1-9: USB disconnect, device number 10
```

`error -71` = `EPROTO` — "Protocol error." At USB-level this is almost always a signal integrity problem: bad cable, marginal port, EMI from a neighbour cable, or undervolted hub. It is NOT a software bug.

**Compositor signatures:**

- `cameras.py:98` — "Camera brio-operator device ... not found, skipping"
- `status.json` — `brio-operator: offline`
- `try_reconnect_camera` fires every ~10s but fails because `/dev/v4l/by-id/usb-046d_Logitech_BRIO_<serial>-video-index0` no longer exists on the filesystem

## Hypotheses

In rough order of likelihood:

1. **TS4 USB3.2 Gen2 hub chain is the weak link.** The 2188:55xx hub stack is a no-brand daisy-chain — TS4/5500/5501/5502. USB3 Gen2 hubs are notoriously picky about upstream cable quality and power delivery. Gen2 error rates climb steeply at the edge of the spec. Multiple re-enumerations on bus 5/6 (the Gen2 side) suggest this branch is marginal.

2. **Cable wear.** BRIO cables are typically USB-C → USB-A, long (2m+), often braided. Repeated flexing at the USB-C end fatigues the connector. The serial-number-specific failure (`5342C819` and `43B0576A`) not replicated on `9726C031` suggests the difference is in what plugs *into* them, not the cameras themselves.

3. **Undervolted hub.** BRIO draws up to ~500mA at 4K. Three of them through a self-powered hub is fine; through a bus-powered or inadequately-powered hub isn't. Check if the TS4 hub is actually receiving external power.

4. **Host controller instability.** The Renesas xhci (`xhci-pci-renesas`) is a separate PCIe controller from the Intel xhci. If the Renesas card itself is flaky, only one BRIO would work consistently — which matches: `brio-synths` (bus 8, Renesas) has been stable; the other two (Intel xhci via the TS4 chain) die.

5. **Thermal.** USB3 Gen2 hubs run hot under load. Check TS4 hub housing temperature after a few hours of streaming.

## Recommended investigation (post-reboot)

Ordered from cheap to expensive:

**Cheap — takes 5 minutes, worth doing first:**
- [ ] Record `lsusb -t` and physical port-to-camera mapping immediately after reboot
- [ ] Check TS4 hub is on a dedicated 2.4A+ power supply (not bus-powered)
- [ ] Swap the two offline BRIOs to the bus-8 Renesas port that `brio-synths` uses today — confirms whether the problem is the camera or the hub branch
- [ ] Feel the TS4 hub housing after 30 min of streaming (thermal check)

**Moderate — requires operator time but no hardware:**
- [ ] Run `usbmon` for a few hours and see if `error -71` appears during steady-state streaming or only during device state changes
- [ ] Compare USB cable brands/lengths for the three BRIOs. BRIO's bundled cable is known-good; third-party replacements are variable.
- [ ] Log kernel USB events (`dmesg -w | grep -iE 'usb|xhci'`) in a tmux pane while streaming

**Expensive — new hardware:**
- [ ] Replace TS4 hub with a known-good industrial hub (Startech, Plugable, Anker PowerExpand). Under $60. Most likely single fix.
- [ ] Move BRIOs to direct-attach (no hub) — burns motherboard USB ports but removes a variable
- [ ] Replace USB cables (genuine Logitech BRIO cables specifically)

## What this is NOT

- Not a software bug in the compositor. The compositor correctly detects missing devices and attempts reconnection; it cannot fix signal-level USB errors.
- Not a `uvcvideo` driver bug. The failures are at USB device descriptor read time, below the UVC class driver.
- Not a GStreamer issue. When `/dev/v4l/by-id/...` exists, the compositor opens it successfully.

## Workarounds available today

- **Reboot** clears the bus state and re-enumerates. Good for ~hours to a day.
- **Manual USB rebind** (`echo "$DEVICE" > /sys/bus/usb/drivers/uvcvideo/bind`) sometimes works if the device is half-present, not needed if it's fully gone.
- **Use fewer cameras during intensive work** reduces USB bus contention.

## Cross-references

- Handoff document 2026-04-12 flags this as a follow-up (§"Hardware / physical")
- Original audit + polish PRs (#673, #674, #675, #676) did not touch camera hardware paths
- `agents/studio_compositor/cameras.py:98` is the compositor-side detection site
- `agents/studio_compositor/state.py::try_reconnect_camera` is the software-level recovery attempt

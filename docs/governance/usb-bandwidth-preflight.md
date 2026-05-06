# USB Bandwidth Preflight Checker

Operator-facing diagnostic that surfaces "this controller is approaching
its bandwidth limit" BEFORE the next plug fails. Software-only — no
firmware writes, no hardware swaps.

## Why

Recommendation #3 from `/tmp/usb-hardening-research-2026-05-02.md` §3.

On 2026-05-02 the operator plugged the ZOOM LiveTrak L-12 into
`usb 1-3.1` (an ASMedia hub downstream of `09:00.0`). The kernel
rejected it with:

```text
Not enough bandwidth for new device state.
Not enough bandwidth for altsetting 1.
usb_set_interface failed (-28)
```

The hub already carried 3 BRIO webcams, a C920, and dock peripherals.
The L-12 — a 14-channel UAC2 multitrack interface — needs ~12 Mbps of
isochronous reservation, which the hub did not have. Multiple replug
cycles failed with the same error before the operator moved the L-12 to
the front-case host controller (still `09:00.0` but a different USB bus
that had spare reservation budget). That fixed it.

A preflight check would have made the saturation visible BEFORE the
plug, saving the replug storm and the cycle of "is the cable bad? is
the device bad?" that wastes attention during livestream prep.

## What it does

`scripts/hapax-usb-bandwidth-preflight` walks `/sys/bus/pci/devices/*/usb*`,
sums per-device bandwidth from the static profile in
`shared/usb_bandwidth_table.py`, and reports per-controller used /
capacity / headroom. The default thresholds are 70% (WARNING) and 80%
(SATURATED) of the controller's nominal capacity — both operator-tunable
via `--warn` and `--saturated`.

The static lookup table is the deliberate first-pass surface. Per the
research drop §3.4, parsing `/sys/kernel/debug/usb/devices` for the
real xHCI bandwidth reservation table needs root + debugfs and is not
portable across kernel versions. The static table covers every device
in the studio inventory (BRIO, C920, L-12, S-4, M8, Erica MIDI, Yeti,
Studio 24c, MT7921 BT) with conservative high-speed isochronous
estimates. Devices not in the table fall back to a generic 2 Mbps
estimate and are tagged `unknown` in output so the operator can extend
the table.

## Usage

### Default mode — current state

```console
$ hapax-usb-bandwidth-preflight
[OK       ] 0000:09:00.0 bus 3:    used     65.0 Mbps / cap    480.0 Mbps (headroom    415.0 Mbps,  13.5%)
    046d:085e Logitech BRIO 4K                  15.0 Mbps
    046d:085e Logitech BRIO 4K                  15.0 Mbps
    046d:085e Logitech BRIO 4K                  15.0 Mbps
    046d:08e5 Logitech C920 PRO HD              10.0 Mbps
    1fc9:0104 Torso Electronics S-4              8.0 Mbps
    b58e:9e84 Blue Yeti microphone               3.0 Mbps
[OK       ] 0000:71:00.0 bus 1:    used     12.0 Mbps / cap    480.0 Mbps (headroom    468.0 Mbps,   2.5%)
    1686:03d5 ZOOM LiveTrak L-12                12.0 Mbps
```

Exit code: `0` if all controllers OK, `1` if any WARNING, `2` if any
SATURATED.

### Simulation mode — "what if I plug X here?"

```console
$ hapax-usb-bandwidth-preflight --device 1686:03d5/0000:09:00.0
Simulating: add ZOOM LiveTrak L-12 (12.0 Mbps) to 0000:09:00.0

[WARNING  ] 0000:09:00.0 bus 3:    used    365.0 Mbps / cap    480.0 Mbps (headroom    115.0 Mbps,  76.0%)
    + 1686:03d5 ZOOM LiveTrak L-12                12.0 Mbps  [SIMULATED]
    ...
```

Without the `/<port-path>` suffix, the simulator picks the first
controller that would saturate, falling back to the least-loaded.

### JSON

```console
$ hapax-usb-bandwidth-preflight --json
{
  "controllers": [...],
  "thresholds": {"warn": 0.7, "saturated": 0.8}
}
```

Suitable for piping into `jq` or downstream automation.

### Monitor mode — Prometheus textfile

```console
$ hapax-usb-bandwidth-preflight --monitor --prom-path /var/lib/node-exporter/textfile/hapax-usb-bandwidth.prom
```

Long-running mode that periodically writes the textfile. The systemd
unit `hapax-usb-bandwidth-preflight.timer` runs the one-shot equivalent
every 60 seconds (operator-installed; this PR does not enable it).

Metrics emitted:

- `hapax_usb_bandwidth_capacity_bps{bdf,bus}` — nominal bus capacity
- `hapax_usb_bandwidth_used_bps{bdf,bus}` — sum of static-table device
  estimates currently bound
- `hapax_usb_bandwidth_headroom_bps{bdf,bus}` — capacity − used
- `hapax_usb_bandwidth_headroom_ratio{bdf,bus}` — fraction remaining

## Interpreting output

| Severity | Default ratio | Meaning |
|----------|---------------|---------|
| `OK` | < 0.70 | Plenty of headroom; safe to plug another high-bandwidth device |
| `WARNING` | 0.70–0.80 | Cleanup margin tight; investigate before plugging anything else |
| `SATURATED` | ≥ 0.80 | The next high-bandwidth plug is at risk of `-ENOSPC` rejection |

The thresholds reflect the USB-IF rule that the host reserves at most
80% of high-speed isochronous bandwidth. Real controllers vary. Values
are conservative — if the preflight reports OK, the plug is very likely
to succeed; if it reports SATURATED, the plug is very likely to fail.

## When to run it

- **Before a livestream prep session** — survey of all controllers to
  catch slow drift in topology.
- **Before plugging a new high-bandwidth device** — `--device <vid>:<pid>`
  to simulate.
- **Before introducing the ReSpeaker XVF3800** — simulate the Seeed firmware
  ID on the chosen host AMD/front-case controller:

  ```console
  $ hapax-usb-bandwidth-preflight --device 2886:001a/0000:09:00.0
  ```

- **As part of post-incident triage** — pair with
  `scripts/hapax-usb-topology-witness` to confirm whether a failed
  plug was a bandwidth issue versus a controller-mortality issue
  (which `hapax-xhci-death-watchdog` covers).

## Limitations

1. **Static lookup table.** Devices not in `shared/usb_bandwidth_table.py`
   fall back to a generic 2 Mbps estimate. Add new rows when the
   `unknown` tag appears for a device that matters.
2. **No partial-reservation accounting.** The kernel sometimes leaks
   partial reservations from failed altset attempts. The preflight
   underestimates reservation pressure in that case. The
   `hapax-usb-bandwidth-watchdog` clears those by rebinding the
   offending device.
3. **Hub-internal bandwidth not modelled.** A 4-port USB 2.0 hub
   advertises 480 Mbps, but a device chain that includes the hub's
   own descriptor handling adds a few percent overhead. The preflight
   does not subtract this — it is small in practice and the
   conservative bandwidth values in the static table absorb it.
4. **xHCI capacity is reported per root hub, not per BDF.** A single
   xHCI controller commonly exposes a USB2 root hub and a USB3 root
   hub under the same PCI BDF; the preflight reports them as separate
   entries (one OK, one possibly SATURATED) which matches the kernel's
   own reservation accounting.

## Install

The PR does NOT install systemd units. Operator action:

```bash
sudo install -m 755 scripts/hapax-usb-bandwidth-preflight /usr/local/bin/
sudo install -m 644 systemd/units/hapax-usb-bandwidth-preflight.service /etc/systemd/system/
sudo install -m 644 systemd/units/hapax-usb-bandwidth-preflight.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hapax-usb-bandwidth-preflight.timer
```

(or skip the timer entirely and run as a CLI tool — the timer only
gates the Prometheus textfile path.)

## References

- Research drop: `/tmp/usb-hardening-research-2026-05-02.md` §3
- Sibling: `scripts/hapax-usb-bandwidth-watchdog` (recovery — already
  shipped)
- Sibling: `scripts/hapax-xhci-death-watchdog` (controller death recovery — already
  shipped)
- Inventory: `config/audio-topology.yaml`, memory `project_studio_cameras`

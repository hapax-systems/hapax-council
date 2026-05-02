# xHCI Death Watchdog

Auto-recovery for dead xHCI USB host controllers via PCIe `remove` + `rescan`.
Software-only mitigation — no firmware writes, no hardware swaps. Triggered by
the 2026-05-02 ASMedia ASM4242 death incident.

## Trigger

The watchdog tails the kernel journal (`journalctl -k --follow`) and matches
either of two patterns:

- `HC died`
- `Abort failed to stop command ring`

Both are emitted by the `xhci_hcd` driver when a controller stops responding.
The matching line must contain a PCI BDF in the canonical
`xhci_hcd DDDD:BB:DD.F` form; the watchdog extracts that BDF for the recovery
target.

## Action

For each matched BDF the watchdog runs the only known software-only recovery
sequence for a fully-dead xHCI controller:

```text
echo 1 > /sys/bus/pci/devices/<bdf>/remove
sleep 2
echo 1 > /sys/bus/pci/rescan
sleep 5
verify /sys/bus/pci/devices/<bdf> exists
```

When the device re-enumerates, the watchdog issues best-effort restarts of:

- `hapax-usb-router.service`
- `hapax-usb-topology-witness.service`

Errors from those restarts are logged but do not crash the watchdog — the
units may be absent on a freshly-installed host, and the controller revival
is the load-bearing outcome.

When the device does NOT re-appear after `rescan`, the watchdog logs a
warning and exits the recovery for that BDF; the operator must reboot. (See
research §1.2 for the corruption-of-config-space minority case.)

## Cooldown

180-second cooldown per BDF. Subsequent matches against a BDF that recovered
inside the window are logged and skipped. Cooldown state lives at
`/run/hapax-xhci-death-watchdog/last-recovery.json` (cleared on reboot via
`StateDirectory=`/`RuntimeDirectory=` semantics; the file persists across
service restarts within a boot).

The cooldown is intentionally per-BDF and not global: if the ASM4242 USB 3.2
controller (`0000:71:00.0`) and its paired USB4 host router (`0000:72:00.0`)
fate-share and both die in the same minute, the watchdog should recover both.

## Dry-run

`--dry-run` logs intended actions without writing to `/sys/bus/pci`. Useful
for smoke-testing on a live host. The watchdog still updates the cooldown
state file in dry-run mode so that real and dry-run modes share a single
state surface.

## Install

The PR ships only the files; the operator does the install separately.

Two equivalent paths:

**Manual** (just this watchdog):

```bash
sudo install -m 755 scripts/hapax-xhci-death-watchdog /usr/local/bin/
sudo cp systemd/units/hapax-xhci-death-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hapax-xhci-death-watchdog
```

**Bundled** (alongside the rest of the USB hardening packet):

```bash
scripts/install-usb-topology-hardening.sh
```

The bundled path also re-runs the existing bandwidth watchdog and topology
witness installs — idempotent, safe to re-run.

The service runs as root (the only user that can write
`/sys/bus/pci/devices/.../remove`). It is not user-scope.

## Monitoring

```bash
# Live log
journalctl -u hapax-xhci-death-watchdog -f

# Recent recoveries
sudo cat /run/hapax-xhci-death-watchdog/last-recovery.json
```

Each recovery emits a single-line JSON log entry of the form:

```text
recovery outcome for 0000:71:00.0: {"bdf": "0000:71:00.0", "remove_succeeded": true, ...}
```

so journal-based dashboards can extract recovery counts and per-BDF outcomes.

## Why this is software-only

`pcie_aspm=off` is already on the kernel cmdline and the per-PCI runtime PM
udev rules already pin the asmedia controllers to `power/control=on`. Both
mitigations were active during the 2026-05-02 death, which means the death is
an xHCI-internal failure that no PM lever prevents. Recovery has to be the
PCIe rebind — there is no other software path back from `HC died`.

## References

- Research: `/tmp/usb-hardening-research-2026-05-02.md` §1
- Sibling watchdog: `scripts/hapax-usb-bandwidth-watchdog`
  (fires on the *bandwidth* class of failure, not death)
- TechOverflow writeup of the recovery technique:
  <https://techoverflow.net/2021/09/16/how-i-fixed-xhci-host-controller-not-responding-assume-dead/>

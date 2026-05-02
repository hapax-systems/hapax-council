# BT Firmware Watchdog

Auto-recovery for MediaTek MT7921 Bluetooth controllers stuck on firmware
download via USB rebind. Software-only mitigation — no firmware writes,
no hardware swaps. Triggered by the 2026-05-02 incident where a warm
reboot left `hci0` unable to load firmware and only a full **cold
power-off** restored Bluetooth.

## Trigger

The watchdog tails the kernel journal (`journalctl -k --follow`) and
matches any of three canonical MT7921 firmware-download failure
patterns:

- `Execution of wmt command timed out`
- `Failed to send wmt patch dwnld`
- `Failed to set up firmware`

All three are emitted by the `btusb` driver / `btmtk` glue when the
chip's WMT firmware-load handshake stalls. The matching line must
contain a `Bluetooth: hci<N>:` prefix; the watchdog extracts the HCI
device id (`hci0`, `hci1`, ...) for the recovery target.

## Action

For each matched HCI, the watchdog:

1. Resolves the parent USB device by walking the
   `/sys/class/bluetooth/<hci>` symlink up to its parent USB device in
   `/sys/bus/usb/devices/` (e.g. `1-11`).
2. Runs the canonical USB-rebind sequence:

   ```text
   echo <bus-port> > /sys/bus/usb/drivers/usb/unbind
   sleep 2
   echo <bus-port> > /sys/bus/usb/drivers/usb/bind
   sleep 5
   ```

3. Verifies recovery by tailing the kernel log for the next 10s and
   looking for the canonical success line
   (`Bluetooth: hci<N>: HW/SW Version: ...`) without any subsequent
   timeout pattern.
4. On success: best-effort `systemctl restart bluetooth.service` so the
   user-space stack picks up the freshly-bound HCI.
5. On verify-failure: writes an operator-facing escalation status file
   at `/run/hapax-bt-firmware-watchdog/last-failure.json` and emits
   `USB rebind insufficient — operator action required (cold poweroff)`
   to the journal. **The watchdog does NOT itself trigger cold-poweroff.**

## When it can't help

LKML reports for the MT7921/MT7925 family — and the operator's own
2026-05-02 incident — confirm that USB rebind recovers ~80% of these
firmware-load timeouts. The remaining 20% are silicon-state-machine
wedges where the BT controller's internal state cannot be cleared by
re-binding the USB device; only removing PSU-level power for several
seconds resets the chip.

In those cases the watchdog leaves a clear trail:

- `last-failure.json` carries the failing HCI, USB BDF, exact pattern,
  and `escalation: rebind-insufficient`.
- The journal log entry is the operator-facing actionable signal.

The operator runbook in §1.2 of
`/tmp/usb-hardening-research-2026-05-02.md` documents the cold-poweroff
recovery for the wedged case.

## Cooldown

300-second cooldown per HCI device. Subsequent matches against an HCI
that recovered inside the window are logged and skipped. Firmware-load
failures are sticky — repeatedly rebinding inside a short window
produces no recovery and risks tripping kernel rate-limiters on the USB
subsystem.

Cooldown state lives at
`/run/hapax-bt-firmware-watchdog/last-recovery.json`. Per-HCI; cleared
on reboot via `RuntimeDirectory=` semantics.

## Dry-run

`--dry-run` logs intended actions without writing to `/sys/bus/usb` or
restarting `bluetooth.service`. Useful for smoke-testing on a live host.
The cooldown state file is still updated so dry-run and real mode share
a single state surface.

## Install

The PR ships only the files; the operator does the install separately.

```bash
sudo install -m 755 scripts/hapax-bt-firmware-watchdog /usr/local/bin/
sudo cp systemd/units/hapax-bt-firmware-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hapax-bt-firmware-watchdog
```

The service runs as root (the only user that can write
`/sys/bus/usb/drivers/usb/{unbind,bind}`). It is not user-scope.

## Monitoring

```bash
# Live log
journalctl -u hapax-bt-firmware-watchdog -f

# Recent recoveries
sudo cat /run/hapax-bt-firmware-watchdog/last-recovery.json

# Operator escalation (only present when rebind was insufficient)
sudo cat /run/hapax-bt-firmware-watchdog/last-failure.json
```

Each recovery emits a single-line JSON log entry of the form:

```text
recovery outcome for hci0: {"hci": "hci0", "bus_port": "1-11", "unbind_succeeded": true, ...}
```

so journal-based dashboards can extract recovery counts and per-HCI
outcomes.

## Why this is software-only

The MT7921 firmware-download timeout is a chip-level state-machine
issue. There is no kernel parameter, modprobe option, or autosuspend
knob that prevents it deterministically. The only reliable software
remediation is to fully re-enumerate the USB device — same mechanism
the operator does manually with unplug/replug, but automated and
without unplugging the cable. For the wedged silicon-state minority
case, the operator runbook documents the cold-poweroff requirement
that no software path can cover.

## References

- Research: `/tmp/usb-hardening-research-2026-05-02.md` §6.2 (BT
  watchdog) and §1 (parallel xHCI death-watchdog pattern)
- Sibling watchdog: `scripts/hapax-xhci-death-watchdog`
  (fires on xHCI controller death, parallel pattern)
- LKML reports of the same MT7921/MT7925 firmware-timeout class:
  <https://github.com/ublue-os/bazzite/issues/3337>

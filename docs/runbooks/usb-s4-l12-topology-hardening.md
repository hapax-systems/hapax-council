# USB S-4/L-12 Topology Hardening

Status: host baseline packet for the livestream workstation.

This runbook makes the 2026-04-29 live S-4/L-12/CalDigit mitigation durable
without writing firmware to S-4, L-12, cameras, or CalDigit hardware.

Known-good evidence captured from cx-violet and the 2026-04-30 post-firmware
replug witness:

- S-4 serial `fedcba9876543220` on approved CalDigit paths:
  `pci-0000:71:00.0-usb-0:1.5` and
  `pci-0000:71:00.0-usb-0:1.1.1.3`.
- L-12 serial `8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF` on USB device `3-1.1.2.2`.
- L-12 PipeWire sink/source present. The default sink is intentionally not
  L-12/MPC; unrouted desktop audio must stay on the local Ryzen monitor path
  unless an explicit governed filter-chain targets the broadcast path.
- Six Logitech cameras are off the CalDigit audio controller path
  `pci-0000:71:00.0`.
- `usbcore.usbfs_memory_mb=128` and `uvcvideo.quirks=0x100` are live.
- S-4 mass-storage and CDC Ethernet functions are ignored by desktop/network
  managers while S-4 audio/MIDI remain available.

## Durable Files

- `config/udev/rules.d/90-hapax-s4-composite.rules`: S-4 power, udisks,
  ModemManager, NetworkManager, and topology-witness hotplug policy.
- `config/udev/rules.d/50-hapax-usb-audio-video-noautosuspend.rules`:
  shared audio/video autosuspend guard.
- `config/NetworkManager/conf.d/90-hapax-s4-unmanaged.conf`: S-4 CDC
  Ethernet unmanaged policy.
- `config/modprobe.d/99-hapax-usb-reliability-override.conf`: usbcore,
  uvcvideo, and LiveTrak snd-usb-audio module options.
- `config/kernel-cmdline/hapax-usb-reliability.params`: bootloader parameter
  source for built-in usbcore and early uvcvideo defaults.
- `scripts/hapax-usb-topology-witness`: JSON status witness and light repair.
  S-4/L-12 identity is matched by stable USB serial/vendor/product attributes;
  bus `ID_PATH` is diagnostic because it drifts across reboots and port moves.
- `systemd/units/hapax-usb-topology-witness.service` and `.timer`: periodic
  user witness.
- `scripts/hapax-usb-bandwidth-watchdog` and
  `systemd/units/hapax-usb-bandwidth-watchdog.service`: root watchdog using
  `dmesg --follow`, not `journalctl -k -f`.
- `systemd/units/midi-route.service`: legacy optional route; skips cleanly
  when `%h/.local/bin/midi-route` is absent.

## Install

Dry-run first:

```bash
scripts/install-usb-topology-hardening.sh --dry-run
```

Apply host files:

```bash
scripts/install-usb-topology-hardening.sh
```

Kernel command-line parameters must be carried by the bootloader too:

```bash
cat config/kernel-cmdline/hapax-usb-reliability.params
grep -F 'usbcore.usbfs_memory_mb=128' /etc/default/limine
grep -F 'uvcvideo.quirks=0x100' /etc/default/limine
```

If either parameter is absent from the bootloader config, add it manually,
rebuild the bootloader config with the host's normal Limine flow, and reboot.
Do not perform device firmware updates as part of this runbook.

## Reboot Validation

After reboot:

```bash
cat /sys/module/usbcore/parameters/usbfs_memory_mb
cat /sys/module/uvcvideo/parameters/quirks
scripts/hapax-usb-topology-witness --status-path /tmp/hapax-usb-topology-status.json
jq . /tmp/hapax-usb-topology-status.json
```

Expected:

- `usbfs_memory_mb` is `128`.
- `uvcvideo` quirks is `256` or `0x100`.
- Witness `ok` is `true`.
- S-4/L-12 `stable_id` values are populated when those devices are present.

Then preserve hardware evidence:

```bash
lsusb
lsusb -t
lsblk -o NAME,LABEL,MODEL,SIZE,TRAN,MOUNTPOINTS
aplay -l
arecord -l
aconnect -l
amidi -l
wpctl status
```

## Replug Validation

Replug S-4, then run:

```bash
scripts/hapax-usb-topology-witness --repair
jq '.s4, .issues' /dev/shm/hapax-usb/topology-status.json
udevadm info -q property -n /dev/disk/by-id/usb-Linux_File-Stor_Gadget_fedcba9876543220-0:0 | \
  rg 'UDISKS_IGNORE|ID_MM_DEVICE_IGNORE|ID_SERIAL_SHORT'
nmcli device status | rg 'eth0|enp113s0u|DEVICE'
```

Expected:

- S-4 serial is `fedcba9876543220`.
- `UDISKS_IGNORE=1` and `ID_MM_DEVICE_IGNORE=1` are present for the storage
  function. The witness prefers `/dev/disk/by-id`; if that symlink is not ready
  during boot, it falls back to udev attributes on sysfs block devices without
  making a volatile `/dev/sdX` name part of the contract.
- `NM_UNMANAGED=1` and `ID_MM_DEVICE_IGNORE=1` are present for the CDC
  Ethernet function.
- `nmcli` reports the S-4 CDC Ethernet interface as unmanaged.
- `power/control` is `on`.
- No `s4_usb_missing`, `s4_sink_missing`,
  `s4_source_missing`, `s4_alsa_*_missing`, or `s4_*midi*_missing` issues.

For L-12:

```bash
pactl get-default-sink
pactl get-default-source
scripts/hapax-usb-topology-witness --repair
```

Expected policy:

- L-12 sink/source are present in `pactl list short sinks` and
  `pactl list short sources`.
- The default sink is the Ryzen/local-monitor sink governed by
  `config/wireplumber/10-default-sink-ryzen.conf`, not the L-12 or MPC.
- The default source may remain L-12 while explicit operator-capture policy is
  unchanged.

## Camera Placement

```bash
scripts/hapax-usb-topology-witness | tee /tmp/hapax-usb-topology.txt
jq '.cameras[] | {serial, path, on_caldigit_audio_controller}' \
  /dev/shm/hapax-usb/topology-status.json
```

Expected: every Logitech camera has `on_caldigit_audio_controller=false`.

## Status JSON Contract

Health, WCS, or handoff surfaces should read the witness JSON instead of
parsing kernel logs:

```bash
jq '{ok, issues, kernel, s4, l12, cameras}' /dev/shm/hapax-usb/topology-status.json
```

Load-bearing fields:

- `ok`: `true` only when boot parameters, S-4 policy, S-4 audio/MIDI, L-12
  defaults, and camera placement all match the baseline.
- `issues[]`: stable machine-readable issue names such as `s4_usb_missing`,
  `l12_default_sink_drift:*`, `camera_on_caldigit:*`, or
  `kernel_usbfs_memory_mb_drift:*`.
- `s4.block`: udisks and ModemManager suppression evidence.
- `s4.stable_id` / `l12.stable_id`: stable USB serial/vendor/product identity.
- `s4.path` / `l12.path`: current bus path for diagnostics only.
- `s4.net`: NetworkManager unmanaged and ModemManager suppression evidence.
- `l12.default_sink` / `l12.default_source`: PipeWire role evidence; default
  sink drift is advisory because L-12/MPC must not be promoted by omission.
- `cameras[]`: Logitech serial/path placement evidence.

## Bluetooth Pressure Relief

MX Ergo S and Keychron K2 HE should remain Bluetooth-first when stable:

```bash
bluetoothctl info D0:CE:43:99:FA:00
bluetoothctl info D9:FD:29:98:B1:6C
```

Expected: each device is paired, trusted, and connected. A USB fallback is a
temporary exception only when Bluetooth is unstable during a live session; note
the exception in the task/relay before adding USB endpoints back to the
livestream workstation.

## Emergency Actions

S-4 absent:

1. Run `scripts/hapax-usb-topology-witness` and preserve the JSON output.
2. Check `journalctl -k -b --no-pager | rg -i 'torso|s-4|usb|reset|disconnect'`.
3. Replug S-4 and re-run the witness. Confirm the returned `stable_id` matches
   the S-4 serial/vendor/product identity; do not promote a volatile bus path
   or `/dev/sdX` name into policy.
4. Do not copy firmware or staged OS payloads unless the operator explicitly
   assigns a firmware task.

L-12 absent:

1. Keep cameras off the CalDigit audio controller.
2. Check `lsusb -t`, `aplay -l`, `arecord -l`, and `wpctl status`.
3. Restart only the route witnesses first:
   `systemctl --user restart hapax-usb-topology-witness.service hapax-usb-router.service`.
4. Use `docs/runbooks/zoom-livetrak-usb-recovery.md` only if the L-12
   enumerates but audio payload is silent.

Bandwidth `-28`:

1. Confirm `hapax-usb-bandwidth-watchdog.service` is active.
2. Inspect `journalctl -k -b --no-pager | rg -i 'not enough bandwidth|-28|altsetting'`.
3. Move the offending camera off the audio controller before touching L-12/S-4.

Camera branch drift:

1. Stop the compositor before moving cameras.
2. Move the camera away from `pci-0000:71:00.0`.
3. Run `scripts/hapax-usb-topology-witness`; require no
   `camera_on_caldigit:*` issue before resuming.

CalDigit reset churn:

1. Preserve `journalctl -k -b` evidence for `thunderbolt`, `caldigit`, `reset`,
   and `disconnect`.
2. Avoid adding more endpoints to the CalDigit audio branch.
3. Power-cycle the dock only after S-4/L-12 evidence has been captured.

## Rollback

```bash
sudo rm -f /etc/udev/rules.d/90-hapax-s4-composite.rules
sudo rm -f /etc/NetworkManager/conf.d/90-hapax-s4-unmanaged.conf
sudo rm -f /etc/modprobe.d/99-hapax-usb-reliability-override.conf
sudo systemctl disable --now hapax-usb-bandwidth-watchdog.service
rm -f ~/.config/systemd/user/hapax-usb-topology-witness.service
rm -f ~/.config/systemd/user/hapax-usb-topology-witness.timer
systemctl --user daemon-reload
sudo udevadm control --reload-rules
```

Remove bootloader parameters only after an operator-approved maintenance
window, then reboot and re-run the validation section.

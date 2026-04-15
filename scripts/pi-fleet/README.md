# scripts/pi-fleet — Raspberry Pi fleet deployment + maintenance scripts

Companion to `docs/superpowers/plans/2026-04-15-pi-fleet-livestream-deployment-plan.md`.

## Files

- `pi5-first-boot.yaml` — Raspberry Pi Imager userconfig for flashing the incoming Pi 5 with hostname `hapax-ai`, SSH pre-auth, first-boot apt list (hailo-all, pipewire-module-roc-*, rnnoise, node-exporter), and `/boot/firmware/config.txt` additions (PCIe Gen3 enable, cooling-fan overlay). Applies via Raspberry Pi Imager Ctrl+Shift+X custom config dialog.
- `dhcp-reservation-notes.md` — Router instructions for DHCP reservations. Reserve `192.168.68.79` for `hapax-ai` (new Pi 5). Lock `hapax-hub` at `192.168.68.81` so it stops wandering (it moved from `.74` → `.81` silently in early April 2026).
- `respeaker-verify.sh` — UAC smoke test for the ReSpeaker USB Mic Array v2.0 (VID:PID `2886:0018`). Runs after Friday unbox: checks lsusb, udev symlink, ALSA enumeration, PipeWire source enumeration, 1-second capture, per-channel peak levels. Pure read-only verification; does not mutate anything.
- `respeaker-udev.rules` — udev rule creating stable `/dev/respeaker-mic-array` and `/dev/respeaker-pcm` symlinks regardless of USB enumeration order. Install on `hapax-ai` via `sudo cp respeaker-udev.rules /etc/udev/rules.d/99-respeaker.rules && sudo udevadm control --reload && sudo udevadm trigger`.
- `rename-runbook.sh` — Parametrized hostname rename sequence for the existing 5-Pi fleet (`hapax-pi1..6` → `hapax-ir-desk`/`ir-room`/`hub`/`sentinel`/`rag`). **Dry-run by default**; operator invokes with `--execute` during a declared maintenance window. Recommended order (lowest risk first): sentinel → rag → ir-desk → ir-room → hub. Per-Pi backup of `/etc/hostname` and `/etc/hosts` before mutation; avahi-daemon restart after mutation.

## Workstation-side companion files

- `config/pipewire/respeaker-room-mic.conf` — PipeWire drop-in: `module-roc-sink` outbound (ReSpeaker → workstation), `module-roc-source` inbound (Yeti post-AEC → hapax-ai-asr), RNNoise filter chain on raw ReSpeaker input, default-source override to the cleaned chain.
- `pi-edge/hapax-ai/` — systemd user units for the new Pi 5 workloads (coprocessor, asr, room-vad) + env template.

## Not in this directory

- The Pi 4 fleet's IR edge daemon code lives at `pi-edge/hapax-ir-edge.service` and `pi-edge/hapax_ir_edge.py`. Those are untouched by this deployment batch.
- Health monitor's `PI_FLEET` dict lives at `agents/health_monitor/constants.py`. It currently only knows `hapax-pi4` and `hapax-pi5`; the deployment plan §7.2 covers the pending update (deferred until the rename runbook runs or operator authorizes the council-side edit).

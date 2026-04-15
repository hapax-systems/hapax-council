# hapax-ai — Raspberry Pi 5 edge node

**Arriving:** Thursday 2026-04-16 (Pi 5 hardware) + Friday 2026-04-17 (ReSpeaker USB Mic Array).

**Role:** Hailo AI coprocessor (vision inference + streaming ASR) + audio ingest (ReSpeaker room mic).

**Hostname:** `hapax-ai` (new — not `hapax-pi7` or `hapax-pi5`; the role-based naming scheme is documented in `docs/superpowers/plans/2026-04-15-pi-fleet-livestream-deployment-plan.md` §1).

## Contents

- `hapax-ai-coprocessor.service` — systemd user unit for the Hailo vision inference daemon (per-person face identity via MobileFaceNet, YOLOv8-pose body tracking, MediaPipe Hands landmark detection). Consumes frames via workstation SHM-over-network, produces structured detection JSON at ~100 FPS to `/dev/shm/hapax-ai/detections.json`. Unblocks LRR Phase 6 §6 presence-detect-without-contract + Phase 8 §11 environmental perception emphasis.
- `hapax-ai-asr.service` — systemd user unit for Hailo-accelerated Whisper streaming ASR. Hybrid pipeline: Whisper encoder offloaded to Hailo, decoder on Pi 5 CPU. ~250 ms latency. Input: operator Yeti via PipeWire `module-roc-source` from workstation. Output: append-only transcript JSONL at `/dev/shm/hapax-ai/transcripts.jsonl`. Unblocks LRR Phase 9 §4 daimonion code-narration.
- `hapax-room-vad.service` — systemd user unit for Silero VAD on the ReSpeaker DSP-processed audio. Emits `room_voice_activity` SHM signal for `presence_engine.py` fusion.
- `hapax-ai.env` — environment file template sourced by the three units above.

## Deployment

All three service units are **scaffolding** — the actual Python workload modules (`hapax_ai.coprocessor`, `hapax_ai.asr`, `hapax_ai.room_vad`) are not yet implemented. The units are pre-staged so Thursday's first-boot deploys cleanly even while the workload code is being written.

First-boot runbook, DHCP reservation notes, and the Raspberry Pi Imager userconfig live under `scripts/pi-fleet/`. The full deployment plan is at `docs/superpowers/plans/2026-04-15-pi-fleet-livestream-deployment-plan.md`.

## Not covered here

- ReSpeaker PipeWire config: `config/pipewire/respeaker-room-mic.conf`
- ReSpeaker udev rule: `scripts/pi-fleet/respeaker-udev.rules`
- Rename runbook for the existing 5 Pi 4 fleet: `scripts/pi-fleet/rename-runbook.sh` (scheduled for the weekend maintenance window; not run on day 1 of hapax-ai deployment)

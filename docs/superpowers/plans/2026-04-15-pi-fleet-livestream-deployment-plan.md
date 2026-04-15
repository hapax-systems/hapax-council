# Pi Fleet Livestream Deployment Plan

**Date:** 2026-04-15 CDT
**Author:** epsilon session
**Scope:** Put the existing 5-Pi 4 fleet + incoming Pi 5 hardware + Friday ReSpeaker to work in support of the 24/7 livestream as the exclusive research vehicle and primary dev platform.
**Status:** Draft — tonight-scope executed as described in §6; deferred items listed in §7.

**In-repo artifact locations** (promoted from the relay context cache per operator direction 2026-04-15 "update docs, pr"):

- `scripts/pi-fleet/pi5-first-boot.yaml` — Raspberry Pi Imager userconfig for Thursday
- `scripts/pi-fleet/dhcp-reservation-notes.md` — router instructions for IP pinning
- `scripts/pi-fleet/rename-runbook.sh` — maintenance-window hostname rename script (dry-run default)
- `scripts/pi-fleet/respeaker-verify.sh` — Friday UAC smoke test
- `scripts/pi-fleet/respeaker-udev.rules` — stable `/dev/respeaker-mic-array` symlink
- `pi-edge/hapax-ai/hapax-ai-coprocessor.service` — Hailo vision inference systemd user unit
- `pi-edge/hapax-ai/hapax-ai-asr.service` — Whisper streaming ASR systemd user unit
- `pi-edge/hapax-ai/hapax-room-vad.service` — Silero room VAD systemd user unit
- `pi-edge/hapax-ai/hapax-ai.env` — shared environment file template
- `pi-edge/hapax-ai/README.md` — per-node overview
- `config/pipewire/respeaker-room-mic.conf` — PipeWire drop-in for ReSpeaker + ROC stream to workstation

The backing files in `~/.cache/hapax/relay/context/pi-fleet/` are retained as the working-copy originals but the in-repo versions are now canonical.

---

## 0. Ground truth (live-verified 2026-04-15 ~03:56Z)

Five Pis online, all responding to ping + mDNS + writing heartbeats to `~/hapax-state/edge/` within the last minute:

| Current hostname | IP (live) | Hardware | Current primary role | Secondary |
|---|---|---|---|---|
| `hapax-pi1` | 192.168.68.78 | Pi 4 | IR perception — desk (YOLOv8n ONNX ~130 ms/frame, NoIR cam) | — |
| `hapax-pi2` | 192.168.68.52 | Pi 4 | IR perception — room | — |
| `hapax-pi4` | 192.168.68.53 | Pi 4 | Health sentinel | Watch backup |
| `hapax-pi5` | 192.168.68.72 | **Pi 4 hardware**, misnamed | RAG edge preprocessor | gdrive-pull timer |
| `hapax-pi6` | **192.168.68.81** | Pi 4 | Sync hub (8 sync agents offloaded from workstation) | IR perception — overhead, album-identifier frame server |

**Critical-finding:** `/etc/hosts` on the workstation still maps `hapax-pi6 → 192.168.68.74`. That IP is DOWN. Pi-6's actual IP has been .81 since the 2026-04-09 GDO handoff noted a DHCP move. Any script hardcoding `hapax-pi6` by hostname-lookup has been silently broken for ~6 days. This is fixed in §6 Action 1.

**Incoming hardware:**
- **Thursday 2026-04-16:** Raspberry Pi 5 (actual model 5, not a Pi 4 named pi5). Operator note — "additional Pi 5 arriving tomorrow."
- **Friday 2026-04-17:** ReSpeaker USB Mic Array v2.0 (XMOS XVF-3000, 4-PDM, onboard AEC + beamforming + VAD). Plugs into the Pi 5 from Thursday.

---

## 1. Naming scheme (decision)

Current `hapax-piN` serial-based naming has two problems: (a) `hapax-pi5` is a Pi 4 — name/hardware collision with incoming Pi 5, (b) serial numbers convey nothing about function.

**New scheme:** `hapax-<role>` with an optional `-<location>` suffix only when one role spans multiple physical locations. Hyphens within role names are allowed (`ir-desk`, `ir-room`).

| Current | New | Rationale |
|---|---|---|
| `hapax-pi1` | **`hapax-ir-desk`** | Primary role: IR perception, desk position |
| `hapax-pi2` | **`hapax-ir-room`** | Primary role: IR perception, room position |
| `hapax-pi6` | **`hapax-hub`** | Primary role: central sync + perception hub. Both "sync hub" and "perception hub" (IR overhead) collapse into one neutral name. Secondary IR role tracked in `PI_FLEET` metadata, not hostname. |
| `hapax-pi4` | **`hapax-sentinel`** | Primary role: health sentinel. Watch backup is a secondary concern tracked in `expected_services`. |
| `hapax-pi5` | **`hapax-rag`** | Primary role: RAG edge preprocessor. Frees the `pi5` string for the actual Pi 5 hardware. Drops the `-edge` suffix because every Pi is an edge node by definition. |
| *(new Thursday)* | **`hapax-ai`** | Primary role: Hailo AI coprocessor + (Friday onwards) audio ingest via ReSpeaker. Single node, two specialty HAT + USB peripherals. |

### Scheme properties

- **Stable to hardware swaps.** If pi-4 sentinel is later migrated to new hardware, the name stays `hapax-sentinel`. The current scheme is tied to acquisition serial.
- **Extensible by location.** `ir-desk`/`ir-room`/`ir-overhead` pattern generalizes — a future `hapax-ir-synths` for the synth corner would slot in without renaming anything.
- **Extensible by role count.** If a second RAG node ever ships, it becomes `hapax-rag-1`/`hapax-rag-2`; current `hapax-rag` stays as the alias for `hapax-rag-1`. Same pattern for `hapax-ai-1`/`hapax-ai-2` if the AI workload grows.
- **Avoids relay namespace collisions.** The Greek-letter session names (alpha, beta, delta, epsilon) are reserved for relay sessions, so we don't use `hapax-alpha` etc. for Pis.
- **Avoids the Pi-4-named-pi5 trap permanently.** Neither hardware revision nor purchase order appears in any hostname.

---

## 2. Transition strategy — dual-binding instead of atomic rename

**Problem:** renaming 5 live Pis atomically breaks every script, config, systemd unit, Ansible play, and journal reference to the old names. At least three places hold old-name references: workstation `/etc/hosts`, `agents/health_monitor/constants.py::PI_FLEET`, the compositor's `album_identifier.service` environment, plus any shell scripts or Grafana dashboards that address Pis by hostname.

**Strategy:** dual-binding for a transition window.

1. **Workstation `/etc/hosts`** gets both names pointing to the same IP: `192.168.68.78 hapax-ir-desk hapax-pi1`. Old `hapax-pi1` keeps working; new `hapax-ir-desk` starts working immediately. This is the tonight action.
2. **Pi-side `hostnamectl`** is deferred to a declared maintenance window (§6 Action 6). Changing the Pi's own hostname affects its heartbeat-writer payload (which includes `hostname` field), its systemd unit naming, and avahi advertisement. That's a scheduled service interruption, not tonight-scope.
3. **Council-side config** updates land in the Pi 5 Thursday deployment PR so new and old names coexist until the maintenance window.
4. **Transition period ends** when the maintenance window completes and all services address Pis by the new names exclusively; then old `hapax-piN` aliases can be removed from `/etc/hosts` in a cleanup commit.

This is the same "dual-write then cut over" pattern the rest of the stack uses (cycle_mode → working_mode, etc.).

---

## 3. Pi 5 Thursday deployment (`hapax-ai`)

### 3.1 Hardware arriving Thursday

- Raspberry Pi 5 (8 GB or 16 GB — ideally 16 GB for headroom; 8 GB works)
- **Required accessories — must have all three at first boot:**
  - Official Active Cooler (thermal-throttles without one, within ~200 s of sustained load)
  - Official 27 W USB-C PD PSU (Pi 5 is PSU-picky; random USB-C chargers trigger current-limit warnings)
  - M.2 HAT+ (comes with AI HAT+ kit, but verify)
- **Recommended:**
  - Raspberry Pi AI HAT+ 26 TOPS (Hailo-8, $110) — vs Pi 4's 7.7 FPS, delivers ~180 FPS YOLOv8n and makes real-time Whisper-small ASR feasible. This is the role's entire justification.
  - Optional: small NVMe (256 GB 2242) + stacking M.2 spacer for local Whisper model cache + 24/7 journal
- **Ordered separately (not blocking Thursday first-boot):**
  - The ReSpeaker USB Mic Array (arrives Friday; §4)

### 3.2 Pre-flight (executed tonight, artifacts in `~/.cache/hapax/relay/context/pi-fleet/`)

- `pi5-first-boot.yaml` — Raspberry Pi Imager userconfig / cloud-init for SSH pre-auth, hostname pre-set to `hapax-ai`, workstation SSH pubkey, WiFi credentials (fallback only; Ethernet primary), time zone CDT, locale en_US.UTF-8.
- `dhcp-reservation-notes.md` — instructions for operator to create a DHCP reservation on the LAN router for the new Pi 5's MAC → `192.168.68.79` (next available IP between sentinel .53 and rag .72; see §3.4).
- `hapax-ai-coprocessor.service` — systemd user unit stub for the Hailo inference daemon (workload TBD post-boot).
- `hapax-ai-asr.service` — systemd user unit stub for the Whisper streaming ASR daemon.
- `hapax-ai.env` — placeholder env file listing the expected SHM output paths (`/dev/shm/hapax-ai/detections.json`, `/dev/shm/hapax-ai/transcripts.jsonl`, `/dev/shm/hapax-ai/presence.json`).

### 3.3 First-boot runbook (Thursday)

1. Flash microSD (or NVMe if ordered with the stacking HAT) with Raspberry Pi OS Bookworm 64-bit via Raspberry Pi Imager, applying `pi5-first-boot.yaml`.
2. Install Active Cooler, AI HAT+, seat M.2 Hailo-8.
3. Boot from Ethernet. Verify DHCP reservation picks up the new MAC and assigns `192.168.68.79`.
4. `ssh hapax@hapax-ai.local` — confirms avahi + SSH key works.
5. Update `/etc/hosts` on workstation to fix the `hapax-ai` line with the assigned IP (replace the `192.168.68.???` placeholder committed tonight).
6. `sudo apt update && sudo apt install -y hailo-all` — installs Hailo firmware, PCIe driver, HailoRT runtime, Hailo Tappas framework.
7. Verify Hailo: `hailortcli fw-control identify` → should report Hailo-8 device.
8. Enable PCIe Gen3 in `/boot/firmware/config.txt` (`dtparam=pciex1_gen=3`) for NVMe speed if NVMe is installed. Reboot.
9. Deploy `hapax-ai-coprocessor.service` and `hapax-ai-asr.service` to `~/.config/systemd/user/`. `systemctl --user daemon-reload && systemctl --user enable --now hapax-ai-coprocessor hapax-ai-asr`.
10. First smoke test: run `hailortcli benchmark yolov8n.hef` — should complete at ~180 FPS.
11. Add `hapax-ai` to workstation's `agents/health_monitor/constants.py::PI_FLEET` (see §6 Action 3).
12. Verify heartbeat: `cat ~/hapax-state/edge/hapax-ai.json` on workstation.

### 3.4 IP assignment

Current Pi IPs (DHCP-reserved on the router, except pi-6 which has wandered):
- pi-1: .78
- pi-2: .52
- pi-4: .53
- pi-5: .72
- pi-6: .81 (wandered from .74)

Natural next slot: **192.168.68.79** (between sentinel and rag, unused per last `nmap`). Reserve it for `hapax-ai` in the router DHCP table.

Incidentally: while we're in the DHCP table, **pin pi-6 to 192.168.68.81** so it stops wandering. Currently it has a lease-based address that the ISP's DHCP may churn on next reboot. This is Action 4 in §6.

### 3.5 Workloads (day-one scope)

| Service | What it does | Input | Output | SHM path |
|---|---|---|---|---|
| `hapax-ai-coprocessor` | Per-person identity via face embeddings (MobileFaceNet or ArcFace on Hailo) + YOLOv8-pose body pose + MediaPipe hands. Consumes frames from compositor's shared-memory RGB ring (same pattern Reverie uses via `/dev/shm/hapax-visual/frame.jpg`). | Frame stream from `brio-operator` via compositor SHM | Per-person `{person_id, bbox, pose, hands, confidence}` at ~100 FPS | `/dev/shm/hapax-ai/detections.json` |
| `hapax-ai-asr` | Streaming Whisper-small ASR on operator voice, with Hailo encoder offload. Hybrid pipeline: encoder on Hailo, decoder on Pi 5 CPU. ~250 ms latency. | Audio stream from workstation's `echo_cancel_source` via PipeWire `module-roc-source` (operator Yeti after AEC) | Append-only transcript JSONL with timestamps + confidence | `/dev/shm/hapax-ai/transcripts.jsonl` |

Both services are **supplementary observers**, not replacements — the existing Pi 4 IR fleet keeps producing its signals, and the workstation daimonion keeps being the canonical STT/TTS runtime. `hapax-ai` adds higher-rate signals (100 FPS vs 0.33 FPS IR) and a redundant transcript path. When Phase 6 §6 (presence-detect-without-contract) opens, the per-person identity output from `hapax-ai-coprocessor` is the data source that unblocks the per-person contract-matching check `presence_engine.py` currently lacks.

### 3.6 Workloads (Friday onwards, post-ReSpeaker)

See §4.

### 3.7 Not in scope for day one

- Phase 6 §6 presence-detect closed loop wiring — blocked on Phase 5 + Phase 6 open
- Phase 8 §11 environmental perception emphasis wiring — blocked on Phase 8 open
- Phase 9 §4 code-narration via ASR transcripts — blocked on Phase 9 open

These land when their phases open. The `hapax-ai` Pi produces the signals; downstream consumers wire in later.

---

## 4. ReSpeaker Friday deployment

### 4.1 Hardware arriving Friday

- ReSpeaker USB Mic Array v2.0 (Seeed SKU 107990053) — 4 PDM mics, XMOS XVF-3000, onboard DSP (AEC, beamforming, 360° DOA, VAD, noise suppression, dereverberation), UAC 1.0 plug-and-play
- Optional: USB 2.0 extension cable (5 m) to put the mic at the room acoustic center while the Pi stays at its thermal/cabling-friendly position

### 4.2 Pre-flight artifacts (tonight)

- `respeaker-pipewire.conf` — PipeWire module config: `module-roc-sink` to stream the ReSpeaker capture to the workstation over the LAN at <50 ms latency; RNNoise plugin chain on the Pi side.
- `respeaker-udev.rules` — udev rule to create a stable `/dev/respeaker-mic-array` symlink regardless of USB enumeration order (so PipeWire config doesn't break when USB devices shuffle).
- `respeaker-verify.sh` — smoke-test script: enumerate UAC, read 1 second of audio, report sample rate + channel count + peak level.
- `hapax-room-vad.service` — systemd user unit stub for the room VAD daemon (reads ReSpeaker stream, emits `room_voice_activity` SHM signal).

### 4.3 First-plug runbook (Friday)

1. `ssh hapax@hapax-ai.local`
2. Plug ReSpeaker into Pi 5 USB 3.0 port.
3. `bash ~/bin/respeaker-verify.sh` — expect UAC device `arecord -l | grep ReSpeaker` visible, 16 kHz × 4 channels (post-DSP: 1-channel processed output + 3 raw mics), no enumeration errors.
4. Install udev rule: `sudo cp respeaker-udev.rules /etc/udev/rules.d/99-respeaker.rules && sudo udevadm control --reload && sudo udevadm trigger`.
5. Verify stable symlink: `ls -l /dev/respeaker-mic-array`.
6. Deploy `respeaker-pipewire.conf` to `~/.config/pipewire/pipewire.conf.d/`. Restart PipeWire user services.
7. Deploy `hapax-room-vad.service` to `~/.config/systemd/user/`. Enable and start.
8. On workstation: add `module-roc-source` to workstation PipeWire config to receive the stream. Verify with `pw-top` that audio is flowing.
9. Subscribe `presence_engine.py` to the `room_voice_activity` SHM signal as a new evidence source with an appropriate likelihood ratio (starting point: LR=3.0 for positive evidence, not bidirectional — room voice activity is positive-only like desk_active).

### 4.4 Scope clarification (critical)

**The ReSpeaker is a ROOM ambient mic, not a second operator mic.** The operator voice path stays on the workstation Blue Yeti via `echo_cancel_source`. The ReSpeaker's DSP output (the 1-channel processed feed, not the raw mics) feeds:

1. `presence_engine.py` room evidence channel — new positive-only signal
2. A future Phase 9 cross-modal fusion: room voice activity ∧ high chat engagement → bias toward `chat` activity
3. A future Phase 9 stereo operator-voice-over-YouTube sidechain compressor — the ReSpeaker observes music leakage from the monitors, and the DSP's AEC cancels it to produce a clean room-side reference

The ReSpeaker does **not** become the operator's spoken-command mic. That path stays Yeti.

---

## 5. LRR phase alignments

| LRR phase | Pi fleet role |
|---|---|
| **Phase 0** Verification | No Pi changes. `hapax-sentinel` keeps running its watch-backup + health-monitor role unchanged. |
| **Phase 3** Hardware validation | `hapax-ai` first boot + DHCP reservation happens in the Phase 3 timeframe if Phase 5 substrate swap is Thursday-or-later. |
| **Phase 5** Hermes substrate swap | No Pi involvement. `hapax-ai` stays out of the swap path (it doesn't run Hermes). |
| **Phase 6** Governance finalization + stream-mode axis | `hapax-ai` produces the `detected_person_ids` per-person identity signal that Phase 6 §6 needs for the presence-detect-without-contract T0 block. `hapax-sentinel` is a natural host for the Phase 6 §5 stimmung-watchdog — independent failure domain from the workstation the watchdog is protecting. |
| **Phase 8** Content programming | `hapax-ai` provides the <100 ms pose/hand signals Phase 8 §11 needs for environmental perception emphasis (hero-mode camera switching). `hapax-hub`'s 8 sync agents stay where they are. |
| **Phase 9** Closed-loop feedback + narration | `hapax-ai-asr` produces a redundant operator transcript path for Phase 9 §4 daimonion code-narration. `hapax-ai` + ReSpeaker provide the `room_voice_activity` signal Phase 9 §1 consumes. |
| **Phase 10** Observability + drills | Per-Pi Prometheus node_exporter on `:9100` sidecar becomes the Pi-fleet observability plane Phase 10 §2 wants. Each Pi gains an exporter, `hapax-sentinel` becomes the aggregator + remote-write relay to the workstation Prometheus. |

Only Phase 6 stimmung-watchdog and Phase 10 Prometheus exporters are deferred to the phases themselves — they are tracked in the Phase 6 / Phase 10 plan files, not here. This plan stages the hardware + hostname substrate; phase-specific wiring lands on the phase branches.

---

## 6. Tonight's execution actions (epsilon session, 2026-04-15)

Only items that are (a) docs-only, (b) direct production edits with low blast radius, or (c) staged artifacts to disk but not committed to git. Git-bound items are pre-staged in `~/.cache/hapax/relay/context/pi-fleet/` matching the alpha-pre-staging pattern already established for LRR phases.

### Action 1 — Fix `/etc/hosts` pi-6 IP + add role-based aliases (dual-binding)

**File:** `/etc/hosts` on workstation.
**Change:** correct `hapax-pi6` from `192.168.68.74` to `192.168.68.81`; add role-based aliases as additional names on each line; insert placeholder comment for `hapax-ai` (Thursday).
**Risk:** zero — adding aliases cannot break existing resolution. Fixing the pi-6 IP unbreaks any currently-silent failure.
**Backup:** copy to `/etc/hosts.bak-20260415-epsilon` before edit.
**Done this session.** ✓

### Action 2 — Update `project_studio_cameras` auto-memory

**File:** `~/.claude/projects/-home-hapax-projects/memory/project_studio_cameras.md`
**Change:** correct "6 Raspberry Pi 4 (all deployed)" → "5 Pi 4s + 1 incoming Pi 5 Thursday 2026-04-16". Record new naming scheme + mapping. Note Pi-6 IP is now .81, not .74.
**Risk:** zero — memory file, not production.
**Done this session.** ✓

### Action 3 — Pre-stage Pi 5 Thursday artifacts

**Location (canonical):** in-repo under `scripts/pi-fleet/` and `pi-edge/hapax-ai/` as enumerated in the "In-repo artifact locations" block at the top of this file. Originally staged in `~/.cache/hapax/relay/context/pi-fleet/`; promoted to git per operator direction 2026-04-15 "update docs, pr".
**Files:** `pi5-first-boot.yaml`, `hapax-ai-coprocessor.service`, `hapax-ai-asr.service`, `hapax-ai.env`, `dhcp-reservation-notes.md`, `README.md`.
**Risk:** zero — systemd unit scaffolding targeting a host that does not yet exist. No production host loads these files until Thursday.
**Done this session.** ✓

### Action 4 — Pre-stage ReSpeaker Friday artifacts

**Location (canonical):** `config/pipewire/respeaker-room-mic.conf`, `scripts/pi-fleet/respeaker-udev.rules`, `scripts/pi-fleet/respeaker-verify.sh`, `pi-edge/hapax-ai/hapax-room-vad.service`.
**Risk:** zero — config drop-ins and systemd units targeting `hapax-ai`, which doesn't exist yet. Not loaded until Friday.
**Done this session.** ✓

### Action 5 — Pre-stage `rename-runbook.sh` for maintenance window

**Location:** `scripts/pi-fleet/rename-runbook.sh`
**Purpose:** parametrized per-Pi hostnamectl + `/etc/hostname` + `/etc/hosts` + avahi restart sequence. **Not executed tonight.** Operator runs in a declared maintenance window.
**Risk:** zero — script file, not executed. Dry-run default.
**Done this session.** ✓

### Action 6 — Update `epsilon.yaml` with Pi fleet workstream

**File:** `~/.cache/hapax/relay/epsilon.yaml`
**Change:** add current workstream summary + convergence log entry.
**Risk:** zero — relay state file, epsilon's own.
**Done this session.** ✓

---

## 7. Deferred items (with reasons)

### 7.1 Atomic hostname rename on live Pis

**Reason:** breaks running services (hapax-ir-edge heartbeat writers, album-identifier frame server on pi-6, hapax-sentinel, systemd unit names that include the hostname) across 5 Pis simultaneously. The livestream is currently not streaming (compositor stopped per alpha direction; hermes quant running overnight) so the window is favorable — but the rename still has real cleanup work per-Pi.
**Trigger:** declared maintenance window, ideally coordinated with the Pi 5 Thursday deployment since that's already a planned intervention.
**Artifact:** `rename-runbook.sh` (pre-staged in Action 5).

### 7.2 Council-side `agents/health_monitor/constants.py::PI_FLEET` update

**Change to make:** add entries for `hapax-ir-desk`, `hapax-ir-room`, `hapax-hub`, plus `hapax-ai` (Thursday) with their expected services. Currently `PI_FLEET` only knows `hapax-pi4` and `hapax-pi5`; IR Pis (`pi-1`/`pi-2`/`pi-6`) are monitored via heartbeat freshness only.
**Status:** still deferred as of 2026-04-15 "update docs, pr" pass — see below. The docs + scaffolding for `hapax-ai` are now in the repo, but the `PI_FLEET` dict itself is intentionally untouched this pass because the exact hostname values depend on whether the maintenance-window rename (§7.1) has run. If the rename runs first, the dict gets clean role-based entries. If the rename is deferred indefinitely, the dict needs to dual-bind (both `hapax-pi4` and `hapax-sentinel` → same `expected_services`), which is uglier and pollutes the health-monitor schema.
**Trigger for executing:** whichever of (a) the weekend rename window completes, or (b) the operator explicitly requests the dual-bound interim form, lands first. Until then, the dict keeps its current two entries.
**Blast radius if left untouched:** low. Health monitor continues to check `hapax-pi4` and `hapax-pi5` as before; the other three Pis (`hapax-pi1`/`pi2`/`pi6`) are checked via heartbeat freshness in `edge.py` regardless of whether they appear in `PI_FLEET`. No degraded-state alerts firing from the omission.

### 7.3 Pi-1 heatsink

**Observation:** IR-perception memory notes `pi-1 runs warm (61°C) under sustained inference — needs heatsink`.
**Reason deferred:** physical action. If the Pi 5 kit ships with a spare Active Cooler or heatsink, this is the time to apply it to pi-1. Flag for operator at Thursday's unboxing.

### 7.4 Phase 6 §5 stimmung-watchdog on `hapax-sentinel`

**Idea:** sentinel is ~1% CPU used; it is the natural independent-failure-domain host for the stimmung auto-private watchdog (Phase 6 §5). Hosting it on the workstation it is watching creates a single point of failure; hosting it on a Pi gives independent blast radius.
**Reason deferred:** Phase 6 implementation is blocked on Phase 5 substrate swap. The watchdog lands with Phase 6, not with this Pi fleet plan. Tracked in `docs/superpowers/plans/2026-04-15-lrr-phase-6-governance-finalization-plan.md` Stage 4 Task 4.1.

### 7.5 Phase 10 per-Pi Prometheus `node_exporter` + `hapax-sentinel` as relay aggregator

**Idea:** each Pi gains `node_exporter` on `:9100`; `hapax-sentinel` runs a Prometheus remote-write relay that collects from all Pis + workstation and forwards to central Prometheus. This is the Phase 10 observability plane, and gives independent observability of the workstation from the workstation's own Prometheus.
**Reason deferred:** Phase 10 open. Tracked in the Phase 10 plan, not here.

### 7.6 Pi-6 memory pressure relief (offload sync agents)

**Observation:** memory says Pi-6 is "memory tight" with 8 concurrent sync agents + IR overhead + album-identifier frame server. It hasn't crashed, but has no headroom.
**Reason deferred:** no clear offload target until `hapax-ai` is deployed and proven. Post-Pi-5-deployment, candidate offloads include: move `album-identifier` frame-fetch path to `hapax-ai` (which already processes the operator-view camera), reducing Pi-6 to sync-hub + pure IR overhead. Review after 1-week soak.

### 7.7 Operator-side decision: AI HAT+ 26 TOPS ($110) vs AI Kit 13 TOPS ($70)

**Open question:** is real-time Whisper-small streaming ASR a priority for the `hapax-ai` day-one scope? If yes, 26 TOPS is required (13 TOPS cannot run Whisper-small at interactive latency). If ASR is deferrable, save $40.
**Reason deferred:** operator decision. Flag in the §8 open questions.

---

## 8. Open questions (operator decisions)

| # | Question | Default if operator silent |
|---|---|---|
| O1 | AI HAT+ 26 TOPS or AI Kit 13 TOPS? | 26 TOPS — unlocks real-time ASR, the speech-side of the livestream's LRR Phase 9 unblock |
| O2 | Pi 5 8 GB or 16 GB RAM? | 16 GB — headroom for future workload scaling costs ~$40 more; 8 GB works for day-one |
| O3 | Thursday rename window or defer to weekend? | Defer to weekend — Thursday focus is getting `hapax-ai` online, not renaming 5 other Pis |
| O4 | Pi-6 (`hapax-hub`) memory pressure — relieve immediately or wait for hapax-ai soak? | Wait — no clear target until hapax-ai proves its role |
| O5 | PI_FLEET dict update goes into which PR? | Whichever PR follows PR #819's merge. Until then, stays staged. |
| O6 | Static IP for `hapax-ai` via DHCP reservation — 192.168.68.79? | Yes — it's the natural next slot |
| O7 | Does `hapax-sentinel`'s spare CPU also get a Phase 10 Prometheus relay role, or just stimmung-watchdog (Phase 6)? | Both; they don't conflict |

---

## 9. Rollback (per-action)

| Action | Rollback |
|---|---|
| `/etc/hosts` edit | `sudo cp /etc/hosts.bak-20260415-epsilon /etc/hosts` |
| Auto-memory update | `git-style` revert — memory file is under `~/.claude/projects/-home-hapax-projects/memory/`, not git-tracked, but we keep the prior content documented in this plan's §0 ground-truth table |
| Staged artifacts in `~/.cache/hapax/relay/context/pi-fleet/` | `rm -rf ~/.cache/hapax/relay/context/pi-fleet/` — nothing else depends on them |
| Epsilon.yaml update | Restore prior version from git history (not git-tracked, but the previous content is in conversation context) |

Tonight's changes are all low-blast-radius and reversible in under 10 seconds total.

---

## 10. What success looks like

- **Tonight:** plan authored, `/etc/hosts` pi-6 IP corrected (ends a 6-day silent failure), role-based aliases dual-bound, auto-memory accurate, Thursday + Friday deployment scripts staged and reviewable, epsilon.yaml reflects the Pi-fleet workstream.
- **Thursday:** `hapax-ai` boots, Hailo verified, systemd units enabled (even if workloads are stubs), heartbeat visible to workstation `~/hapax-state/edge/hapax-ai.json`.
- **Friday:** ReSpeaker plugged into `hapax-ai`, UAC class-compliance verified, PipeWire ROC stream flowing to workstation, `room_voice_activity` signal populated in `presence_engine.py`.
- **Weekend maintenance window:** all 5 existing Pis renamed to role-based names via runbook, old `hapax-piN` aliases removed from `/etc/hosts`, `PI_FLEET` dict updated on a fresh branch when branch discipline allows.
- **Phase 6 open (eventual):** stimmung-watchdog lands on `hapax-sentinel`; presence-detect-without-contract block lands on `hapax-ai`.
- **Phase 10 open (eventual):** per-Pi `node_exporter` + sentinel-hosted Prometheus relay.

---

## 11. Protocol commitments (reminders)

- Epsilon does not commit to beta-authored branches (including `beta-phase-4-bootstrap`) without an inflection + ack cycle.
- Epsilon does not write to `beta.yaml` — that file reflects the "real beta" session's state (currently shipping drop #47 Ring 1 work per the inbound convergence entry).
- Epsilon does not claim Phase 6 implementation ownership without operator direction; this plan stages Pi hardware substrate only.
- The actual hostname rename on running Pis is declared as maintenance-window work, not spontaneous.

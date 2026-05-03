# systemd Service Management

All production services run as systemd user units under `user@1000.service` with lingering enabled. No process supervisors (process-compose, supervisord) in the boot chain.

## Directory Structure

```
systemd/
├── units/              Service and timer unit files (source of truth)
├── user-preset.d/      Presets for repo-owned user timers
├── overrides/          Drop-in .conf files for dependency ordering and resource limits
│   ├── dev/            Timer frequency overrides for dev cycle mode
│   └── *.service.d/    Per-service drop-ins
├── scripts/            install-units.sh, backup.sh, camera-setup.sh
└── watchdogs/          Health check scripts
```

## Architecture

Three tiers, two managers:

```
Docker Compose (infrastructure)     systemd user units (application + utilities)
─────────────────────────────────   ─────────────────────────────────────────────
qdrant, postgres, redis,            hapax-secrets     → all credentials (oneshot)
litellm, langfuse, grafana,         logos-api         → FastAPI :8051
prometheus, clickhouse,             hapax-daimonion       → voice daemon (GPU)
n8n, open-webui, minio, ntfy       visual-layer-agg  → perception pipeline
                                    studio-compositor → camera tiling (GPU)
Managed by:                         studio-fx-output  → ffmpeg /dev/video50
  llm-stack.service (oneshot)       hapax-watch-recv  → Wear OS biometrics
  llm-stack-analytics.service       31 timers         → sync, health, backups
```

## Grouping Targets

Two top-level grouping targets organise the application stack:

- **`hapax-visual-stack.target`** — production visual surface pipeline: `hapax-imagination`, `hapax-imagination-loop`, `hapax-dmn`, `hapax-reverie`, `hapax-content-resolver`, `visual-layer-aggregator`, `studio-compositor`. Lists dependents explicitly via `Wants=`. The Tauri/WebKit `hapax-logos` preview is decommissioned and is not pulled in by this target.
- **`hapax.target`** — non-visual application services: broadcast/audio (`hapax-mastodon-post`, `hapax-bluesky-post`, `hapax-omg-lol-fanout`, `hapax-channel-trailer`, `hapax-live-cuepoints`), awareness (`hapax-operator-awareness`), marketing/observability (`hapax-chronicle-quality-exporter`, `hapax-feedback-loop-detector`, `hapax-impingement-sampler`, `hapax-quota-observability`, `hapax-youtube-telemetry`), mail-monitor (`hapax-mail-monitor-watch-renewal`, `hapax-mail-monitor-weekly-digest`), `hapax-broadcast-orchestrator`. Dependent units declare `WantedBy=hapax.target`; enabling each unit creates a symlink under `~/.config/systemd/user/hapax.target.wants/`, and starting the target pulls the whole stack. The `hapax-discord-webhook` unit was previously listed here but was decommissioned 2026-05-01 — see the `DECOMMISSIONED_UNITS` bullet list below.

Both targets are `WantedBy=default.target` so they activate on user login.

## Boot Sequence

```
1. hapax-secrets.service     Load credentials from pass store → /run/user/1000/hapax-secrets.env
2. llm-stack.service         docker compose --profile full up -d (waits 30s for Docker daemon)
3. llm-stack-analytics       docker compose --profile analytics up -d (60s after llm-stack)
4. logos-api.service         After: llm-stack, hapax-secrets
5. officium-api.service      After: llm-stack, hapax-secrets
6. hapax-daimonion.service       After: pipewire, hapax-secrets (+10s delay for GPU sequencing)
7. hapax-imagination        After: hapax-secrets (GPU wgpu visual surface)
7a. hapax-reverie             After: hapax-secrets, hapax-dmn (visual expression daemon)
7b. hapax-content-resolver   After: logos-api (content resolution daemon)
7c. hapax-imagination-loop   After: hapax-secrets (imagination reverberation)
8. visual-layer-aggregator   After: logos-api, hapax-daimonion, hapax-secrets
9. studio-compositor         After: hapax-daimonion, visual-layer-aggregator (+10s for USB cameras)
10. studio-fx-output         After: studio-compositor
11. Timers activate          vram-watchdog (30s), health-monitor (15m), sync agents, backups,
                              rebuild-logos (5m), rebuild-services (5m)
```

## Secrets

Single centralized service (`hapax-secrets.service`) loads all credentials once at boot:

- `LITELLM_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` — API access
- `HF_TOKEN` — HuggingFace model downloads
- `LITELLM_BASE_URL`, `LANGFUSE_HOST` — service endpoints

Written to `/run/user/1000/hapax-secrets.env` (tmpfs, 0600). All services declare `Requires=hapax-secrets.service` and read via `EnvironmentFile=/run/user/1000/hapax-secrets.env`.

### Studio Mobile RTMP

`studio-compositor` supports a parallel 9:16 mobile RTMP egress. Runtime
mode defaults to `dual`; set `HAPAX_BROADCAST_MODE=desktop|mobile|dual` or
write `/dev/shm/hapax-compositor/broadcast-mode.json` through
`PATCH /api/studio/broadcast-mode`.

- `HAPAX_MOBILE_RTMP_URL` defaults to `rtmp://127.0.0.1:1935/mobile`.
- `HAPAX_MOBILE_RTMP_KEY` is optional and must come from `hapax-secrets` or
  another runtime-only secret source, never from repo config.

## Resource Isolation

**Per-service caps** (MemoryMax / OOMScoreAdjust):

| Service | MemoryMax | OOMScoreAdjust | Notes |
|---------|-----------|----------------|-------|
| hapax-daimonion | 16G | -500 | GPU STT models, grows under conversation load |
| studio-compositor | 6G | -800 | livestream critical |
| hapax-imagination | 4G | -800 | wgpu visual surface |
| hapax-rebuild-logos | 12G | default | transient cargo+rustc wgpu build |
| hapax-rebuild-services | 6G | default | transient python rebuild cascade |
| album-identifier | 4G | -800 | IR vision + audio track recognition |
| youtube-player | 2G | default | ffmpeg children |
| chat-monitor | 2G | -800 | YouTube Live chat analysis |
| logos-api | 1G | -800 | FastAPI :8051 |
| visual-layer-aggregator | 1G | -800 | perception pipeline |
| hapax-reverie | 1G | -800 | visual expression daemon |
| hapax-dmn | 1G | -800 | cognitive substrate |
| officium-api | 512M | -800 | FastAPI :8050 |
| hapax-content-resolver | 512M | -800 | content resolver |
| hapax-watch-receiver | 256M | -800 | Wear OS biometrics |
| hapax-recent-impingements | 128M | -800 | salience overlay producer |

**System-wide memory infrastructure:**

- **Swap topology**: zram (31G zstd, priority=100) as tier-1 + `/samples/swapfile` (32G, priority=5) as tier-2 backstop. Total 63G swap on 62G RAM.
- **Kernel reclaim tuning** (`/etc/sysctl.d/99-hapax-memory.conf`):
  - `vm.min_free_kbytes=524288` — 512MB allocation buffer (raised from default 66MB) to prevent cascade OOM under transient spikes
  - `vm.watermark_scale_factor=100` — kswapd reclaims at 1% pressure (default 10 is too late under zram+heavy-IO)
  - `vm.swappiness=150` — tuned for zram zstd compression
- **earlyoom** (`/etc/default/earlyoom`): fires SIGTERM @ 5% avail / 5% swap-free, SIGKILL @ 2.5%.
  - `--prefer`: `cargo|rustc|ld.lld|chrome|electron|node|claude|next-server|ffmpeg|bwrap` (expendable targets for OOM)
  - `--avoid`: `Hyprland|pipewire|wireplumber|dockerd|containerd|bluetoothd|systemd|foot|waybar|hapax-imagination|hapax-daimonion|studio-compositor|logos-api|officium-api` (stack protection)
- **System-level OOM overrides**: earlyoom (-1000), docker (-900), pipewire/wireplumber (-900).

**Design principle**: prevent global OOM by bounding the transient memory spikers (cargo builds, ffmpeg) and giving kernel reclaim a larger buffer. Critical stack services are additionally protected via `OOMScoreAdjust=-500/-800` so the kernel strongly prefers killing unbounded leaf processes (interactive Claude sessions, transient tools) over the stack in a true crisis. Interactive Claude sessions run in `session-N.scope` under `user-1000.slice` (not `user@1000.service`) and are intentionally left uncapped + unprotected — they are the designated sacrifice target.

## Ollama GPU Assignment

**Dual-GPU policy (2026-04-17):** Ollama runs on GPU 1 (5060 Ti, 16 GB); TabbyAPI runs exclusively on GPU 0 (3090, 24 GB). This replaces the earlier CPU-only isolation after the secondary GPU came online and the volitional-director rebalance freed the 3090 residency for Command-R 35B.

**Enforcement**: `/etc/systemd/system/ollama.service.d/z-gpu-5060ti.conf` sets `CUDA_VISIBLE_DEVICES=1`, `OLLAMA_NUM_GPU=999`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`. The `z-` prefix guarantees it is loaded last alphabetically, overriding the older `vram-optimize.conf` CPU-only settings. TabbyAPI's `config.yml` pins `gpu_split=[16, 10]` — TabbyAPI uses 16 GB on GPU 0 and 10 GB on GPU 1; Ollama uses the remaining ~6 GB on GPU 1. The two do not collide on GPU 0.

**Historical context**: LiteLLM previously had fallback chains (`local-fast → qwen3:8b`) that loaded Ollama's qwen3:8b on GPU 0 when TabbyAPI was slow. This caused a death spiral on the single-GPU era (qwen3:8b GPU 5.5 GiB + TabbyAPI 13 GiB = OOM on 24 GiB card; CPU fallback ate 900% CPU). Fallback chains were removed from `~/llm-stack/litellm-config.yaml`. The 5060 Ti installation + `z-gpu-5060ti.conf` pinning (2026-04-17) now make a repeat impossible: any GPU-capable Ollama model lands on GPU 1, which cannot collide with TabbyAPI's GPU 0 residency.

**Current Ollama role**: still embedding-heavy. `nomic-embed-cpu` (CPU-tagged, called directly by `shared/config.py:embed()`) is the only model typically loaded. `qwen3:8b` was deleted; `qwen3.5:27b` was deleted 2026-04-21 to eliminate the largest VRAM-splash risk. Steady-state Ollama VRAM footprint: ~256 MB (CUDA driver context only, no model weights). On-demand inference can load onto GPU 1's remaining ~6 GB.

**Embed frequency optimization** (PR #617): Startup capability indexing batched from 142 individual Ollama calls to 1 `embed_batch()` call, with a disk-persisted cache (`~/.cache/hapax/embed-cache.json`) that eliminates re-embedding across restarts. Second-and-subsequent daimonion startups index 142 capabilities with zero Ollama calls. Steady-state impingement embeds deduplicated by rendered narrative text (~50% reduction). See `shared/embed_cache.py`, `shared/affordance_pipeline.py:index_capabilities_batch()`.

## Installation

```bash
# Symlink all units from this directory (idempotent)
systemd/scripts/install-units.sh

# Or manually link a single unit
ln -sf "$PWD/systemd/units/my-service.service" ~/.config/systemd/user/
systemctl --user daemon-reload
```

**Units are symlinked, not copied.** Edits to `systemd/units/` take effect on `daemon-reload` without re-running the install script. The script covers `.service`, `.timer`, `.target`, and `.path` files.

`install-units.sh` also removes and masks retired units listed in its
`DECOMMISSIONED_UNITS` array if stale copies are present under
`~/.config/systemd/user/`. Currently retired:

- `hapax-logos.service`, `hapax-build-reload.path`,
  `hapax-build-reload.service`, `logos-dev.service` — Tauri/WebKit
  runtime, replaced by `hapax-imagination`.
- `tabbyapi-hermes8b.service` — second-instance TabbyAPI for the
  Hermes 3 8B parallel pivot. Operator abandoned Hermes 2026-04-15
  (drop #62 §14, commit `2bc6aec17`); the unit was retained as
  audit-trail reference until 2026-04-30 and never deployed (weights
  and config file referenced by the unit do not exist on disk).
  Cleanup also removes the linked `tabbyapi-hermes8b.service.d/`
  drop-in directory.
- `hapax-discord-webhook.service` — cross-surface Discord webhook
  poster for the `discord-webhook` publication-bus surface. Retired
  2026-05-01 per cc-task `discord-public-event-activation-or-retire`
  to close the constitutional drift between the existing
  `leverage-REFUSED-discord-community` refusal-brief (ratified
  2026-04-26) and the still-deployed FULL_AUTO surface entry. The
  agent module at `agents/cross_surface/discord_webhook.py` is
  retained as legacy reference; the surface is now `REFUSED` tier in
  `agents/publication_bus/surface_registry.py` so the orchestrator
  cannot reach it at runtime. The unit had been linked but never
  active (operator never bootstrapped `HAPAX_DISCORD_WEBHOOK_URL`).

**Newly installed timers are auto-enabled.** As of the audit-followups-e1 PR, `install-units.sh` runs `systemctl --user enable --now <name>.timer` for every timer file it sees for the first time. Existing timers are left alone (re-running is idempotent). To suppress this for a one-off install, set `SKIP_TIMER_ENABLE=1` before running the script (intentionally not a flag — disabling auto-enable is the rare case).

`systemd/user-preset.d/hapax.preset` mirrors the timers that must be enabled by default when preset tooling is used. Timer units still belong in `systemd/units/`; root-level `systemd/*.timer` files are not install-visible and should be moved into `systemd/units/`.

## Development

For development, stop systemd services and use process-compose:

```bash
systemctl --user stop logos-api hapax-daimonion visual-layer-aggregator studio-compositor
process-compose up           # TUI mode
process-compose attach       # attach to running instance
```

See `process-compose.yaml` (development only, not in boot chain).

## Auto-Rebuild on Main Advance

Two timers poll `origin/main` every 5 minutes and rebuild/restart services when relevant files change. Notifications go to ntfy topic `hapax-build` on `localhost:8090`.

### Rust Binaries (`hapax-rebuild-logos.timer`)

`scripts/rebuild-logos.sh` — compatibility timer name; fetches main, compares SHA to `~/.cache/hapax/rebuild/last-build-sha`, builds and installs only `hapax-imagination`, then restarts `hapax-imagination.service` if the running binary is stale. It intentionally does not build, install, or restart the decommissioned Tauri/WebKit `hapax-logos` runtime.

### Python Services (`hapax-rebuild-services.timer`)

`scripts/rebuild-service.sh` — generic script accepting `--repo`, `--service`, `--watch`, `--sha-key`, `--pull-only`. Checks if watched paths changed between last SHA and current `origin/main`. Only restarts the service if relevant files differ.

| Service | Repo | Watched Paths | SHA Key |
|---------|------|---------------|---------|
| `hapax-daimonion.service` | hapax-council | `agents/hapax_daimonion/` `shared/` | `voice` |
| `logos-api.service` | hapax-council | `logos/` | `logos-api` |
| `officium-api.service` | hapax-officium | (entire repo) | `officium` |
| hapax-mcp (pull-only) | hapax-mcp | (entire repo) | `hapax-mcp` |

SHA state files: `~/.cache/hapax/rebuild/last-{key}-sha`.

### Post-Merge Auto-Deploy (`hapax-post-merge-deploy.path`)

`scripts/hapax-post-merge-deploy` covers everything the python-services rebuild
cascade doesn't: systemd unit files, drop-ins, pipewire/wireplumber confs,
`scripts/hapax-*` symlinks, and helper watchdog binaries. Until 2026-05-03 it
was manual-only; the audit in `cc-task deploy-pipeline-canonical-worktree-isolation`
found 25 systemd units canonical-but-not-installed because nothing fired the
script after merges.

`hapax-post-merge-deploy.path` watches the canonical local main ref
(`/home/hapax/projects/hapax-council/.git/refs/heads/main`). When
`rebuild-service.sh` ff-merges `origin/main` into local main (or any other
caller advances the ref), the path unit fires `hapax-post-merge-deploy.service`,
which resolves the new HEAD SHA and invokes the script.

Loop-safety: the deploy script only writes to `~/.config/systemd/user/`,
`~/.config/pipewire/`, `~/.local/bin/`, and `~/.cache/hapax/post-merge-traces/`;
it never touches `.git/refs`. Belt-and-braces: `StartLimitIntervalSec=60` /
`StartLimitBurst=3` on the `[Unit]` section caps runaway fires. Failures route
through `OnFailure=notify-failure@%n.service`. Trace inspection is documented
at `docs/runbooks/post-merge-traces.md`.

Bootstrap: the path unit is canonical at `systemd/units/hapax-post-merge-deploy.path`;
the operator must `systemctl --user enable --now hapax-post-merge-deploy.path` once
after the deploy script's normal install step copies the units in place. From the
next merge onward the chain self-hosts.

## Storage Management

Two automated systems prevent disk exhaustion:

### Cache Cleanup (`cache-cleanup.timer` — weekly Sun 03:00)

Prunes reproducible caches: Docker build cache (168h+), dangling images, uv cache, pacman cache, stale worktree `.venv` dirs (7d+), leaked wav files in `/tmp` and `~/.cache/hapax/tmp-wav/`, Chrome crash reports, `__pycache__` (7d+), perception logs (7d), systemd journal (7d).

### Ryzen pin-glitch watchdog (`hapax-pin-check.timer` — every 120s)

The Ryzen HDA codec's pin multiplexer silently desynchronises from
PipeWire after a restart that enumerates a new USB audio device
(operator report 2026-04-20: S-4 plug-in). `pactl` reports the sink
RUNNING + unmuted but physical output stays silent until the card
profile is toggled off and back on.

`scripts/hapax-pin-check-probe.sh` (driven by `hapax-pin-check.timer`,
120s cadence) reads the sink's State + active-input count + monitor
RMS dB on every tick and hands the probe to `hapax-audio-topology
pin-check`. The CLI's stateful detector accumulates silent ticks in
`/run/user/$UID/hapax-pin-glitch-state.json`; when 5 s of sustained
RUNNING-but-silent crosses the threshold, `--auto-fix` invokes the
known-good recovery (`pactl set-card-profile … off → output:analog-stereo`).

Install:

```fish
install -m644 systemd/units/hapax-pin-check.service \
    ~/.config/systemd/user/hapax-pin-check.service
install -m644 systemd/units/hapax-pin-check.timer \
    ~/.config/systemd/user/hapax-pin-check.timer
systemctl --user daemon-reload
systemctl --user enable --now hapax-pin-check.timer
```

Override defaults via env (typically in `~/.config/environment.d/`):
`HAPAX_PIN_CHECK_SINK`, `HAPAX_PIN_CHECK_CARD`, `HAPAX_PIN_CHECK_PROFILE`,
`HAPAX_PIN_CHECK_AUTO_FIX` (default 1), `HAPAX_PIN_CHECK_CAPTURE_S` (0.5).

Detection module: `shared/audio_pin_glitch.py`. CLI subcommand:
`scripts/hapax-audio-topology pin-check`. Memory:
`reference_ryzen_codec_pin_glitch`.

### Webcam USB-audio suppression (cc-task audio-audit-O1)

All council webcams (Logitech BRIO `046d:085e`, C920 PRO `046d:08e5`, C920 HD
Pro `046d:082d`) expose a USB-audio interface that the studio never uses —
video is ingested via V4L2 only and the operator's mic chain is the Studio
24c plus the Cortado MKIII contact mic. Auditor A (audit-2026-05-02 finding
#9) flagged the unused `alsa_card.usb-…Logi` cards as an xhci-jitter and
USB-isoc-bandwidth tax (overlaps with O3b territory).

Suppression is via `config/udev/rules.d/56-hapax-webcam-audio-suppress.rules`,
which scopes `ENV{PULSE_IGNORE}=1` to `bInterfaceClass==01` (USB-Audio
class) only — the video interface (class `0e`) is untouched, so studio-
compositor V4L2 ingest is unaffected. Each rule line carries an
`ENV{ID_HAPAX_AUDIO_SUPPRESSED}` marker (`brio`, `c920-pro`, `c920-hd-pro`)
so `udevadm info /dev/...` reports which device a suppression came from.

Install: `bash scripts/install-webcam-audio-suppress-udev.sh` (sudo). Verify
with `pactl list cards short | grep -i 'alsa_card\.usb.*Logi'` — empty output
means the rule is live. Regression pin: `tests/scripts/test_webcam_audio_suppress_udev.py`.

### CLAUDE.md Audit (`claude-md-audit.timer` — monthly)

Runs `scripts/monthly-claude-md-audit.sh` on a monthly cadence. Sweeps every workspace CLAUDE.md (council beta worktree + sibling repos + workspace root + dotfiles symlinks) through `check-claude-md-rot.sh` (default + `--strict`) and `check-vscode-sister-extensions.sh`. Posts to ntfy on findings; silent on success. Operator can run by hand at any time. Spec: `docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`.

### Backups (two tiers)

| Tier | Timer | Destination | Tool |
|------|-------|-------------|------|
| Local | `hapax-backup-local.timer` daily 03:00 | `/store/hapax-backups/restic` | restic |
| Remote | `hapax-backup-remote.timer` Wed 04:00 | `rclone:b2:hapax-backups/restic` | restic + rclone → Backblaze B2 |

Both tiers back up: PostgreSQL dumps, Qdrant snapshots, n8n workflows, Docker volume metadata, git bundles, systemd configs, user configs, LLM stack, system files.

Secrets: local password in `pass show backups/restic-password`, remote in `pass show backblaze/restic-password`.

### Minio Object Lifecycle

Langfuse writes trace events and media to the `langfuse` minio bucket on `/data`. Without a lifecycle policy, objects accumulate indefinitely and can exhaust ext4 inodes (21M+ objects observed in April 2026 incident, causing ENOSPC on `/data` which broke backups and all services writing to that partition).

**Prevention:** A 14-day lifecycle rule is configured on the `events/` prefix:

```bash
docker exec minio mc alias set L http://localhost:9000 minioadmin minioadmin
docker exec minio mc ilm rule list L/langfuse   # verify
docker exec minio mc ilm rule add L/langfuse --prefix "events/" --expire-days 14  # recreate if needed
```

Trace metadata survives in ClickHouse/Postgres — only raw event blobs expire. Monitor inode usage: `df -i /data`.

### Known Leak Sources

- **album-identifier pw-cat**: The album identifier records audio clips via `pw-cat` to `/tmp/*.wav` for Shazam-style fingerprinting. Fixed (commit `6c58ca75b`) to use `finally` cleanup. Previously leaked orphan wavs on every early-return path, filling `/tmp` (32G tmpfs) within hours. `tmp-monitor.timer` (5-min) acts as a safety net, deleting wav/raw/pcm files older than 5 min.
- **pacat --record**: Voice daemon's audio capture backends spawn `pacat` subprocesses that can orphan on crash/OOM. Each writes an unbounded WAV file (~7GB before detection). Mitigated by cache-cleanup.
- **Claude Code task output**: Background task output in `/tmp/claude-1000/` can grow unbounded. Not automatically cleaned — monitor `/tmp` usage.

## Disabled Services (archival pipeline)

The following services and timers are disabled (2026-03-27). They supported 24/7 audio/video recording, classification, and RAG ingestion — purely archival with no live consumers. The live perception and effects pipeline (compositor, VLA, fx, person detector) is unaffected as it captures directly from cameras and PipeWire.

**LRR Phase 2 item 1 scope (2026-04-15):** the archival pipeline is partially re-enabled under the *archive-as-research-instrument* framing per `docs/superpowers/specs/2026-04-15-lrr-phase-2-archive-research-instrument-design.md` §3.1 + §4 decision 3. Scope is narrowed to **audio recording only** — classification, cross-modal correlation, and RAG ingest remain disabled and are deferred to LRR Phase 5+.

| Unit | Purpose | LRR Phase 2 scope | Re-enable with |
|------|---------|-------------------|----------------|
| `audio-recorder.service` | Blue Yeti → FLAC archival | **in-scope (Phase 2 item 1)** | `systemctl --user enable --now audio-recorder` |
| `contact-mic-recorder.service` | Cortado → FLAC archival | **in-scope (Phase 2 item 1)** | `systemctl --user enable --now contact-mic-recorder` |
| `rag-ingest.service` | Document watchdog → Qdrant | DEFERRED to Phase 5+ (§4 decision 3) | `systemctl --user enable --now rag-ingest` |
| `audio-processor.timer` | FLAC classify → RAG docs | DEFERRED to Phase 5+ (classification) | `systemctl --user enable --now audio-processor.timer` |
| `video-processor.timer` | MKV classify → sidecars | DEFERRED to Phase 5+ (classification) | `systemctl --user enable --now video-processor.timer` |
| `av-correlator.timer` | Cross-modal → studio_moments | DEFERRED to Phase 5+ (cross-modal) | `systemctl --user enable --now av-correlator.timer` |
| `flow-journal.timer` | Flow transitions → RAG docs | DEFERRED to Phase 5+ (RAG) | `systemctl --user enable --now flow-journal.timer` |
| `video-retention.timer` | Prune old MKV segments | DEFERRED to Phase 5+ (retention policy TBD) | `systemctl --user enable --now video-retention.timer` |

### LRR Phase 2 item 1 activation — operator runs manually

The two in-scope services (`audio-recorder`, `contact-mic-recorder`) are **ratified for re-enablement but NOT auto-enabled by this commit**. Starting audio recording is an operational change against live hardware (Blue Yeti + Cortado MKIII contact mic) that should happen under operator consent in a moment of the operator's choosing, not at merge time.

Operator activation sequence after this commit merges:

```bash
# Pre-check — hardware available, disk has headroom for FLAC at ~1.4 GB/day per mic
pactl list short sources | grep -E 'Yeti|Contact'
df -h ~/audio-recording

# Enable + start the two in-scope services
systemctl --user enable --now audio-recorder.service
systemctl --user enable --now contact-mic-recorder.service

# Verify each starts cleanly
systemctl --user status audio-recorder.service contact-mic-recorder.service

# Watch the first FLAC segment land
ls -lt ~/audio-recording/raw/ | head -5
journalctl --user -u audio-recorder.service -n 30
journalctl --user -u contact-mic-recorder.service -n 30
```

Rollback if either service fails its first run:

```bash
systemctl --user disable --now audio-recorder.service
systemctl --user disable --now contact-mic-recorder.service
```

The 6 DEFERRED services (classification, cross-modal, RAG, retention) remain untouched by LRR Phase 2. They re-enable under a future LRR Phase 5+ decision after the classifier model, Qdrant cardinality budget, and retention policy decisions land.

## Recovery

The system is configured for 24/7 unattended operation:

- **Kernel panic** → auto-reboot in 10s (`kernel.panic=10`, `softlockup_panic=1`, `hung_task_panic=1`)
- **systemd hang** → hardware watchdog reset in 30s (SP5100 TCO, `RuntimeWatchdogSec=30`)
- **Shutdown hang** → hardware watchdog reset in 10min (`RebootWatchdogSec=10min`)
- **Display manager** → greetd autologin (no password prompt)
- **User services** → lingering enabled, all services start at boot without login
- **Docker containers** → `restart: always` on all 13 containers
- **Service crash** → `Restart=always` or `Restart=on-failure` with rate limiting
- **Journal persistence** → `SyncIntervalSec=15s`, `ForwardToKMsg=yes`, pstore for crash dumps

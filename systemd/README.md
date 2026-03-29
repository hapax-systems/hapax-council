# systemd Service Management

All production services run as systemd user units under `user@1000.service` with lingering enabled. No process supervisors (process-compose, supervisord) in the boot chain.

## Directory Structure

```
systemd/
├── units/              Service and timer unit files (source of truth)
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
prometheus, clickhouse,             hapax-voice       → voice daemon (GPU)
n8n, open-webui, minio, ntfy       hapax-logos       → Tauri native app (GPU)
                                    visual-layer-agg  → perception pipeline
                                    studio-compositor → camera tiling (GPU)
Managed by:                         studio-fx-output  → ffmpeg /dev/video50
  llm-stack.service (oneshot)       hapax-watch-recv  → Wear OS biometrics
  llm-stack-analytics.service       31 timers         → sync, health, backups
```

## Boot Sequence

```
1. hapax-secrets.service     Load credentials from pass store → /run/user/1000/hapax-secrets.env
2. llm-stack.service         docker compose --profile full up -d (waits 30s for Docker daemon)
3. llm-stack-analytics       docker compose --profile analytics up -d (60s after llm-stack)
4. logos-api.service         After: llm-stack, hapax-secrets
5. officium-api.service      After: llm-stack, hapax-secrets
6. hapax-voice.service       After: pipewire, hapax-secrets (+10s delay for GPU sequencing)
7. hapax-logos.service        After: graphical-session, logos-api (__NV_DISABLE_EXPLICIT_SYNC=1)
8. visual-layer-aggregator   After: logos-api, hapax-voice, hapax-secrets
9. studio-compositor         After: hapax-voice, visual-layer-aggregator (+10s for USB cameras)
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

## Resource Isolation

| Service | MemoryMax | OOMScoreAdjust | Nice | CPUWeight |
|---------|-----------|----------------|------|-----------|
| hapax-voice | 8G | -500 | -10 | default |
| hapax-logos | 4G | default | default | default |
| studio-compositor | 4G | default | default | 500 |
| visual-layer-aggregator | 1G | default | default | default |
| logos-api | 1G | default | default | default |
| officium-api | 512M | default | default | default |
| studio-fx-output | 512M | default | 10 | default |
| hapax-watch-receiver | 256M | default | default | default |

System-level OOM overrides: earlyoom (-1000), docker (-900), pipewire/wireplumber (-900), ollama (-500).

## Installation

```bash
# Install/update all units from this directory
systemd/scripts/install-units.sh

# Or manually link a single unit
systemctl --user link "$PWD/systemd/units/my-service.service"
systemctl --user enable my-service.service
systemctl --user daemon-reload
```

## Development

For development, stop systemd services and use process-compose:

```bash
systemctl --user stop logos-api hapax-voice visual-layer-aggregator studio-compositor
process-compose up           # TUI mode
process-compose attach       # attach to running instance
```

See `process-compose.yaml` (development only, not in boot chain).

## Auto-Rebuild on Main Advance

Two timers poll `origin/main` every 5 minutes and rebuild/restart services when relevant files change. Notifications go to ntfy topic `hapax-build` on `localhost:8090`.

### Rust Binaries (`hapax-rebuild-logos.timer`)

`scripts/rebuild-logos.sh` — fetches main, compares SHA to `~/.cache/hapax/rebuild/last-build-sha`, runs `cargo build --release` for hapax-logos and hapax-imagination, copies binaries to `~/.local/bin/`, restarts `hapax-imagination.service`.

### Python Services (`hapax-rebuild-services.timer`)

`scripts/rebuild-service.sh` — generic script accepting `--repo`, `--service`, `--watch`, `--sha-key`, `--pull-only`. Checks if watched paths changed between last SHA and current `origin/main`. Only restarts the service if relevant files differ.

| Service | Repo | Watched Paths | SHA Key |
|---------|------|---------------|---------|
| `hapax-voice.service` | hapax-council | `agents/hapax_voice/` `shared/` | `voice` |
| `logos-api.service` | hapax-council | `logos/` | `logos-api` |
| `officium-api.service` | hapax-officium | (entire repo) | `officium` |
| hapax-mcp (pull-only) | hapax-mcp | (entire repo) | `hapax-mcp` |

SHA state files: `~/.cache/hapax/rebuild/last-{key}-sha`.

## Storage Management

Two automated systems prevent disk exhaustion:

### Cache Cleanup (`cache-cleanup.timer` — weekly Sun 03:00)

Prunes reproducible caches: Docker build cache (168h+), dangling images, uv cache, pacman cache, stale worktree `.venv` dirs (7d+), leaked wav files in `/tmp` and `~/.cache/hapax/tmp-wav/`, Chrome crash reports, `__pycache__` (7d+), perception logs (7d), systemd journal (7d).

### Backups (two tiers)

| Tier | Timer | Destination | Tool |
|------|-------|-------------|------|
| Local | `hapax-backup-local.timer` daily 03:00 | `/data/backups/restic` | restic |
| Remote | `hapax-backup-remote.timer` Wed 04:00 | `rclone:b2:hapax-backups/restic` | restic + rclone → Backblaze B2 |

Both tiers back up: PostgreSQL dumps, Qdrant snapshots, n8n workflows, Docker volume metadata, git bundles, systemd configs, user configs, LLM stack, system files.

Secrets: local password in `pass show backups/restic-password`, remote in `pass show backblaze/restic-password`.

### Known Leak Sources

- **pacat --record**: Voice daemon's audio capture backends spawn `pacat` subprocesses that can orphan on crash/OOM. Each writes an unbounded WAV file (~7GB before detection). Mitigated by cache-cleanup.
- **Claude Code task output**: Background task output in `/tmp/claude-1000/` can grow unbounded. Not automatically cleaned — monitor `/tmp` usage.

## Disabled Services (archival pipeline)

The following services and timers are disabled (2026-03-27). They supported 24/7 audio/video recording, classification, and RAG ingestion — purely archival with no live consumers. The live perception and effects pipeline (compositor, VLA, fx, person detector) is unaffected as it captures directly from cameras and PipeWire.

| Unit | Purpose | Re-enable with |
|------|---------|---------------|
| `audio-recorder.service` | Blue Yeti → FLAC archival | `systemctl --user enable --now audio-recorder` |
| `contact-mic-recorder.service` | Cortado → FLAC archival | `systemctl --user enable --now contact-mic-recorder` |
| `rag-ingest.service` | Document watchdog → Qdrant | `systemctl --user enable --now rag-ingest` |
| `audio-processor.timer` | FLAC classify → RAG docs | `systemctl --user enable --now audio-processor.timer` |
| `video-processor.timer` | MKV classify → sidecars | `systemctl --user enable --now video-processor.timer` |
| `av-correlator.timer` | Cross-modal → studio_moments | `systemctl --user enable --now av-correlator.timer` |
| `flow-journal.timer` | Flow transitions → RAG docs | `systemctl --user enable --now flow-journal.timer` |
| `video-retention.timer` | Prune old MKV segments | `systemctl --user enable --now video-retention.timer` |

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

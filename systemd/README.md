# systemd Service Management

Application and utility services run as systemd user units under `user@1000.service` with lingering enabled. Narrow host-safety units, including the root OOM enforcer and its failure-intake bridge, run in the system manager. No process supervisors (process-compose, supervisord) are in the boot chain.

**Topology:** <!-- topology-inventory:services -->301<!-- /topology-inventory:services --> services, <!-- topology-inventory:timers -->147<!-- /topology-inventory:timers --> timers, 6 paths, 3 targets. Verify with `uv run python scripts/hapax_topology_inventory.py --check`.

`scripts/hapax_topology_inventory.py` is source-only: it verifies the
git-tracked `systemd/units/` topology and does not prove what the live user
manager has loaded or enabled. For runtime reconciliation, use:

```bash
uv run python scripts/hapax-systemd-inventory-reconcile --summary
uv run python scripts/hapax-systemd-inventory-reconcile --json
```

The reconciler is read-only. It compares `git ls-files systemd/units` with
`systemctl --user list-unit-files --type=service,timer` and
`systemctl --user list-units --all --type=service,timer`, then reports matched,
tracked-only, and runtime-only units with the exact commands and timestamp.
Do not use source topology counts as claims about active runtime state.

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
  llm-stack-analytics.service       147 timers        → sync, health, backups
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
| album-identifier | 4G | default | IR vision + audio track recognition |
| youtube-player | 2G | default | ffmpeg children |
| chat-monitor | 2G | default | YouTube Live chat analysis |
| logos-api | 1G | default | FastAPI :8051 |
| visual-layer-aggregator | 1G | default | perception pipeline |
| hapax-reverie | 1G | default | visual expression daemon |
| hapax-dmn | 1G | default | cognitive substrate |
| officium-api | 512M | default | FastAPI :8050 |
| hapax-content-resolver | 512M | default | content resolver |
| hapax-watch-receiver | 256M | default | Wear OS biometrics |
| hapax-recent-impingements | 128M | -800 | salience overlay producer |
| stimmung-sync | 2G | default | MemoryHigh=1G; role-specific source ceiling after 2026-05-13 `CONSTRAINT_MEMCG` evidence |

**System-wide memory infrastructure:**

- **128GB host memory policy**: the retired 62G RAM / 63G swap inventory is
  not current source truth for this host. Runtime zram/swap sizing must be
  verified from a read-only host receipt before any zram-generator or swapfile
  change; source policy currently treats zram saturation, global RAM pressure,
  and service-local cgroup OOMs as separate incident classes.
- **Kernel reclaim tuning** (`/etc/sysctl.d/99-hapax-memory.conf`):
  - `vm.min_free_kbytes=524288` — 512MB allocation buffer (raised from default 66MB) to prevent cascade OOM under transient spikes
  - `vm.watermark_scale_factor=100` — kswapd reclaims at 1% pressure (default 10 is too late under zram+heavy-IO)
  - `vm.swappiness=5` — tuned for 128GB RAM with audio/livestream workload (low swap preference)
- **`stimmung-sync.service` ceiling rationale**: the 2026-05-13 incident was
  service-local cgroup pressure, not global RAM exhaustion: `stimmung-sync` was
  killed under `CONSTRAINT_MEMCG` at the old 128M hard ceiling while the host
  still had tens of GiB available. A runtime mitigation completed at 56.9M
  peak with a 512M hard ceiling; source now keeps this periodic RAG/state sync
  job at `MemoryHigh=1G` and `MemoryMax=2G` to absorb Python import,
  embedding, and persistence bursts while remaining bounded. This is not a
  blanket limit increase for 128M utility timers.
- **earlyoom** (`/etc/default/earlyoom`, source: `config/earlyoom/default`): fires SIGTERM @ 5% avail / 5% swap-free, SIGKILL @ 2.5%.
  - `--prefer`: `cargo|rustc|ld.lld|chrome|electron|node|claude|next-server|ffmpeg|bwrap` (expendable targets for OOM)
  - `--avoid`: `Hyprland|pipewire|wireplumber|dockerd|containerd|bluetoothd|systemd|foot|waybar|hapax-imaginati` (best-effort process-comm matching; `hapax-imaginati` is the live-observed `/proc/<pid>/comm` 15-byte truncation. Python-hosted daimonion and currently inactive services are not represented by speculative unit-name tokens; the explicitly enumerated protected units below receive separate memory reservations and root-enforced live OOM scores.)
  - `--ignore`: `apcupsd|systemd-logind|systemd-resolve|systemd-timesyn|systemd-userdbd|dbus-broker|dbus-daemon|NetworkManager|sshd|sshd-session|getty|agetty` (operator recovery and UPS telemetry must not be earlyoom victims; long names use `/proc/<pid>/comm` 15-byte truncation)
- **P0 OOM containment package** (`scripts/install-p0-oom-containment`): installs source-controlled recovery policy into `/etc/default/earlyoom`, `/etc/systemd/system/*.service.d/oom-protect.conf`, `/etc/systemd/system/system.slice.d/oom-containment.conf`, `/etc/systemd/system/user.slice.d/oom-containment.conf`, `/etc/systemd/system/user-1000.slice.d/oom-containment.conf`, `/etc/systemd/system/user@1000.service.d/oom.conf`, `~/.config/systemd/user/app.slice.d/oom-containment.conf`, and the root-side `hapax-oom-score-enforce` service/timer plus the activation-independent `hapax-root-failure-intake@.service` bridge. It also installs `hapax-oom-policy-audit` and `hapax-root-required-deploy-audit` under `/usr/local/sbin` and copies their user services/timers into `~/.config/systemd/user`, so recurring safety audits do not depend on a mutable source-activation alias. This podium package is intentionally bound to account `hapax`, UID 1000, and the corresponding fixed system-unit names; target environment overrides support tests and state-path recovery but do not make the installed unit graph portable to another account.
  - `user.slice`: `MemoryLow=16G` and `MemoryMin=8G`, with `MemoryHigh`, `MemoryMax`, and `MemorySwapMax` explicitly `infinity`, allocates protection at the required ancestor so descendant UID, manager, app, and leaf reservations are effective.
  - `user-1000.slice` and `user@1000.service`: `MemoryHigh=80G`, `MemoryMax=96G`, `MemorySwapMax=8G`, `MemoryLow=16G`, `MemoryMin=8G`; `user@1000.service` also carries `OOMScoreAdjust=100`, restoring the packaged kill ordering so the whole user manager does not shield every interactive workload, and explicit `OOMPolicy=continue`, so an OOM kill in a descendant cgroup does not stop the manager and every visible session. The UID-level cap covers both `app.slice` and sibling session scopes, so an app runaway plus a long-lived interactive session cannot recreate the host-wide memory collapse.
  - `system.slice`: `MemoryLow=24G` and `MemoryMin=12G`, with `MemoryHigh`, `MemoryMax`, and `MemorySwapMax` explicitly `infinity`, reciprocally reserve the measured recovery-plane footprint. The recurring audit checks all five properties so a finite recovery-plane hard ceiling cannot hide. At the 2026-07-09 recurrence review it used 24.6 GiB and had peaked at 28.8 GiB.
  - Recovery daemons: apcupsd (`-900`), systemd-logind/resolved/timesyncd/NetworkManager (`-800`), and D-Bus (`-900`). `sshd` stays at `OOMScoreAdjust=0` with `OOMPolicy=continue`, so interactive children do not inherit OOM immunity while loss of one session does not stop the recovery daemon. Install verification and the recurring OOM audit require every recovery daemon to have a live main PID, compare each effective loaded `OOMScoreAdjust` with that PID's live `oom_score_adj`, and require effective SSH `OOMPolicy=continue`. The installer writes running main PIDs without restarting login/network.
  - Broadcast-critical user services: pipewire/pipewire-pulse/wireplumber (live target `-900`), hapax-daimonion (`-500`), studio-compositor (`-800`), and hapax-imagination (`-800`) carry source-controlled memory reservations and an explicit valid startup `OOMScoreAdjust=100`. An unprivileged user manager cannot lower a child below its own score, so encoding the negative live target as the unit property is ineffective. Each drop-in instead runs a fail-open `ExecStartPost=` call through passwordless `sudo -n` to the allowlisted root helper's `--apply-unit %n` mode; that startup mode resolves the unit's authoritative cgroup and lowers its stable `MainPID` without enumerating the helper's own short-lived descendants. The system timer repeats the full cgroup-PID enforcement pass every 30 seconds for later children and repair fallback. `After=user@1000.service` only orders a transaction that already contains both units; non-resurrection is provided by the helper's explicit active-manager guard, which exits successfully when the manager is intentionally stopped.
  - Root enforcer failures are accumulated across all attempted PIDs, returned nonzero after the full pass, and routed to `/usr/local/sbin/hapax-root-failure-intake`. That helper calls the stable D2 recovery bundle under `~/.local/lib/hapax-recovery/council/current` and records an emergency JSONL fallback if the bundle is missing. The failure bridge admits at most one start per hour, preventing a persistent 30-second enforcer failure from creating an incident storm while leaving successful timer runs unrestricted.
  - `app.slice`: `MemoryHigh=72G`, `MemoryMax=88G`, `MemorySwapMax=8G`, `MemoryLow=16G`, `MemoryMin=8G` as an aggregate user-app RAM/swap backstop for units under app.slice; broadcast-critical app.slice members carry per-unit `MemoryLow`/`MemoryMin` reservations so reclaim pressure lands on agent/browser runaways first. Live activation uses `systemctl --user set-property --runtime` and must not restart the slice. New transient `tmux-spawn-*` scopes outside app.slice fail the audit until their launcher supplies per-scope bounds; the audit reads `Slice=` before treating an unbounded scope as app-slice-backed.
  - `MemoryMax=88G` on app.slice is the app-workload hard stop; `MemoryMax=96G` on `user-1000.slice` is the UID-level stop that includes sibling session scopes. Podium has `134152699904` bytes of RAM by `free -b`, so the UID cap leaves roughly 29 GiB outside UID 1000 while `MemoryHigh=72G`/`80G` starts reclaim earlier and `MemorySwapMax=8G` prevents the 33 GiB swap exhaustion recorded in the incident.
  - Recheck: `scripts/install-p0-oom-containment --check`, `scripts/install-p0-oom-containment --verify-live`, `/usr/local/sbin/hapax-oom-policy-audit --json`, `systemctl show user@1000.service -p OOMScoreAdjust -p OOMPolicy -p MainPID`, `systemctl is-enabled hapax-oom-score-enforce.timer earlyoom.service`, `systemctl is-active hapax-oom-score-enforce.timer earlyoom.service`, and `systemctl show hapax-oom-score-enforce.service -p Result -p ExecMainStartTimestamp`. Also require `systemctl --user is-enabled hapax-oom-policy-audit.timer hapax-root-required-deploy-audit.timer` and `systemctl --user is-active hapax-oom-policy-audit.timer hapax-root-required-deploy-audit.timer`. Inspect recurrence state with `jq . ~/.cache/hapax/p0-incident-intake/state.json` and `tail -n 20 ~/.cache/hapax/p0-incident-intake/events.jsonl`.
  - Root-required post-merge installers return rc `77` when non-interactive sudo is unavailable; `hapax-post-merge-deploy` derives each package trigger set from the versioned ownership manifests on both sides of the deployed diff and atomically stages reconstructible packages at `~/.cache/hapax/post-merge-root-required/<sha>/`, while desired SHAs, installed source snapshots, installed SHA receipts, and the shared lock live durably under `~/.local/state/hapax/root-required/`. The desired SHA is recorded before each install attempt, so loss of a cached RUNBOOK remains audit-failing until that desired package is installed. Desired transitions are monotonic under the shared lock: post-merge and both installers preserve a newer desired descendant, accept a newer candidate, and accept an ancestry-divergent squash/rebase transition only when both versioned ownership manifests are identical and every owned package file is byte-identical. Every install, including a direct repair from a clean worktree, verifies the candidate against both installed and desired receipts, its versioned manifest, and every owned source file before live mutation; `--install` always performs live verification before installed-source snapshots or receipts advance. A manifest may add owned paths, but removing or renaming an installed path fails before mutation until explicit governed live-removal handling exists. The recurring audit takes the shared lock, requires desired and installed SHAs to agree, binds each installed snapshot back to its receipt commit without a source-activation fallback, rejects symlinked snapshots or live artifacts, and enforces exact `0644`/`0755` installer modes. Installers default commit lookup to the stable source-activation worktree rather than a developer worktree. Run each staged RUNBOOK command after `sudo -v`; a successful or superseded installer marks only the exact validated `<sha>/<package>` source drained by renaming `RUNBOOK.txt` to `DRAINED.txt`, never deleting its own execution tree. A missing receipt/snapshot or non-equivalent divergent, modified, or unverifiable package fails closed. Post-merge deployment never republishes installed source after the owning installer releases its lock and never bulk-deletes deferrals from other SHAs.
- **Other system-level OOM overrides**: docker (-900), pipewire/wireplumber (-900), and hardware/service-specific drop-ins documented beside their installers.
- **UPS power-alert provenance** (`scripts/install-apcupsd-power-alerts`): installs the apcupsd config/hooks/helper into `/etc/apcupsd`, hard-codes production hooks to `/etc/apcupsd/hapax-power-event.py`, installs `/etc/logrotate.d/hapax-ups-power-events` for `/var/log/hapax/ups-power-events.jsonl`, and enables/starts `apcupsd.service` so the sole shutdown-policy owner survives reboot; live verification requires both enabled and active state. The logrotate stanza uses `su root root` because `/var/log/hapax` is group-writable for local audit writers. Battery-transfer receipts say only that the transfer event itself does not request shutdown (`event_requests_shutdown=false`), while global `shutdown_requested` remains unknown; restoration receipts are also neutral because either event can follow a real `doshutdown`. All three hooks fail open so telemetry failure cannot suppress or indefinitely delay apccontrol: `onbattery` and `offbattery` have a hard ten-second whole-helper deadline, while the dedicated `doshutdown` hook has a hard three-second deadline and attempts to record both shutdown fields as true. A blocked helper may therefore complete without a receipt. On the shutdown path, apcaccess and ntfy also have one-second internal ceilings.
  - `apcupsd` is the sole UPS shutdown-policy owner. `/etc/UPower/UPower.conf.d/90-hapax-apcupsd-owner.conf` keeps UPower available for status/history while pinning its critical action to `Ignore`; every normal install reloads both daemons even when files already match. Live installation and the recurring root audit require UPower's D-Bus `GetCriticalAction` value to be `Ignore` and compare apcupsd's loaded `MBATTCHG`, `MINTIMEL`, and `MAXTIME` values against source `BATTERYLEVEL`, `MINUTES`, and `TIMEOUT` before receipts can advance. apcupsd retains the configured 20% charge / 5-minute runtime shutdown thresholds.
  - Recheck: `scripts/install-apcupsd-power-alerts --check` and `scripts/install-apcupsd-power-alerts --verify-live`; use `scripts/install-apcupsd-power-alerts --install --verify-live` to repair live drift. Root invocation resolves podium UID 1000's home/group and returns durable state ownership to `hapax`; target overrides support tests and state-path recovery, not a portable alternate-account installation.

**Runtime application / receipt path:** source changes in this directory are
not host mutation authority. A runtime-authorized follow-on task must first
record a read-only receipt:

- `free -h`
- `zramctl --raw --output NAME,DISKSIZE,DATA,COMPR,ALGORITHM,PRIO`
- `cat /proc/swaps`
- `cat /proc/sys/vm/swappiness`
- `systemctl --user show stimmung-sync.service -p MemoryHigh -p MemoryMax -p MemoryPeak -p NRestarts -p ActiveState -p Result --no-pager`

Only that separate runtime path may perform sysctl writes, zram-generator
changes, daemon reloads, unit installation, or service restarts.

**Design principle**: prevent global OOM by bounding transient memory spikers (cargo builds, ffmpeg) and giving kernel reclaim a larger buffer. Critical stack services are additionally protected via `OOMScoreAdjust=-500/-800` so the kernel strongly prefers killing leaf processes (interactive agent sessions, transient tools) over the stack in a true crisis. Individual `session-N.scope` leaves may have no local limit, but they remain killable and are covered by the aggregate `user-1000.slice` hard ceiling.

## Ollama GPU Assignment

**Dual-GPU policy (2026-04-17):** Ollama runs on GPU 1 (5060 Ti, 16 GB); TabbyAPI runs exclusively on GPU 0 (3090, 24 GB). This replaces the earlier CPU-only isolation after the secondary GPU came online and the volitional-director rebalance freed the 3090 residency for Command-R 35B.

**Enforcement**: `/etc/systemd/system/ollama.service.d/z-gpu-5060ti.conf` sets `CUDA_VISIBLE_DEVICES=1`, `OLLAMA_NUM_GPU=999`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`. The `z-` prefix guarantees it is loaded last alphabetically, overriding the older `vram-optimize.conf` CPU-only settings. TabbyAPI's `config.yml` pins `gpu_split=[16, 10]` — TabbyAPI uses 16 GB on GPU 0 and 10 GB on GPU 1; Ollama uses the remaining ~6 GB on GPU 1. The two do not collide on GPU 0.

**Historical context**: LiteLLM previously had fallback chains (`local-fast → qwen3:8b`) that loaded Ollama's qwen3:8b on GPU 0 when TabbyAPI was slow. This caused a death spiral on the single-GPU era (qwen3:8b GPU 5.5 GiB + TabbyAPI 13 GiB = OOM on 24 GiB card; CPU fallback ate 900% CPU). Fallback chains were removed from `~/llm-stack/litellm-config.yaml`. The 5060 Ti installation + `z-gpu-5060ti.conf` pinning (2026-04-17) now make a repeat impossible: any GPU-capable Ollama model lands on GPU 1, which cannot collide with TabbyAPI's GPU 0 residency.

**Current Ollama role**: still embedding-heavy. `nomic-embed-cpu` is the stable Hapax alias called directly by `shared/config.py:embed()`; after the 2026-05-12 Nomic repair it aliases `nomic-embed-text-v2-moe:latest` (`nomic-bert-moe`, 768-dimensional embeddings, 512-token context). The alias name is historical and does not prove CPU-only execution: the active service is pinned to GPU 1 by `z-gpu-5060ti.conf`, and Ollama scheduling may use that GPU when it loads model weights. `qwen3:8b` was deleted; `qwen3.5:27b` was deleted 2026-04-21 to eliminate the largest VRAM-splash risk. Steady-state Ollama VRAM footprint is expected to be CUDA driver context only when no model weights are loaded. On-demand inference can load onto GPU 1's remaining memory.

**Embed frequency optimization** (PR #617): Startup capability indexing batched from 142 individual Ollama calls to 1 `embed_batch()` call, with a disk-persisted cache (`~/.cache/hapax/embed-cache.json`) that eliminates re-embedding across restarts. Second-and-subsequent daimonion startups index 142 capabilities with zero Ollama calls. Steady-state impingement embeds deduplicated by rendered narrative text (~50% reduction). See `shared/embed_cache.py`, `shared/affordance_pipeline.py:index_capabilities_batch()`.

## Installation

```bash
# Install/symlink all user units and drop-ins from this directory (idempotent)
systemd/scripts/install-units.sh

# Or manually link a single unit
ln -sf "$PWD/systemd/units/my-service.service" ~/.config/systemd/user/
systemctl --user daemon-reload
```

Top-level user `.service`, `.timer`, `.target`, `.path`, and `.slice`
units are normally symlinked, so edits to `systemd/units/` take effect on
`daemon-reload` without re-running the install script. `install-units.sh`
also installs drop-ins under `.service.d`, `.timer.d`, `.slice.d`, and
`.scope.d`; ordinary drop-ins are symlinked, while P0 host-safety OOM
drop-ins and the two recurring P0 audit service/timer pairs are skipped because
only `scripts/install-p0-oom-containment` may copy them from a governed staged
source. System-scoped units marked
`# Hapax-Install-Scope: system` require their dedicated installer or a
root-required post-merge deploy path.

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
- `hapax-environmental-emphasis.service`, `hapax-environmental-emphasis.timer`
    — continuous-loop emphasis timer driver and its companion timer.
    Unit files and the `scripts/environmental_emphasis_tick.py` script were
    removed from the repo; stale symlinks discovered 2026-05-14 pointing to
    the deleted paths.
- `hapax-visual-pool-snapshot-harvester.service`,
    `hapax-visual-pool-snapshot-harvester.timer` — visual pool snapshot
    harvester for compositor frame capture. Unit files and the
    `scripts/visual-pool-snapshot-harvester.py` script were removed from
    the repo; stale symlinks discovered 2026-05-14.

**Newly installed timers are auto-enabled.** As of the audit-followups-e1 PR, `install-units.sh` runs `systemctl --user enable --now <name>.timer` for every timer file it sees for the first time. Existing timers are left alone (re-running is idempotent). To suppress this for a one-off install, set `SKIP_TIMER_ENABLE=1` before running the script (intentionally not a flag — disabling auto-enable is the rare case).

`systemd/user-preset.d/hapax.preset` mirrors the timers that must be enabled by default when preset tooling is used. Timer units still belong in `systemd/units/`; root-level `systemd/*.timer` files are not install-visible and should be moved into `systemd/units/`.

## CC Task Automation

The cc-task automation timers run against the source-activation worktree, not
the operator's interactive checkout:

| Timer | Script | Purpose |
|-------|--------|---------|
| `hapax-cc-hygiene.timer` | `scripts/cc-hygiene-sweeper.py` | Read-only cc-task vault diagnostics. |
| `hapax-cc-pr-autoqueue.timer` | `scripts/cc-pr-autoqueue.py --apply` | Governed PR auto-queue/auto-merge arming for task-linked PRs. |
| `hapax-cc-pr-merge-watcher.timer` | `scripts/cc-pr-merge-watcher.py` | Auto-close active cc-tasks after linked PRs merge. |
| `hapax-pr-review-dispatch.timer` | `scripts/cc-pr-review-dispatch.py --all --apply` | Review-team dossier refresh for open task-linked PRs. |

Recheck the review-dispatch timer claim with:
`systemctl --user list-timers --all hapax-pr-review-dispatch.timer` and
`systemctl --user status hapax-pr-review-dispatch.timer hapax-pr-review-dispatch.service --no-pager`.
For a source-level dry run, use
`uv run python scripts/cc-pr-review-dispatch.py --pr <PR_NUMBER>`.

`cc-pr-autoqueue` fails closed: a PR must be linked to exactly one cc-task, the
task must carry AuthorityCase/parent-spec metadata plus
`route_metadata_schema: 1`, and the PR must not be draft, held, dirty, failed,
already queued, or already auto-merge-armed. Green PRs are added to the merge
queue; governed PRs with pending checks but no failures are armed with
GitHub auto-merge so branch protection and the merge queue perform the final
merge when requirements pass. Killswitch:
`HAPAX_CC_PR_AUTOQUEUE_OFF=1` or the broader `HAPAX_CC_HYGIENE_OFF=1`.

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

`scripts/rebuild-service.sh` — generic script accepting `--repo`, `--service`, `--watch`, `--sha-key`, `--pull-only`. Council service entries run against the dedicated rebuild worktree at `~/.cache/hapax/rebuild/worktree`, not the operator's interactive `~/projects/hapax-council` checkout. The script creates that worktree on first use, resets it to `origin/main` at the start of every run, checks whether watched paths changed between the last deployed SHA and current `origin/main`, and only restarts the service if relevant files differ.

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
(`/home/hapax/projects/hapax-council/.git/refs/heads/main`). The dedicated
rebuild worktree shares that ref namespace with the canonical checkout, so when
`rebuild-service.sh` advances local main to `origin/main` the path unit fires
`hapax-post-merge-deploy.service`, which resolves the new HEAD SHA and invokes
the script.

Loop-safety: the deploy script writes directly to deploy destinations:
`~/.config/systemd/user/`, `~/.config/systemd/user-preset/`,
`~/.config/pipewire/`, `~/.config/wireplumber/`, `~/.config/hapax/`,
`~/.local/bin/`, `~/.local/share/wireplumber/scripts/hapax/`,
`~/.local/lib/hapax-recovery/council/`, the canonical gate destination under
`~/.local/lib/hapax/hooks/`, `~/.cache/hapax/post-merge-traces/`, and
`~/.cache/hapax/deploy-symlink-drift/`. When it delegates active coord staging
before restarting `hapax-coord.service`, `hapax-coord-deploy` also writes
`~/.cache/hapax/coord-activation/` and fetches refs inside
`HAPAX_COORD_DEPLOY_REPO` (default `/home/hapax/projects/hapax-coord`). Recheck
the inventory with
`rg -n "PW_CONF_DIR|HAPAX_CONF_DIR|WP_CONF_DIR|WP_SCRIPTS_DIR|SYSTEMD_USER_DIR|SYSTEMD_USER_PRESET_DIR|LOCAL_BIN|TRACE_PATH|HAPAX_DRIFT_STATE_DIR|coord-activation|HAPAX_COORD_DEPLOY_REPO|hapax-recovery|hooks-doctor" scripts/hapax-post-merge-deploy scripts/hapax-coord-deploy`.
The deploy script itself never touches council `.git/refs`. Belt-and-braces:
`StartLimitIntervalSec=60` / `StartLimitBurst=3` on the `[Unit]` section caps
runaway fires. Failures route through `OnFailure=notify-failure@%n.service`.
Trace inspection is documented at `docs/runbooks/post-merge-traces.md`.

Bootstrap: the path unit is canonical at `systemd/units/hapax-post-merge-deploy.path`;
the operator must `systemctl --user enable --now hapax-post-merge-deploy.path` once
after the deploy script's normal install step copies the units in place. From the
next merge onward the chain self-hosts.

### Audio Config Naming

Deployable hand-authored PipeWire files under `config/pipewire/*.conf`
must be named `hapax-*.conf`. This keeps post-merge deploy traces,
operator copies into `~/.config/pipewire/pipewire.conf.d/`, and grep
queries deterministic. `scripts/check-audio-conf-names.py` enforces the
rule in pre-commit for top-level PipeWire confs; generated compiler
artifacts under `config/pipewire/generated/` keep the audio-routing
compiler's node-id filename convention.

## Storage Management

Automated systems prevent disk exhaustion:

### Cache Cleanup (`cache-cleanup.timer` — weekly Sun 03:00)

Prunes reproducible caches: Docker build cache (168h+), dangling images, uv cache, pacman cache, stale worktree `.venv` dirs (7d+), leaked wav files in `/tmp` and `~/.cache/hapax/tmp-wav/`, Chrome crash reports, `__pycache__` (7d+), perception logs (7d), systemd journal (7d).

### Worktree GC (`hapax-worktree-gc.timer` — every 6h)

Runs `scripts/hapax-worktree-gc.sh` against the canonical council checkout.
It removes non-primary git worktrees older than 48h only when their branch is
merged into `origin/main` and the worktree has no uncommitted or untracked
changes. Worktrees older than 7d whose branches are not merged are left in
place and reported to ntfy topic `hapax-worktree-gc` for manual review.

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

### Backups (local plus critical offsite)

| Tier | Timer | Destination | Tool |
|------|-------|-------------|------|
| Local | `hapax-backup-local.timer` daily 03:00 | `/mnt/nas/backups/restic` | restic |
| Critical offsite | `hapax-backup-gdrive-critical.timer` daily 04:35 | `rclone:gdrive:hapax-backups/restic-critical` | restic + rclone → Google Drive |

The local tier backs up PostgreSQL dumps, Qdrant snapshots, n8n workflows,
Docker volume metadata, git bundles, systemd configs, user configs, LLM stack,
and system files.

The GDrive critical lane is intentionally narrower. It backs up already
materialized Postgres PITR artifacts, latest Qdrant snapshot files, and selected
vault evidence/SOP artifacts after broad Backblaze B2 was retired by operator
policy on 2026-06-06. It does
not create Qdrant snapshots, dump databases into `/tmp`, upload live MinIO, or
run destructive restic prune.

`llm-backup.timer` is retained only as a deprecated compatibility receipt. It
does not produce backup artifacts; it points at the local/GDrive lanes above.
Restore details: `docs/runbooks/llm-stack-backup-reconciliation.md`.

Secrets: local password in `pass show backups/restic-password`; current GDrive
critical repo password remains in `pass show backblaze/restic-password` until a
separate credential-rename task changes custody.

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

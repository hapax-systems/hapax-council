# Project Consolidation Implementation Plan

**Goal:** Simplify the development surface from 16 repos to 10, eliminate code duplication, and containerize the cockpit API and RAG sync pipeline.

**Design:** See `~/projects/hapax-mgmt/docs/plans/2026-03-09-project-consolidation-design.md`

---

## Completed

### Phase 1: Cleanup
- Deleted 6 dead repos: audio-gen, tabbyapi (empty), docs (empty), rag-pipeline, mcp-server-midi, midi-mcp-server. 16 → 10 repos.
- Renamed hapax-containerization → hapax-mgmt. All cross-project references updated (hapaxromana, hapax-system, global Claude config).
- Claude Code memory migrated to new project path.

### Phase 2: Containerization
- Split pyproject.toml into extras: core (base), cockpit-api, sync-pipeline, audio, host.
- Dockerfile.cockpit-api: multi-stage slim build (~675MB vs 15.4GB). Port 8051. Lazy demos import avoids playwright dependency.
- Dockerfile.sync-pipeline: 7 RAG sync agents on supercronic (~838MB). GPG agent socket forwarding for Google OAuth. CYCLE_MODE env var selects crontab.
- docker-compose.yml: wires both containers with host networking + init:true for sync-pipeline.
- All 7 sync agents verified end-to-end inside container (4 Google OAuth + 3 local filesystem).
- Stale refs cleaned: RAG_PIPELINE_DIR, HAPAX_CONTAINERIZATION_DIR removed from shared/config.py and drift_detector.py.
- Fixed test_vault_writer.py (removed deleted INBOX_DIR import).
- Documentation updated across ai-agents, cockpit-web, hapax-system, hapaxromana.

### Phase 3: Systemd Timer Migration
- Disabled 7 sync-related systemd timers (gdrive-sync, gcalendar-sync, gmail-sync, youtube-sync, claude-code-sync, obsidian-sync, chrome-sync).
- Sync-pipeline container running as replacement.
- Removed stale systemd dev overrides for 4 containerized agents.
- Updated hapax-mode script to only manage host-side timers.
- audio_processor stays on host (requires GPU/CUDA, no CPU fallback).
- obsidian-webui-sync stays as systemd timer (Open WebUI, not RAG).

### Phase 4: System Review Fixes
- Unified cockpit API port to 8051 everywhere (CORS, __main__.py defaults, README, demo pipeline).
- Health monitor now checks ai-agents containers (cockpit-api, sync-pipeline) in addition to llm-stack.
- Health monitor gdrive check updated from systemd timer to container status.
- Drift detector fixed: hapax-containerization → hapax-mgmt (HAPAX_MGMT_DIR).
- Profiler sources fixed: rag-pipeline → hapax-mgmt.
- Cockpit manual fixed: rag-pipeline reference → ingest agent.
- Cycle mode route: fallback to direct file write when hapax-mode script unavailable (container).
- Dev crontab frequencies corrected to be lower than prod (was inverted).
- Backup script now covers sync agent cache state (~/.cache/*-sync/).
- Failure notifications added to sync-pipeline run-agent.sh (ntfy).
- hapaxromana CLAUDE.md: sync agents moved from systemd timers to container section.
- hapaxromana CLAUDE.md: fixed profile-update (12h → 6h) and vram-watchdog (5min → 30min) schedules.

## Remaining

### Monitoring (48h observation)
- Monitor sync-pipeline container for 48h, verify all 7 agents run correctly on schedule.
- Verify Google OAuth token refresh works through GPG socket forwarding.

## Not Doing
- hapax-mgmt thinning: working independent demo system, deliberate extraction. Leave alone.

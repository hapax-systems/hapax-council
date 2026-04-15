# systemd user timers sweep audit

Generated: 2026-04-15

| Timer | Cadence | Target Service | Last Run | Status | Notes |
|-------|---------|----------------|----------|--------|-------|
| vram-watchdog.timer | ActiveSec: 30s, BootSec: 60 | vram-watchdog.service | 16:38:55 CDT 16s | OK | - |
| hapax-reverie-monitor.timer | ActiveSec: 1min, BootSec: 1min | hapax-reverie-monitor.service | 16:39:00 CDT 22s | OK | - |
| hls-archive-rotate.timer | ActiveSec: 60s, BootSec: 2min | hls-archive-rotate.service | 16:39:00 CDT 22s | OK | - |
| hapax-rebuild-services.timer | ActiveSec: 5min, BootSec: 3min | hapax-rebuild-services.service | 16:39:23 CDT 45s | FAILED | Failed to start Hapax Python services — rebuild from main. |
| screen-context.timer | ActiveSec: 5min, BootSec: 3min | screen-context.service | 16:39:23 CDT 45s | OK | - |
| profile-update.timer | ActiveSec: 12h, BootSec: 10min | profile-update.service | 16:40:28 CDT 1min | OK | - |
| health-monitor.timer | ActiveSec: 15min, BootSec: 2min | health-monitor.service | 16:41:02 CDT 2min | OK | - |
| gpg-keyboxd-watchdog.timer | ActiveSec: 300, BootSec: 60 | gpg-keyboxd-watchdog.service | 16:42:26 CDT 3min | OK | - |
| hapax-sprint-tracker.timer | ActiveSec: 5min, BootSec: 60s | hapax-sprint-tracker.service | 16:42:26 CDT 3min | OK | - |
| tmp-monitor.timer | ActiveSec: 5min, BootSec: 2min | tmp-monitor.service | 16:43:22 CDT 4min | OK | - |
| video-processor.timer | ActiveSec: 30min, BootSec: 10min | video-processor.service | 16:44:51 CDT 6min | OK | - |
| digest.timer | Calendar: *-*-* 06:45:00 | digest.service | 16:45:00 CDT 6min | OK | - |
| vault-context-writer.timer | Calendar: *:0/15 | vault-context-writer.service | 16:45:00 CDT 6min | FAILED | Failed to start Write working context to Obsidian daily note. |
| flow-journal.timer | ActiveSec: 15min, BootSec: 4min | flow-journal.service | 16:45:10 CDT 6min | OK | - |
| stimmung-sync.timer | ActiveSec: 15min, BootSec: 5min | stimmung-sync.service | 16:46:10 CDT 7min | OK | - |
| video-retention.timer | ActiveSec: 15min, BootSec: 5min | video-retention.service | 16:46:10 CDT 7min | OK | - |
| rag-ingest.timer | ActiveSec: 15min, BootSec: 5min | rag-ingest.service | 16:47:09 CDT 8min | FAILED | Failed to start RAG Document Ingestion Watchdog. |
| av-correlator.timer | ActiveSec: 30min, BootSec: 20min | av-correlator.service | 16:50:21 CDT 11min | OK | - |
| log-anomaly-alert.timer | Calendar: *:00/30 | log-anomaly-alert.service | 17:00:38 CDT 22min | OK | - |
| disk-space-check.timer | ActiveSec: 30min, BootSec: 5min | disk-space-check.service | 17:01:06 CDT 22min | OK | - |
| weather-sync.timer | Calendar: *:00 | weather-sync.service | 17:01:28 CDT 22min | OK | - |
| mixer-keepalive.timer | ActiveSec: 2h, BootSec: 10min | mixer-keepalive.service | 17:06:04 CDT 27min | OK | - |
| claude-code-sync.timer | ActiveSec: 6h, BootSec: 6min | claude-code-sync.service | 17:06:24 CDT 27min | OK | - |
| obsidian-sync.timer | ActiveSec: 6h, BootSec: 7min | obsidian-sync.service | 17:07:00 CDT 28min | OK | - |
| gmail-sync.timer | ActiveSec: 6h, BootSec: 8min | gmail-sync.service | 17:07:25 CDT 28min | OK | - |
| chrome-sync.timer | ActiveSec: 6h, BootSec: 5min | chrome-sync.service | 17:07:28 CDT 28min | OK | - |
| audio-processor.timer | ActiveSec: 30min, BootSec: 5min | audio-processor.service | 17:07:38 CDT 29min | OK | - |
| langfuse-sync.timer | ActiveSec: 6h, BootSec: 10min | langfuse-sync.service | 17:10:54 CDT 32min | OK | - |
| youtube-sync.timer | ActiveSec: 6h, BootSec: 8min | youtube-sync.service | 17:13:41 CDT 35min | OK | - |
| dev-story-index.timer | ActiveSec: 6h, BootSec: 8min | dev-story-index.service | 17:15:50 CDT 37min | OK | - |
| gdrive-sync.timer | ActiveSec: 6h, BootSec: 8min | gdrive-sync.service | 17:15:53 CDT 37min | OK | - |
| gcalendar-sync.timer | ActiveSec: 6h, BootSec: 8min | gcalendar-sync.service | 17:17:05 CDT 38min | OK | - |
| storage-arbiter.timer | ActiveSec: 1h, BootSec: 15min | storage-arbiter.service | 17:17:38 CDT 39min | OK | - |
| git-sync.timer | ActiveSec: 6h, BootSec: 5min | git-sync.service | 17:23:26 CDT 44min | OK | - |
| hapax-queue-gc.timer | ActiveSec: 1h, BootSec: 5min | hapax-queue-gc.service | 17:27:53 CDT 49min | OK | - |
| llm-cost-alert.timer | Calendar: *-*-* 09:00:00 | llm-cost-alert.service | 18:00:00 CDT 1h | OK | - |
| daily-briefing.timer | Calendar: *-*-* 07:00:00 | daily-briefing.service | 19:00:00 CDT 2h | OK | - |
| cache-cleanup.timer | Calendar: *-*-* 03:00 | cache-cleanup.service | 03:23:27 CDT 10h | OK | - |
| hapax-backup-local.timer | Calendar: *-*-* 03:00:00 | hapax-backup-local.service | 03:23:33 CDT 10h | FAILED | Failed to start Hapax Local Backup (restic). |
| knowledge-maint.timer | Calendar: Sun *-*-* 04:30:00 | knowledge-maint.service | 04:34:02 CDT 11h | OK | - |
| health-connect-parse.timer | ActiveSec: 24h, BootSec: 30min | health-connect-parse.service | 11:26:03 CDT 18h | OK | - |
| stack-maintenance.timer | Calendar: Sun *-*-* 02:00:00 | stack-maintenance.service | 02:03:50 CDT 3 | OK | - |
| llm-backup.timer | Calendar: Sun *-*-* 02:00:00 | llm-backup.service | 02:20:26 CDT 3 | OK | - |
| manifest-snapshot.timer | Calendar: Sun *-*-* 02:30:00 | manifest-snapshot.service | 02:32:00 CDT 3 | OK | - |
| drift-detector.timer | Calendar: Sun *-*-* 03:00:00 | drift-detector.service | 03:04:51 CDT 3 | OK | - |
| tailscale-cleanup.timer | Calendar: Sun *-*-* 03:30 | tailscale-cleanup.service | 03:38:15 CDT 3 | OK | - |
| hapax-backup-remote.timer | Calendar: Wed *-*-* 04:00:00 | hapax-backup-remote.service | 04:25:40 CDT 6 | OK | - |
| scout.timer | Calendar: Wed *-*-* 10:00:00 | scout.service | 10:02:57 CDT 6 | OK | - |
| claude-md-audit.timer | Calendar: monthly | claude-md-audit.service | 00:53:45 CDT 2 | OK | - |
| hapax-rebuild-logos.timer | ActiveSec: 5min, BootSec: 2min | hapax-rebuild-logos.service | Wed 2026-04-15 16:38:21 | OK | - |
| hapax-vision-observer.timer | ActiveSec: 10, BootSec: 30 | hapax-vision-observer.service | Wed 2026-04-15 16:38:31 | FAILED | Failed to start Hapax Vision Observer — visual surface description. |
| rclone-gdrive-drop.timer | ActiveSec: 5s, BootSec: 5s | rclone-gdrive-drop.service | Wed 2026-04-15 16:38:05 | FAILED | Failed to start rclone bisync gdrive:drop ↔ ~/gdrive-drop. |

## Drift from CLAUDE.md

- **Documented count:** 49
- **Actual count:** 52
- **Drift:** +3 timers
- **Note:** New timers like `hapax-vision-observer.timer` and `rclone-gdrive-drop.timer` have likely been added since the last documentation update.

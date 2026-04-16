---
title: systemd user timers schedule matrix
date: 2026-04-16
queue_item: '320'
epic: lrr
phase: substrate-scenario-2
status: catalog
---

# systemd user timers — schedule matrix

Survey of timers in `systemd/units/` and active `~/.config/systemd/user/`.

## Summary

| Metric | Count |
|---|---|
| Repo .timer files | 52 |
| Installed .timer symlinks | 52 |

## Repo timers (systemd/units/)

| Unit | OnCalendar | OnBootSec | OnUnitActiveSec | Persistent |
|---|---|---|---|---|
| `audio-processor.timer` | - | 5min | 30min | - |
| `av-correlator.timer` | - | 20min | 30min | - |
| `cache-cleanup.timer` | *-*-* 03:00 | - | - | true |
| `chrome-sync.timer` | - | 5min | 6h | true |
| `claude-code-sync.timer` | - | 6min | 6h | true |
| `claude-md-audit.timer` | monthly | - | - | true |
| `daily-briefing.timer` | *-*-* 07:00:00 | - | - | true |
| `dev-story-index.timer` | - | 8min | 6h | true |
| `digest.timer` | *-*-* 06:45:00 | - | - | true |
| `disk-space-check.timer` | - | 5min | 30min | - |
| `drift-detector.timer` | Sun *-*-* 03:00:00 | - | - | true |
| `flow-journal.timer` | - | 4min | 15min | true |
| `gcalendar-sync.timer` | - | 8min | 6h | true |
| `gdrive-sync.timer` | - | 8min | 6h | true |
| `git-sync.timer` | - | 5min | 6h | true |
| `gmail-sync.timer` | - | 8min | 6h | true |
| `gpg-keyboxd-watchdog.timer` | - | 60 | 300 | - |
| `hapax-backup-local.timer` | *-*-* 03:00:00 | - | - | true |
| `hapax-backup-remote.timer` | Wed *-*-* 04:00:00 | - | - | true |
| `hapax-lrr-phase-4-integrity.timer` | daily | - | - | true |
| `hapax-rebuild-logos.timer` | - | 2min | 5min | - |
| `hapax-rebuild-services.timer` | - | 3min | 5min | - |
| `hapax-reverie-monitor.timer` | - | 1min | 1min | - |
| `hapax-sprint-tracker.timer` | - | 60s | 5min | - |
| `hapax-vision-observer.timer` | - | 30 | 10 | - |
| `health-connect-parse.timer` | - | 30min | 24h | true |
| `health-monitor.timer` | - | 2min | 15min | true |
| `hls-archive-rotate.timer` | - | 2min | 60s | - |
| `knowledge-maint.timer` | Sun *-*-* 04:30:00 | - | - | true |
| `langfuse-sync.timer` | - | 10min | 6h | true |
| `llm-backup.timer` | Sun *-*-* 02:00:00 | - | - | true |
| `llm-cost-alert.timer` | *-*-* 09:00:00 | - | - | true |
| `log-anomaly-alert.timer` | *:00/30 | - | - | true |
| `manifest-snapshot.timer` | Sun *-*-* 02:30:00 | - | - | true |
| `mixer-keepalive.timer` | - | 10min | 2h | - |
| `obsidian-sync.timer` | - | 7min | 6h | true |
| `profile-update.timer` | - | 10min | 12h | true |
| `rag-ingest.timer` | - | 5min | 15min | - |
| `rclone-gdrive-drop.timer` | - | 5s | 5s | - |
| `scout.timer` | Wed *-*-* 10:00:00 | - | - | true |
| `screen-context.timer` | - | 3min | 5min | true |
| `stack-maintenance.timer` | Sun *-*-* 02:00:00 | - | - | true |
| `stimmung-sync.timer` | - | 5min | 15min | true |
| `storage-arbiter.timer` | - | 15min | 1h | true |
| `tailscale-cleanup.timer` | Sun *-*-* 03:30 | - | - | true |
| `tmp-monitor.timer` | - | 2min | 5min | - |
| `vault-context-writer.timer` | *:0/15 | - | - | true |
| `video-processor.timer` | - | 10min | 30min | - |
| `video-retention.timer` | - | 5min | 15min | true |
| `vram-watchdog.timer` | - | 60 | 30s | - |
| `weather-sync.timer` | *:00 | - | - | true |
| `youtube-sync.timer` | - | 8min | 6h | true |

## Classification

- Timers with OnCalendar only: 18
- Timers with OnUnitActiveSec only: 34
- Timers with both: 0

## Live timer state (systemctl --user list-timers)

```
NEXT                                  LEFT LAST                              PASSED UNIT                         ACTIVATES
Thu 2026-04-16 13:11:22 CDT             3s Thu 2026-04-16 13:10:52 CDT      26s ago vram-watchdog.timer          vram-watchdog.service
Thu 2026-04-16 13:12:16 CDT            57s Thu 2026-04-16 13:11:16 CDT       2s ago hapax-reverie-monitor.timer  hapax-reverie-monitor.service
Thu 2026-04-16 13:12:16 CDT            57s Thu 2026-04-16 13:11:16 CDT       2s ago hls-archive-rotate.timer     hls-archive-rotate.service
Thu 2026-04-16 13:13:47 CDT       2min 28s Thu 2026-04-16 13:08:47 CDT 2min 31s ago gpg-keyboxd-watchdog.timer   gpg-keyboxd-watchdog.service
Thu 2026-04-16 13:13:47 CDT       2min 28s Thu 2026-04-16 13:08:47 CDT 2min 31s ago hapax-sprint-tracker.timer   hapax-sprint-tracker.service
Thu 2026-04-16 13:14:40 CDT       3min 21s Thu 2026-04-16 13:09:40 CDT 1min 38s ago hapax-rebuild-logos.timer    hapax-rebuild-logos.service
Thu 2026-04-16 13:14:40 CDT       3min 21s Thu 2026-04-16 13:09:40 CDT 1min 38s ago tmp-monitor.timer            tmp-monitor.service
Thu 2026-04-16 13:15:00 CDT       3min 40s Thu 2026-04-16 13:00:00 CDT    11min ago vault-context-writer.timer   vault-context-writer.service
Thu 2026-04-16 13:15:31 CDT       4min 12s Thu 2026-04-16 13:00:31 CDT    10min ago flow-journal.timer           flow-journal.service
Thu 2026-04-16 13:15:51 CDT       4min 32s Thu 2026-04-16 13:10:51 CDT      27s ago screen-context.timer         screen-context.service
Thu 2026-04-16 13:16:36 CDT           5min Thu 2026-04-16 13:01:35 CDT     9min ago stimmung-sync.timer          stimmung-sync.service
Thu 2026-04-16 13:16:36 CDT           5min Thu 2026-04-16 13:01:35 CDT     9min ago video-retention.timer        video-retention.service
Thu 2026-04-16 13:20:04 CDT           8min Thu 2026-04-16 13:04:14 CDT     7min ago health-monitor.timer         health-monitor.service
Thu 2026-04-16 13:25:39 CDT          14min Thu 2026-04-16 13:08:46 CDT 2min 33s ago rag-ingest.timer             rag-ingest.service
Thu 2026-04-16 13:28:00 CDT          16min Thu 2026-04-16 12:28:00 CDT    43min ago hapax-queue-gc.timer         hapax-queue-gc.service
Thu 2026-04-16 13:30:06 CDT          18min Thu 2026-04-16 12:59:44 CDT    11min ago audio-processor.timer        audio-processor.service
Thu 2026-04-16 13:30:10 CDT          18min Thu 2026-04-16 13:00:52 CDT    10min ago log-anomaly-alert.timer      log-anomaly-alert.service
Thu 2026-04-16 13:31:20 CDT          20min Thu 2026-04-16 13:01:20 CDT     9min ago disk-space-check.timer       disk-space-check.service
Thu 2026-04-16 13:33:11 CDT          21min Thu 2026-04-16 13:03:08 CDT     8min ago video-processor.timer        video-processor.service
Thu 2026-04-16 13:38:49 CDT          27min Thu 2026-04-16 12:37:32 CDT    33min ago storage-arbiter.timer        storage-arbiter.service
Thu 2026-04-16 13:41:46 CDT          30min Thu 2026-04-16 13:10:51 CDT      27s ago av-correlator.timer          av-correlator.service
Thu 2026-04-16 14:01:28 CDT          50min Thu 2026-04-16 13:00:28 CDT    10min ago weather-sync.timer           weather-sync.service
Thu 2026-04-16 14:45:00 CDT       1h 33min Thu 2026-04-16 12:45:00 CDT    26min ago digest.timer                 digest.service
Thu 2026-04-16 15:00:00 CDT       1h 48min Thu 2026-04-16 11:00:00 CDT 2h 11min ago daily-briefing.timer         daily-briefing.service
Thu 2026-04-16 15:06:09 CDT       1h 54min Thu 2026-04-16 13:06:08 CDT     5min ago mixer-keepalive.timer        mixer-keepalive.service
Thu 2026-04-16 17:18:58 CDT        4h 7min Thu 2026-04-16 11:18:16 CDT 1h 53min ago langfuse-sync.timer          langfuse-sync.service
Thu 2026-04-16 17:26:03 CDT       4h 14min Thu 2026-04-16 11:16:39 CDT 1h 54min ago chrome-sync.timer            chrome-sync.service
Thu 2026-04-16 17:26:28 CDT       4h 15min Thu 2026-04-16 11:23:52 CDT 1h 47min ago obsidian-sync.timer          obsidian-sync.service
Thu 2026-04-16 17:27:27 CDT       4h 16min Thu 2026-04-16 11:24:42 CDT 1h 46min ago dev-story-index.timer        dev-story-index.service
Thu 2026-04-16 17:27:50 CDT       4h 16min Thu 2026-04-16 11:23:32 CDT 1h 47min ago gmail-sync.timer             gmail-sync.service
Thu 2026-04-16 17:28:01 CDT       4h 16min Thu 2026-04-16 11:22:14 CDT 1h 49min ago claude-code-sync.timer       claude-code-sync.service
Thu 2026-04-16 17:33:49 CDT       4h 22min Thu 2026-04-16 11:24:43 CDT 1h 46min ago youtube-sync.timer           youtube-sync.service
Thu 2026-04-16 17:42:43 CDT       4h 31min Thu 2026-04-16 11:40:17 CDT 1h 31min ago gcalendar-sync.timer         gcalendar-sync.service
Thu 2026-04-16 17:43:37 CDT       4h 32min Thu 2026-04-16 11:35:13 CDT 1h 36min ago gdrive-sync.timer            gdrive-sync.service
Thu 2026-04-16 17:50:30 CDT       4h 39min Thu 2026-04-16 11:36:11 CDT 1h 35min ago git-sync.timer               git-sync.service
Thu 2026-04-16 18:00:00 CDT       4h 48min Thu 2026-04-16 09:00:00 CDT 4h 11min ago llm-cost-alert.timer         llm-cost-alert.service
Fri 2026-04-17 03:20:38 CDT            14h Thu 2026-04-16 03:23:27 CDT       9h ago cache-cleanup.timer          cache-cleanup.service
Fri 2026-04-17 03:21:25 CDT            14h Thu 2026-04-16 03:23:33 CDT       9h ago hapax-backup-local.timer     hapax-backup-local.service
Fri 2026-04-17 04:32:54 CDT            15h Thu 2026-04-16 04:34:03 CDT       8h ago knowledge-maint.timer        knowledge-maint.service
Fri 2026-04-17 11:26:04 CDT            22h Thu 2026-04-16 11:26:04 CDT 1h 45min ago health-connect-parse.timer   health-connect-parse.service
Sun 2026-04-19 02:03:30 CDT         2 days Sun 2026-04-12 02:02:44 CDT            - stack-maintenance.timer      stack-maintenance.service
Sun 2026-04-19 02:28:24 CDT         2 days Sun 2026-04-12 02:00:51 CDT            - llm-backup.timer             llm-backup.service
Sun 2026-04-19 02:32:11 CDT         2 days Sun 2026-04-12 02:31:12 CDT            - manifest-snapshot.timer      manifest-snapshot.service
Sun 2026-04-19 03:01:50 CDT         2 days Wed 2026-04-15 03:02:14 CDT            - drift-detector.timer         drift-detector.service
Sun 2026-04-19 03:36:56 CDT         2 days Tue 2026-04-14 11:45:47 CDT            - tailscale-cleanup.timer      tailscale-cleanup.service
Wed 2026-04-22 04:16:45 CDT         5 days Wed 2026-04-15 04:27:40 CDT            - hapax-backup-remote.timer    hapax-backup-remote.service
Wed 2026-04-22 10:01:45 CDT         5 days Wed 2026-04-15 10:03:54 CDT            - scout.timer                  scout.service
Fri 2026-05-01 00:40:11 CDT 2 weeks 0 days Tue 2026-04-14 11:25:37 CDT            - claude-md-audit.timer        claude-md-audit.service
-                                        - Thu 2026-04-16 13:10:51 CDT      27s ago hapax-rebuild-services.timer hapax-rebuild-services.service
-                                        - Thu 2026-04-16 13:10:57 CDT      21s ago hapax-vision-observer.timer  hapax-vision-observer.service
-                                        - Thu 2026-04-16 13:10:38 CDT      41s ago profile-update.timer         profile-update.service
-                                        - Thu 2026-04-16 13:11:04 CDT      15s ago rclone-gdrive-drop.timer     rclone-gdrive-drop.service

52 timers listed.
```

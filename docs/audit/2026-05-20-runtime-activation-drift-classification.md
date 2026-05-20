# Runtime Activation Drift Warning Classification

CC-task: `runtime-activation-drift-warning-classification-20260518`
Source audit: `~/.cache/hapax/runtime-activation-drift/audit-20260518T1748Z.json`
Classified: 2026-05-20

## Summary

27 warnings, 0 critical. Classification: 3 transient (existing tasks), 10 timers need preset entry, 3 services need auto-enable, 5 template/timer-activated (no action), 6 intentionally disabled.

## Failed Units (3) — transient, covered by existing tasks

| Unit | Status | Rationale |
|------|--------|-----------|
| `hapax-daimonion.service` | transient | Was failed at audit; now active. Restart=always recovers it. |
| `hapax-obsidian-publish-sync.service` | known-failing | Task `obsidian-publish-sync-auth-preflight-20260518` covers. |
| `hapax-segment-prep.service` | known-failing | Existing segment-prep work covers. Timer restarts on schedule. |

## Missing Units (18) — in repo, installed, not enabled

### Timers needing preset entry (10)

| Unit | Fix |
|------|-----|
| `hapax-backup-watchdog.timer` | preset |
| `hapax-container-cleanup.timer` | preset |
| `hapax-dataset-card-generator.timer` | preset |
| `hapax-l12-critical-usb-guard.timer` | preset |
| `hapax-omg-lol-fanout.timer` | preset |
| `hapax-ram-allocation-audit.timer` | preset |
| `hapax-v4l2-watchdog.timer` | preset |
| `hapax-velocity-digest.timer` | preset |
| `hapax-velocity-report.timer` | preset |
| `hapax-broadcast-audio-health.timer` | already enabled — no fix needed |

### Services needing auto-enable (3)

| Unit | Fix |
|------|-----|
| `hapax-camera-loopback-setup.service` | AUTO_ENABLE_SERVICES |
| `hapax-chronicle-high-salience-public-event-producer.service` | AUTO_ENABLE_SERVICES |
| `hapax-coordinator.service` | AUTO_ENABLE_SERVICES |

### No action needed (5)

| Unit | Reason |
|------|--------|
| `hapax-camera-loopback@.service` | Template — per-instance enablement |
| `hapax-dataset-card-generator.service` | Timer-activated |
| `hapax-ram-allocation-audit.service` | Timer-activated |
| `hapax-velocity-digest.service` | Timer-activated |

## Disabled Units (6) — all intentional

| Unit | Reason |
|------|--------|
| `hapax-audio-self-perception.service` | Operator opt-in; running when manually started |
| `hapax-broadcast-audio-health.service` | Timer-activated (timer is enabled) |
| `hapax-frontier-triage-officer.service` | Timer/manual invocation only |
| `hapax-information-density.service` | Resource-heavy; manual start |
| `hapax-obs-livestream.service` | Stream-only; manual start |
| `hapax-video42-format-guard.service` | Compositor-gated; running when manually started |

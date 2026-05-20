# Imagination Bookend Metadata Deploy Receipt

**Date:** 2026-05-20T16:15Z
**Authority:** REQ-20260518225227-compositor-incident-recovery-ledger
**Deployer:** delta session
**Trigger:** PR #3551 merged but running imagination process older than rebuilt binary

## Pre-Restart Evidence

| Field | Value |
|-------|-------|
| Source activation SHA | 7e82429eeabb8c3d80ea53a681f9a595ffe326f9 |
| Binary mtime | 2026-05-20 11:14:45 CDT |
| Process start (stale) | 2026-05-20 05:26:07 CDT |
| Process PID (stale) | 1002361 |
| Effect drift gaps pre-restart | 0 |
| Bookend gaps pre-restart | none |

## Deployment Action

`systemctl --user restart hapax-imagination.service` at 2026-05-20T16:15:17Z CDT.

## Post-Restart Evidence

| Field | Value |
|-------|-------|
| Process start (fresh) | 2026-05-20 11:15:17 CDT |
| Process PID (fresh) | 994669 |
| Service state | active |
| Effect drift gaps post-restart | 0 |
| Bookend gaps (fb/post) post-restart | none |

## Live Surface Preflight

- hapax-imagination.service: **active**
- hapax-dmn.service: **active**
- studio-compositor.service: **active**
- hapax-logos.service: inactive (expected — dev server not running)
- Audio routing: 2 pre-existing violations (unrelated to imagination)

## Verdict

Imagination renderer restarted onto rebuilt binary. No `fb` or `post` bookend
gaps in effect-drift state before or after restart. Live surface preflight
shows no regression from the restart.

## Stale Claim Hygiene

The source task `compositor-bookend-source-bound-metadata-repair` was closed
by codex-main with two live acceptance checks unchecked. This deploy task
witnesses the runtime behavior that the source task's live checks required.

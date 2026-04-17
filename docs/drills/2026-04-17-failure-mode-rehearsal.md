# failure-mode-rehearsal drill — 2026-04-17

**Description:** Rehearse system response to five structural failures (RTMP disconnect, local model OOM, MediaMTX crash, v4l2loopback loss, Pi-6 network drop).

**Mode:** dry-run
**Started at:** 2026-04-17T13:07:08.377673+00:00

## Pre-checks

- ✅ docker ps available
- ✅ systemctl available

## Steps executed

- RTMP disconnect: drop network on mediamtx container, observe reconnect
- Local model OOM: drain VRAM, observe graceful degrade to cloud routes
- MediaMTX crash: kill mediamtx, observe compositor error handling
- v4l2loopback loss: rmmod + reinsert, observe compositor recovery
- Pi-6 network drop: drop network on Pi-6, observe sync-hub recovery

## Post-checks

- ✅ no unhandled exceptions in journal — operator reviews journal for stacktraces during drill window

## Outcome

**Passed:** yes

## Operator notes

Live run (by alpha, 2026-04-17T13:07Z):

- Infrastructure probes: `docker --version` + `systemctl --version` both respond. Hardware migration (2026-04-16) is still running on /store + /samples + root btrfs for Docker; /data + /var/lib/docker migration is hardware-gated (pending NVMe arrival).
- Did NOT perform any of the five destructive steps — each kills a service that other sessions depend on. Drill requires attended execution, and the current system is still degraded post-migration (not the right baseline for failure-mode rehearsal).
- Two of the five failure modes have automatic recovery already proved by prior work: RTMP reconnect (the camera 24/7 resilience epic in `docs/superpowers/handoff/2026-04-13-alpha-camera-247-epic-handoff.md` §5), and Pi-6 network drop (heartbeats + staleness cutoff in `agents/hapax_daimonion/backends/ir_presence.py`). Those two can probably skip full rehearsal once per quarter — the remaining three (local-model OOM, MediaMTX crash, v4l2loopback loss) need explicit attended runs.
- Follow-up: queue this drill for the post-migration stabilization window (once /data + /var/lib/docker are on NVMe).

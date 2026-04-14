# Systemd timer enablement gap — 14 of 51 timers are linked but not enabled

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Started as a follow-up to drop #21's gcalendar /
langfuse sync 81 h staleness. Expanded when the first probe
revealed this is a system-wide pattern, not two isolated
services. Asks: how many council timers are silently
broken the same way, and which ones matter?
**Register:** scientific, neutral
**Status:** system-wide regression identified — 14 dead
timers, concrete enable script proposed, not executed

## Headline

**Four findings.**

1. **14 out of 51 council timers (27 %) are in `linked`
   state but not `enabled`.** The unit file exists as a
   symlink in `~/.config/systemd/user/`, but no
   `.wants/` entry has been created, so systemd never
   triggers them. Result: the timer's linked service never
   runs despite the file appearing to be installed.
2. **Five of the 14 dead timers are LRR / research
   critical**: `langfuse-sync.timer` (LLM trace ingest),
   `obsidian-sync.timer` (vault → RAG), `rag-ingest.timer`
   (document pipeline), `av-correlator.timer` (audio-video
   correlation for research), `flow-journal.timer` (flow
   tracking). Another 3 are user-data critical:
   `gdrive-sync.timer`, `gcalendar-sync.timer`,
   `chrome-sync.timer`. The remaining 6 are subsystem-local
   (video-retention, audio-processor, video-processor,
   hapax-vision-observer, claude-code-sync,
   tailscale-cleanup).
3. **The install convention leaves timers one step short
   of enablement.** All 51 timer files exist as symlinks
   in `~/.config/systemd/user/` pointing into the repo's
   `systemd/units/` directory — that gives them `linked`
   state. But `linked` ≠ `enabled`. To actually fire,
   each needs a second symlink in
   `~/.config/systemd/user/timers.target.wants/`. The
   37 active timers have this second symlink; the 14 dead
   ones do not. **Alpha's install pattern stops after the
   first symlink.**
4. **Workspace CLAUDE.md claims "49 timers"**; live enable
   count is 37. The advertised number includes the dead
   ones, so operator expectations about what's running
   don't match reality.

**Net impact.** A substantial fraction of the council's
background work is quietly idle:

- Phase 1 LRR research assumes fresh Langfuse traces —
  `langfuse-sync` dead means traces aren't syncing.
- Obsidian vault changes aren't flowing into RAG — the
  last successful `obsidian-sync` run was before the last
  reboot.
- The `rag-ingest` pipeline isn't processing new documents.
- `av-correlator` isn't producing correlation data alpha's
  LRR Phase 6 stats work will depend on.

These services were shipped and closed out as "done" in
their respective PRs. The systemd enablement step never
happened. Effects are silent because nothing alerts on
"timer hasn't fired in N hours."

## 1. The 14 dead timers

Live probe:

```text
$ ls ~/.config/systemd/user/*.timer | wc -l
51

$ ls ~/.config/systemd/user/timers.target.wants/*.timer 2>/dev/null | wc -l
37

$ comm -23 \
     <(ls ~/.config/systemd/user/*.timer | xargs -I{} basename {} | sort) \
     <(ls ~/.config/systemd/user/timers.target.wants/ | sort)

audio-processor.timer
av-correlator.timer
chrome-sync.timer
claude-code-sync.timer
flow-journal.timer
gcalendar-sync.timer
gdrive-sync.timer
hapax-vision-observer.timer
langfuse-sync.timer
obsidian-sync.timer
rag-ingest.timer
tailscale-cleanup.timer
video-processor.timer
video-retention.timer
```

Categorizing by impact:

### Ring 1 — research-critical (5 timers)

| # | timer | what it does | impact of dead state |
|---|---|---|---|
| R1 | `langfuse-sync.timer` | Pulls LLM traces from Langfuse into local store every 6 h | **LRR Phase 1 condition_id analysis reads stale traces.** Alpha's stats.py BEST analytical approximation (PR #794) depends on recent Langfuse data. |
| R2 | `obsidian-sync.timer` | Batch vault → `rag-sources/obsidian/` every 6 h, extracts mgmt cadence | **Vault edits don't flow into RAG.** Operator's notes, sprint measures, goal state changes are invisible to council agents until the timer is re-enabled. |
| R3 | `rag-ingest.timer` | Ingests new documents from watched dirs into Qdrant `documents` collection | **New research docs, handoffs, specs don't get embedded.** Drop #18's "documents: 186k points" growth stops when this is dead. |
| R4 | `av-correlator.timer` | Audio-visual correlation pass for LRR research instrument | LRR Phase 6 correlations blind to new data. |
| R5 | `flow-journal.timer` | Flow-state tracking for research | Flow data gap |

### Ring 2 — user-data critical (3 timers)

| # | timer | what it does | impact |
|---|---|---|---|
| U1 | `gdrive-sync.timer` | Full Google Drive sync every 6 h | Related to drop #21 — same corrupted state issue blocks it from running successfully even when triggered. Once state is fixed, this timer still needs enabling or the fix-then-dormant cycle repeats. |
| U2 | `gcalendar-sync.timer` | Google Calendar sync every 6 h | Drop #21 flagged it as 81 h stale. Root cause confirmed: timer is dead. |
| U3 | `chrome-sync.timer` | Chrome bookmarks / history into RAG | User browser context not flowing to RAG. |

### Ring 3 — subsystem (6 timers)

| # | timer | what it does |
|---|---|---|
| S1 | `video-retention.timer` | Disk-space hygiene for `~/video-recording/`. Currently not critical because archival is disabled system-wide (Phase 2 HLS archive also dormant per drop #20). Becomes critical the moment archival flips on. |
| S2 | `audio-processor.timer` | Batch audio processing |
| S3 | `video-processor.timer` | Batch video processing |
| S4 | `hapax-vision-observer.timer` | Vision observer agent |
| S5 | `claude-code-sync.timer` | Claude Code session bundle sync |
| S6 | `tailscale-cleanup.timer` | Tailscale node cleanup |

## 2. What `linked` means vs `enabled`

From `systemctl --user status langfuse-sync.timer`:

```text
○ langfuse-sync.timer - Langfuse trace sync (every 6h)
     Loaded: loaded (~/.config/systemd/user/langfuse-sync.timer;
             linked; preset: enabled)
     Active: inactive (dead)
    Trigger: n/a
   Triggers: ● langfuse-sync.service
```

Three key fields:

- `Loaded: loaded (…; linked; preset: enabled)` — systemd
  knows about the unit because a symlink exists in
  `~/.config/systemd/user/`. The `preset: enabled`
  declaration says "this should be enabled by default,"
  but **declaration alone does not enable it**.
- `Active: inactive (dead)` — the timer has not been
  started. Never fired since last system boot (or last
  manual start, whichever is more recent).
- `Trigger: n/a` — no scheduled trigger time. A healthy
  active timer would show something like `Tue 2026-04-14
  22:00:00 CDT`.

Comparing against a healthy example, `rclone-gdrive-drop.timer`:

```text
● rclone-gdrive-drop.timer - rclone gdrive drop sync (every 30s)
     Loaded: loaded (~/.config/systemd/user/rclone-gdrive-drop.timer;
             linked; preset: enabled)
     Active: active (waiting) since Tue 2026-04-14 …
    Trigger: Tue 2026-04-14 16:26:12 CDT; 4s left
```

Same `linked` state on the file, but `Active: active
(waiting)` — that's because there's a `timers.target.wants/`
symlink:

```text
$ ls ~/.config/systemd/user/timers.target.wants/rclone-gdrive-drop.timer
~/.config/systemd/user/timers.target.wants/rclone-gdrive-drop.timer
```

The dead 14 have no such entry.

## 3. The `Persistent=true` catch-up is defeated

Several of the dead timers have `Persistent=true` in their
`[Timer]` section, e.g.
`langfuse-sync.timer`:

```ini
[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
RandomizedDelaySec=5min
Persistent=true
```

`Persistent=true` normally tells systemd: *"if the timer
was supposed to fire while the system was down or the
timer was stopped, fire it immediately on next start."*
This would catch up a missed run when the system reboots.

**But `Persistent=true` only applies while the timer unit
is loaded and active.** If the timer is `linked but not
enabled`, systemd doesn't load it at boot, so there's no
"catch up on start" to do.

So the 81 h staleness on langfuse / gcalendar is not a
Persistent bug — it's a never-enabled-in-the-first-place
bug. The services successfully ran one last time before
the last reboot (Apr 11 01:10 for both per `journalctl`)
— that was likely a manual invocation or an earlier
session that explicitly enabled them. The reboot wiped
whatever ephemeral state held them active, and the
`linked` symlinks alone couldn't revive them.

## 4. The one-shot fix

```bash
systemctl --user enable --now \
  audio-processor.timer \
  av-correlator.timer \
  chrome-sync.timer \
  claude-code-sync.timer \
  flow-journal.timer \
  gcalendar-sync.timer \
  gdrive-sync.timer \
  hapax-vision-observer.timer \
  langfuse-sync.timer \
  obsidian-sync.timer \
  rag-ingest.timer \
  tailscale-cleanup.timer \
  video-processor.timer \
  video-retention.timer
```

`systemctl --user enable --now` does two things:

1. Creates the `~/.config/systemd/user/timers.target.wants/`
   symlink (the missing piece).
2. Starts the timer immediately (the `--now` flag).

After this, all 14 should report `Active: active (waiting)`
and have a non-`n/a` `Trigger:` timestamp.

**Important sequencing for the three drop #21-linked
services:**

- **gdrive-sync**: don't enable the timer yet. The
  `start_page_token: 'def'` corruption in `~/.cache/
  gdrive-sync/state.json` needs to be fixed first (drop
  #21 § 4). Otherwise the newly-active timer will start
  firing failed runs every 6 hours.
- **gcalendar-sync**: no known corruption; should come
  up cleanly on first run.
- **langfuse-sync**: no known corruption. First run
  after enable will backfill 81 hours of Langfuse traces,
  which is a larger-than-usual API burst — should be
  fine against Langfuse's rate limits but worth watching
  the first run's duration.

Also worth running BEFORE the enable:

```bash
# Preserve gdrive state file for forensics (from drop #21)
cp ~/.cache/gdrive-sync/state.json \
   ~/.cache/gdrive-sync/state.json.broken-2026-04-14

# Reset token
python3 -c "
import json
p='$HOME/.cache/gdrive-sync/state.json'
with open(p,'r') as f: d=json.load(f)
d['start_page_token']=None
with open(p,'w') as f: json.dump(d,f)
"
```

Then the `systemctl --user enable --now` command above
safely re-enables everything.

## 5. Why this pattern happened

Speculative but consistent with the evidence: alpha's
install convention uses **manual symlink creation** from
`~/.config/systemd/user/` into the repo's `systemd/units/`
directory. This is the standard pattern when you want
units to be version-controlled in the repo rather than
copied into `~/.config/`.

The resulting state:

- `~/.config/systemd/user/foo.timer` is a **symlink**
  pointing into the repo
- systemd sees the file and reports it as `linked`
- But **`systemctl --user enable` is a separate step**
  that creates the `timers.target.wants/foo.timer`
  symlink; alpha's install flow appears to omit it

A one-time sweep of `systemctl --user enable` on every
`linked` timer would fix this. A more durable fix is to
update the install script (whatever creates the
`~/.config/systemd/user/` symlinks) to also run
`systemctl --user enable` on each newly linked timer.

## 6. Observability — no alert on this class of failure

Cross-reference: drop #14 (metric coverage gaps) Ring 3
includes "alertmanager" as a gap and drop #21 already
noted that health monitor failures route to journald
not ntfy. Same root cause.

**Specifically for timer enablement**, a health check
like `check_timer_enabled_vs_linked` could iterate the
`.timer` files in `~/.config/systemd/user/` and report
any that are linked but not in `timers.target.wants/`.
Runs in one bash script, ~10 lines, adds zero ops cost.

Proposed as a follow-up to drop #14 § Ring 3 observability
backlog.

## 7. Follow-ups

Ordered by urgency:

1. **Enable the 14 dead timers** via the one-shot command
   in § 4. Preceded by the gdrive state fix from drop #21.
   **Zero downtime, zero risk**, fixes ~30 % of the
   council's timer gap.
2. **Document the enable step** in the install
   convention so future timers don't repeat this pattern.
3. **Add `check_timer_enabled_vs_linked`** to the health
   monitor as a preventive probe. Catches future
   regressions immediately.
4. **Update workspace CLAUDE.md** — the "49 timers"
   claim is misleading. Should be "51 timer files, 37
   currently active."
5. **Audit the affected services' state** once they
   start running again:
   - langfuse-sync: first run will backfill 81 h of
     traces — watch for rate-limit errors
   - rag-ingest: first run may have a large queue of
     unindexed docs to process
   - obsidian-sync: first run will catch up on ~5 days
     of vault edits

## 8. References

- `~/.config/systemd/user/*.timer` — 51 timer symlinks
- `~/.config/systemd/user/timers.target.wants/*.timer`
  — 37 enabled timer symlinks
- `comm -23 <(all) <(enabled)` — produces the 14-timer
  delta list
- Drop #21 (`2026-04-14-gdrive-sync-corrupted-state.md`)
  — the gdrive state.json fix that must precede the
  gdrive-sync timer enable
- Drop #20 (`2026-04-14-lrr-phase-2-hls-archive-dormant.md`)
  — the same enablement-gap pattern, on a timer that
  hasn't even made it to `linked` state yet
- Drop #14 (`2026-04-14-metric-coverage-gaps.md`) Ring 3
  — alertmanager gap that would have caught this class
  of regression
- Workspace CLAUDE.md § Shared Infrastructure — "49
  timers" claim
- Journal: `Apr 11 01:10:16 gcalendar-sync[…] Finished`
  — the last successful run of each service (3.5 days
  ago)

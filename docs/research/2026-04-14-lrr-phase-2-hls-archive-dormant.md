# LRR Phase 2 HLS archive is dormant — segments are being deleted, not archived

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Live investigation of the HLS archive pipeline
alpha shipped in LRR Phase 2 (PR #797). Asks: is the
"Archive + Replay as Research Instrument" actually
archiving anything?
**Register:** scientific, neutral
**Status:** critical gap identified — archive is empty,
segments are being silently deleted, rotation timer is not
installed on the live system. No code change

## Headline

**Four findings, Ring 1 (drop-everything) severity.**

1. **`hls-archive-rotate.timer` is shipped in the council
   repo but not installed / activated on the running
   workstation.** `systemctl --user status hls-archive-
   rotate.timer` returns "Unit could not be found."
   `journalctl --user -u hls-archive-rotate.service` shows
   "No entries." **The rotation has never run.**
2. **The compositor's `hlssink2` element is configured
   with `max_files: 15`** (from
   `agents/studio_compositor/models.py:60-61`, default
   HLS config). At 4-second segments, that's a ~60-second
   playlist window, and hlssink2 **deletes older files**
   as new ones are written. Live `ls` confirms: currently
   16 `.ts` files in the HLS cache dir, total 63 MB,
   oldest segment ~60 seconds old.
3. **The archive destination directory
   `~/hapax-state/stream-archive/hls/` does not exist.**
   Not a missing timer run — the directory itself was
   never created, confirming no segment has ever been
   rotated.
4. **Every HLS segment produced since the compositor
   started is gone.** The compositor has been up for
   many hours; at 15 segments/minute, that's ~9 000
   segments today alone that hlssink2 wrote and deleted.
   LRR Phase 2's stated goal — *"Archive + Replay as
   Research Instrument"* — is blocked by a missing
   `systemctl --user enable hls-archive-rotate.timer`.

**Net impact.** LRR Phase 2 is currently closed-out at
10/10 items shipped (per alpha's retirement handoff), but
the integration point that makes the archive actually
capture data is missing. The feature is installed as code
+ systemd unit files but not as a running daemon.
**Every minute of livestream data is being discarded at
the 60-second retention boundary.** Any research analysis
that wants to replay stream data, correlate reactions
with segments, or inspect historical stimmung + audience
snapshots **has nothing to work with.**

## 1. Timing race — why rotation must run continuously

Timeline:

```
t=0    hlssink2 writes segment N
t=4    hlssink2 writes segment N+1 (→ 16 files in dir)
t=4    hlssink2 deletes segment N-14 (now 15 files)
t=60   segment N+15 written, segment N deleted
```

Every segment lives ~60 seconds in the cache before
hlssink2's `max_files=15` threshold prunes it. The
rotation helper's `STABLE_MTIME_WINDOW_SECONDS = 10`
means it waits 10 seconds after a segment's mtime stops
advancing before rotating.

**So a segment is rotatable from t+10 to t+60 — a
50-second window.** The timer runs every 60 seconds
(`OnUnitActiveSec=60s`), which should catch each segment
once if the timer is active.

But when the timer is **not** active, every segment ages
out of the cache at t+60 and is deleted by hlssink2
before anything can rotate it. The window collapses to
zero.

## 2. Live state — all three pieces of evidence

### 2.1 Cache directory state

```text
$ ls ~/.cache/hapax-compositor/hls/ | wc -l
17                                             # 16 .ts + 1 stream.m3u8

$ du -sh ~/.cache/hapax-compositor/hls/
63M     ~/.cache/hapax-compositor/hls/

$ ls -la ~/.cache/hapax-compositor/hls/*.ts | head -3
-rw-r--r-- segment00488.ts  (~60 s old)
-rw-r--r-- segment00489.ts
-rw-r--r-- segment00490.ts
```

16 segments, 63 MB total, ~60-second playlist window. The
segment numbers are monotonically increasing (currently
around 500) — this isn't the first time the compositor
has produced HLS output. The older numbered segments
(`00000` through `00487`) have already been deleted by
hlssink2's `max_files: 15`.

### 2.2 Archive destination

```text
$ ls -la ~/hapax-state/stream-archive/hls/
ls: cannot access '~/hapax-state/stream-archive/hls/':
   No such file or directory
```

The target directory doesn't exist. Not "empty" — **it
was never created**. The `rotate_segment` helper in
`hls_archive.py:146` does `target_dir.mkdir(parents=True,
exist_ok=True)` — so the first successful rotation would
create it. It has never fired.

### 2.3 Systemd unit state

```text
$ systemctl --user status hls-archive-rotate.timer --no-pager
Unit hls-archive-rotate.timer could not be found.

$ journalctl --user -u hls-archive-rotate.service --since "1 hour ago"
-- No entries --
```

Timer is not known to systemd. That means either:

- The unit file is in the repo at
  `systemd/units/hls-archive-rotate.timer` but no
  `systemctl --user enable` has been run for it
- OR no symlink from `~/.config/systemd/user/` to the
  repo's unit file has been created

Checked:

```text
$ find ~/.config/systemd/user -name "hls-archive*"
(no matches)
```

Confirmed: **not installed into the user systemd tree at
all.**

## 3. The one-line fix (not shipping from this drop)

Alpha needs to:

```bash
# Create the symlink (assuming the ops convention elsewhere
# in the council systemd units is symlink-not-copy):
ln -s ~/projects/hapax-council/systemd/units/hls-archive-rotate.service \
      ~/.config/systemd/user/hls-archive-rotate.service
ln -s ~/projects/hapax-council/systemd/units/hls-archive-rotate.timer \
      ~/.config/systemd/user/hls-archive-rotate.timer

systemctl --user daemon-reload
systemctl --user enable --now hls-archive-rotate.timer

# Verify:
systemctl --user status hls-archive-rotate.timer
journalctl --user -u hls-archive-rotate.service --since "5 minutes ago"
```

After enablement, the first timer fire (within 2 minutes
of boot + 60-second intervals after) will create the
archive directory and move the first batch of stable
segments. Archive starts populating immediately.

**Delta is not running these commands from this drop.**
`systemctl --user enable` is an installer-level operation
and per the ops rule delta stays in research lane. Flag
for alpha or operator.

## 4. Retroactive data loss and scope

What's been lost so far:

- Compositor uptime to process restart: ~5 min 38 s
  (elapsed 10:40–10:46 at the sample time)
- HLS writer cadence: ~15 segments/minute
- Data lost to hlssink2 pruning: every segment that aged
  past the 60-second window

**The compositor was restarted multiple times today**
(per sprint-5 delta audit § 8.1 and subsequent drops).
Each restart resets the segment counter to 0 and starts
a new HLS stream. Between restarts the writer runs at
~15 seg/min, each ~4 MB → ~60 MB/min of raw HLS data
produced and then deleted.

Over a full day of continuous streaming, **~86 GB of
HLS data** would have been produced and deleted. That's
the budget LRR Phase 2 was supposed to capture into
`~/hapax-state/stream-archive/`.

The data is gone. Starting fresh after the fix lands is
the only option.

## 5. Design note — hlssink2 retention should be lenient

Even with the rotation timer installed, the current
config has **no safety margin** for transient rotation
failures. If the rotation timer fails for any reason
(e.g. disk full on the archive target, or a spec bug
that makes one pass error out), hlssink2 continues
deleting segments while the rotation is stuck.

**Recommended config change** (not an urgent fix, belongs
in a follow-up PR):

```yaml
# agents/studio_compositor/models.py — hls config
class HlsConfig:
    playlist_length: int = 10      # unchanged — client-facing playlist
    max_files: int = 120           # was 15 → 8 minutes of cushion
```

At `max_files=120` and 4-second segments, hlssink2 keeps
**8 minutes** of segments before deletion. That gives
the rotation timer multiple retry opportunities per
segment — if one pass errors out, the next pass still
catches it. Costs ~480 MB of cache disk budget
(120 × 4 MB), trivially affordable given `/` has
677 GB free.

## 6. Observability gap — no alert on this

The `hapax-health-monitor.service` (drop #14 § Ring 3
references it) exists as a periodic health check but
**does not check the HLS archive path for staleness**.
A LRR-aware health check would alert on:

- `stream-archive/hls/$(today)/` missing or empty while
  compositor is running and hlssink2 is producing
- `hls-archive-rotate.service` not firing for >5 minutes
  while compositor is active
- archive growth rate << expected (
  `~60 MB/min × 60 / max_files ratio`)

Without any of these checks, the rotation being dormant
could persist for weeks before someone notices. **This
finding itself was only surfaced because delta went
looking for the rotation path on day 1 of the ship.**

Flag for alpha to add a `check_hls_archive_rotation`
health monitor probe.

## 7. Follow-ups

Ordered by drop-everything severity:

1. **Enable the timer.** One `systemctl --user enable
   --now hls-archive-rotate.timer` call. Requires the
   symlink from `~/.config/systemd/user/` into the repo
   unit file — convention per other council units. Zero
   downtime, zero risk.
2. **Bump `max_files` in hls config** to 120 or higher.
   Provides multi-pass safety margin for the rotation.
   One-line change in `models.py:61`.
3. **Add `check_hls_archive_rotation` health monitor
   probe** so a future regression is loud instead of
   silent. One check, returns stale when
   archive-growth-rate is zero during compositor
   activity.
4. **Acknowledge the retroactive data loss** in the LRR
   Phase 2 close-out doc. The archive began on
   2026-04-14 at timer-enable-time, not at PR #797 merge
   time. Downstream analyses that assume archive data
   exists back to merge-time will need to be scoped to
   enable-time onward.

## 8. References

- `agents/studio_compositor/hls_archive.py` — the rotation
  code, 251 lines
- `scripts/hls-archive-rotate.py` — CLI wrapper that the
  service invokes
- `systemd/units/hls-archive-rotate.service` — service
  unit, `Type=oneshot`, `Nice=10`, IO best-effort
- `systemd/units/hls-archive-rotate.timer` — timer unit,
  `OnBootSec=2min OnUnitActiveSec=60s`
- `agents/studio_compositor/models.py:60-61` — hls
  config defaults (`playlist_length: 10`, `max_files: 15`)
- `agents/studio_compositor/recording.py:100-103` —
  hlssink2 element construction
- Alpha retirement handoff (PR #800,
  `docs/superpowers/handoff/2026-04-14-alpha-continuation-retirement.md`)
  — Phase 2 reported as 10/10 items shipped
- Live probes: `ls` on cache + archive paths, `systemctl
  --user status` on the timer, `journalctl --user -u`
  on the service — all at 2026-04-14T16:17 UTC

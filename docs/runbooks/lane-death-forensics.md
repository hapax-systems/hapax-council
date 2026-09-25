# Lane death forensics — where a dead lane's evidence is, and how liveness is judged

**Why this exists.** On 2026-09-16T01:19:34Z a lane's `claude` died with no coredump, no
kernel line, no oomd record and no supervisor or launcher kill. tmux tore the pane down with
the process, so the exit status, the signal and the scrollback were gone: the cause was not
unknown, it was *unmeasurable*. Task
`lane-death-forensics-remain-on-exit-and-supervisor-liveness-20260916`, PR #4675.

## What changed, in one table

| piece | before | now |
|---|---|---|
| lane window (`hapax-claude`, `hapax-codex`) | tmux default: pane closes with its process | `remain-on-exit failed`: a signal death or non-zero exit **keeps** the pane; a clean exit still closes it |
| supervisor liveness (`hapax-lane-supervisor`) | `tmux has-session` | a session is alive only if at least one of its panes has `pane_dead=0`; a session of only dead panes is DEAD |
| respawn | `new-session` refused over the corpse (lane wedged) | the corpse is **captured, then killed**, then the launcher runs |
| tmux targets | bare names | anchored `=name`; pane lists read server-wide and filtered on the exact name |

## Where the evidence is

Each death writes one file:

```
~/.cache/hapax/tmux-pane-exits/<UTC stamp>-<lane>.log
```

containing, per pane: `pane_dead_status`, `pane_dead_signal` (mutually exclusive — a signal
death has an empty status), `pane_dead_time`, `pane_start_command`, and the last 60 lines of
scrollback. Retention is 30 days, pruned after each capture.

Knobs: `HAPAX_PANE_EXIT_LOG_DIR` (default above), `HAPAX_PANE_EXIT_RETENTION_DAYS` (default 30).

## Recheck commands

After a suspected death, before touching the lane:

```bash
ls -t ~/.cache/hapax/tmux-pane-exits | head            # newest certificate first
tmux list-panes -a -F '#{session_name} #{pane_id} pane_dead=#{pane_dead} status=#{pane_dead_status} signal=#{pane_dead_signal}'
journalctl --user -u hapax-lane-supervisor --since -1h | grep -E 'dead pane retained|forensics'
```

A supervisor line reading `forensics NOT written to …` means the capture failed (usually an
unwritable log directory); the line names the fix. The corpse is still cleared so the lane
can relaunch — the evidence for *that* death is lost, so fix the directory before the next.

If a launcher prints `could not set remain-on-exit on <session>`, the lane is running but a
bad death will leave nothing to read; the message names the checks (`tmux -V` ≥ 3.2).

## Things to know

- **A planned reboot mints certificates.** Lanes SIGKILLed by a shutdown timeout leave a
  log each for a death that is not a fault. `failed` ignores clean exits, so an orderly
  `systemctl --user stop` closes the pane silently. There is deliberately no
  shutdown-aware suppression: it would be a guess at a condition not yet measured.
- **Exact names matter.** tmux resolves a bare target by exact name, then prefix, then
  fnmatch, and lane names nest (`cx-cap` / `cx-cap-money`). Measured on tmux 3.7c: with only
  `hapax-claude-delta-2` running, `has-session -t hapax-claude-delta` succeeded and
  `kill-session -t hapax-claude-delta` killed the sibling. Every session target in the
  supervisor and the launchers is therefore `=name`, and `list-panes` — where `=` does not
  anchor — is replaced by a server-wide listing filtered on the exact name.
- **Why not a tmux hook.** `pane-died` does fire under `remain-on-exit failed` and its
  fields resolve, but a hook that only writes the log leaves the corpse in the launcher's
  way; the capture and the kill must be one ordered unit owned by whoever respawns, and a
  hook set at launch misses sessions older than the change. The supervisor owns both.

## Tests

`tests/scripts/test_lane_supervisor_pane_death_forensics.py` — fake-tmux cases (call order,
exact-name resolution, failure paths) and real-tmux cases on a private socket
(`tmux -L`). Real-tmux cases skip without tmux ≥ 3.2; set `HAPAX_TEST_REQUIRE_TMUX=1` to make
that skip a failure, so a run that never touched a real server cannot pass as one that did.

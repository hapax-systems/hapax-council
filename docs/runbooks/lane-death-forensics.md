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
| respawn | `new-session` refused over the corpse (lane wedged) | for an unclaimed lane, the corpse is **captured, then killed**, then the launcher runs after occupancy and claim rechecks; active claims hold recovery |
| tmux targets | bare names | anchored `=name`; pane lists read server-wide and filtered on the exact name |

## Where the evidence is

When an unclaimed lane reaches dead-pane capture, the supervisor attempts to write:

```
~/.cache/hapax/tmux-pane-exits/<UTC stamp>-<lane>.log
```

containing, per pane: `pane_dead_status`, `pane_dead_signal` (mutually exclusive — a signal
death has an empty status), `pane_dead_time`, `pane_start_command`, and the last 60 lines of
scrollback. Retention is 30 days, pruned after each capture.

An active claim holds recovery before this capture step. Its retained pane may therefore
have no pane-exit file; inspect the claim-holder receipt and the retained pane instead.

Knobs: `HAPAX_PANE_EXIT_LOG_DIR` (default above), `HAPAX_PANE_EXIT_RETENTION_DAYS` (default 30).

## Recheck commands

After a suspected death, before touching the lane:

```bash
ls -t ~/.cache/hapax/tmux-pane-exits | head            # newest certificate first
tmux list-panes -a -F '#{session_name} #{pane_id} pane_dead=#{pane_dead} status=#{pane_dead_status} signal=#{pane_dead_signal}'
journalctl --user -u hapax-lane-supervisor --since -1h | grep -E 'dead pane retained|forensics'
```

A supervisor line reading `forensics NOT written to …` means the capture failed (usually an
unwritable log directory); the line names the fix. For an unclaimed lane, the corpse is still
cleared so the lane can relaunch after occupancy and claim rechecks — the evidence for
*that* death is lost, so fix the directory before the next.

An active claim holds automatic recovery even when its session is dead and another pane
keeps the role alive. The supervisor reports `claim_holder_live`, `claim_orphaned`, or
`claim_orphan_unresolved`; non-live observations retain claim, epoch and task-note hashes
in the lane bus when those inputs exist (otherwise the hash is null). Inspect them with:

```bash
journalctl --user -u hapax-lane-supervisor --since -1h | grep -E 'claim_holder_live|claim_orphaned|claim_orphan_unresolved|pane_changed_during_capture'
lane=gamma  # replace with the lane named in the supervisor event
claim_bus="${HAPAX_SUPERVISOR_LANEBUS_DIR:-$HOME/Documents/Personal/30-areas/hapax/lanebus}"
ls -t "$claim_bus/$lane/"*claim-holder*.json | head
# Read the exact receipt path returned above:
python3 -m json.tool '<receipt-path>'
```

Use the supervisor service's configured `HAPAX_SUPERVISOR_LANEBUS_DIR` value when
it differs from the inspecting shell. To compare the receipt with current inputs:

```bash
python3 - '<receipt-path>' <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text())
key = receipt['lane'] + ('-' + receipt['session_id'] if receipt['session_id'] else '')
cache = Path.home() / '.cache/hapax'
vault = Path(os.environ.get('HAPAX_SUPERVISOR_VAULT_ROOT',
                           str(Path.home() / 'Documents/Personal/20-projects/hapax-cc-tasks')))
inputs = {'claim_sha256': cache / ('cc-active-task-' + key),
          'epoch_sha256': cache / ('cc-claim-epoch-' + key)}
if receipt['task_id']:
    note = vault / 'active' / (receipt['task_id'] + '.md')
    if not note.is_file():
        note = vault / 'closed' / (receipt['task_id'] + '.md')
    inputs['note_sha256'] = note
for field, path in inputs.items():
    expected = receipt.get(field)
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    outcome = 'unobserved' if expected is None else 'match' if actual == expected else 'changed/missing'
    print(field, outcome, path)
PY
```

Use the service's configured vault root too. A changed or missing input requires fresh
inspection; a stored hash does not certify current ownership. A live holder requires
the session and HOME to match and the process executable to match the native `claude`
resolved on the supervisor's PATH. A surviving helper or launcher is insufficient;
an unresolved executable binding holds for inspection. For a pane-change hold, use
the `tmux list-panes` command above and recheck the next supervisor tick before repair.

Preserve the claim while resolving session ownership. If an admitted rebind is unavailable,
request the exact-path approval required by
[Manual Stale-Lease Release](gate0b-claim-publication-fallback.md#manual-stale-lease-release)
and follow that procedure only after approval. Do not copy claim sidecars or launch a second writer over a
live pane or live claim. Missing or conflicting identity evidence remains an unresolved
hold; output silence alone never authorizes recovery.

Launcher cleanup also holds active or unresolved claims, including beyond the six-hour
lifetime ceiling. Immediately before SIGTERM, the reaper requires an observed terminal
task assigned to the lane, no active/unresolved lane claims, and an unchanged launcher
PID binding. The terminal claim must match the launcher's unique session PID binding
and current-task file. An empty claim is unresolved publication; another session's
terminal task cannot authorize cleanup. A session PID file older than the process is
stale evidence and holds. Missing claims or notes do not prove completion. For `reap_hold`, inspect
the claim events and receipts above plus the launcher's task and PID binding, then
recheck the next tick; preserve the lease until governed repair is authorized.

```bash
python3 - "$lane" <<'PY'
import os
import sys
from pathlib import Path

lane = sys.argv[1]
runtime = Path(os.environ.get('HAPAX_SUPERVISOR_RUNTIME_DIR',
                             f'/run/user/{os.getuid()}/hapax-claude'))
cache = Path.home() / '.cache/hapax'
paths = [runtime / f'{lane}.launcher.pid', runtime / f'{lane}.current-task']
for binding in sorted(runtime.glob(f'{lane}-*.launcher.pid')):
    sid = binding.name[len(lane) + 1:-len('.launcher.pid')]
    paths += [binding, cache / f'session-role-{sid}', cache / f'cc-active-task-{lane}-{sid}']
for path in paths:
    print(path, repr(path.read_text()) if path.is_file() else 'MISSING')
    if path.is_file():
        print('mtime_ns', path.stat().st_mtime_ns)
pidfile = runtime / f'{lane}.launcher.pid'
pid = pidfile.read_text().strip() if pidfile.is_file() else ''
if pid.isdecimal() and int(pid) > 0:
    statfile = Path('/proc') / pid / 'stat'
    if statfile.is_file():
        fields = statfile.read_text().rsplit(')', 1)[1].split()
        print('launcher pid', pid, 'state', fields[0], 'start_ticks', fields[19])
    else:
        print('launcher process missing')
else:
    print('launcher PID unresolved; inspect the supervisor event for any /proc-discovered PID')
PY
```

Use the service's runtime-directory setting. Older or remote launchers without a
local session PID binding remain held; these inspection outputs do not authorize a
signal or claim transfer.

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

Reaper publication and binding regressions are in
`tests/scripts/test_lane_supervisor_reaper.py`. To rerun the corresponding deliberate
break/red/exact-restore/green checks in an isolated, claimed source checkout, use
`uv run python tests/scripts/test_lane_supervisor_reaper_mutations.py --output <new-directory>`.
The runner preserves logs and source hashes in that create-once directory. Historical
local mutation receipts are evidence of their recorded heads, not substitutes for
rerunning the committed tests against the head under review.

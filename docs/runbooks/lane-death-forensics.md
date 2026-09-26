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
| supervisor liveness (`hapax-lane-supervisor`) | `tmux has-session` | a session is alive only if at least one of its panes has `pane_dead=0`; a session of only dead panes is DEAD; empty, malformed or failed pane observations hold as occupied |
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
import re
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text())
cache = Path.home() / '.cache/hapax'
lane = receipt.get('lane')
raw_path = receipt.get('claim_path')
if not isinstance(lane, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', lane):
    sys.exit('receipt_path_unresolved: invalid lane; preserve receipt and inspect supervisor inputs')
if not isinstance(raw_path, str) or not raw_path:
    sys.exit('receipt_path_unresolved: missing observed path; preserve receipt and obtain a fresh observation')
claim = Path(raw_path)
prefix = 'cc-active-task-' + lane
if claim.parent != cache or not (claim.name == prefix or claim.name.startswith(prefix + '-')):
    sys.exit('receipt_path_unresolved: outside lane claim namespace; preserve receipt and inspect supervisor inputs')
epoch = cache / claim.name.replace('cc-active-task-', 'cc-claim-epoch-', 1)
if claim.is_symlink() or epoch.is_symlink():
    sys.exit('receipt_path_unresolved: symlinked input; preserve receipt and inspect claim publication')
vault = Path(os.environ.get('HAPAX_SUPERVISOR_VAULT_ROOT',
                           str(Path.home() / 'Documents/Personal/20-projects/hapax-cc-tasks')))
inputs = {'claim_sha256': claim, 'epoch_sha256': epoch}
task = receipt.get('task_id')
if not isinstance(task, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', task):
    sys.exit('receipt_task_unresolved: missing or invalid task; preserve receipt and inspect claim publication')
if task:
    note = vault / 'active' / (task + '.md')
    if not note.is_file():
        note = vault / 'closed' / (task + '.md')
    inputs['note_sha256'] = note
for field, path in inputs.items():
    expected = receipt.get(field)
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    outcome = 'unobserved' if expected is None else 'match' if actual == expected else 'changed/missing'
    print(field, outcome, path)
PY
```

`claim_path` is the observed direct file in this lane's claim cache namespace;
`session_id: null` can mean an invalid session key as well as a legacy claim. The
command uses that exact path and derives its corresponding epoch filename. It
refuses paths outside the namespace and symlinked inputs. Older receipts without
`claim_path` remain preserved evidence; obtain a fresh supervisor observation
before rechecking rather than inferring a path from an unresolved session ID.

Use the service's HOME and configured vault root too. A changed or missing input requires fresh
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
terminal task cannot authorize cleanup. The claim's epoch must name the same task
and contain a positive claim time. The note must identify that task and lane;
claim, epoch, note and launcher inputs must remain unchanged across the observation.
The covered role projection and its epoch are checked too, because they can publish
before the session claim. An active note assigned to the lane that is not terminal
also holds cleanup, covering note publication before any sidecar changes. Unknown
or changing publication holds for another tick. A session PID file older than the process is
stale evidence and holds. Missing claims or notes do not prove completion. For `reap_hold`, inspect
the claim events and receipts above plus the launcher's task and PID binding, then
recheck the next tick; preserve the lease until governed repair is authorized.

```bash
python3 - "$lane" <<'PY'
import os
import re
import sys
from pathlib import Path

lane = sys.argv[1]
runtime = Path(os.environ.get('HAPAX_SUPERVISOR_RUNTIME_DIR',
                             f'/run/user/{os.getuid()}/hapax-claude'))
cache = Path.home() / '.cache/hapax'
vault = Path(os.environ.get('HAPAX_SUPERVISOR_VAULT_ROOT',
                           str(Path.home() / 'Documents/Personal/20-projects/hapax-cc-tasks')))
paths = [runtime / f'{lane}.launcher.pid', runtime / f'{lane}.current-task',
         cache / f'cc-active-task-{lane}', cache / f'cc-claim-epoch-{lane}']
for binding in sorted(runtime.glob(f'{lane}-*.launcher.pid')):
    sid = binding.name[len(lane) + 1:-len('.launcher.pid')]
    paths += [binding, cache / f'session-role-{sid}', cache / f'cc-active-task-{lane}-{sid}',
              cache / f'cc-claim-epoch-{lane}-{sid}']
for path in paths:
    print(path, repr(path.read_text()) if path.is_file() else 'MISSING')
    if path.is_file():
        print('mtime_ns', path.stat().st_mtime_ns)
    if path.name.startswith('cc-active-task-') and path.is_file():
        task = path.read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', task):
            print('reap_hold: invalid/empty task; preserve launcher and inspect publication')
            continue
        note = vault / 'active' / (task + '.md')
        if not note.is_file():
            note = vault / 'closed' / (task + '.md')
        text = note.read_text() if note.is_file() else ''
        front = text.split('---', 2)[1] if text.startswith('---\n') else ''
        print('note', note)
        for key in ('task_id', 'status', 'assigned_to'):
            match = re.search(rf'^{key}:[ \t]*(.*)$', front, re.MULTILINE)
            print(key, match.group(1) if match else 'UNRESOLVED — preserve launcher; inspect note')
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


## Remote claim materialization holds

The Claude remote wrapper acquires `claim_role_exclusion` using the execution
host composition roots from `default_claim_publication_roots(home=Path.home())`,
keyed by the exact `HAPAX_AGENT_ROLE`. It holds that role lock across the marker,
role/session epochs and role/session claim writes. The lock does not cover a
different host, confer rebind authority or establish writer liveness. Existing
conflicting, incomplete or noncanonical claims/epochs hold. Materialization
requires either no existing role/session claim or epoch, or all four exactly
matching files with the same task and epoch. A matching role-only claim
does not identify this session as its owner, even if its task matches or this
session has a matching role marker. Any nonempty partial claim/epoch binding
holds with `remote_claim_binding_unresolved` before creating new sidecars or
executing. Preserve those files and use the governed ownership repair path;
do not complete a partial binding by retrying the remote wrapper. Sidecar reads open
without following symlinks and reject nonregular or multiply linked files;
FIFOs hold without waiting for a writer. Every sidecar is created exclusively,
or checked for exact matching bytes through that safe read. No sidecar is
truncated: matching retries preserve bytes, inode and mtime. A conflicting or
symlinked entry arriving between inspection and publication holds with
`remote_claim_binding_unresolved` before native execution; partial earlier
writes remain evidence. A matching epoch is preserved. The
session-role marker is created exclusively before any epoch or claim write;
different roles racing for one session cannot overwrite it under separate role
locks. An exact matching regular-file marker is retained without rewriting it.
A conflicting, incomplete or symlinked marker produces
`remote_session_role_unresolved` and holds before native execution. Preserve that
marker and reconcile the dispatch identity through the governed path; do not
replace it or invent another session ID to bypass the hold. This excludes other
participating remote materializers, not legacy writers that truncate markers.

An unavailable interface, invalid identity, busy lock or failed write exits 75
before native exec. The existing remote dispatch proof records `dispatch_state:
hold`, `claim_materialized: false` and `claim_materialization_reason`, retaining
role, session and task. A successful materialization also records `claim_epoch`.
Inspect the proof on the execution host (use its configured
`HAPAX_DISPATCH_PROOF_DIR`), then inspect its role/session claims and epochs before
retrying. Partial files after an I/O failure remain evidence; do not delete them
or copy a peer claim to force a handoff. Qualify the shared interface and its
Python dependencies on that execution host through the governed installation
path. Source-only tests are not installed-interface or cross-host qualification;
the supervisor signal exclusion and normal-close cleanup remain release blockers.
The candidate's default-root lookup still needs reconciliation with the peer's
independently accepted installed composition. Its source tests substitute that
interface; they do not prove exclusion with an installed publisher using a
nondefault root. Keep deployment held until that dependency is qualified.

Run this on the **execution host**, using its qualified Python environment and
the execution source root recorded for that dispatch. The proof path is the exact
file under that host's configured `HAPAX_DISPATCH_PROOF_DIR`, not a coordinator
copy. It prints the proof identity and current marker/claim/epoch hashes, checks
the host and bindings, and exits 75 for partial, conflicting or held evidence.
These reads are an inspection snapshot; they do not authorize retry, transfer or
signal and do not certify that the writer is alive.

```bash
python3 - '<execution-source-root>' '<dispatch-proof-path>' <<'PY'
import hashlib
import json
import re
import socket
import sys
from pathlib import Path

def hold(reason):
    print('remote_claim_recheck_hold: ' + reason + '; preserve proof and sidecars; inspect dispatch identity', file=sys.stderr)
    sys.exit(75)

sys.path.insert(0, sys.argv[1])
try:
    from shared.gate0b_claim_publication_install import default_claim_publication_roots
    from shared.session_identity import is_claim_keyable_session_id
    proof_path = Path(sys.argv[2])
    proof_bytes = proof_path.read_bytes()
    proof = json.loads(proof_bytes)
    cache = Path(default_claim_publication_roots(home=Path.home()).claim_cache_dir)
except Exception as exc:
    hold('contract or proof unavailable: ' + type(exc).__name__)
if not isinstance(proof, dict):
    hold('proof is not an object')
print('proof_sha256', hashlib.sha256(proof_bytes).hexdigest(), proof_path)
for field in ('actual_host', 'role', 'session_id', 'task_id', 'claim_epoch',
              'dispatch_state', 'claim_materialized', 'claim_materialization_reason'):
    print(field, repr(proof.get(field)))
role, sid, task = (proof.get(key) for key in ('role', 'session_id', 'task_id'))
if (proof.get('event') != 'dispatch_remote_exec' or proof.get('platform') != 'claude-headless'
        or proof.get('actual_host') != socket.gethostname()):
    hold('wrong execution host or proof kind')
if (not isinstance(sid, str) or sid != sid.strip() or not is_claim_keyable_session_id(sid)
        or any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value)
               for value in (role, task))):
    hold('invalid role, session or task')
epoch = proof.get('claim_epoch')
valid_epoch = type(epoch) is int and epoch > 0
expected = {cache / ('session-role-' + sid): (role + '\n').encode()}
for key in (role, role + '-' + sid):
    expected[cache / ('cc-active-task-' + key)] = (task + '\n').encode()
    expected[cache / ('cc-claim-epoch-' + key)] = (f'{epoch} {task}\n').encode() if valid_epoch else None
matched = True
for path, wanted in expected.items():
    if path.is_symlink() or not path.is_file():
        print('missing/nonregular', path)
        matched = False
        continue
    try:
        data = path.read_bytes()
        metadata = path.stat()
    except OSError as exc:
        hold('input unavailable: ' + type(exc).__name__)
    match = wanted is not None and data == wanted
    print('match' if match else 'unresolved', path, 'sha256', hashlib.sha256(data).hexdigest(),
          'inode', metadata.st_ino, 'mtime_ns', metadata.st_mtime_ns)
    matched = matched and match
if (not matched or not valid_epoch or proof.get('dispatch_state') != 'ready'
        or proof.get('claim_materialized') is not True):
    hold('materialization or current binding unresolved')
print('bindings match at inspection; independent installed qualification and liveness remain separate')
PY
```

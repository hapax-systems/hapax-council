# Codex Headless Dispatch

`scripts/hapax-codex-headless` is the governed `codex exec` launcher for `cx-*`
lanes. It must not create or repair remote worktrees until the local dispatch has
passed the task/claim gate and the single-live-lane PID guard.

Retired or wound-down relays stay fail-closed by default. Direct, read-only, or
advisory-only headless launches must not pass `--force`; they should fail at the
relay guard with a recheck command. Mutable unbound launches are blocked earlier
by `hapax-methodology-dispatch` at the durable MQ authority gate.
`scripts/hapax-methodology-dispatch --launch` may pass `--force` only after the
task validates, route policy returns `launch`, and the mutable Codex launch is
bound to a fresh, non-advisory durable MQ dispatch message with a concrete
`message_id`. That reactivates a clean retired relay without broadening
appendix/local fallback: `HAPAX_DISPATCH_HOST_FALLBACK=local` remains restricted
to the P0 Codex drain-lane rule.

Recheck dispatcher-level relay behavior from the council repo:

```bash
rg -n "def test_(codex_p0_incident_drain_lane_allows_local_fallback|codex_p0_incident_local_fallback_force_is_independent_of_reactivation_flag|governed_relay_reactivation_passes_force_to_headless_launcher|governed_codex_dispatch_reactivates_clean_retired_relay|governed_relay_reactivation_predicate_accepts_bound_mutable_launch|governed_relay_reactivation_rejects_advisory_or_unbound_binding|codex_headless_dispatch_propagates_retired_relay_block|codex_headless_dispatch_blocks_mq_bound_read_only_exempt_retired_relay)" tests/scripts/test_hapax_methodology_dispatch.py
uv run pytest tests/scripts/test_hapax_methodology_dispatch.py -q -k 'codex_p0_incident_drain_lane_allows_local_fallback or codex_p0_incident_local_fallback_force_is_independent_of_reactivation_flag or governed_relay_reactivation_passes_force_to_headless_launcher or governed_codex_dispatch_reactivates_clean_retired_relay or governed_relay_reactivation_predicate_accepts_bound_mutable_launch or governed_relay_reactivation_rejects_advisory_or_unbound_binding or codex_headless_dispatch_propagates_retired_relay_block or codex_headless_dispatch_blocks_mq_bound_read_only_exempt_retired_relay'
uv run pytest tests/scripts/test_hapax_codex_headless.py -q -k 'force_reactivates_retired_relay or blocks_retired_relay_without_force'
```

For a direct, read-only, or advisory-only launch into a retired relay, the
expected result is fail-closed at the relay guard (`retired/wound-down`) and no
Codex process start. For a mutable unbound methodology-dispatch launch, the
expected result is an earlier durable-MQ block, before the headless launcher is
invoked. For a P0 drain-lane local fallback, verify the launcher argv contains
`--force` and the environment contains `HAPAX_DISPATCH_HOST_FALLBACK=local`.

Remote appendix dispatch uses this order:

1. validate the session name, relay state, local worktree, hook adapter, task/claim,
   and live PID guard;
2. run a remote token-only preflight before any remote worktree mutation; the
   published Codex OAuth token must be fresh and accepted by `codex debug models`;
3. bootstrap the default remote session worktree if it is missing and
   `HAPAX_CODEX_CREATE_WORKTREE=1` (the unset/default value is `1`);
4. run full remote preflight for required directories, hook adapter, `python3`,
   `codex`, OAuth freshness, and `codex debug models` bearer actuation;
5. snapshot the exact preflight-proven token into a short-lived remote handoff
   file before the local `cc-claim` boundary. The handoff create is exclusive,
   `0600`, and non-following where the dispatch host exposes `O_NOFOLLOW`; a
   preexisting file or symlink is a hard preflight failure;
6. execute `codex exec` on the remote host with that handoff token, deleting the
   handoff as it is consumed. Later rotation of the published token file must not
   change the bearer used for this exec. A failed handoff deletion is a hard
   launcher failure rather than a best-effort cleanup warning.

Local headless dispatch similarly proves the published OAuth token with
`codex debug models` before `cc-claim` and reuses that proven bearer for the
subsequent `codex exec`; it must not reread a mutable token file after claim.

On the remote host, the launcher materializes both the legacy and session-keyed
claim caches plus their epoch sidecars before `codex exec` starts:
`cc-active-task-<cx-session>`, `cc-claim-epoch-<cx-session>`,
`cc-active-task-<cx-session>-<session_id>`, and
`cc-claim-epoch-<cx-session>-<session_id>`. Recheck a live remote claim with:

```bash
role=cx-amber
for f in ~/.cache/hapax/cc-active-task-"$role"*; do
  key=${f##*/cc-active-task-}
  printf '%s -> %s :: ' "$f" "$(head -n1 "$f")"
  head -n1 ~/.cache/hapax/cc-claim-epoch-"$key"
done
```

Default worktrees are constructive: if `$HOME/projects/hapax-council--<cx-session>`
is missing on the dispatch host, the launcher may create it from the remote primary
council checkout using branch `codex/<cx-session>`. Override the branch prefix with
`HAPAX_CODEX_BRANCH_PREFIX`; the unset/default prefix is `codex`.

Explicit workdirs are not constructive. If `HAPAX_CODEX_HEADLESS_WORKDIR` is set,
that exact path must already exist locally and remotely. A missing explicit path
fails closed; unset the variable or create the path deliberately before retrying.

Remote bootstrap failures print the failing branch and a next action. Check:

- target worktree path;
- remote primary council checkout;
- `git` on the dispatch host;
- `HAPAX_CODEX_CREATE_WORKTREE` (default `1`);
- `HAPAX_CODEX_BRANCH_PREFIX` (default `codex`);
- `HAPAX_CODEX_WORKTREE_BASE` if a non-default base was requested.

Recheck the contract from the council repo with:

```bash
bash -n scripts/hapax-codex-headless
shellcheck -S warning scripts/hapax-codex-headless
uv run pytest tests/scripts/test_hapax_codex_headless.py -q
uv run pytest tests/scripts/test_hapax_codex_headless.py tests/scripts/test_hapax_codex_headless_fallback.py -q
```

For the P0 dispatch-starvation exit predicate, recheck the live coordinator
predicate and P0 intake ledger after the launcher tests. Platform receipts and
lane health are supporting evidence; they do not replace the predicate that
emitted the alert (`offered_tasks > 0`, `dispatches_this_tick == 0`,
`refusal_ledger.starvation_active == true`, and
`refusal_ledger.starvation_escalated == true`):

```bash
python - <<'PY'
import json
from pathlib import Path

coordinator = json.loads(Path("/dev/shm/hapax-coordinator/state.json").read_text())
refusal = coordinator.get("refusal_ledger", {})
print(
    {
        "timestamp": coordinator.get("timestamp"),
        "offered_tasks": coordinator.get("offered_tasks"),
        "lanes_idle": coordinator.get("lanes_idle"),
        "dispatches_this_tick": coordinator.get("dispatches_this_tick"),
        "starvation_active": refusal.get("starvation_active"),
        "starvation_escalated": refusal.get("starvation_escalated"),
    }
)
PY
python - <<'PY'
import json
from pathlib import Path

fingerprint = "sdlc_dispatch_starvation:dispatched"
state = json.loads(Path("~/.cache/hapax/p0-incident-intake/state.json").expanduser().read_text())
incident = state.get("incidents", {}).get(fingerprint)
print(
    {
        "fingerprint": fingerprint,
        "count": None if incident is None else incident.get("count"),
        "last_seen": None if incident is None else incident.get("last_seen"),
        "recurrence_count": None if incident is None else incident.get("recurrence_count"),
        "task_id": None if incident is None else incident.get("task_id"),
    }
)
PY
python - <<'PY'
import json
from pathlib import Path

fingerprint = "sdlc_dispatch_starvation:dispatched"
latest = None
events = Path("~/.cache/hapax/p0-incident-intake/events.jsonl").expanduser()
for line in events.read_text().splitlines():
    if not line.strip():
        continue
    event = json.loads(line)
    if event.get("fingerprint") == fingerprint:
        latest = event
print(
    {
        "fingerprint": fingerprint,
        "latest_ts": None if latest is None else latest.get("ts"),
        "latest_count": None if latest is None else latest.get("count"),
        "latest_task_id": None if latest is None else latest.get("task_id"),
    }
)
PY
uv run python scripts/hapax-platform-capability-receipts --json
scripts/hapax-codex-health --json cx-agy cx-p0 cx-ghrate
scripts/hapax-quota-telemetry-writer --json
```

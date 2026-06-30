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
2. bootstrap the default remote session worktree if it is missing and
   `HAPAX_CODEX_CREATE_WORKTREE=1` (the unset/default value is `1`);
3. run remote preflight for required directories, hook adapter, `python3`, and
   `codex`;
4. execute `codex exec` on the remote host.

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

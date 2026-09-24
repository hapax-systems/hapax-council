# Codex Headless Dispatch

`scripts/hapax-codex-headless` is the governed `codex exec` launcher for `cx-*`
lanes. It must not create or repair remote worktrees until the local dispatch has
passed the task/claim gate and the single-live-lane PID guard.

## Invocation load evidence

Fresh local `codex.headless.full` launches freeze a
`native-*.load-set.json` beside their native stream before starting the child.
The selected release's `hapax-platform-capability-receipts` writes the existing
`PlatformCapabilityReceipt.load_sets` representation and reads it back through
the existing typed reader. A failed write, existing artifact or unequal
readback refuses the launch with exit 9. Keep failed/predecessor artifacts;
retry with a fresh launch after repairing the reported boundary.

The observation binds the declaration digest, actual native home, final `--cd`
root and prompt-free argument digest. It records explicit hook/MCP override
names after later argv overrides, flag names and declared-file hashes. Config
values, command bodies, environment values and prompt text are not persisted.
Unknown argument shapes, including resume/review/worktree submodes, refuse
instead of producing a misleading inventory; qualify their construction before
extending this bounded observer.

This is construction evidence. It does not attest native loading or instruction
use, and it does not turn unknown ambient plugins, skills, hooks or MCP into
empty sets. Host configuration presence remains a filesystem observation.
Capability, resource, quota and provider-doc probes remain unobserved in this
per-invocation receipt. Do not copy it into the host capability receipt directory
or use it to admit routes. SSH, Spark, interactive and blind-review invocations
are outside this producer's scope and receive no such observation.

## Declared execution identity

Both Codex launchers resolve identity before any auth probe, claim or spawn.
`config/platform-capability-registry.json` already contains structured
`execution_descriptor` values: at this change, `codex.headless.full` selects
`gpt-6-astra` / `xhigh`, and `codex.headless.spark` selects
`gpt-5.3-codex-spark` / `xhigh`. This change preserves those existing choices;
the task’s earlier `gpt-5.5-xhigh` census is historical. Runtime resolution
reads the structured field, never the legacy `model_or_engine` text.

Recheck the current registry without starting a native client:

```bash
uv run --no-sync python -m shared.capability_execution --route codex.headless.full --
uv run --no-sync python -m shared.capability_execution --route codex.headless.spark --
```

Installed launchers resolve the identity helper from the governed activation
root, `~/.cache/hapax/source-activation/worktree`, or its explicit
`HAPAX_SOURCE_ACTIVATE_WORKTREE` binding. An explicit `HAPAX_COUNCIL_DIR` remains
usable for a provisioned relocated source when no activation override is set.
The helper resolves its own source release and executable `.venv/bin/python`;
it does not inherit the legacy primary checkout's runtime. That source must
contain its `shared/` modules, registry and `scripts/capability-execution.sh`.
A worktree containing only copied launchers is insufficient. Restore the source
through `hapax-source-activate` or the existing Council `uv` provisioning workflow. An intentional
`HAPAX_PLATFORM_CAPABILITY_REGISTRY` override must be readable and valid.
A missing runtime, registry, route or concrete descriptor refuses with exit9
before native invocation; it never falls back to the user's default model.
`--execution-route` selects a declared Codex route; it is not admission to it.
Without that option, the named `codex.headless.full` route remains the launcher
default. Its registry descriptor is still required; this does not select a
native client's undeclared model default.

Resolver and decoder Python imports are isolated from the caller's cwd and
`PYTHONPATH`. Both launchers preserve the selected release's physical path.
Interactive runners carry that path and launcher into tmux re-entry; headless
lifecycle observation uses that release and its interpreter after native exit,
even if the activation symlink advances meanwhile. Decoded arguments must carry
both model and effort; malformed or identity-free output refuses before native
invocation. Recheck those boundaries without provider calls:

```bash
uv run pytest tests/scripts/test_capability_execution_contract.py -q
uv run --no-sync python scripts/check-execution-descriptor-mutations.py
```

This refusal applies to the governed launchers. A bare `codex` or `codex exec`
can still use the vendor built-in default; removing the repository config
default does not intercept that path. Such calls are unbound and are not
descriptor-conforming estate runs. Automatic detection/consumer integration
remains outstanding; this PR does not claim to enforce every direct CLI call.

Compare a real native rollout using the supplied checker:

```bash
uv run --no-sync python -m shared.codex_execution_receipt \
  --route codex.headless.full --rollout /absolute/owned/rollout.jsonl
```

The checker emits one declared/observed comparison per `turn_context`, including
mid-session changes. Missing observations remain unverified; mismatches remain
misattributed. Valid comparisons are printed as they are read, so a later malformed
line cannot discard an already observed mismatch. A parsing error still exits2
and names the next action; output before that error is partial evidence.

Fresh local headless dispatch also captures the descriptor and argv from one
resolution. At native exit, the lifecycle observer correlates the stream's native
session ID with its owned session store, cwd and launch time, and records the
observed rollout byte prefix. The existing methodology result reader recomputes
identity from that prefix and frozen declaration, including on result replay.
It never substitutes a later registry value or trusts a receipt's `matched` flag.
A later append does not rewrite the earlier result; changed prefix bytes,
missing evidence and wrong-session records cannot establish a match.

Process completion and identity agreement remain separate. The declaration and
ownership fields are producer claims; byte checks do not attest provider identity,
ownership or work quality. Remote runs and old receipts without the correlation
inputs retain unverified identity. Interactive and bare vendor runs are not
automatically consumed by this fresh-local-headless path, and quota telemetry
integration across all estate runs remains unfinished.

Recheck the actual producer, result reader and terminal-event replay with:

```bash
uv run --no-sync pytest -q \
  tests/scripts/test_capability_execution_contract.py::test_headless_identity_reaches_result_reader_with_frozen_declaration \
  tests/scripts/test_codex_identity_consumer.py \
  tests/shared/test_codex_run_identity.py \
  tests/scripts/test_hapax_methodology_dispatch.py::test_launch_idempotency_replays_without_second_launcher_call
```

The last test runs a successful first dispatch and verifies the serialized
terminal event and result reference on replay without another launcher call;
it also exercises missing, modified and legacy evidence. A content reference
does not retain its target. If receipt or native bytes were pruned, readback
stays unobserved; the retained reference identifies the unavailable original
and never licenses a replacement provider call.

`DispatchLaunchResult.result_ref` reuses the existing immutable `ContentAddress`
contract. Its lightweight module avoids importing the admission dependency graph
into standalone receipt readers; the original admission import remains supported.
The claim-publisher's bound source closure includes the extracted module, so a
new source activation requires the normal shipped-installer migration. Recheck
that contract, including identical and changed sources across release paths:

```bash
uv run --no-sync pytest -q tests/shared/test_content_address.py \
  tests/shared/test_gate0b_claim_publication_machinery.py \
  tests/shared/test_gate0b_descriptor_release_independence.py
```

After merge, verify the source activation's Git HEAD against the merged commit
and compare the installed `hapax-codex-headless` and
`hapax-methodology-dispatch` bytes with that release. Refresh the changed claim
source closure with the shipped `install_claim_publication_composition` in
`shared/gate0b_claim_publication_install.py`, preserving the prior receipt and
manifest, declared roots, authority bindings and non-authorizing flags. Verify
the resulting installation using the default-path checks in
[the claim-publication runbook](gate0b-claim-publication-fallback.md#default-recheck).
Run the producer/result-reader recheck above from the activated physical release
with its pinned interpreter. These checks establish source and installed-byte
activation for this consumer, not a production container migration or proof of
every native invocation.

```bash
release_root="$(readlink -f "$HOME/.cache/hapax/source-activation/worktree")"
git -C "$release_root" rev-parse HEAD  # Compare with the PR's actual merge SHA.
cmp "$HOME/.local/bin/hapax-codex-headless" "$release_root/scripts/hapax-codex-headless"
cmp "$HOME/.local/bin/hapax-methodology-dispatch" "$release_root/scripts/hapax-methodology-dispatch"
```

Lifecycle ownership remains a receipt claim. Existing coordination replay does
not exclude concurrent or interrupted inflight launches. This local reader's
absolute paths are not a portable artifact resolver for arbitrary remote workers.
A null result reference does not distinguish an absent collector from failed
collection. Collector warnings go to the process logging output; consult them
and native diagnostics if retained. The terminal event does not retain that
failure reason, so a later replay cannot reconstruct it from null alone. Neither case
changes the already observed launcher outcome or establishes identity agreement.
The shared reader preserves validated Claude lifecycle evidence, but replaces
receipt-carried Claude model identity with `unverified` until an implemented
checker can revalidate it. Other lifecycle mappings remain unsupported.

The contract test includes a redacted field projection from a captured native
Codex0.155.1 rollout, with original event/file hashes and provenance in
`tests/fixtures/codex-native-turn-context-0.155.1.md`. It pins the observed
`model`/`effort` field names independently of generated checker fixtures.

Governed Claude and Vibe dispatch likewise passes descriptor-derived values.
Vibe dispatch refuses missing identity or an effort without a native mapping;
it always sets `VIBE_ACTIVE_MODEL`, which its generated terminal runner exports.
Direct unbound Vibe invocations are outside that dispatch claim and are not
receipt evidence. Recheck actual controlled native-child delivery with
`uv run pytest tests/test_methodology_dispatch_model_pin.py -q`.

For an already authorized Claude task/lane, the native availability recheck is
one ordinary dispatch, for example
`scripts/hapax-methodology-dispatch --task TASK --lane LANE --platform claude --mode headless --profile opus --launch`.
Inspect that invocation’s native initialization/transcript model against
`resolve_execution_descriptor("claude.headless.opus").model_id` and the
requested effort. A successful launcher exit or controlled argv recorder alone
is not this observation. The source tests establish concrete argument delivery;
this PR does not claim new provider availability measurements for every profile.
The printed Claude path templates now use this governed entrypoint, preserving
the selected profile rather than suggesting an unbound direct launch.

A bounded native check on 2026-09-21 at05:36Z used Claude Code2.1.278, the
declared `claude-opus-4-8` / `xhigh`, one turn, no tools or MCP, and saved
subscription authentication. It exited0 with the requested sentinel; both
native initialization and the assistant event reported `claude-opus-4-8`.
This verifies concrete-id acceptance for that invocation, not all profiles,
provider-side identity, or an independently observed reasoning effort.

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
2. run a remote saved-login auth preflight before any remote worktree mutation;
   the dispatch host must already have a working `codex login` session, and the
   preflight runs a bounded `codex exec` sentinel with inherited Codex auth
   env stripped (`CODEX_ACCESS_TOKEN`, `CODEX_HOME`, `CODEX_API_KEY`, and
   `OPENAI_API_KEY`);
3. bootstrap the default remote session worktree if it is missing and
   `HAPAX_CODEX_CREATE_WORKTREE=1` (the unset/default value is `1`);
4. run full remote preflight for required directories, hook adapter, `python3`,
   `codex`, and saved-login `codex exec` actuation;
5. after the local `cc-claim` boundary accepts the dispatch, carry the matching
   local `cc-claim-epoch-<cx-session>` line plus matching `cc-active-task` as the
   remote claim proof, then rerun the remote saved-login preflight;
6. execute `codex exec` on the remote host using that host's saved ChatGPT auth.
   The launcher never ships, injects, persists, or reuses a published bearer
   token, and remote exec strips inherited Codex auth env before starting.

Local headless dispatch similarly proves saved-login auth with a bounded
`codex exec` sentinel before `cc-claim`; it must strip inherited Codex auth env
and must not treat published token caches or API-key env as authority.

If appendix reports `token_invalidated` or `refresh_token_invalidated`, refresh
the dispatch-host login and recheck the sentinel before launching governed lanes:

```bash
ssh -t appendix 'codex login'
ssh appendix 'bash -lc '\''unset CODEX_ACCESS_TOKEN CODEX_HOME CODEX_API_KEY OPENAI_API_KEY; exec codex exec --ephemeral --skip-git-repo-check --ignore-rules --sandbox read-only --json --cd ~ "Reply exactly: HAPAX_CODEX_EXEC_AUTH_OK"'\'''
```

If `codex login --device-auth` is unavailable by account or workspace policy,
use the documented saved-login cache fallback only under explicit
credential-transfer authorization. Treat `~/.codex/auth.json` like a password:
do not paste it into chat, tickets, task notes, or logs. Copy from a
browser-authenticated host to the dispatch host, preserve an owner-only backup,
and immediately re-run both the host sentinel and the platform capability
receipt probe:

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
ssh appendix "bash -lc 'mkdir -p ~/.codex && chmod 700 ~/.codex && if [ -f ~/.codex/auth.json ]; then cp -p ~/.codex/auth.json ~/.codex/auth.json.pre-copy-$stamp; fi'"
ssh appendix "bash -lc 'umask 077; cat > ~/.codex/auth.json.tmp && chmod 600 ~/.codex/auth.json.tmp && mv ~/.codex/auth.json.tmp ~/.codex/auth.json'" < ~/.codex/auth.json
ssh appendix "bash -lc 'stat -c \"%a %U %G %s\" ~/.codex/auth.json && unset CODEX_ACCESS_TOKEN CODEX_HOME CODEX_API_KEY OPENAI_API_KEY && codex login status'"
ssh appendix 'bash -lc '\''unset CODEX_ACCESS_TOKEN CODEX_HOME CODEX_API_KEY OPENAI_API_KEY; exec codex exec --ephemeral --skip-git-repo-check --ignore-rules --sandbox read-only --json --cd ~ "Reply exactly: HAPAX_CODEX_EXEC_AUTH_OK"'\'''
HAPAX_CODEX_EXEC_AUTH_HOST=appendix uv run python scripts/hapax-platform-capability-receipts --platform codex --codex-exec-auth-probe --json
scripts/hapax-quota-telemetry-writer --json
```

`scripts/hapax-quota-telemetry-writer` must not mark Codex subscription quota
fresh while the current fresh Codex platform capability receipt reports
`codex_exec_auth_failed`, `codex_exec_auth_token_invalidated`, or
`codex_exec_auth_refresh_token_invalidated`; it records the subscription snapshot
as `unknown` until a repaired receipt is observed. When no dispatch-host
environment is set, telemetry and availability admission bind to the platform
receipt probe's default appendix witness. Local/current-host witnesses are only
accepted when `HAPAX_CODEX_EXEC_AUTH_HOST`, `HAPAX_DISPATCH_HOST`, or
`HAPAX_DEFAULT_DISPATCH_HOST` explicitly selects that host. If receipt refresh
itself is stale or skipped, dispatch launchers still run their saved-login
preflight and must fail closed before starting Codex work.

On the remote host, the launcher materializes both the legacy and session-keyed
claim caches plus their epoch sidecars before `codex exec` starts, using the
matched local claim epoch. Remote exec refuses task-bound dispatch if the local
payload lacks a matching `HAPAX_METHODOLOGY_DISPATCH_CLAIM_EPOCH`; it must never
invent a fresh epoch from `HAPAX_METHODOLOGY_DISPATCH_TASK` alone:
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
- saved-login Codex auth on the dispatch host with inherited Codex auth env
  stripped (`CODEX_ACCESS_TOKEN`, `CODEX_HOME`, `CODEX_API_KEY`, and
  `OPENAI_API_KEY`).

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
`refusal_ledger.starvation_escalated == true`).

Pre-merge source review can prove the source predicate, launcher contract, and
regression coverage, but it cannot honestly claim that the live incident is
closed while `hapax-coordinator.service` is still running the `origin/main`
source-activation release. If the live predicate is still active only because
the PR head is not deployed, record the state as
`post_merge_runtime_activation_required`, keep the incident open, and do not
mark the P0 exit predicate cleared until the merged or otherwise governed
runtime activation has been restarted and rechecked.

Run this on the coordinator host. If the coordinator state path is non-default,
set `HAPAX_COORDINATOR_STATE_PATH` before running the command.

```bash
python - <<'PY'
import json
import os
from pathlib import Path

state_path = Path(os.environ.get("HAPAX_COORDINATOR_STATE_PATH", "/dev/shm/hapax-coordinator/state.json"))
if not state_path.exists():
    raise SystemExit(
        f"coordinator state missing at {state_path}; run on the coordinator host "
        "or set HAPAX_COORDINATOR_STATE_PATH"
    )
coordinator = json.loads(state_path.read_text())
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
uv run python scripts/hapax-platform-capability-receipts --platform codex --codex-exec-auth-probe --json
scripts/hapax-codex-health --json cx-agy cx-p0 cx-ghrate
scripts/hapax-quota-telemetry-writer --json
```

# Estate store registration — Stage 1

Status: report-only. The accepted coordination baseline is installed/disabled;
this document describes the producer interface, not a live runtime readback.

`config/estate-store-registry.yaml` is the passive enumeration artifact. The
reader in `shared.estate_store_registry` returns only entries declared for the
calling consumer. It never discovers an undeclared filesystem path on a
consumer's behalf. The sweep is the separate reality check.

## Report surfaces

A sweep writes JSON reports beneath
`~/.cache/hapax/estate-registration/reports/`. Individual Canary B flags,
canary registrations, and detector state live under the same declared runtime
store. Stage 1 writes reports and receipts only. Its report records
`mutation_actions: []`; it has no rename, move, delete, quarantine, or restore
operation.

The existing `docker-volumes` scan root declares `kind: docker-volumes`, retaining
`path: /var/lib/docker/volumes` and its depth-one filesystem observation. The
scanner also runs exactly `docker volume ls --format '{{.Name}}'` through the same
bounded process-capture helper used by SSH. This binding needs names only; it does
not query sizes or mountpoints or invoke any other Docker verb. Volume names map
to candidates below the declared root, with kind `docker-volume`; these paths
are registry locators, not inspected mountpoints. Invalid names fail the read.

The report and local completion line carry `root_observations`, one entry per
Docker root, with two named observations: `filesystem` and `docker-volume-ls`.
Both successful and failed CLI results retain exact stdout/stderr, the observed
return code, the 15-second timeout bound and any transport failure. Missing
executables and timeouts record `returncode: absent`. Partial failed output is
evidence only and does not become a list of candidates. Zero names is a successful
empty CLI read, distinguishable from every failure.

Either observation failing leaves the root `read-failed`, retains a `scan-error`
finding and makes the sweep exit 2. In particular, successful CLI enumeration
does not erase a filesystem permission error or qualify that sweep as clean.
`read-ok` requires both observations to succeed and does not assert that all
candidates are registered. Failed roots are never dropped. `root_observations`
is an empty list for a completed sweep whose registry has no Docker roots;
ordinary root failures continue to appear in `findings` as `scan-error`.

Vendor binary roots, including `~/.claude`, `~/.codex`, `~/.kimi-code`,
`~/.gemini`, `~/.grok`, and the opencode store, are permanently
`class: vendor-root, action: flag-only`. Registry validation refuses a stronger
action even if a future stage changes the general policy.

The grandfather command writes a reviewable YAML fragment and refuses an
incomplete scan. Every emitted row is `lifecycle: grandfathered`, carries the
scan root and timestamp that discovered it, and records
`operator_blessing: null`. It does not edit the registry or confer blessing:

```bash
uv run python scripts/hapax-estate-store-registry grandfather \
  --host appendix --output reports/appendix-grandfather.yaml
```

## Canary contract

The hourly originator writes both canaries on its local host. Canary A writes a
unique artifact under the registered runtime store and a matching runtime
registration receipt. Canary B writes a unique store-shaped directory beneath
`30-areas/hapax`; at UTC hour 00 it instead writes a new `$HOME` dotfile root.
It has a manifest but deliberately has no registration.

The opposite host checks Canary A over the existing SSH link within 90 minutes.
It also requires the same origination event's Canary B manifest, so a partially
dead originator is not reported healthy. The daily unit asks the opposite host
to run its own sweep. A dead host, broken SSH link, stale Canary A, or incomplete
pair makes the peer unit fail loudly.

## Physical source binding

Both `scripts/hapax-estate-store-registry` and the declaration checker promote
the resolved script tree to `sys.path[0]` unconditionally, removing duplicate
occurrences before importing `shared`. They then verify that `shared.__file__`
resolves beneath that physical tree before importing its submodules. An inherited
`PYTHONPATH` or editable install cannot put a different checkout ahead of it.
A cached foreign `shared` package refuses with exit 2 and a repair/restart remedy.
The producer emits a failed completion line even for that bootstrap refusal;
host, argument and boot observations have not run yet and remain `absent`.
`source.verified_shared_root` records the verified root on success and `absent`
on bootstrap refusal. The checker's JSON report carries the same verified root.

`sweep-peer` and `check-peer` accept `--peer-source-root /absolute/physical/release`.
The default is `HAPAX_ESTATE_PEER_SOURCE_ROOT`, so a coordinator-owned service
drop-in can supply the separately verified opposite host's retained release
without constructing a shell command. An explicit option overrides the environment.
The caller must verify release integrity and retention before supplying this path;
a commit-shaped directory name alone proves neither.

`--qualified` requires the binding even without native service metadata. Any
observed `INVOCATION_ID`, `SYSTEMD_EXEC_PID`, or `TRIGGER_*` variable listed below
also requires it. Missing, relative, non-normalized and control-character paths
refuse before SSH. On the peer, `realpath -e` and physical working-directory
readback must agree with the supplied root. The script and registry must resolve
inside that same root without symlink redirection. A refusal names
`peer_source_root` and the remedy. The peer invokes the verified physical release's
explicit `<release>/.venv/bin/python -I` and absolute artifact paths with
`--expected-source-root`; the CLI checks its resolved script tree and registry
against that expectation. If that interpreter is missing or not executable,
execution refuses with exit 2, the exact interpreter path and the remedy to
provision the verified release virtual environment before enabling. There is no
fallback interpreter. The command contains no `uv`, so `UV_PROJECT_ENVIRONMENT`,
`UV_CONFIG_FILE`, `UV_PYTHON` and other uv configuration cannot redirect execution.
Python's `-I` isolates it from Python environment overrides. The venv executable
may be a normal virtual-environment symlink; release/venv integrity is still an
admission responsibility.

An unqualified manual call may omit the binding. It resolves the legacy
`$HOME/.cache/hapax/source-activation/worktree` alias once, before execution,
then uses the physical destination. Evidence records `source_binding.kind:
alias`, the requested alias, and the actual physical source separately. Alias
promotion after that resolution does not redirect the execution. Retention and
source-integrity admission remain the coordinator's responsibility; this
producer does not replace the source activator.

## Complete command and environment interface

`--host` requests a registry label; it is not an observation of the executing
machine. Every command reads `/proc/sys/kernel/hostname` (the explicit Linux
kernel hostname source, without an environment or resolver fallback) and
`/etc/machine-id` read-only. It compares the hostname with the resolved label
and its declared aliases, and the machine id with `hosts.<label>.machine_id`.
Boot identity continues to come from `/proc/sys/kernel/random/boot_id`.
Identity observations and their binding live only in completion evidence;
no field is added to the v1 drift report or stdout summary for this binding.

The checked-in registry declares both coordinator-verified machine ids, read at
2026-09-05T06:40Z:

| Host | `hosts.<label>.machine_id` | Readback source |
|---|---|---|
| appendix | `ffc36d1a0ca64320a3f1c9f1060292af` | `/etc/machine-id` on hapax-appendix, locally |
| podium | `15c4e584aac74d048bcbe90fc35e6da3` | `/etc/machine-id` on hapax-podium, over read-only SSH |

Read a host's id with `cat /etc/machine-id` on that host. The coordinator used
`ssh hapax-podium cat /etc/machine-id` for podium's readback. These commands read
identity only; updating a declaration requires separately verified readback.
The producer never learns or installs an expected identity from the peer it is
checking. A missing declaration still records
`local_declared_machine_id_absent` / `peer_declared_machine_id_absent` and prevents
`ok` completion.

An own-label mismatch on a qualified run is a binding failure and refuses before
any scan, write or SSH dispatch. This includes explicit `--qualified` and native
service metadata without an identity override. An unqualified manual run, or an
explicit fixture override without `--qualified`, records each named mismatch
and continues. Its `identity_binding.status` remains `failed` to preserve the
comparison result, while successful execution completes `unqualified` with
`scheduled: absent`. Scan or transport failures still fail the execution.
The same binding checks the peer completion in both declared directions, independently
of the consistent requested label in its report and summary. The actual SSH
argv target is retained and checked against the requested peer's declared
`ssh_target` and aliases. Mismatch errors name the requested label, observed
value and declaration (and the dispatched target for a peer). Peer binding
failures produce `peer.status: failed` and a nonzero initiator exit.

Unreadable, empty or undecodable native identity fields become `absent` and
make successful execution `unqualified`, including with `--qualified`. Without
either a requested label or an observed hostname, execution stops unqualified
before dispatch or writes. A missing boot id still fails as before.
`--observed-host-override HOSTNAME MACHINE_ID` is the sole producer fixture
binding: it replaces the two identity observations, names itself in evidence
and errors, and can never produce `ok` or `scheduled: true`. Overrides still
undergo declaration checks; local mismatches are recorded and continue unqualified.
`--qualified` refuses the flag
outright, including when its values match. The override is never forwarded to
the peer. Qualified peer dispatch forwards `--qualified`; the initiator also
rejects peer override evidence when explicitly invoked with `--qualified`.

The positional command is one of `list`, `originate`, `export-canary`,
`check-peer`, `sweep`, `sweep-peer`, or `grandfather`. Options are accepted by
the common parser; only the named operations use each operation-specific option.

| Flag | Default and effect |
|---|---|
| `-h`, `--help` | Print parser help and exit; no execution evidence line |
| `--registry PATH` | Running physical tree's `config/estate-store-registry.yaml`; local registry for every command |
| `--host ID_OR_ALIAS` | Requested label or alias; defaults to the natively observed hostname, resolved through the registry; every command checks the independent observed identity |
| `--observed-host-override HOSTNAME MACHINE_ID` | Unset; CLI-only fixture binding for both observations, empty values become `absent`; always recorded and unqualified (or failed), never scheduled; refused by `--qualified` |
| `--home PATH` | `Path.home()`; local home/vault/runtime path binding, never forwarded to the peer |
| `--consumer NAME` | Unset; required by `list`. Choices validated by reader: `assemble`, `brief-dispatch`, `census`, `drift-sweep`, `pillar-matcher`, `task-intake` |
| `--report-root PATH` | Registry `policy.reports_path`; local `sweep` only |
| `--output PATH` | Unset; required by `grandfather`, must resolve inside the current worktree |
| `--json` | False; JSON stdout instead of YAML. Peer commands always request and forward peer JSON |
| `--peer-source-root PATH` | `HAPAX_ESTATE_PEER_SOURCE_ROOT` or unset; `check-peer` and `sweep-peer`, explicit flag wins |
| `--qualified` | False; refuses own-label identity mismatches and local or peer observed-identity overrides; requires an explicit physical peer binding for peer commands; forwarded on qualified peer dispatch; does not attest scheduling or supply missing identity declarations |
| `--expected-source-root PATH` | Unset; every command refuses a different physical script tree, registry or redirected registry path |
| `--include-report` | False; local `sweep` adds exact report bytes as `report_base64` to stdout; always passed by `sweep-peer` |

There is no `-o` short option on the producer. `--output` is the grandfather
artifact option, not an execution-evidence destination. Completion evidence goes
to stderr. Parser errors and help exit before evidence construction.

| Environment binding | Use |
|---|---|
| `HAPAX_ESTATE_PEER_SOURCE_ROOT` | Peer-root option default; unset means no explicit root, empty is an invalid explicit path |
| `INVOCATION_ID`, `SYSTEMD_EXEC_PID`, `TRIGGER_UNIT`, `TRIGGER_PATH`, `TRIGGER_TIMER_REALTIME_USEC`, `TRIGGER_TIMER_MONOTONIC_USEC` | Copied into `native` or `absent` when empty/unset. Any value other than the `absent` sentinel requires the physical peer binding. Scheduling calculation is specified below |
| `HOME` | Standard `Path.home()` default locally; peer shell uses its own `$HOME` only when resolving the unqualified legacy source alias |
| `PATH` | Standard command lookup for local Docker, SSH and Git, and remote shell utilities; pinned remote Python uses an explicit path |
| Inherited process environment | Passed through unchanged to Docker and SSH, including their native configuration/identity bindings. No producer-specific Docker environment override or alternate Docker command is accepted. SSH uses existing native trust and identity configuration |
| `GIT_*` | Excluded from the local source-identity Git subprocess environment |
| `UV_*`, uv configuration, `VIRTUAL_ENV` | No binding in the composed remote command: no uv process or environment discovery occurs |
| `PYTHON*` | Remote interpreter's `-I` ignores Python environment overrides |
| Observed-identity environment bindings | None added. `HOSTNAME`, `HOST`, `MACHINE_ID`, and `HAPAX_ESTATE_OBSERVED_HOST_OVERRIDE` have no identity-binding effect; use only the explicit CLI fixture flag |

No other environment variable is explicitly read by the producer, and
`HAPAX_ESTATE_SCHEDULED` has no effect. The producer does not serialize its
inherited environment or credential configuration into evidence.

## Execution evidence and failure semantics

Each CLI execution emits one compact `hapax.estate-execution/v1` JSON line to
stderr on completion, including failure. `started_at` is captured before the
command executes and `finished_at` after it completes. The existing service
journal captures stderr. A peer's stderr is forwarded verbatim before the
initiator's completion line, so the initiating journal contains both identities.
If peer stderr has no trailing newline, a framing newline separates it from the
initiator's JSON line; the captured peer result remains byte-for-byte intact.
An interrupted process without a completion line has no successful completion
witness. No additional evidence file is created.

The peer sweep uses `--include-report --json`: stdout contains the existing
summary plus `report_sha256`, `host`, `boot_id`, `source` and `report_base64`.
Base64 transports the exact report bytes, including whitespace and
`root_observations`, without rewriting the immutable report on disk. The
initiator recomputes SHA-256, compares it to both the summary and peer completion,
and checks the report path, declared opposite host, report host, boot identity
and physical source. Boot comes from the peer process, not the initiator. The
report has no boot field; that binding is carried by the peer's summary and
completion evidence. `export-canary` includes boot/source in its CLI response;
it does not produce a drift report.

| Field | Source | When `absent` |
|---|---|---|
| `schema`, `command` | Evidence schema constant and parsed CLI command | Never |
| `host` | Registry-resolved local host id | Execution refused before or during host resolution |
| `requested_host` | Exact `--host` argument, otherwise the observed hostname (possibly from the explicit fixture flag) | No label supplied and hostname observation is absent |
| `observed_hostname` | Read-only `/proc/sys/kernel/hostname`, stripped; explicit fixture flag's first value when used | Unreadable, undecodable or empty, including an empty fixture value |
| `observed_machine_id` | Read-only `/etc/machine-id`, stripped; explicit fixture flag's second value when used | Unreadable, undecodable or empty, including an empty fixture value |
| `observed_host_override` | Literal `--observed-host-override` when that flag is supplied | Flag not supplied |
| `identity_binding.declared_hostnames` | Requested registry label plus its `aliases` | Entire `identity_binding` is `absent` before host resolution/binding; list otherwise |
| `identity_binding.declared_machine_id`, `.declared_ssh_target` | Requested host's registry `machine_id` and `ssh_target` | Declaration missing or empty, or entire binding absent |
| `identity_binding.status`, `.errors` | Local observed/declaration comparison: `ok`, `unqualified` for missing evidence, or `failed` for mismatch; reason list | Entire binding absent before comparison |
| `boot_id` | Local `/proc/sys/kernel/random/boot_id` | Missing, unreadable or empty; command fails |
| `native.INVOCATION_ID` | Environment `INVOCATION_ID`, copied as observed | Unset or empty |
| `native.SYSTEMD_EXEC_PID` | Environment `SYSTEMD_EXEC_PID` | Unset or empty |
| `native.TRIGGER_UNIT` | Environment `TRIGGER_UNIT` | Unset or empty |
| `native.TRIGGER_PATH` | Environment `TRIGGER_PATH` | Unset or empty |
| `native.TRIGGER_TIMER_REALTIME_USEC` | Environment of the same name | Unset or empty |
| `native.TRIGGER_TIMER_MONOTONIC_USEC` | Environment of the same name | Unset or empty |
| `scheduled` | `true` only for an observed `.timer` trigger unit and at least one positive integer native timer timestamp, with no execution/binding errors or identity override | Every other case, including manual calls, missing identity evidence, overrides and `--qualified` alone |
| `source.physical_root` | Resolved path of the running script's tree, fixed at import | Never |
| `source.verified_shared_root` | Physical root verified against the imported `shared.__file__` before loading its submodules | Bootstrap import binding refused |
| `source.git_head` | Successful `git -C <physical_root> rev-parse HEAD`; Git environment overrides excluded | Git unavailable, failed or invalid output |
| `started_at`, `finished_at` | Local UTC clock immediately around execution | Never in an emitted completion |
| `report.path`, `report.sha256`, `report.host` | Local sweep's returned path, SHA-256 of its exact bytes and local host | Entire `report` is `absent` when no local report was returned |
| `root_observations` | Local sweep's Docker root observations, identical to the report field | Entire field `absent` until a local sweep report is read successfully; `[]` if completed with no Docker roots |
| `root_observations[].scan_root`, `.path`, `.kind` | Declared root id, expanded path, `docker-volumes` kind | Never in a root entry |
| `root_observations[].status`, `.candidate_count` | `read-failed` if either observation fails, otherwise `read-ok`; distinct candidate paths across both observations | Never in a root entry |
| `root_observations[].observations[].method` | `filesystem`, then `docker-volume-ls` | Never |
| `root_observations[].observations[].status`, `.candidate_count` | Individual read outcome and number of candidates; failed CLI yields zero candidates | Never |
| `root_observations[].observations[].errors` | Read errors as objects with `scan_root`, `path`, `error` (declared id, failing path, exception/CLI reason and CLI remedy) | Never; `[]` when this observation succeeded |
| `root_observations[].observations[1].command` | Exact fixed Docker argv | Never |
| `root_observations[].observations[1].stdout`, `.stderr` | Exact process bytes decoded with UTF-8/surrogateescape, including partial timeout output | Never `absent`; empty string when no stream bytes were observed |
| `root_observations[].observations[1].returncode` | Observed process return code | Launch failure or timeout |
| `root_observations[].observations[1].transport_error` | `timeout` or exception class | Process completed, even with nonzero exit |
| `root_observations[].observations[1].timeout_seconds` | Fixed `DOCKER_TIMEOUT_SECONDS`, 15 | Never |
| `peer` | Result of the current SSH call | No peer call completed, or binding refused before dispatch |
| `peer.observed_hostname`, `.observed_machine_id` | Peer's own completion fields, independently checked against the initiator's registry for the requested peer label | Field missing, empty, null or explicitly `absent`; prevents qualification |
| `peer.observed_host_override` | Peer's completion marker | Peer marker missing or explicitly `absent`; override errors also prevent qualification even without the marker |
| `peer.ssh_target` | Actual target argument passed to the SSH capture boundary | Result has no captured target; binding fails |
| `peer.identity_binding.declared_hostnames`, `.declared_machine_id`, `.declared_ssh_target` | Initiator registry's declarations for the requested peer; same shapes as local binding | Missing/empty machine-id or target declaration; entire `peer` absent before dispatch |
| `peer.identity_binding.status`, `.errors` | Peer observation and actual dispatch-target comparisons; same three statuses as local binding | Entire `peer` absent before dispatch |
| `peer.source_binding.kind`, `.requested` | `physical` plus explicit root, or `alias` plus legacy alias | Never when a peer result exists |
| `peer.report_path`, `peer.report_sha256` | Peer stdout summary, checked against peer completion | Missing summary fields, or command produces no report |
| `peer.computed_sha256` | SHA-256 recomputed by initiator over decoded `report_base64` | Base64 decoding failed before hashing, or command produces no report; missing base64 defaults to empty bytes, whose digest is retained alongside `peer_report_invalid_or_absent` |
| `peer.host`, `peer.boot_id`, `peer.source` | Peer stdout summary, checked against peer completion and requested physical binding | Missing fields; binding failures are recorded |
| `peer.source.physical_root`, `.verified_shared_root`, `.git_head` | Peer's script tree, verified package root and Git HEAD, with the same provenance as local `source` | Entire source is `absent` if no source object was observed; a peer-produced `git_head` is `absent` on its Git read failure; older producers omit `.verified_shared_root` |
| `peer.returncode` | Exact observed SSH process return code, including negative signal codes | Transport launch failure or timeout has no observed code |
| `peer.transport_error` | `timeout` or transport exception class | Transport completed normally, even with nonzero exit |
| `peer.status`, `peer.errors` | Binding validation and peer process outcome | Never when a peer result exists; `ok`, `unqualified` or `failed`, plus reason list |
| `returncode`, `status`, `errors` | CLI exit, observed scheduling completeness and execution/binding checks | Never; errors includes missing-identity, override and unqualified local mismatch reasons even on a zero exit |

The `absent` sentinel describes unavailable observations, not every malformed
value. Peer summary values are retained as observed (including explicit nulls)
and validation records their binding failures separately. Command-specific
fields under the Docker CLI observation are not keys on the filesystem
observation. `root_observations` on an initiating peer command remains `absent`;
the remote observations travel in its forwarded peer completion and exact report.

Native trigger metadata is best effort and may coalesce triggers. It cannot
prove the absence of missing timer slots. See the upstream
[systemd execution environment contract](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.exec.xml).
`--qualified` requires source and identity binding; it does not attest scheduling.
Status is `failed` for nonzero exit, `unqualified` for successful execution
with identity omissions/overrides, recorded local mismatches, or without both observed timer metadata and
an invocation id, and `ok` otherwise. Identity omissions/overrides on a peer
also leave the initiator unqualified. Only the specific peer completion errors
for absent native identity, absent declared machine id and the explicit fixture
override are accepted as unqualified zero-exit evidence; other peer errors fail.
An SSH-invoked peer normally reports `unqualified`; its successful causal report
binding is still usable by the initiating invocation. No cadence, streak,
cross-invocation join or acceptance decision is computed here.

Failed peer exits remain nonzero (positive peer codes are propagated; signals
and transport/binding errors produce CLI exit 2). Peer stdout and stderr are
preserved in full and forwarded, including failed report summaries. The Python
API returns a `PeerCommandResult` with `check=False`; default checked callers
receive `PeerCommandError.result` with the identical streams and code. This
module has no secret filter, so it does not transform the captured streams;
tests use only synthetic diagnostics. Timeout output is retained and its return
code remains unobserved. Digest, host, boot, source, path, missing-evidence and
scan failures remain visible in `errors`. Existing reports, findings and failed
results are never removed or rewritten. Ordinary unregistered-store findings
remain report-only; a zero exit does not assert a clean report.

These commands only read the current host's journal. Run them on the host whose
producer evidence is being inspected; no SSH or manager mutation is involved:

```bash
journalctl --user -u hapax-estate-drift-sweep.service \
  --since '2026-09-05 00:00:00 UTC' --no-pager -o cat \
  | jq -Rc 'fromjson? | select(.schema == "hapax.estate-execution/v1")'

journalctl --user -u hapax-estate-canary-peer-check.service \
  --since '2026-09-05 00:00:00 UTC' --no-pager -o cat \
  | jq -Rc 'fromjson? | select(.schema == "hapax.estate-execution/v1")'

journalctl --user -u hapax-estate-drift-sweep.service \
  --since '2026-09-05 00:00:00 UTC' --no-pager -o json \
  | jq -c '{boot: ._BOOT_ID, invocation: ._SYSTEMD_INVOCATION_ID,
            unit: ._SYSTEMD_USER_UNIT, realtime: .__REALTIME_TIMESTAMP,
            monotonic: .__MONOTONIC_TIMESTAMP, message: .MESSAGE}'
```

The final command retains journal metadata and manager messages for the
coordinator's independent reader; forwarded peer evidence has its own embedded
host/boot and must not inherit the local journal's identity.

The sweep reads Canary B manifests independently from candidate classification.
Two consecutive distinct manifests that do not appear in the sweep's
unregistered findings cause it to file
`incident-estate-detector-dead-*.json`. The incident names
`hapax-estate-store-registry sweep` as the dead detector. Stage 1 deliberately
does not self-clean either canary because the accepted stage forbids sweep
deletion; cleanup remains an activation-stage decision.

Each missed streak filed in a sweep has its own numbered incident filename;
`detector_incident_path` retains the last incident path for compatibility. Read
all `incident-estate-detector-dead-<host>-<sweep-stamp>-*.json` records to inspect
every streak from that sweep.

If a sweep stops after flag creation but before detector state persistence, the
next sweep validates and reuses that receipt without changing its bytes, inode
or timestamp. It checks schema, canary id, host, artifact path, action, detector
identity and a timezone-bearing `flagged_at`. Original v1 receipts without an
explicit detector field identify the sole producer by their schema; explicit
foreign identities refuse. Invalid or mismatched receipts remain preserved and
produce a named repair-and-rerun error. State and reports remain immutable.

## Executable guarantee rechecks

Run from the physical checkout. These tests use temporary stores and fake
process/identity boundaries; they do not contact a host, Docker daemon or user
manager. This selection pins the two-miss threshold and detector name, records
both incidents for `miss, miss, flagged, miss, miss`, rejects vendor quarantine
even when the general action allowlist permits it, verifies collision refusal
without rewriting an existing report, and checks candidate bytes/inode plus
`mutation_actions == []`:

```bash
env -u HAPAX_GLMCP_MODEL -u HAPAX_GLMCP_REVIEW_MODEL \
  -u HAPAX_GLMCP_REVIEW_PAYG_FALLBACK -u HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL \
  UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify \
  uv run pytest -q -p no:cacheprovider \
  tests/shared/test_estate_registration.py::test_two_distinct_unflagged_b_instances_file_self_named_incident \
  tests/shared/test_estate_registration.py::test_sweep_records_both_missed_streaks_in_one_sweep \
  tests/shared/test_estate_store_registry.py::test_registry_rejects_vendor_root_quarantine_even_if_general_policy_is_edited \
  tests/shared/test_estate_registration.py::test_sweep_report_collision_preserves_immutable_record \
  tests/shared/test_estate_registration.py::test_sweep_flags_and_files_without_mutating_candidate
```

The incident tests assert the two distinct triggering ids and `miss_streak == 2`
for both streaks. The vendor test expands `ALLOWED_ACTIONS` in memory while
requiring `RegistryError`. The report collision test requires `RegistrationError`
and unchanged report bytes/inode, also checking the first report's mtime. Retry
and source binding have separate executable checks:

```bash
env -u HAPAX_GLMCP_MODEL -u HAPAX_GLMCP_REVIEW_MODEL \
  -u HAPAX_GLMCP_REVIEW_PAYG_FALLBACK -u HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL \
  UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify \
  uv run pytest -q -p no:cacheprovider \
  tests/shared/test_estate_registration.py::test_sweep_recovers_flag_receipt_after_interrupted_state_write \
  tests/shared/test_estate_registration.py::test_sweep_refuses_invalid_existing_flag_with_named_repair \
  tests/shared/test_estate_store_registry.py::test_scripts_bind_shared_import_to_physical_tree
```

Mutation verification recipe: in an admitted, isolated checkout with no other
writer, temporarily remove exclusive creation from `_write_json`. The collision
test must turn red with `Failed: DID NOT RAISE ... RegistrationError` (pytest exit
1). The driver restores the exact source bytes in `finally`, leaves the file's
mode intact, and writes no report or new source file. Its own exit is zero only
when pytest observed the expected red result. Rerun the first selection afterward
to confirm green. A process killed before `finally` runs requires restoring the
`os.O_EXCL` term before any further work.

```bash
python3 - <<'PY'
from pathlib import Path
import subprocess

path = Path("shared/estate_registration.py")
original = path.read_bytes()
before = b"os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC"
after = b"os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC"
assert original.count(before) == 1
try:
    path.write_bytes(original.replace(before, after))
    result = subprocess.run([
        "env", "-u", "HAPAX_GLMCP_MODEL", "-u", "HAPAX_GLMCP_REVIEW_MODEL",
        "-u", "HAPAX_GLMCP_REVIEW_PAYG_FALLBACK",
        "-u", "HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL",
        "UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify",  # pragma: allowlist secret
        "uv", "run", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short",
        "tests/shared/test_estate_registration.py::test_sweep_report_collision_preserves_immutable_record",
    ], check=False)
finally:
    path.write_bytes(original)
assert result.returncode == 1, f"expected pytest exit 1, observed {result.returncode}"
PY
```

## New-unit declaration report

The deploy checker is advisory in Stage 1. A new service with `ExecStart=` must
declare one or more registered store IDs as `X-Hapax-Store=...`, or declare the
computed absence explicitly as `X-Hapax-Store=None`. Findings return exit zero
and say `blocking: false`; inability to determine the exact new-unit set refuses
instead of substituting a guessed base:

```bash
uv run python scripts/check-estate-store-declarations.py --base-ref origin/main
```

This is not registered as a hook and is not called by a deploy service.

## Consumption binding status

The council worktree contains the registry and reader, but the named frame
consumers are canonical vault files outside this lane's permitted mutation
root. They must not be silently represented as bound:

- TODO `census`: replace the hard-coded `~/.claude`, foreign-capability, vault,
  and repo source enumeration in
  `30-areas/hapax/frame/census.py` with
  `enumerate_stores(..., consumer="census")` from this reader.
- TODO `assemble.py`: replace `DATA.glob("brief-*.jsonl")` in
  `30-areas/hapax/frame/assemble.py` with registry entries declared for
  `assemble`; explicit `--extra` inputs must be registered or refused.
- TODO brief dispatch: bind the frame brief producer/dispatcher to
  `consumer="brief-dispatch"`; no uniquely named brief-dispatch implementation
  exists in this council tree.
- TODO pillar matcher: replace memory/vault/project root constants and recursive
  walks in `30-areas/hapax/frame/pillar_census.py` with
  `consumer="pillar-matcher"` enumeration.
- TODO task intake: identify the frame task-intake dominator, then replace its
  source enumeration with `consumer="task-intake"`; the council tree contains
  multiple unrelated intake surfaces, so choosing one here would be an
  unmeasured binding.

These TODOs require a separately authorized vault/source-activation lane.

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

The positional command is one of `list`, `originate`, `export-canary`,
`check-peer`, `sweep`, `sweep-peer`, or `grandfather`. Options are accepted by
the common parser; only the named operations use each operation-specific option.

| Flag | Default and effect |
|---|---|
| `-h`, `--help` | Print parser help and exit; no execution evidence line |
| `--registry PATH` | Running physical tree's `config/estate-store-registry.yaml`; local registry for every command |
| `--host ID_OR_ALIAS` | Local hostname resolved through registry aliases; every command |
| `--home PATH` | `Path.home()`; local home/vault/runtime path binding, never forwarded to the peer |
| `--consumer NAME` | Unset; required by `list`. Choices validated by reader: `assemble`, `brief-dispatch`, `census`, `drift-sweep`, `pillar-matcher`, `task-intake` |
| `--report-root PATH` | Registry `policy.reports_path`; local `sweep` only |
| `--output PATH` | Unset; required by `grandfather`, must resolve inside the current worktree |
| `--json` | False; JSON stdout instead of YAML. Peer commands always request and forward peer JSON |
| `--peer-source-root PATH` | `HAPAX_ESTATE_PEER_SOURCE_ROOT` or unset; `check-peer` and `sweep-peer`, explicit flag wins |
| `--qualified` | False; requires an explicit physical peer binding for peer commands; does not attest scheduling |
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
| `boot_id` | Local `/proc/sys/kernel/random/boot_id` | Missing, unreadable or empty; command fails |
| `native.INVOCATION_ID` | Environment `INVOCATION_ID`, copied as observed | Unset or empty |
| `native.SYSTEMD_EXEC_PID` | Environment `SYSTEMD_EXEC_PID` | Unset or empty |
| `native.TRIGGER_UNIT` | Environment `TRIGGER_UNIT` | Unset or empty |
| `native.TRIGGER_PATH` | Environment `TRIGGER_PATH` | Unset or empty |
| `native.TRIGGER_TIMER_REALTIME_USEC` | Environment of the same name | Unset or empty |
| `native.TRIGGER_TIMER_MONOTONIC_USEC` | Environment of the same name | Unset or empty |
| `scheduled` | `true` only for an observed `.timer` trigger unit and at least one positive integer native timer timestamp | Every other case, including manual calls and `--qualified` alone |
| `source.physical_root` | Resolved path of the running script's tree, fixed at import | Never |
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
| `peer.source_binding.kind`, `.requested` | `physical` plus explicit root, or `alias` plus legacy alias | Never when a peer result exists |
| `peer.report_path`, `peer.report_sha256` | Peer stdout summary, checked against peer completion | Missing summary fields, or command produces no report |
| `peer.computed_sha256` | SHA-256 recomputed by initiator over decoded `report_base64` | Base64 decoding failed before hashing, or command produces no report; missing base64 defaults to empty bytes, whose digest is retained alongside `peer_report_invalid_or_absent` |
| `peer.host`, `peer.boot_id`, `peer.source` | Peer stdout summary, checked against peer completion and requested physical binding | Missing fields; binding failures are recorded |
| `peer.source.physical_root`, `.git_head` | Peer's script tree and Git HEAD, with the same provenance as local `source` | Entire source is `absent` if no source object was observed; a peer-produced `git_head` is `absent` on its Git read failure |
| `peer.returncode` | Exact observed SSH process return code, including negative signal codes | Transport launch failure or timeout has no observed code |
| `peer.transport_error` | `timeout` or transport exception class | Transport completed normally, even with nonzero exit |
| `peer.status`, `peer.errors` | Binding validation and peer process outcome | Never when a peer result exists; `ok` or `failed`, plus reason list |
| `returncode`, `status`, `errors` | CLI exit, observed scheduling completeness and execution/binding checks | Never; errors is an empty list on success |

The `absent` sentinel describes unavailable observations, not every malformed
value. Peer summary values are retained as observed (including explicit nulls)
and validation records their binding failures separately. Command-specific
fields under the Docker CLI observation are not keys on the filesystem
observation. `root_observations` on an initiating peer command remains `absent`;
the remote observations travel in its forwarded peer completion and exact report.

Native trigger metadata is best effort and may coalesce triggers. It cannot
prove the absence of missing timer slots. See the upstream
[systemd execution environment contract](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.exec.xml).
`--qualified` is a source-safety requirement, not a scheduling attestation.
Status is `failed` for nonzero exit, `unqualified` for successful execution
without both observed timer metadata and an invocation id, and `ok` otherwise.
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

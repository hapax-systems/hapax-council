# Native harness substrates

Containers may supply a reusable substrate for several capability shapes. An
image is not a capability identity. A shape binds the selected native client,
instructions and task context, tool/service interfaces, authority, continuation
state and resource policy for a demand. Several shapes can share an image or
base layers, and a shape can depend on separately served capabilities.

The purpose is to remove accidental dependency on the workstation and repeated
maintenance, while retaining useful specialization and failure diversity. Do not
equate one vendor, one image and one capability. Mediation may deliberately change
native behavior when the resulting capability better serves its demand; preserving
every native quirk is not the acceptance criterion. Nor does making all reviewers
share one history improve independent review.

`docker/Dockerfile.native-harness` provides a common base with Claude and Codex
client targets. `docker/native-harness.compose.yaml` shows bounded measurement
configurations. They are not newly admitted production workers. Existing adapter
admission, context canon, registry and receipt paths remain the control plane.

| Binding | Instruction-loading fixture | Production obligation |
| --- | --- | --- |
| Immutable inputs | Pinned base digest, verified client bytes, shared policy and native configuration | Release by tested image ID/digest; record selected configuration independently. |
| Working context | Isolated Git fixture mounted read-only at `/work` | Declare source revision, cwd, nested context and any separate worktree Git metadata. |
| Credentials | None | Runtime credential references from the existing store; no token in image or report. |
| Services | Network disabled; no provider request | Declare required endpoints, egress and actual service readiness. A running container is insufficient. |
| Mutable state | Only the invocation's state/evidence mounts and named temporary directories | Owner, retention, continuation compatibility and recovery policy. Never mount all of HOME. |
| Resources | UID 1000, capabilities dropped, no new privileges, 2 CPUs/2 GiB/128 PIDs | Select limits for the demand; preserve device/shared-inference dependencies explicitly. |
| Authority | Support-only observation | Admission and effects still belong to the existing capability contract. |

Codex keeps SQLite/log data, installation identity and writer locks under `/state`,
and session journals in its owned `sessions` directory. Its immutable configuration
points there; `/tmp`, cache and bundled skill installation have explicit temporary
bindings. Create `sessions` and `thread-writer-locks` in the owned state directory.
Claude's session state has a separate projects binding. Neither global policy nor
credentials belong in mutable session state.

The native Codex inner shell sandbox cannot create user namespaces under the
measured Docker policy. The instruction fixture therefore leaves shell execution
unobserved. The separate trusted-source trial below uses the outer OCI boundary
explicitly; it does not enable privileged Docker or relax the host's seccomp policy.

## Build and replay

Use an isolated build context containing only:

- `config/agent-instructions/`
- `scripts/install-agent-instructions.py`
- `docker/Dockerfile.native-harness` and `docker/native-codex.toml`
- `artifacts/claude` and `artifacts/codex`, the explicitly selected native binaries.
- `artifacts/codex-code-mode-host`, from the same Codex release. The CLI alone
  loads instructions but cannot run its native code-mode tools without this companion.

The Dockerfile verifies the recorded client SHA-256 values. Direct package versions
are pinned, and each target retains its complete installed package inventory at
`/opt/hapax/os-packages.txt`. Transitive repository resolution is not fully locked;
this is a tested immutable image, not a claim of indefinitely reproducible rebuilds.

```bash
substrate_revision=$(git rev-parse HEAD)
substrate_build=$(mktemp -d)
git archive "$substrate_revision" config/agent-instructions \
  scripts/install-agent-instructions.py docker/Dockerfile.native-harness \
  docker/native-codex.toml | tar -x -C "$substrate_build"
install -Dm755 /absolute/chosen/claude "$substrate_build/artifacts/claude"
install -Dm755 /absolute/chosen/codex "$substrate_build/artifacts/codex"
install -Dm755 /absolute/chosen/codex-code-mode-host \
  "$substrate_build/artifacts/codex-code-mode-host"
docker build -f "$substrate_build/docker/Dockerfile.native-harness" \
  --target claude --build-arg SOURCE_REVISION="$substrate_revision" \
  --iidfile "$substrate_build/claude.id" "$substrate_build"
docker build -f "$substrate_build/docker/Dockerfile.native-harness" \
  --target codex --build-arg SOURCE_REVISION="$substrate_revision" \
  --iidfile "$substrate_build/codex.id" "$substrate_build"
python3 scripts/probe-native-harness-container.py --source . \
  --source-revision "$substrate_revision" \
  --claude-image "$(cat "$substrate_build/claude.id")" \
  --codex-image "$(cat "$substrate_build/codex.id")" \
  --output-dir /tmp/native-substrate-replay-new
```

The output directory must be new and writable by the declared UID. Use a committed
source tree matching the source revision. The manual diagnostic uses native Claude
SDK initialization and Codex app-server control messages. It never submits a model
turn. Codex `thread/inject_items` inserts a fixture message to exercise persistence
without inference, then a new container resumes the same native session ID from
the owned state. Root and nested cwd are separate cells.

Positive assertions check actual Claude load-hook paths/hashes, Codex native
`instructionSources`, immutable file readback and denied writes, writable owned
state, and continuation identity plus persisted fixture bytes. Negative cells
detect an unexpected override, missing project instructions and an invalid resume
ID. These observations do not prove task outcomes, semantic compliance, tool
execution, provider reachability, cancellation of a model request or production
readiness. Lifecycle cancellation has separate owned-process tests.

For another supported host, transfer the **same image IDs** with `docker save` /
`docker load` and a minimal source/probe archive, then rerun in a new owned fixture
directory. Do not transfer workstation HOME or authentication. Compare image,
instruction and probe hashes as well as outcomes. A replay establishes portability
only for the measured bindings and interfaces on those hosts.

Shared policy is also a correlated-failure surface: a bad common rule reaches
several shapes. Review and reversible publication reduce that risk; native
differences and independently obtained review evidence should remain visible.

The final installer revision completed the same-image Appendix/Podium replay.
An intermediate attempt exceeded the ten-second Codex graceful-exit deadline
after nested resume and required a forced stop; that failed attempt is retained.
Successful later cells do not establish production lifecycle reliability. Both
accepted observations and failed attempts are recorded in the
[sanitized evidence](evidence/native-harness-reductions-20260920.yaml).
Instruction sets and bytes matched. Across accepted replays, Claude hook-event arrival order has both
matched and differed. Neither observation establishes instruction precedence or
semantic equivalence.

The installed lifecycle observer uses Council's governed activation root,
`HAPAX_SOURCE_ACTIVATE_WORKTREE` or `~/.cache/hapax/source-activation/worktree`.
Before a second repository adopts the installed launcher, bind its governed
activation root explicitly and rerun the installed-copy receipt tests against
that repository. Sharing the default alias does not establish correct selection
across repositories.

## Trusted source-analysis execution trial

`scripts/probe-native-harness-execution.py` is a manual diagnostic for a bounded,
read-only source-analysis demand. It is not installed as a worker launcher and
does not confer production admission. Its inputs are an exact image ID, closed
source packet, prompt, descriptor-derived route and a new owned output directory.
An image supplies reusable tools; the demand still selects its model, effort,
authority, context and state separately.

The trial keeps the root filesystem and source read-only, uses UID1000 and bounded
resources, and exposes neither host HOME nor a Docker socket. It deliberately
uses Codex app-server with the **outer OCI container** as the tool boundary.
Bridge egress is unrestricted. This configuration is qualified for trusted source
and the measured support demand, not an untrusted-repository execution service.
Account-backed apps, plugins, remote plugins, multi-agent execution and web search
are disabled explicitly. An empty local MCP configuration alone did not prevent
native account-backed apps from loading in the retained first attempt.

Authentication uses the existing saved ChatGPT access credential through native
`account/login/start` external-token mode and ephemeral storage. The controller
does not refresh credentials, transmit a refresh token, mount an auth file or
enable API/credit fallback. It refuses a credential expiring within the trial
window and requires native `ordinaryUsageAllowed=true` before a model turn.
These checks measure the selected subscription path, not all possible native
billing behavior. Native state is scanned for credential persistence. Raw account
and native journals remain private; publish only the sanitized evidence summary.

```bash
uv run --no-sync python scripts/probe-native-harness-execution.py \
  --source /absolute/closed-source-packet \
  --prompt /absolute/source-analysis-brief.md \
  --image "$(cat /absolute/tested-codex.id)" \
  --output /absolute/new-owned-invocation --execute
# Same inputs and invocation path; verifies stored results without a provider call:
uv run --no-sync python scripts/probe-native-harness-execution.py \
  --source /absolute/closed-source-packet \
  --prompt /absolute/source-analysis-brief.md \
  --image "$(cat /absolute/tested-codex.id)" \
  --output /absolute/new-owned-invocation --execute --replay
```

For a remote runtime, transfer the same image and packet, create separate owned
state with `sessions` and `thread-writer-locks`, and supply `--docker-host`,
`--runtime-source` and `--runtime-state`. The controller checks the actual mounted
packet before external login and again after the turn. Placement changes these
bindings, not source code. Each invocation gets separate state; sharing an image
does not authorize shared histories or credentials.

The native stream must correlate one thread/turn and a successful terminal event
with the actual owned container exit. The saved rollout must independently match
the selected descriptor and turn. A nonempty native final answer and successful
native tool execution are also required. Hashes bind the request, source packet,
controller, image, stream, rollouts and result. These are consistency observations
at the owned boundary, not provider attestation or independent work acceptance.

`--cancel-after-tool` interrupts an actual native command. Successful interruption
means the native turn reports interrupted and the owned runtime has stopped;
provider-side cancellation is not attested. SIGTERM cleanup is measured separately.
Exclusive invocation directories prevent silently repeating this manual demand.
After an incomplete invocation or hard controller/host failure, inspect the exact
container ID in `launch.json` using the recorded Docker endpoint, stop only that
owned container if needed, and preserve the bundle. Missing or changed result
bytes are an error, never permission to resubmit the same invocation. No automatic
SIGKILL/power-loss recovery service is introduced.

## Existing dispatch result delivery

The optional `DispatchLaunchResult.result_ref` reuses `ContentAddress`; the
primitive now lives in `shared/content_address.py` and remains re-exported from
`shared/execution_admission.py` with the same schema. This removes an import of
the entire admission dependency graph from a lightweight receipt reader.
The claim-publication descriptor's existing generation roots also bind the
extracted file, preserving the source-generation check that covered this validator
before extraction. Moving code must not silently remove its execution binding.

The existing terminal coordination event retains the exact native lifecycle
receipt reference. Methodology dispatch verifies its bytes and referenced stream,
recomputes native observations, and restores that evidence on replay. Launch status
retains its original meaning; missing evidence cannot become native completion or
work acceptance. Receipt ownership fields remain claims, not independent ownership
proof. Existing coordination replay still does not exclude concurrent or interrupted
inflight launches. The manual trial's exclusive-directory behavior does not repair
that broader limitation.

For fresh local Codex headless work, the same receipt now carries the immutable
launch descriptor and a correlated native model/effort observation. The result
reader rechecks the actual native prefix against its saved hash and declaration;
an invented `matched` field is replaced by the recomputed observation. A verified
native mismatch survives missing evidence on another axis or an unrelated
pre-launch turn. Incomplete original identity evidence stays unverified even if
a new file appears later. This readback confers no work acceptance or authority.

This consumer is local to its declared native session store. Its absolute paths
are not a portable artifact-address resolver for arbitrary remote workers. The
separate container trial's bound output bundle remains the observed cross-host
surface; neither result is evidence that all production shapes have migrated.

Recheck these seams with:

```bash
uv run --no-sync pytest -q tests/shared/test_execution_observer.py \
  tests/scripts/test_probe_native_harness_execution.py \
  tests/scripts/test_hapax_methodology_dispatch.py \
  tests/scripts/test_codex_identity_consumer.py tests/shared/test_codex_run_identity.py \
  tests/test_coord_dispatch_liveness_gate.py tests/test_capability_adapter_protocol.py \
  tests/shared/test_execution_admission.py
```

The source-analysis trial has an actual consumer in the integration workstream.
The production headless route still uses its existing launcher. No production
construction branch is retired until ordinary admission, independent review and
an actual consumer cutover establish that its obligations are preserved.

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

| Binding | This measured construction | Production obligation |
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

The native Codex client reports that its shell sandbox requires user namespaces
under the measured Docker policy. Instruction loading and continuation succeed,
but shell execution is **unobserved**. Do not infer a general coding worker from
those successes or silently grant privileged host access. Selecting a suitable
host/kernel sandbox interface is a subsequent shape-construction requirement.

## Build and replay

Use an isolated build context containing only:

- `config/agent-instructions/`
- `scripts/install-agent-instructions.py`
- `docker/Dockerfile.native-harness` and `docker/native-codex.toml`
- `artifacts/claude` and `artifacts/codex`, the explicitly selected native binaries.

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

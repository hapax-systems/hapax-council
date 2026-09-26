# Repository instruction binding

Author repository instructions in `AGENTS.md`. The root `CLAUDE.md` is a relative
symlink to `AGENTS.md`, not a second policy document. Edit the target directly.
Keep native-specific guidance explicit inside the canonical document where it
changes how a capability works.

The symlink is deliberate: estate filesystem readers of `CLAUDE.md` must continue
to receive the instruction body. A file containing only `@AGENTS.md` works for
Claude's import loader, but those readers would see only the import directive.
Git-blob readers must read `AGENTS.md`: `git show HEAD:CLAUDE.md` returns the link
target name, not the target body. The monthly audit handles this explicitly.

Recheck from a committed checkout:

```bash
test "$(readlink CLAUDE.md)" = AGENTS.md
test "$(git show HEAD:CLAUDE.md)" = AGENTS.md
cmp CLAUDE.md AGENTS.md
uv run pytest tests/scripts/test_monthly_instruction_audit.py -q
```

The first three commands succeed without output: the filesystem alias reads the
body while the Git blob stores its target name. The monthly audit tests must pass.

Claude documents this binding, including deduplication and instruction-load hook
behavior: [Claude memory documentation](https://code.claude.com/docs/en/memory#share-one-file-with-other-coding-tools).
It also works when direct AGENTS discovery is unavailable or a CLAUDE file takes
precedence. There is no need to enable a new plugin setting for this migration.

This binding targets the estate's Linux checkouts and Linux containers. Preserve
symlinks when building an image or copying the source. On Windows without Git
symlink support, use a native `@AGENTS.md` import and adapt raw readers; do not
claim that a plain-text link target is an equivalent checkout. Existing nested
instruction files and global bindings retain their own scopes.

## Verification and limits

- Confirm `readlink CLAUDE.md` is `AGENTS.md` and both filesystem reads return the
  same bytes. A Git checkout must preserve mode `120000` for the alias.
- Run the focused instruction-binding, governance-path, launcher and rotation
  tests. Rotation discovery, pre-commit selection and CI must cover both names.
- Exercise the installed native loader where available, including a nested cwd
  and its actual trust configuration. Retain version, configuration, discovered
  paths and content evidence. Do not change repository trust merely to get a pass.
- Check a fresh Claude session's instruction-load evidence before treating the
  binding as observed there. Existing sessions can retain old context until a
  fresh load. A successful filesystem check is not a measured Claude session.

Instruction delivery is not semantic compliance. An agent restating a rule is
not evidence it followed it, and filename agreement does not establish equivalent
precedence, trust, imports, context budgets, hooks or tool authority across engines.
Future containerization must declare those bindings alongside state and service
access; an image alone does not freeze the resulting capability.

From the repository root, replay the filesystem, protection, audit and launcher
checks with:

```bash
readlink CLAUDE.md
git ls-files --stage CLAUDE.md
uv run pytest tests/test_agent_instruction_binding.py tests/test_policy_floor.py \
  tests/test_release_auto_arm.py tests/scripts/test_invariant_touch_report.py \
  tests/scripts/test_screwm_compositor_sunset_boundary.py \
  tests/scripts/test_monthly_instruction_audit.py \
  tests/scripts/test_hapax_codex_launcher.py -q
bash tests/test_check_claude_md_rot.sh
bash scripts/check-claude-md-rot.sh
```

The alias checks should report `AGENTS.md` and mode `120000`. All test commands
should exit zero. Audit tests use an isolated Git repository and replace `curl`;
they send no notifications.

Replay the native loader fixture against an **existing, explicitly chosen**
Claude binary (substitute its absolute path):

```bash
uv run python scripts/probe-claude-instruction-binding.py \
  --claude /absolute/path/to/claude \
  --instructions AGENTS.md \
  --output-dir /tmp/claude-binding-replay
```

The output directory must be new. The probe copies instructions into an isolated
root/nested fixture, creates the relative alias, and uses an isolated home/config
with no inherited provider credentials. MCP servers and tools are empty. It sends
only an SDK `initialize` control request followed by EOF, with no user turn. It
does not install a client, alter the checkout or mutate estate trust. If the
chosen binary cannot run, resolve that installation separately or select an
existing working binary; do not substitute another version without recording it.

Exit zero requires exactly one project `InstructionsLoaded` event per cwd, naming
the alias at session start and matching the canonical SHA-256 measured by the
hook. Older clients can finish initialization before the hook writes; the probe
keeps input open until a receipt arrives or ten seconds elapse, then sends EOF.
Missing evidence fails the probe; initialization success alone is insufficient.
Inspect `summary.json`, the raw `*-instructions.jsonl`, and stdout/stderr.
For a head-bound witness, commit the source first and require
`source_matches_head: true`. Preserve the sanitized summary with the client hash,
configuration and source head; do not publish raw session traces indiscriminately.
The initial replay receipts are in
[the versioned evidence file](evidence/agent-instruction-binding-20260920.yaml).
These observations concern the compatibility binding, not direct AGENTS discovery,
semantic uptake, resume, or the coordinator's live session.

The wider variation-reduction assessment and implementation receipts are in the
operator's vault at `30-areas/hapax/frame/harness-variation-reduction-agents-md-assessment-20260920.md`.

## Global authorship and distribution

`config/agent-instructions/AGENTS.md` owns shared global policy. Small native
additions under `native/` retain actual operational differences. `bindings.json`
selects native destinations; generated files contain the full readable body,
not another client's import syntax. The neutral deployed copy is
`~/.config/hapax/agent-instructions/AGENTS.md`. Workspace orientation remains
`~/AGENTS.md`; changing lane/task identity stays in context and relay delivery.

| Native client | Default global binding | Material difference |
| --- | --- | --- |
| Claude | `.claude/CLAUDE.md` | Preserve compatibility alias; direct AGENTS discovery is configuration-dependent. |
| Codex | `.codex/AGENTS.md` | A nonempty `AGENTS.override.md` shadows it; installation refuses that conflict. |
| Grok | `.grok/AGENTS.md` | 10,000 characters per file; trust, Git boundary and exclusions still apply. |
| Kimi | `.kimi-code/AGENTS.md` | Do not also inject the common body through `.agents/AGENTS.md`. |
| Vibe | `.vibe/AGENTS.md` | User source must be enabled; project source depends on trust. |
| OpenCode | `.config/opencode/AGENTS.md` | Native global prevents the documented Claude-global fallback. |
| agy | `.gemini/GEMINI.md` | This is the remaining native filename holdout; no claim of direct AGENTS support. |
| Muse | `.config/muse/AGENTS.md` | Native `/rules` identifies this user rule; foreign personal discovery is distinct. |

Binding a file does not admit a worker route. In particular, installed Grok,
OpenCode and Muse clients are not thereby new entries in the capability registry,
and agy remains a read-only review route. Installed does not mean admitted.

The repository core is below Grok's cap. Full domain instructions were moved
verbatim to `council-domain-context.md`; the core requires reading the applicable
sections before domain work. Codex's global plus repository body fits its default
32 KiB budget, but additional nested files still need their own budget check.
The Codex bootstrap no longer unconditionally rereads Claude's global body, and
the Vibe launcher and standup utility no longer write lane identity into repository
instructions. They preserve authored files and leave absent files absent;
lane identity remains in environment/relay context. Recheck with
`uv run pytest tests/scripts/test_vbe_dispatch.py -q`.

Grok previously discovered both its own global and Claude's global. The installer
sets only `compat.claude.agents=false` in its existing TOML. Grok's naming is
significant: `agents` controls named Claude instruction files, while `rules`
controls rule directories. Native inspection confirms the former suppresses
`~/.claude/CLAUDE.md`, preserves ordinary project-root `CLAUDE.md`, and leaves
rule directories, skills, MCP and hooks independently configured. Hidden project
`.claude/CLAUDE*.md` is also suppressed by that native control; use canonical
project AGENTS for that scope. Environment overrides remain a separate input.

Muse 1.3.0's native `/rules` fixture, with native and both foreign globals present,
reported its native global loaded and both foreign globals unread. The result was
the same with its rules-only setting enabled or disabled. No Muse settings change
is needed for this binding; that observation does not claim equivalence for
another release or a missing native global.

`scripts/hapax-post-merge-deploy` stages the installer and its inputs from the
specified Git commit. It does not render from an arbitrarily dirty checkout.
Deployment stages live under the existing instruction state directory. A failed
deploy retains its private staged executable, so the printed recovery command
survives temporary-directory cleanup and reboot; successful staging is removed.
Publication backs up originals, detects overlapping destinations, verifies
readback and restores attempted writes on failure. Rollback errors retain the
backup and report both failures with a copyable recovery command. A pending
transaction records known postimages before publication; it blocks a successor
installation until recovery. Recovery checks every destination against its saved
preimage or known postimage before restoring anything. Intervening edits require
reconciliation, including edits to a predecessor receipt. This also covers a
failed first install or interrupted rollback where no current receipt exists.
A retry with the same source revision, complete binding selection, verified
regular payloads and supported receipt returns the existing receipt under the
install lock. It leaves files and the original rollback boundary intact. Drift,
a changed revision or a changed selection follows the normal publication path.
The current receipt records hashes, byte counts
and source revision; it deliberately says native loading is unobserved.
No coordinator restart or trust change is required. Existing sessions are not
claimed to have reloaded the new body.

After a pre-merge scoped activation, normal deployment republishes from the
actual merged revision, even when payload bytes are unchanged. Verify all
selected payloads and the receipt against that revision, confirm no pending
transaction remains, and update the private recovery guide to the newly
recorded backup. The pre-merge receipt remains historical evidence; never
relabel it as proof of the merged revision.

For isolated preparation or a scoped activation, stage the committed source:

```bash
instruction_revision=$(git rev-parse HEAD)
instruction_stage=$(mktemp -d)
git archive "$instruction_revision" config/agent-instructions \
  scripts/install-agent-instructions.py | tar -x -C "$instruction_stage"
python3 "$instruction_stage/scripts/install-agent-instructions.py" \
  --source "$instruction_stage" --home /absolute/target/home \
  --source-revision "$instruction_revision"
# Add --apply when activating the inspected result.
# Use --check with the same source, home, revision and binding options to
# report drift without writes (exit 1 for missing/changed bindings or receipt).
```

The default binds the explicit home's default native paths. Ambient `CODEX_HOME`,
`GROK_HOME`, other native-home variables and `XDG_CONFIG_HOME` are ignored unless
`--use-native-home-env` is supplied deliberately. Preserve a supported deployment's
chosen roots; do not silently install into another session's alternate home.
Use `--binding NAME` for a selected substrate. The neutral shared copy is always
included. The installer changes no provider credentials, trust or running process.

Recovery must use a reviewed installer that preserves the validated receipt
postimages during rollback and checks saved preimages before publishing both
payloads and `current.json`. An archived activation stage can predate those
repairs. Do not run its recorded rollback command without checking its source.
Next action: stage the repaired installer and its inputs from the reviewed Git
revision using the archive procedure above, retain that private stage, and use
its executable with the existing backup. Verify current live bindings read-only
before recovery; staging the executable does not require reinstalling unchanged
policy or rewriting the historical install receipt. Preserve the original stage
as evidence. Existing pending transactions and intervening edits still require
reconciliation through the installer's normal checks.

To restore the latest install, pass its `current.json` rollback path to
`--restore-backup PATH --home /absolute/target/home`. This restores original file
contents, modes, symlinks, absence and the predecessor receipt. The CLI refuses
if a successor install or changed output needs reconciliation. Backups of native
settings remain local and private; never publish their contents. If publication
or rollback failed, use the recovery command in its error; `pending.json`
identifies that transaction even after `current.json` has been restored.
Automatic rollback uses those same known-preimage/postimage checks before
restoring. Unknown edits or file types retain the pending transaction and its
private backup for reconciliation instead of being overwritten. The install lock
serializes participating installers; these checks are not a filesystem transaction
against arbitrary simultaneous writers.

`--check` is an explicit read-only diagnostic, not a background drift monitor.
It compares expected payloads and the current source receipt, identifies pending
recovery, and does not assert native loading. Re-run it after deployment or
native configuration edits. Policy protection, governance review, prose rotation
and assertion extraction include the authored shared/native and domain sources.
The installer and binding JSON receive governance protection but not prose
rotation. Ordinary runbooks and generated evidence remain outside that policy
authorship boundary.

## Declared inputs and native lifecycle

`PlatformCapabilityRoute.native_load_set` extends the existing registry. Eleven
native routes declare instruction inputs, optional configuration paths, native
home selection, memory scope and loading flags. `null` extension sets mean
unobserved, not empty. API/tool routes are not forced into a native-file model.
Digests pin authored expectations, rather than adopting whatever bytes happen
to be installed. After policy changes, update the corresponding declaration
digests; `test_registry_instruction_hashes_match_authored_payloads` recomputes
them against the renderer and repository sources and rejects stale values.
Run that specific re-render comparison in the same policy-change PR:

```bash
uv run pytest tests/shared/test_capability_load_set.py::test_registry_instruction_hashes_match_authored_payloads -q
```

The blind `claude.review.opus` route deliberately declares no ambient instruction
files. Its existing wrapper requests safe mode, `--disable-slash-commands`, no
session persistence and strict empty MCP configuration, then supplies the review packet
and appended review prompt. It must not inherit the worker routes' required
global `CLAUDE.md` and project `AGENTS.md` declaration. The optional native
settings-file observation remains: safe mode does not remove authentication,
model selection or permissions. Plugins, skills and MCP are declared empty,
while hooks remain unknown. The [CLI reference](https://code.claude.com/docs/en/cli-reference)
defines `--safe-mode` to disable custom plugins, skills and auto memory, including
managed plugins and skills, while retaining policy-configured hooks.
These empty lists declare intended extension inputs; they are not observations
that the native process loaded none.
`source_refs` names the wrapper containing the appended prompt; this is not a
complete digest of the provider's effective context. Built-in tools also retain
their native behavior; the wrapper separately requests empty tool lists.

The real wrapper argv is checked against this declaration in
`tests/scripts/test_hapax_claude_reviewer.py::test_claude_reviewer_binds_declared_identity_and_disables_tools`.
It checks every argument, including the empty tool/MCP configuration, so an
added undeclared instruction or configuration option requires review. Recheck
the launch declaration and its independent registry byte pin with:

```bash
uv run --no-sync pytest -q \
  tests/scripts/test_hapax_claude_reviewer.py::test_claude_reviewer_binds_declared_identity_and_disables_tools \
  tests/docs/test_platform_capability_registry_contract.py::test_registry_bytes_are_pinned
```

The subprocess test uses a stub native executable: it verifies launch inputs,
not native consumption, managed policy, or semantic uptake. A declaration with
only configuration files plus an empty native receipt list does not prove that
nothing loaded. The host observer keeps that case incomplete and separately
reports ambient instruction files that are present. Effective per-invocation
inputs still need observations from the actual native loading boundary.

The reviewer resolves `claude.review.opus` once through
`shared.capability_execution` in its physical release's `.venv/bin/python -I`.
Like the Codex launchers, it selects `HAPAX_SOURCE_ACTIVATE_WORKTREE`, then an
explicit `HAPAX_COUNCIL_DIR`, otherwise `~/.cache/hapax/source-activation/worktree`.
The selected path resolves to its physical target once before the resolver runs.
This works with the deployer's regular copy in `~/.local/bin`; the installed
script's parent directory is not a source release. Source-checkout invocations
must explicitly select that checkout when testing an unactivated change.
That binding supplies the concrete model and effort arguments, plus the child
environment's `CLAUDE_CODE_EFFORT_LEVEL` and fast-mode disable setting. Neither
the moving `opus` alias nor ambient effort selects the review identity anymore.
The current declaration is `claude-opus-4-8` / `xhigh`; this is a material change
from the old alias, not evidence of review-quality equivalence with the model
the alias happened to select. Route admission and quality assessment remain
the review dispatcher's responsibility. `--model`, if supplied, is only an
assertion matching the declaration; it cannot select a different model.
Unsupported descriptor axes or missing/malformed resolver output refuse before
the native process starts. Provision the physical release runtime to repair a
missing resolver; do not fall back to native defaults or a caller's checkout.

The environment binding matters: an offline Claude Code 2.1.278 request fixture
on 2026-09-21 observed CLI `xhigh` with environment `low` send `low`, while matching
both sent `xhigh`. Per-model `high` also overrode global `low` in the settings-only
case. Each request deliberately received HTTP 400; the client's native OTel
`api_error` event matched the request's model and effort. These are request
construction observations, not successful inference, saved-subscription
qualification or provider-side attestation. The [model configuration reference](https://code.claude.com/docs/en/model-config)
describes precedence and managed effort caps; [monitoring documentation](https://code.claude.com/docs/en/monitoring-usage)
describes the client request/error fields. No telemetry collector is deployed
by this wrapper change, and native remaps, managed caps and effective context
remain separately unobserved here. Existing native identity-consumer work is
still required before calling a completed review's execution verified.
The redacted capture projection, native-client/image hashes and per-cell raw
capture hashes are in
`tests/fixtures/claude-native-request-controls-2.1.278.json`. Raw captures and
the offline driver are retained at
`~/.local/share/hapax/harness-trials/20260921-cx-blue/claude-request-controls-20260921T1917Z/`.
The local fixture endpoint returned errors rather than proxying requests;
no real credential or external network was available to those containers.
This is a historical native measurement, not an automated test or a claim
about a later client release. No repository test regenerates or consumes this
capture. The recheck below validates wrapper construction and refusal only;
repeating native precedence requires a new bounded observation with its own
client, configuration and transport evidence. A static fixture assertion would
not reproduce that behavior.

Recheck request construction, environment isolation, refusal, output and
process-group cancellation without provider calls:

```bash
uv run --no-sync pytest tests/scripts/test_hapax_claude_reviewer.py -q
```

The `agy.review.direct` wrapper also supplies blind-review context rather than
worker instructions. It creates a temporary workspace and per-invocation
HOME/XDG roots and sends its fixed review prompt and complete supplied packet
as one `event: user` message on native `--input-format stream-json` stdin.
The packet is absent from argv and does not require a filesystem search. Its load
declaration therefore does not require the operator's global `GEMINI.md` or a
worker checkout's `AGENTS.md`. `source_refs` points to the wrapper that constructs
the prompt. The optional configuration path is
`.gemini/antigravity-cli/settings.json` relative to the invocation HOME; the wrapper
does not copy host settings into that location. Its existing OAuth seed remains a
separate credential binding; this declaration never contains credential bytes.

The declared loading flags match the wrapper's sandbox, permission and slash
command options. Plugins, skills, hooks and MCP remain unknown: disabling slash
commands does not prove that all extensions are absent. Temporary HOME and cwd
construction is also not proof of filesystem containment or delivered model
context. The general platform receipt still observes host files at its named
`host_observation` boundary; those hashes do not describe this invocation's
fresh roots. Native discovery and content use remain unobserved here.

Recheck the actual child argv, temporary roots, dossier construction and selected
host-input exclusion, together with the declaration and registry byte pin:

```bash
uv run --no-sync pytest tests/scripts/test_hapax_agy_reviewer.py \
  tests/shared/test_capability_load_set.py \
  tests/docs/test_platform_capability_registry_contract.py -q
```

These tests use a controlled executable and synthetic credential fixture. They
must pass; on failure, reconcile the wrapper and declaration before release.
They do not execute a provider model or establish native sandbox enforcement.

`hapax-platform-capability-receipts` attaches host-side observations to its existing
receipt. Presence and matching bytes do not establish native delivery.
Its observed project comes from `HAPAX_SOURCE_ACTIVATE_WORKTREE` or the default
governed activation tree, including when that tree is missing. Installed copies
import their implementation from activation; a source-checkout invocation keeps
its own implementation dependencies without substituting that checkout as the
observed deployment. Recheck installed/default/override/missing cases with
`uv run pytest tests/shared/test_platform_capability_receipts.py -k 'selected_activation or imports_from_activation' -q`.

`shared.capability_load_set.observe_load_set` can join native path/hash witnesses
to the declaration and identify missing, changed or unexpected inputs. Unknown
hashes cannot pass as observed delivery. Resolved-path declarations with conflicting
digests are rejected independently of their order; identical expectations may
share one native witness. Receipts retain resolved roots, actual
resolved file paths, declaration source references and a declaration digest, so
equal bytes in different native homes remain distinguishable. The present inventory covers declared
native/project roots; it is not a complete scan of ancestors, nested imports,
plugins, skills, hooks, MCP or memory. Caller-provided witnesses are support
evidence with `may_authorize=false`. The offered declared-load-set programme
remains open for complete native producers and configuration inventories.

Codex headless execution now gives each launch a fresh native JSON stream and
separate stderr. Its supervisor waits for the actual child, emits a create-once
lifecycle receipt, and the existing methodology-dispatch receipt consumes that
exact path. `output.jsonl` remains a compatibility symlink; predecessor files are
retained. The observer resolves from the existing governed source-activation
tree (`HAPAX_SOURCE_ACTIVATE_WORKTREE`, otherwise
`~/.cache/hapax/source-activation/worktree`) and runs by absolute path in
isolated Python mode. Neither a stale primary nor a stale child checkout selects
that dependency. A missing producer, an old module without the receipt CLI or a
missing fresh receipt produces a diagnostic; it does not manufacture completion. A reader holding the previous
`output.jsonl` file descriptor keeps the previous stream; consumers needing the
new launch should use the receipt's exact stream path. The observer runs beside
the local launcher even for SSH dispatch; the remote case records transport
output and never marks an SSH exit as owned native-process completion. Requested host names, an SSH transport exit, PID existence and a
successful interactive launcher do not establish native completion.

Completion needs an unambiguous native session, successful terminal event, clean
event stream and owned process exit zero. Signal-cause confirmation requires a
native wait witness. Bash conflates signal termination with explicit exit codes,
so this supervisor records the requested signal and reaped exit without converting
that shell status into a negative native wait result. Cancellation targets the process group created for this invocation, including a
native child behind an npm launcher; escalation still reaches the group if its
leader exits first. The grace interval is approximately five seconds; reaping
can still wait on uninterruptible kernel sleep. Only that launch-time group is owned, never a group inferred
from a PID file. Descendants that deliberately detach into a different session or
process group are outside this guarantee. Remote SSH teardown does not prove
remote termination. Resume identity, readiness, instruction delivery and task
acceptance remain distinct.
Claude's event vocabulary is mapped by the observer but does not acquire a new
production supervisor through this change. Other native mappings remain visibly
unimplemented. Existing ExecutionDescriptor work in PR4699 owns invocation
model/effort identity; this change does not create a competing identity source.

Recheck the declaration digests, observations, process lifecycle and dispatch
receipt consumer from this checkout:

```bash
uv run pytest tests/shared/test_capability_load_set.py \
  tests/shared/test_execution_observer.py \
  tests/scripts/test_hapax_codex_headless.py \
  tests/scripts/test_hapax_methodology_dispatch.py -q
```

All tests must pass. The cancellation fixtures exercise real local processes;
provider execution and semantic instruction uptake are not implied by this run.

Container construction and replay are documented in
[Native harness substrates](native-harness-substrates.md).

## Manual native foreign-instruction fixture

Use existing native Linux executables, with an output directory that does not
exist. Substitute the explicitly selected Grok binary path; the Muse path below
identifies the binary used for the original scratch observation.

```bash
python3 scripts/probe-native-foreign-instructions.py \
  --grok /absolute/path/to/native/grok \
  --muse /absolute/path/to/native/muse-bin-1.3.0-R3401.1 \
  --output-dir /tmp/native-foreign-instructions-replay
```

The script rejects shell wrappers, creates four isolated homes and Git projects,
and supplies explicit fixture instructions. Its child environment does not inherit
host credentials, provider settings, native-home overrides or XDG configuration.
It neither installs clients nor edits live configuration. Native initialization
may write state inside the fixtures. This is environment isolation, not an OS
sandbox or proof that a native client cannot consult system-wide paths.

Grok runs `inspect --json` with process-local `GROK_FOLDER_TRUST=0` in its
isolated HOME/GROK_HOME. This bypasses the folder-trust prompt only for that
fixture process; it changes no estate trust setting.
The cases set `compat.claude.agents=true/rules=false` and
`agents=false/rules=true`. Expected active paths include native global/project
AGENTS and root project CLAUDE in both cases. Foreign global and hidden project
CLAUDE follow `agents`; the foreign global `rules/unique.md` follows `rules`.
Entries marked disabled are excluded from the active set; the original inspection
output remains intact.

Muse uses its echo provider with approval judging, shell and write tools disabled,
and trusts only its fixture workspace. Both cases contain native, Claude and Codex
globals; only `context.foreign_personal_rules` changes, while
`foreign_personal_skills=true`. A 40×120 PTY answers cursor-position requests and
sends `/rules` and Enter separately, then `/exit` and Enter separately. Capture
and child cleanup are bounded. The script sends no inference prompt.

Inspect `summary.json` and its `raw_logs` paths. Exit zero means all four fixture
observations matched. Muse requires the actual rules report, its native user rule,
and explicit “not read” reports for both foreign globals; a prompt or completion
menu alone is insufficient. `terminated` records whether Muse required cleanup
after `/exit`. Missing, changed or timed-out evidence exits nonzero and retains
raw output for inspection.

These are discovery/report observations for the selected binaries and fixtures.
They do not establish content delivery, semantic uptake, live-session readiness,
quota headroom, or route admission. The summary records
`semantic_uptake: unobserved` and `may_authorize: false`. A missing native global,
other releases, and foreign skill loading remain outside this fixture.


Automatic repository rotation discovers regular authored files, including the
extracted policy sources. An in-tree compatibility symlink is covered through
its canonical target once. For an instruction symlink targeting outside that
scan tree, pass the alias explicitly to `scripts/check-claude-md-rot.sh`; the
workspace monthly audit follows named aliases and deduplicates resolved targets.


### Recheck Agy dossier delivery and child cleanup

Run `uv run --no-sync pytest tests/scripts/test_hapax_agy_reviewer.py -q` from
the candidate source. Protocol/ownership doubles replace only the mount-command
builder in a test harness so their original Python fixtures remain executable;
the shipped wrapper has no bypass switch. Separate real-Bubblewrap tests exercise
host-root marker hiding, host `/proc` hiding, read-only mounts, missing runtime or
containment refusal, contained stdin/OAuth delivery, exit, tool refusal, timeout
and caller lifetime cancellation. The protocol doubles exercise short and 2.5 MB
Unicode dossiers,
OAuth isolation and raw/nested-JSON-escaped echo suppression on both streams before
parsing (including native failures), semantic YAML token checks, native final-result
unwrapping, malformed output, timeout, caller cancellation and process ownership.
The caller retains YAML schema/checklist validation after the wrapper extracts
one successful native result's fenced response. Before forwarding that response,
the wrapper uses the runtime's declared PyYAML dependency and the caller's
SafeLoader to check all string keys/values and binary scalars for seeded secrets.
YAML escapes and line continuations therefore cannot reconstruct a token after
the guard. Malformed YAML is refused; the wrapper does not delegate an unexamined
document to the caller's prose-repair path. Native errors retain nonzero
status and screened stderr; partial model responses are not forwarded.

Containment integration tests skip with the missing bindings listed on hosts
without the qualified runtime files (including generic Ubuntu CI). Such a skip
is unobserved containment, not a pass. Missing-Bubblewrap and missing-dependency
refusal tests still run there. On the qualified host, a namespace setup failure
fails the integration tests rather than skipping them.

Before accepting a result, the wrapper also checks every native `step_update`.
Only known `user_input`, `agent_response` and `checkpoint` steps are accepted.
Tool/subagent steps, invocation metadata (even null), unknown fields/categories,
and malformed step envelopes are refused with a next action. This also discards
native stderr for that review; an existing nonzero native status is preserved.
Raw secret screening still runs first, and owned-group cleanup precedes parsing.
The native event contract is described in the
[headless reference](https://antigravity.google/docs/cli/headless/).

This is refusal of a completed stream, not prevention of tool execution. A valid
fenced result, prompt prohibition, or stream without tool events does not prove
complete no-search. Qualify any proposed isolated native no-tool configuration
with a negative tool-attempt probe and compare observed client/model, credential
binding, admission route, billing surface and timeout before adopting it. Keep
tool-attempt reviews refused if that qualification is unavailable. CLI help and
official permission/custom-agent documentation are candidate configuration
evidence; neither replaces an observed enforcement boundary.

The wrapper forks a small lifetime supervisor before launching Bubblewrap, which
leads a new session/process group containing Agy. The supervisor observes exit
with `waitid(WNOWAIT)`
and checks the unreaped child's PGID/SID before signalling that group. Keeping
the child unreaped reserves its identifier until TERM, a 150 ms cleanup grace,
KILL and wait finish. The original print timeout and pinned model are unchanged.
The private lifetime pipe closes if the caller kills the outer wrapper, including
SIGKILL from `subprocess.run(timeout=...)`, so the supervisor can finish cleanup
and remove the temporary credential workspace. Captured output uses unlinked
files, avoiding a hang on pipe descriptors inherited by descendants.

During native launch the supervisor latches SIGTERM/SIGINT without raising, so
the child handle cannot be lost between spawn and assignment. Launch and timeout
setup are inside the cleanup boundary; cancellation is raised after ownership
is recorded. Cleanup still verifies PGID/SID, ignores repeated cancellation
until reaping finishes, and restores the previous signal handlers. Focused
`test_launch_window_signal_cleans_live_owned_group` cases inject both signals
before `Popen` returns and during deadline setup, plus a direct setup exception.

This is bounded process-group cleanup. At that boundary, a descendant which
deliberately leaves
the group/session is not proven owned by that boundary and is not killed. Killing
the supervisor itself with SIGKILL, host failure, or external child reaping is
outside the cleanup guarantee. Do not remedy those limits by killing role-wide
matches or guessing ownership from command names. The tests retain an escaped
child and an unrelated process deliberately, then dispose of their own fixtures.
The additional PID namespace and `--die-with-parent` bound the contained process
tree. This does not authorize signalling any unrelated host process.

The mandatory `/usr/bin/bwrap` boundary constructs an empty filesystem with a
private PID namespace and procfs, fresh devices and `/tmp`, disabled nested user
namespaces, and dropped capabilities. It binds only the existing invocation's
workspace (including its original seeded HOME) and individual read-only runtime
files. `REVIEW_RUNTIME_FILES` declares the qualified x86-64 Linux loader and its
native/shell libraries, bash, DNS configuration and CA bundle; the selected Agy
binary is bound as `/usr/bin/agy`. The list is a runtime binding, not permission
to discover and mount parent trees. No host home, repository, host `/proc`, system
directory tree or host socket is mounted. Missing files, unavailable Bubblewrap
or rejected namespace setup refuse execution; there is no uncontained retry.
Requalify exact dependency bindings on a different host rather than widening
mounts. See the [Bubblewrap options](https://github.com/containers/bubblewrap/blob/main/bwrap.xml).

Network remains shared for the same subscription route. This filesystem boundary
is not an egress filter or a no-search guarantee: a contained tool attempt still
causes stream refusal, and the seeded credential remains readable to the native
client. The existing token screens remain mandatory. Use a harmless host-only
marker outside the bound workspace for a negative read/search probe and inspect
the actual Agy executable hash, mount/PID namespaces, pinned model and native
result. Keep that source-probe evidence separate from installed qualification.

The qualified-host full-wrapper regression exercises both the wrapper's print
timeout and the actual caller's `subprocess.run(timeout=...)` SIGKILL path with
real Bubblewrap. It observes a live descendant in separate PID/mount namespaces,
then checks the recorded process identities and removal of the seeded temporary
workspace. It does not replace the wrapper's containment command. Reproduce it
in the source checkout with:

```bash
uv run --no-sync pytest tests/scripts/test_hapax_agy_reviewer.py \
  -k full_contained_wrapper_timeout -q -rs
```

A skip means the host lacks a declared runtime binding; it is unobserved evidence,
not a containment pass. On the qualified host both cases must pass without skips.
Generic CI and this synthetic-client regression do not qualify installed Agy.

Before claiming activation, bind the installed wrapper path and SHA-256 to the
accepted source, record local `agy --help` and binary identity, and observe an
admitted exact-head review through the actual caller. Check that the final result
parses, no dossier-search command is launched, and no members of that invocation's
proven group remain after completion/timeout. Source doubles and native local
`/help` parsing establish their respective boundaries only; they do not establish
provider reasoning, signed acceptance, or the installed runtime postimage. Do not
alter existing reviewer sessions or admission, model, billing or review-seat rules
while making that observation.


Runnable recheck (bash, on the bound runtime host). These commands record
identities, hashes and process metadata, never token files, environment contents
or process arguments. The review launch requires independent acceptance and
separate release/runtime authorization; source authors must leave it unexecuted
while release is held. Select an admitted PR/head under that authorization.

```bash
agy_recheck_root=$(systemctl --user show hapax-pr-review-dispatch.service \
  --property=WorkingDirectory --value)
test -n "$agy_recheck_root" && test -d "$agy_recheck_root" || exit 1
agy_recheck_dir=$(mktemp -d)
export AGY_RECHECK_ROOT="$agy_recheck_root" AGY_RECHECK_DIR="$agy_recheck_dir"
python3 - <<'PY_IDENTITIES'
import hashlib, json, os
from pathlib import Path
root = Path(os.environ["AGY_RECHECK_ROOT"])
paths = [root / "scripts/hapax-agy-reviewer", root / "scripts/cc-pr-review-dispatch.py",
         Path.home() / ".local/bin/hapax-agy-reviewer", Path("/usr/bin/agy")]
rows = [{"path": str(p), "resolved": str(p.resolve(strict=True)),
         "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
         "mode": oct(p.stat().st_mode & 0o777), "size": p.stat().st_size} for p in paths]
Path(os.environ["AGY_RECHECK_DIR"], "identities.json").write_text(json.dumps(rows, indent=2))
print(json.dumps(rows, indent=2))
PY_IDENTITIES
/usr/bin/agy --help > "$agy_recheck_dir/agy-help.txt"
# Compare identities.json with the exact accepted source hashes before continuing.
# Set AGY_RECHECK_PR to the separately authorized, admitted PR number.
: "${AGY_RECHECK_PR:?set the authorized PR number}"
gh pr view "$AGY_RECHECK_PR" --repo hapax-systems/hapax-council \
  --json headRefOid > "$agy_recheck_dir/head-before.json"
uv --directory "$agy_recheck_root" run python scripts/cc-pr-review-dispatch.py \
  --pr "$AGY_RECHECK_PR" > "$agy_recheck_dir/admission-plan.json"
```

Inspect the plan's route, quality floor and admission before applying it. Do not
use `--force`, change routes or renew receipts to bypass a refusal. The following
observer launches the installed caller once and samples only its descendants.
It records start times as well as PID/PGID/SID, preserving the observed ancestry
for the Bubblewrap session leader and its Agy descendant. It never signals any
process.

```bash
export AGY_RECHECK_PR
uv --directory "$agy_recheck_root" run python - <<'PY_OBSERVE'
import hashlib, json, os, subprocess, time
from pathlib import Path
root, evidence = Path(os.environ["AGY_RECHECK_ROOT"]), Path(os.environ["AGY_RECHECK_DIR"])
agy = Path("/usr/bin/agy").resolve(strict=True)
agy_sha256 = hashlib.sha256(agy.read_bytes()).hexdigest()
def snapshot():
    rows = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            raw = path.read_text()
            fields = raw.rsplit(")", 1)[1].split()
            pid = int(path.parent.name)
            rows[pid] = {"pid": pid, "ppid": int(fields[1]), "pgid": int(fields[2]),
                         "sid": int(fields[3]), "start": fields[19], "state": fields[0],
                         "name": raw.split("(", 1)[1].rsplit(")", 1)[0]}
        except (OSError, ValueError, IndexError):
            continue
    return rows
leaders, searches, clients = {}, [], {}
with (evidence / "caller-output.json").open("x") as out, (evidence / "caller-stderr.txt").open("x") as err:
    proc = subprocess.Popen(["uv", "--directory", str(root), "run", "python",
                             "scripts/cc-pr-review-dispatch.py", "--pr",
                             os.environ["AGY_RECHECK_PR"], "--apply"], stdout=out, stderr=err)
    while proc.poll() is None:
        rows = snapshot()
        for pid, row in rows.items():
            chain, parent = [row], row["ppid"]
            while parent in rows and parent not in {item["pid"] for item in chain}:
                chain.append(rows[parent])
                if parent == proc.pid:
                    try:
                        executable = Path(f"/proc/{pid}/exe")
                        if executable.resolve(strict=True) == Path("/usr/bin/bwrap"):
                            if row["pid"] == row["pgid"] == row["sid"]:
                                leaders[(pid, row["start"])] = chain
                        if row["name"] == "agy" and (pid, row["start"]) not in clients:
                            clients[(pid, row["start"])] = {
                                "pid": pid, "pgid": row["pgid"], "ancestry": chain,
                                "binary_hash_matches": hashlib.sha256(executable.read_bytes()).hexdigest() == agy_sha256,
                                "private_mount_namespace": os.readlink(f"/proc/{pid}/ns/mnt") != os.readlink("/proc/self/ns/mnt"),
                                "private_pid_namespace": os.readlink(f"/proc/{pid}/ns/pid") != os.readlink("/proc/self/ns/pid"),
                            }
                        if row["name"] == "find":
                            searches.append(row)
                    except OSError:
                        pass
                    break
                parent = rows[parent]["ppid"]
        time.sleep(0.02)
    time.sleep(1)  # allow the lifetime supervisor's cleanup grace to finish
    groups = {pid for pid, start in leaders}
    survivors = [row for row in snapshot().values() if row["pgid"] in groups]
    result = {"caller_exit": proc.returncode, "leader_ancestries": list(leaders.values()),
              "native_clients": list(clients.values()),
              "observed_find": searches, "group_members_after": survivors,
              "coverage": "sampled /proc only; short-lived processes may be missed"}
    (evidence / "owned-groups.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
PY_OBSERVE
gh pr view "$AGY_RECHECK_PR" --repo hapax-systems/hapax-council \
  --json headRefOid > "$agy_recheck_dir/head-after.json"
cmp "$agy_recheck_dir/head-before.json" "$agy_recheck_dir/head-after.json"
```

Re-run the installed caller's read-only plan to validate the stored exact-head
dossier and report its admission blockers:

```bash
uv --directory "$agy_recheck_root" run python scripts/cc-pr-review-dispatch.py \
  --pr "$AGY_RECHECK_PR" > "$agy_recheck_dir/post-review-validity.json"
```

Require independent signature verification under the existing FileStore signing
binding, plus the dossier's exact head, Gemini verdict and `parse_path: fence`;
disposition any route debt separately. An exit-zero caller alone is
not a successful review: it can return a refusal or an already-reviewed result.
Missing leader ancestry means the owned-group observation is **unobserved**.
Require a native client with matching executable hash, separate mount/PID
namespaces, and PGID matching a recorded leader; otherwise containment at the
installed caller boundary is **unobserved**.
Any remaining member, including a zombie, needs disposition; never kill it from
this sample. Sampling cannot certify absence of short-lived dossier searches or
escaped descendants. Record that limit; a complete no-search claim still needs
an authorized execution trace or equivalent native tool-event observation with
credential-safe capture. Do not dump native logs, token files or `/proc/*/cmdline`.
The source timeout tests do not substitute for a separately authorized installed
timeout observation. Preserve this record as pending if release, admission or
observation coverage is missing.

The independent runtime observer can verify a returned dossier without printing
its findings or signing material. Set `AGY_RECHECK_DOSSIER` to the exact
`dossier_path` returned by the caller, then run:

```bash
: "${AGY_RECHECK_DOSSIER:?set the caller-returned dossier path}"
export AGY_RECHECK_DOSSIER
uv --directory "$agy_recheck_root" run python - <<'PY_SIGNATURE'
import hashlib, json, os, subprocess
from pathlib import Path
import yaml
from shared.public_gate_receipts import _mapping_has_trusted_authority_signature
evidence = Path(os.environ["AGY_RECHECK_DIR"])
path = Path(os.environ["AGY_RECHECK_DOSSIER"])
raw = path.read_bytes()
dossier = yaml.safe_load(raw)
key = subprocess.run([str(Path.home() / ".local/bin/hapax-secret"),
                      "hapax-public-gate-authority-hmac-key"],
                     capture_output=True, text=True, timeout=20)
if key.returncode or not key.stdout.strip():
    raise SystemExit("Signing binding unavailable; restore the declared FileStore credential.")
verified = _mapping_has_trusted_authority_signature(dossier, key.stdout.strip())
expected = json.loads((evidence / "head-before.json").read_text())["headRefOid"]
row = {"dossier_path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
       "hmac_verified": verified, "head_matches": dossier.get("head_sha") == expected,
       "pr_matches": dossier.get("pr") == int(os.environ["AGY_RECHECK_PR"]),
       "team_verdict": dossier.get("review_team_verdict"),
       "gemini": [{"verdict": seat.get("verdict"), "parse_path": seat.get("parse_path")}
                  for seat in dossier.get("reviewers", []) if seat.get("family") == "gemini"],
       "route_debt": dossier.get("post_route_receipt_rereview_required")}
with (evidence / "signature-readback.json").open("x") as out:
    json.dump(row, out, indent=2)
print(json.dumps(row, indent=2))
raise SystemExit(0 if verified and row["head_matches"] and row["pr_matches"] else 1)
PY_SIGNATURE
```

This checks signature and identity, not acceptance. A signed blocked verdict is
still blocked. Check the Gemini fence result and disposition route debt separately.
The following executable readback reports the existing process sampler's search
and cleanup observations, and fails closed on the complete no-search predicate:

```bash
python3 - <<'PY_SEARCH_READBACK'
import json, os
from pathlib import Path
evidence = Path(os.environ["AGY_RECHECK_DIR"])
sample = json.loads((evidence / "owned-groups.json").read_text())
row = {"find_observed": bool(sample["observed_find"]),
       "leader_observed": bool(sample["leader_ancestries"]),
       "remaining_group_members": len(sample["group_members_after"]),
       "complete_no_search": "unobserved: /proc sampling can miss short-lived tools",
       "next_action": "runtime owner must supply an authorized complete execution/tool-event trace"}
with (evidence / "search-readback.json").open("x") as out:
    json.dump(row, out, indent=2)
print(json.dumps(row, indent=2))
raise SystemExit(1)
PY_SEARCH_READBACK
```

No complete execution/tool-event trace collector is supplied by this source
repair. That negative observation remains a runtime qualification blocker, even
when the sampler saw no `find`. Do not turn this command's deliberate nonzero exit
into a passing no-search claim or substitute source doubles for the missing trace.

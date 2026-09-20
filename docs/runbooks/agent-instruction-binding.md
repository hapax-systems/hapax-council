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
the Vibe launcher no longer writes lane identity into repository instructions.

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
Publication backs up originals, detects overlapping destinations, verifies
readback and restores attempted writes on failure. Rollback errors retain the
backup and report both failures. The current receipt records hashes, byte counts
and source revision; it deliberately says native loading is unobserved.
No coordinator restart or trust change is required. Existing sessions are not
claimed to have reloaded the new body.

For isolated preparation or a scoped activation, stage the committed source:

```bash
instruction_revision=$(git rev-parse HEAD)
instruction_stage=$(mktemp -d)
git archive "$instruction_revision" config/agent-instructions \
  scripts/install-agent-instructions.py | tar -x -C "$instruction_stage"
python3 "$instruction_stage/scripts/install-agent-instructions.py" \
  --source "$instruction_stage" --home /absolute/target/home \
  --source-revision "$instruction_revision"
# Add --apply only when activating the inspected result.
```

The default binds the explicit home's default native paths. Ambient `CODEX_HOME`,
`GROK_HOME`, other native-home variables and `XDG_CONFIG_HOME` are ignored unless
`--use-native-home-env` is supplied deliberately. Preserve a supported deployment's
chosen roots; do not silently install into another session's alternate home.
Use `--binding NAME` for a selected substrate. The neutral shared copy is always
included. The installer changes no provider credentials, trust or running process.

To restore the latest install, pass its `current.json` rollback path to
`--restore-backup PATH --home /absolute/target/home`. This restores original file
contents, modes, symlinks, absence and the predecessor receipt. The CLI refuses
if a successor install or changed output needs reconciliation. Backups of native
settings remain local and private; never publish their contents.

## Declared inputs and native lifecycle

`PlatformCapabilityRoute.native_load_set` extends the existing registry. Eleven
native routes declare instruction digests, optional configuration paths, native
home selection, memory scope and loading flags. `null` extension sets mean
unobserved, not empty. API/tool routes are not forced into a native-file model.
`hapax-platform-capability-receipts` attaches host-side observations to its existing
receipt. Presence and matching bytes do not establish native delivery.

`shared.capability_load_set.observe_load_set` can join native path/hash witnesses
to the declaration and identify missing, changed or unexpected inputs. Unknown
hashes cannot pass as observed delivery. The present inventory covers declared
native/project roots; it is not a complete scan of ancestors, nested imports,
plugins, skills, hooks, MCP or memory. Caller-provided witnesses are support
evidence with `may_authorize=false`. The offered declared-load-set programme
remains open for complete native producers and configuration inventories.

Codex headless execution now gives each launch a fresh native JSON stream and
separate stderr. Its supervisor waits for the actual child, emits a create-once
lifecycle receipt, and the existing methodology-dispatch receipt consumes that
exact path. `output.jsonl` remains a compatibility symlink; predecessor files are
retained. Requested host names, an SSH transport exit, PID existence and a
successful interactive launcher do not establish native completion.

Completion needs an unambiguous native session, successful terminal event, clean
event stream and owned process exit zero. Cancellation requires observed signal
termination; the supervisor bounds termination and reaps its child. Resume
identity, readiness, instruction delivery and task acceptance remain distinct.
Claude's event vocabulary is mapped by the observer but does not acquire a new
production supervisor through this change. Other native mappings remain visibly
unimplemented. Existing ExecutionDescriptor work in PR4699 owns invocation
model/effort identity; this change does not create a competing identity source.

Container construction and replay are documented in
[Native harness substrates](native-harness-substrates.md).

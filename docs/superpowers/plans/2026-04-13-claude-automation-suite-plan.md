# Claude Code Automation Suite — Plan

**Date:** 2026-04-13
**Author:** beta session 5
**Related design:** `docs/superpowers/specs/2026-04-13-claude-automation-suite-design.md`

---

## 1. Phases

| Phase | Scope | Output | Risk |
|---|---|---|---|
| 1 | Three hook scripts in `hooks/scripts/` | Three `.sh` files + smoke test transcripts | Low — exit-0 advisories, no behaviour change in success paths |
| 2 | Three subagent definitions in `tooling/claude-agents/` | Three `.md` files + an `INSTALL.md` | Low — machine-local install, no CI impact |
| 3 | Wire hooks into the operator's global Claude settings + smoke-test each | One settings.json patch + three transcripts | Low — easily reverted |
| 4 | Bundle into PR + merge | One PR with hooks + tooling + design + plan + carrier | Medium — first PR with new hook scripts |

All four phases land in **one PR** because the hooks and subagents are interdependent (the design doc references them, the install doc references all of them, and the smoke test depends on the hooks being present at their canonical paths).

## 2. Phase 1 — Hook scripts

### 2.1 `hooks/scripts/docs-only-pr-warn.sh`

**Trigger:** PreToolUse, matcher `Bash`, command matching `\bgit\s+commit\b`.

**Logic:**

1. Read JSON from stdin via `INPUT="$(cat)"`.
2. Extract `.tool_input.command` via jq. Bail with exit 0 if not a `git commit`.
3. Bail with exit 0 if not in a git work tree.
4. Bail with exit 0 if current branch is `main` or `master` (the warning only matters on feature branches that will become PRs).
5. Get staged file list: `git diff --cached --name-only` (also include unstaged via `git diff --name-only` if the command contains `-a` or `--all`).
6. If the staged file list is empty, exit 0.
7. Test if every staged file matches one of the paths-ignore patterns:
   - `docs/`
   - `*.md` at root (no slash)
   - `lab-journal/`
   - `research/`
   - `axioms/.*\.md$`
8. If ALL staged files match, emit stderr advisory:
   ```
   ADVISORY: All staged changes are under ci.yml paths-ignore (docs/**, *.md, lab-journal/**, research/**, axioms/**/*.md).
   The CI test job will not fire and branch protection will block the PR from merging.
   Bundle a non-markdown carrier file. Examples from prior PRs:
     - PR #708: __all__ export in shared/impingement_consumer.py
     - PR #720: __all__ export in agents/reverie/debug_uniforms.py
   See CLAUDE.md § Council-Specific Conventions for the canonical pattern.
   ```
9. Exit 0 (advisory).

**Edge cases:**

- `git commit --amend` on a docs-only commit: still warn (the amended PR will hit the same wall).
- `git commit -m "message about *.md files"`: must not match the docs-only pattern from the message text. Solution: only inspect `git diff --cached --name-only`, not the command string.
- `git commit -a` with mixed staged + unstaged: include both in the test.
- Initial commit with no parent: `git diff --cached` works on initial commit too.

### 2.2 `hooks/scripts/cargo-check-rust.sh`

**Trigger:** PostToolUse, matcher `Edit|Write|MultiEdit|NotebookEdit`.

**Logic:**

1. Read JSON from stdin via `INPUT="$(cat)"`.
2. Extract `.tool_input.file_path` (and the `.path` / `.notebook_path` aliases for safety).
3. Bail with exit 0 if path doesn't match `hapax-logos/crates/*/src/*`.
4. Extract the crate name from the path (e.g., `hapax-logos/crates/hapax-visual/src/foo.rs` → `hapax-visual`).
5. Resolve the workspace root by walking up to find `hapax-logos/Cargo.toml`.
6. Check a per-crate cache file at `/tmp/hapax-cargo-check-<crate>.lock`. If mtime is < 30s old, skip (debounce).
7. Run `cd <workspace>/hapax-logos && cargo check -p <crate> --offline` with a 60s timeout. Capture stderr.
8. If exit code is 0:
   - Touch the cache file. Exit 0 silently.
9. If exit code is non-zero:
   - Print first 20 lines of stderr (filtered to error/warning lines via `grep -E 'error|warning'`).
   - Print "Run `cd hapax-logos && cargo check -p <crate>` to see the full diagnostic."
   - Exit 0 (still advisory — don't block, the operator may be mid-edit).

**Why offline first:** Cold-cache cargo check reaches the network and takes ~30s. Offline check is ~1s incremental. Falling back to network only on offline failure keeps the common case fast.

**Why a 30s debounce:** Sequential edits to the same crate would otherwise re-run cargo check N times. 30s is short enough to catch fresh errors but long enough to not block iteration.

### 2.3 `hooks/scripts/relay-coordination-check.sh`

**Trigger:** PreToolUse, matcher `Edit|Write|MultiEdit|NotebookEdit`.

**Logic:**

1. Read JSON from stdin via `INPUT="$(cat)"`.
2. Extract `.tool_input.file_path` (and aliases).
3. Bail with exit 0 if the path doesn't match a cross-worktree-territory prefix (see design §4.3 for the list).
4. Compute the relative path from the workspace root.
5. Glob `~/.cache/hapax/relay/*.yaml` (excluding the current session's own yaml — detect via the `session:` field).
6. For each peer yaml:
   - Skip if `session_status` is `RETIRED` or `CLOSED`.
   - Extract the prose fields: `focus`, `current_item`, every `decisions[].what`, every `context_artifacts[]` element.
   - For each prose field, check if the file basename or any path component (the directory immediately above the file) appears in the prose. Use `grep -F` (literal) for low false-positive rate.
7. If any peer has a match:
   - Emit stderr advisory:
     ```
     ADVISORY: <peer> session is ACTIVE and references <matched-token> in its <field-name>.
     Peer relay: ~/.cache/hapax/relay/<peer>.yaml
     Recent convergence notes: tail -20 ~/.cache/hapax/relay/convergence.log
     Consider checking for in-flight edits before modifying <file-path>.
     ```
   - Continue checking other peers (multiple matches are fine).
8. Exit 0 (advisory).

**Why fuzzy match against prose:** The relay yaml is human-curated. Adding a structured `file_scope` field would force every relay update to maintain it. Fuzzy match against existing fields catches the common case (peers naming a file or directory in `focus`) and degrades gracefully to "no match" otherwise.

**Why exclude RETIRED peers:** The PR #715 cross-worktree edit (delta closed → beta touches Rust) was the canonical safe case. Closed peers don't get the advisory.

## 3. Phase 2 — Subagent definitions

### 3.1 `tooling/claude-agents/shader-bridge-auditor.md`

```yaml
---
name: shader-bridge-auditor
description: Use this agent to audit the four-hop Reverie GPU bridge after editing
  the Python uniforms writer, the Rust override branch in dynamic_pipeline.rs, the
  uniform buffer struct, or any WGSL shader file. Use proactively after editing
  agents/reverie/_uniforms.py, agents/shaders/nodes/*.wgsl,
  hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs, or
  hapax-logos/crates/hapax-visual/src/uniform_buffer.rs.
  <example>
  Context: Operator just added a new content.* key to _uniforms.py.
  user: "Add content.warmth = imagination.warmth * silence to _uniforms.py"
  assistant: "I've added content.warmth. Now I'll use the shader-bridge-auditor
  to verify the new key is routed all the way to a shader read site."
  </example>
  <example>
  Context: Edit to dynamic_pipeline.rs render() loop.
  user: "Add a per-frame override branch for signal.luminosity"
  assistant: "Done. Let me invoke shader-bridge-auditor to confirm there is a
  WGSL shader that actually reads the new signal."
  </example>
  <example>
  Context: WGSL shader edit adding a new uniform read.
  user: "Make content_layer.wgsl read uniforms.intensity for the slot fade-in"
  assistant: "Edited. shader-bridge-auditor will trace this back to confirm a
  Python writer and a Rust override path exist for content.intensity."
  </example>
model: opus
tools: [Glob, Grep, Read, Bash]
---

You are the **shader-bridge-auditor**. You verify the integrity of the
four-hop Reverie GPU bridge any time a participant in that bridge is
edited.

## The four hops

1. **Python writer** — `agents/reverie/_uniforms.py::write_uniforms`
   writes a dict to `/dev/shm/hapax-imagination/uniforms.json`. Each
   key is either `signal.<name>`, `content.<name>`, `<node>.<param>`,
   or `fb.trace_<...>`.

2. **uniforms.json key** — the file that lives in shm. The Rust side
   reads it once per frame.

3. **Rust override branch** — in
   `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs::render`,
   inside the `for (key, &val) in &overrides` loop. Each key prefix
   (`signal.`, `content.`, `<node>.`) has a different routing branch.
   Per-node params route via `params_buffer`; signal/content keys
   route into named fields on `UniformData`.

4. **Shader read site** — the WGSL file that consumes the uniform
   (e.g., `agents/shaders/nodes/content_layer.wgsl` reads
   `uniforms.custom[0][0]` for `material_id`).

## Your audit

For every edit to any of the four hops:

1. **Inventory** every key currently written by `_uniforms.py` (grep for
   `uniforms\["` and `uniforms\.\w+\s*=`).
2. **Inventory** every key read by the Rust override loop (grep for
   `strip_prefix` and the match arms).
3. **Inventory** every WGSL uniform read by every shader in
   `agents/shaders/nodes/*.wgsl` and
   `hapax-logos/crates/hapax-visual/src/shaders/*.wgsl`.
4. **Cross-reference** the three inventories. Report any:
   - Key written by Python with no Rust handler (DEAD WIRE — write goes
     into uniforms.json but Rust drops it on the floor).
   - Key read by a Rust branch with no Python writer (DORMANT HOOK — the
     branch exists for a future writer; document but do not flag as bug).
   - Shader uniform with no Rust populator (BROKEN BRIDGE — the GPU
     reads stale or zero data; this is the F8 class).
5. Format the report as a table with columns:
   `python_writer | uniforms.json key | rust_handler | shader_read | status`.
   Status ∈ {LIVE, DORMANT, DEAD_WIRE, BROKEN_BRIDGE}.

## Constraints

- Read-only. Do not modify any files.
- Do not invent fixes. Report status only; the operator decides whether
  to fix DEAD_WIRE / BROKEN_BRIDGE findings.
- If a finding is in the BROKEN_BRIDGE category (most severe), recommend
  the user run `python -m agents.reverie.debug_uniforms` for the live
  view of the bridge.
- Do not duplicate the bridge documentation in
  `docs/superpowers/specs/2026-04-12-reverie-bridge-repair-design.md` —
  link to it instead.

## Output format

```
shader-bridge-auditor report — <ISO timestamp>

| python_writer | uniforms key | rust_handler | shader_read | status |
| --- | --- | --- | --- | --- |
| _uniforms.py:165 | content.material | dynamic_pipeline.rs:840 | content_layer.wgsl:162 | LIVE |
| _uniforms.py:166 | content.salience | dynamic_pipeline.rs:841 | content_layer.wgsl:169 | LIVE |
| _uniforms.py:167 | content.intensity | dynamic_pipeline.rs:842 | content_layer.wgsl:171 | LIVE |
| (none) | signal.intensity | dynamic_pipeline.rs:816 | (multiple) | DORMANT |
| ... |

Summary: N LIVE, M DORMANT, X DEAD_WIRE, Y BROKEN_BRIDGE.
```

If X or Y > 0, end the report with a clear "ACTION REQUIRED" header.
```

### 3.2 `tooling/claude-agents/affordance-pipeline-tracer.md`

```yaml
---
name: affordance-pipeline-tracer
description: Use this agent to verify every recruited capability has a live dispatch
  handler after editing daimonion run loops, init_pipeline.py, the CPAL runner, or
  any *_capability.py file. Use proactively after editing
  agents/hapax_daimonion/run_*.py, agents/hapax_daimonion/init_pipeline.py,
  agents/hapax_daimonion/cpal/*.py, agents/hapax_daimonion/capability.py, or any
  agents/*_capability.py file. The PR #555 silent regression (six dispatch effects
  dead for ~10 days) is exactly the failure mode this agent catches.
  <example>
  Context: Operator removed a background task from run_inner.py.
  user: "Delete the legacy proactive_delivery_loop spawn from run_inner.py"
  assistant: "I've removed the spawn. Now I'll use affordance-pipeline-tracer to
  verify nothing else depends on that loop being active."
  </example>
  <example>
  Context: Operator added a new capability to init_pipeline.py.
  user: "Register a new memory.recall_episode capability in the affordance pipeline"
  assistant: "Registered. Let me invoke affordance-pipeline-tracer to confirm the
  new capability has a live dispatch handler somewhere — otherwise it would be
  recruited but never executed (the PR #555 class)."
  </example>
  <example>
  Context: Edit to cpal/runner.py.
  user: "Add a new effect to process_impingement"
  assistant: "Done. affordance-pipeline-tracer will verify the new effect doesn't
  duplicate or shadow an existing dispatch path."
  </example>
model: opus
tools: [Glob, Grep, Read]
---

You are the **affordance-pipeline-tracer**. You verify that every
capability registered in the daimonion's affordance pipeline has a live
dispatch handler. The PR #555 regression — six dispatch effects went
silently dead for ten days because the spawn of `impingement_consumer_loop`
was removed without removing the capability registrations — is exactly
the failure mode you exist to catch.

## The dispatch chain

1. **Capability registration** — `agents/hapax_daimonion/init_pipeline.py`
   adds `CapabilityRecord(name=...)` to `_all_records` and indexes them
   into `daemon._affordance_pipeline`.
2. **Pipeline selection** — `daemon._affordance_pipeline.select(imp)`
   returns ranked candidates per impingement.
3. **Dispatch handler** — somewhere in the codebase, a background task
   (typically in `run_loops*.py` or `cpal/runner.py`) iterates the
   selected candidates and routes them to a real effect:
   `_speech_capability.activate`, `activate_notification`,
   `_expression_coordinator.coordinate`,
   `_apperception_cascade.process`, `_system_awareness.activate`, etc.
4. **Background spawn** — the dispatch handler must be inside an
   `asyncio.create_task(...)` call somewhere in
   `run_inner.py` or `run_loops*.py`. If the spawn is missing, the
   handler never runs.

## Your audit

For every edit to a file in the dispatch chain:

1. **Inventory** every `CapabilityRecord(name=...)` registered in
   `init_pipeline.py` (grep for `CapabilityRecord(`).
2. **Inventory** every reference to `daemon._affordance_pipeline.select`
   and `daemon._affordance_pipeline.record_outcome` across the codebase.
3. **Inventory** every dispatch attribute on the daemon
   (`daemon._speech_capability`, `_expression_coordinator`, etc.). For
   each attribute, find:
   - Where it is assigned (init_pipeline.py).
   - Where its `.activate` / `.coordinate` / `.process` / `.search` /
     `.propose` method is called.
   - Whether the calling site is reachable from a spawned background
     task in `run_inner.py`.
4. **Cross-reference** the three inventories. Report any:
   - Capability registered but never selected anywhere (DEAD_REG).
   - Daemon attribute assigned but never invoked (DEAD_ATTR — the
     PR #555 class for `_expression_coordinator` and others).
   - Method called but only from an unspawned function (DEAD_HANDLER —
     the PR #555 class for `impingement_consumer_loop`).
5. Format the report as a table with columns:
   `capability/attribute | registered_at | invoked_at | spawned_from | status`.
   Status ∈ {LIVE, DEAD_REG, DEAD_ATTR, DEAD_HANDLER}.

## Constraints

- Read-only.
- Do not invent fixes. Report status only.
- The PR #710 fix established the canonical pattern: every dispatch
  handler must be reachable from an `asyncio.create_task(...)` call in
  `run_inner.py`. Use that as the gold standard.
- Apperception cascade is a known exception — it is owned by
  `ApperceptionTick` inside `agents/visual_layer_aggregator/aggregator.py`
  and runs on its own cadence. Do not flag it as DEAD_HANDLER.

## Output format

```
affordance-pipeline-tracer report — <ISO timestamp>

| capability/attribute | registered_at | invoked_at | spawned_from | status |
| --- | --- | --- | --- | --- |
| speech_production | init_pipeline.py:122 | cpal/runner.py:484 | run_inner.py:144 | LIVE |
| _expression_coordinator | init_pipeline.py:159 | run_loops_aux.py:266 | run_inner.py:164 | LIVE |
| (PR #555 era — would have been:) |
| _expression_coordinator | init_pipeline.py:159 | run_loops_aux.py:266 | (none) | DEAD_HANDLER |
| ... |

Summary: N LIVE, X DEAD_REG, Y DEAD_ATTR, Z DEAD_HANDLER.
```

If any DEAD_* count > 0, end with "ACTION REQUIRED — silent regression class".
```

### 3.3 `tooling/claude-agents/gpu-smoke-verifier.md`

```yaml
---
name: gpu-smoke-verifier
description: Use this agent to verify the live Reverie GPU bridge after a PR merges
  that touches hapax-visual, agents/reverie/_uniforms.py, agents/reverie/mixer.py,
  or any shader file. Also use when the operator says "verify the bridge",
  "smoke test reverie", or asks about uniforms.json health. Use proactively after
  any cargo-check-clean Rust change to dynamic_pipeline.rs lands on main, because
  end-to-end GPU bridge correctness cannot be verified inside pytest (no wgpu
  device in CI).
  <example>
  Context: A PR touching dynamic_pipeline.rs just merged and the operator wants
  to confirm the bridge is healthy.
  user: "PR #715 just merged. Is the bridge OK?"
  assistant: "Let me invoke gpu-smoke-verifier to read the live state of
  uniforms.json, plan.json, and predictions.json and report HEALTHY/DEGRADED."
  </example>
  <example>
  Context: After a hapax-imagination restart.
  user: "I restarted hapax-imagination, can you check?"
  assistant: "I'll use gpu-smoke-verifier to confirm the new process is rendering
  with the expected uniform key count and recent mtime."
  </example>
  <example>
  Context: Operator asks about reverie health generically.
  user: "How healthy is reverie right now?"
  assistant: "gpu-smoke-verifier will give you a structured report from the live
  shm files."
  </example>
model: opus
tools: [Read, Bash]
---

You are the **gpu-smoke-verifier**. You report the live health of the
Reverie GPU bridge. You exist because end-to-end GPU bridge correctness
cannot be tested in pytest (no wgpu device in CI), so deploy verification
is a manual operation that gets forgotten.

## What you read

| Path | What it tells you |
|---|---|
| `/dev/shm/hapax-imagination/uniforms.json` | Live uniform writes from the reverie mixer (must be ≥ plan_defaults_count - 5 keys, mtime < 60s) |
| `/dev/shm/hapax-imagination/pipeline/plan.json` | Current shader plan (the canonical defaults set) |
| `/dev/shm/hapax-imagination/current.json` | The active imagination fragment (salience, material, dimensions) |
| `/dev/shm/hapax-reverie/predictions.json` | The 8-prediction monitor sample (P1–P8, look at P7 and P8 specifically for bridge health) |
| `/dev/shm/hapax-visual/frame.jpg` mtime | Frame cadence (must be < 5s old for an active session) |

## Your smoke

1. Run `python -m agents.reverie.debug_uniforms --json` to get the
   canonical `UniformsSnapshot`. This is the same data model used by P8
   in the prediction monitor and the `reverie_uniforms_*` Prometheus
   gauges, so all three sources will agree.
2. Read `/dev/shm/hapax-reverie/predictions.json` and extract P7
   (uniforms freshness) and P8 (uniforms coverage) status.
3. Read `/dev/shm/hapax-imagination/current.json` and report the active
   imagination fragment salience and material.
4. `stat -c '%Y' /dev/shm/hapax-visual/frame.jpg` and compute the age
   relative to `date +%s`.
5. Cross-reference: if uniforms.json reports `content.material > 0`,
   verify current.json has a non-water material. If they disagree, the
   bridge is fresh but the writer is producing stale data — that's a
   different class of bug than F8.

## Health classification

- **HEALTHY** — uniforms.json deficit ≤ 5, P7 healthy, P8 healthy, frame
  age < 5s, current.json salience > 0.
- **DEGRADED** — any of the above out of bounds. Report which one and
  point at the canonical fix path.
- **DROUGHT** — uniforms.json deficit > 5 OR P8 unhealthy. This is the
  F8 / dimensional-drought class. Recommend the operator run
  `python -m agents.reverie.debug_uniforms` for the verbose report and
  check `journalctl --user -u hapax-reverie -n 100` for stack traces.
- **DEAD** — uniforms.json missing or empty, frame age > 60s. The
  daemon is down or stuck. Recommend
  `systemctl --user status hapax-reverie hapax-imagination
  hapax-imagination-loop`.

## Constraints

- Read-only. You can run jq, stat, systemctl is-active, but no writes.
- If `python -m agents.reverie.debug_uniforms` is not available (the
  fallback CLI doesn't exist on this branch), parse the JSON yourself
  with jq.
- If the live shm files are missing entirely, classify as DEAD and stop.

## Output format

```
gpu-smoke-verifier report — <ISO timestamp>

Status: HEALTHY | DEGRADED | DROUGHT | DEAD

uniforms.json
  path: /dev/shm/hapax-imagination/uniforms.json
  age: <Ns>
  key_count: N (plan defaults: M, deficit: D)
  content.{material,salience,intensity}: <values>

predictions.json
  P7 (freshness): healthy=<bool> actual=<Ns>
  P8 (coverage):  healthy=<bool> actual=<deficit>

current.json
  salience: <0.0-1.0>
  material: <name>

frame.jpg
  age: <Ns>

Recommendation: <next-action> if not HEALTHY.
```
```

### 3.4 `tooling/claude-agents/INSTALL.md`

```markdown
# Installing the Claude Code automation suite

Per-machine install steps. Run after merging the PR that ships these
files.

## 1. Copy subagent definitions to the global agents directory

Locate your global Claude agents directory. The default is
`~/.claude/agents/`. If it doesn't exist, create it.

```bash
mkdir -p ~/.claude/agents
cp tooling/claude-agents/{shader-bridge-auditor,affordance-pipeline-tracer,gpu-smoke-verifier}.md ~/.claude/agents/
```

These subagents are auto-invoked by the main Claude based on the
`description:` field in each file. You do not need to invoke them
explicitly — Claude reasons about when to spawn them based on the
trigger phrases ("Use proactively after editing X").

## 2. Wire the new hooks into the global Claude settings

Add the three new hook entries to your global Claude `settings.json`
(typically `~/.claude/settings.json`). The hooks live in the workspace
at `<workspace>/hooks/scripts/`.

Add these entries to the existing `hooks.PreToolUse` and
`hooks.PostToolUse` arrays:

```jsonc
{
  "hooks": {
    "PreToolUse": [
      // ... existing entries ...
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "<workspace>/hooks/scripts/docs-only-pr-warn.sh" }
        ]
      },
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          { "type": "command", "command": "<workspace>/hooks/scripts/relay-coordination-check.sh" }
        ]
      }
    ],
    "PostToolUse": [
      // ... existing entries ...
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          { "type": "command", "command": "<workspace>/hooks/scripts/cargo-check-rust.sh" }
        ]
      }
    ]
  }
}
```

Replace `<workspace>` with the absolute path to your hapax-council
checkout.

## 3. Restart any open Claude Code sessions

Hooks are loaded at session start. Existing sessions will not see the
new hooks until restart.

## 4. Smoke test

### Hook 1: docs-only-pr-warn
On a feature branch, stage a docs-only change and try to commit:
```bash
git checkout -b test/docs-only
echo "test" > docs/test.md
git add docs/test.md
git commit -m "test"
```
Expected: stderr advisory about the carrier bundle. Commit still succeeds.

### Hook 2: cargo-check-rust
Edit a file under `hapax-logos/crates/*/src/` (e.g., add a comment to
`dynamic_pipeline.rs`). The hook should silently run cargo check on the
relevant crate. Introduce a syntax error and the hook should print the
first 20 error lines to stderr.

### Hook 3: relay-coordination-check
With an active peer relay yaml in `~/.cache/hapax/relay/`, edit a file
under one of the cross-worktree-territory prefixes
(`hapax-logos/crates/`, `agents/reverie/`, etc). If the peer's
`focus`/`current_item`/etc references the file, the hook prints an
advisory.

### Subagent invocation
After editing `agents/reverie/_uniforms.py`, the main Claude should
spontaneously invoke the `shader-bridge-auditor` agent. After editing
`agents/hapax_daimonion/run_inner.py`, it should invoke the
`affordance-pipeline-tracer` agent. After noting a PR has merged that
touches `hapax-visual`, it should invoke `gpu-smoke-verifier`.

## 5. Disable individually

To disable any single hook, remove its entry from `settings.json` and
restart sessions.

To disable any single subagent, delete the corresponding `.md` from
`~/.claude/agents/` and restart sessions.

The hook scripts in `hooks/scripts/` and the canonical sources in
`tooling/claude-agents/` can stay in the repo indefinitely.
```

## 4. Phase 3 — Wire and smoke-test

The hook bindings are added to the operator's global Claude `settings.json`
(local to this machine). Three smoke tests:

### 4.1 docs-only-pr-warn smoke

Construct a fake JSON payload and pipe it to the hook:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git commit -m test"}}' \
  | hooks/scripts/docs-only-pr-warn.sh
```

Expected behaviour:
- On a feature branch with only docs/md staged → stderr advisory + exit 0.
- On a feature branch with mixed staged → exit 0 silently.
- On main → exit 0 silently.

### 4.2 cargo-check-rust smoke

```bash
echo '{"tool_name":"Edit","tool_input":{"file_path":"<workspace>/hapax-logos/crates/hapax-visual/src/lib.rs"}}' \
  | hooks/scripts/cargo-check-rust.sh
```

Expected: silent exit 0 (assuming hapax-visual currently compiles). If
a deliberate syntax error is introduced, stderr should show the cargo
error.

### 4.3 relay-coordination-check smoke

```bash
echo '{"tool_name":"Edit","tool_input":{"file_path":"<workspace>/agents/reverie/_uniforms.py"}}' \
  | hooks/scripts/relay-coordination-check.sh
```

Expected: if any peer's relay yaml references `_uniforms.py` or
`reverie/`, stderr advisory; otherwise silent exit 0.

## 5. Phase 4 — PR + merge

PR title: `feat(claude-automation): hooks + subagents for auto-firing safeguards`

PR body: bullet list of the three hooks, three subagents, install path,
and the design+plan doc references.

Bundle:
- `hooks/scripts/docs-only-pr-warn.sh` (executable)
- `hooks/scripts/cargo-check-rust.sh` (executable)
- `hooks/scripts/relay-coordination-check.sh` (executable)
- `tooling/claude-agents/shader-bridge-auditor.md`
- `tooling/claude-agents/affordance-pipeline-tracer.md`
- `tooling/claude-agents/gpu-smoke-verifier.md`
- `tooling/claude-agents/INSTALL.md`
- `docs/superpowers/specs/2026-04-13-claude-automation-suite-design.md`
- `docs/superpowers/plans/2026-04-13-claude-automation-suite-plan.md`

The hook scripts and `tooling/` files are non-md so the PR escapes the
CI paths-ignore filter without needing a separate carrier. (This is the
first PR shipped through the new `docs-only-pr-warn` hook's logic, in a
sense: the suite carries its own carrier by virtue of the hook scripts.)

CI should pass cleanly because none of the changes touch tested code
paths. The hook scripts are bash, not Python, so ruff/pyright/pytest
all see no diff in their domains.

After merge:
1. Reset beta-standby to main.
2. Run the manual install steps from `tooling/claude-agents/INSTALL.md`.
3. Verify each hook fires once (smoke transcript).
4. Verify each subagent is auto-invoked once (the next time the trigger
   condition is met during real work).

## 6. Sequencing

Phase 1 → Phase 2 → Phase 3 → Phase 4 in strict order. Within Phase 1,
the three hooks are independent and can be written in any order.
Within Phase 2, the three subagents are independent. Phase 3 cannot
start until both Phase 1 and Phase 2 are committed (the install doc
needs the canonical paths). Phase 4 cannot start until Phase 3 smoke
tests pass.

Total time budget: ~2 hours. Phase 1 (~30 min, shell scripting + smoke),
Phase 2 (~45 min, subagent prompts), Phase 3 (~15 min, JSON wiring +
smoke), Phase 4 (~30 min, PR + CI + merge).

## 7. Definition of done

- All 10 acceptance criteria from the design doc § 9 satisfied.
- PR is open and has passing CI.
- PR is merged.
- The three hooks are wired in the operator's global settings.json and
  fire on their respective triggers (verified by smoke tests).
- The three subagents are installed in the operator's global agents
  directory and auto-invoked at least once each.
- A retirement note is appended to `~/.cache/hapax/relay/beta.yaml`
  marking the automation suite as shipped.
- The convergence log gets a final entry summarizing the suite and
  pointing at the design+plan docs.

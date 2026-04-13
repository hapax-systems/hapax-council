# Installing the Claude Code automation suite

Per-machine install steps. Run after merging the PR that ships these files.

## What this suite installs

- **3 hooks** (`hooks/scripts/*.sh` — already tracked, no install needed except wiring)
  - `docs-only-pr-warn.sh` — PreToolUse Bash advisory when `git commit` would create a docs-only PR (CI paths-ignore filter)
  - `cargo-check-rust.sh` — PostToolUse Edit/Write advisory that runs `cargo check -p <crate>` after editing a `.rs` file under `hapax-logos/crates/`
  - `relay-coordination-check.sh` — PreToolUse Edit/Write advisory that fuzzy-matches the edit path against active peer relay yaml files
- **3 subagents** (`tooling/claude-agents/*.md` — copy to your global agents dir)
  - `shader-bridge-auditor` — auto-invoked when editing the four-hop Reverie GPU bridge participants
  - `affordance-pipeline-tracer` — auto-invoked when editing daimonion run loops, init_pipeline, or capability files
  - `gpu-smoke-verifier` — auto-invoked after PRs touching hapax-visual or reverie merge

All six automations are auto-firing — none of them require a `/slash-command` or explicit invocation. The hooks fire on tool events, the subagents are spawned by the main Claude based on description routing.

## 1. Copy subagent definitions to the global agents directory

```bash
mkdir -p ~/.claude/agents
cp tooling/claude-agents/{shader-bridge-auditor,affordance-pipeline-tracer,gpu-smoke-verifier}.md ~/.claude/agents/
```

The default global agents directory is `~/.claude/agents/`. Each `.md` file has a frontmatter `description:` field that tells the main Claude when to spawn it. You do not need to invoke them explicitly — Claude reasons about when to spawn them based on the trigger phrases ("Use proactively after editing X").

## 2. Wire the three new hooks

Add the three new hook entries to your global Claude `settings.json` (typically `~/.claude/settings.json`). Replace `<workspace>` with the absolute path to your hapax-council checkout (e.g., the path you see in `git rev-parse --show-toplevel`).

Append these entries to the existing `hooks.PreToolUse` and `hooks.PostToolUse` arrays:

```jsonc
{
  "hooks": {
    "PreToolUse": [
      // ... existing entries ...
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "<workspace>/hooks/scripts/docs-only-pr-warn.sh"
          }
        ]
      },
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "<workspace>/hooks/scripts/relay-coordination-check.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      // ... existing entries ...
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "<workspace>/hooks/scripts/cargo-check-rust.sh"
          }
        ]
      }
    ]
  }
}
```

## 3. Restart any open Claude Code sessions

Hooks are loaded at session start. Existing sessions will not see the new hooks until restart.

## 4. Smoke test

### Hook 1: docs-only-pr-warn

On a feature branch, stage a docs-only change and try to commit:

```bash
git checkout -b test/docs-only
mkdir -p docs/test
echo "test" > docs/test/test.md
git add docs/test/test.md
git commit -m "test"
```

Expected: stderr advisory about the carrier bundle. Commit still succeeds.

### Hook 2: cargo-check-rust

Edit a file under `hapax-logos/crates/*/src/` (e.g., add a comment to `dynamic_pipeline.rs`). The hook should silently run cargo check on the relevant crate. Introduce a syntax error and the hook should print the first 20 error lines to stderr.

Manually invoke for testing:

```bash
echo '{"tool_name":"Edit","tool_input":{"file_path":"'"$(pwd)"'/hapax-logos/crates/hapax-visual/src/lib.rs"}}' \
  | hooks/scripts/cargo-check-rust.sh
```

### Hook 3: relay-coordination-check

With an active peer relay yaml in `~/.cache/hapax/relay/`, edit a file under one of the cross-worktree-territory prefixes (`hapax-logos/crates/`, `agents/reverie/`, etc). If the peer's `focus`/`current_item`/etc references the file or its parent directory, the hook prints an advisory.

Manually invoke for testing:

```bash
echo '{"tool_name":"Edit","tool_input":{"file_path":"'"$(pwd)"'/agents/reverie/_uniforms.py"}}' \
  | hooks/scripts/relay-coordination-check.sh
```

### Subagent invocation

After editing `agents/reverie/_uniforms.py`, the main Claude should spontaneously invoke the `shader-bridge-auditor` agent. After editing `agents/hapax_daimonion/run_inner.py`, it should invoke `affordance-pipeline-tracer`. After noting a PR has merged that touches `hapax-visual`, it should invoke `gpu-smoke-verifier`.

Subagent invocation is probabilistic — Claude may not always spawn the agent if the context is ambiguous. The `description:` field's `<example>` blocks shape Claude's reasoning, but they're hints, not guarantees. You can always force-invoke via the Task tool or the `/agent <name>` command.

## 5. Disable individually

To disable a single hook, remove its entry from `~/.claude/settings.json` and restart sessions.

To disable a single subagent, delete the corresponding `.md` from `~/.claude/agents/` and restart sessions.

To disable a single hook by environment variable (no settings.json edit):

- `HAPAX_CARGO_CHECK_HOOK=0` — disables `cargo-check-rust.sh`
- `HAPAX_RELAY_CHECK_HOOK=0` — disables `relay-coordination-check.sh`
- (no env var for `docs-only-pr-warn.sh` — it's already lightweight)

The hook scripts in `hooks/scripts/` and the canonical sources in `tooling/claude-agents/` can stay in the repo indefinitely without being wired.

## 6. Updating

When this repo updates the canonical sources (e.g., a future PR adds a new subagent or refines an existing one), re-run step 1 to copy the latest definitions into your global agents directory. Hooks update automatically because the workspace path is referenced by absolute path in `settings.json`.

# Antigrav (agy) enforcing-gate — LIVE witness

**Captured:** 2026-06-01T01:02:26Z · lane `delta` · task `reform-fix-antigrav-activation-20260531`
· authority `CASE-CROSS-RUNTIME-COMMS-001`

This is the integration witness the unit tests cannot provide: proof that the
**live** agy hook configuration on this host activates the Hapax governance gate.
It complements (does not replace) the re-runnable coverage in
`tests/hooks/test_antigrav_gate_enforcement.py`,
`tests/hooks/test_antigrav_hook_adapter.py`, and
`tests/scripts/test_hapax_antigrav_launcher.py`.

Background: `scripts/hapax-antigrav` (R7 / #3802) wires the agy PreToolUse gate
into `~/.gemini/antigravity-cli/hooks.json`, but that file only materializes on a
launch — and a normal launch pops the interactive Antigravity IDE. This task adds
`hapax-antigrav --wire-hooks-only`, which writes that file and exits with **no IDE
window**, then captures the witness below.

## How the gate was activated (no IDE window)

```
HAPAX_COUNCIL_DIR=/home/hapax/projects/hapax-council--delta \
  ./scripts/hapax-antigrav --wire-hooks-only
# → hapax-antigrav: wired agy PreToolUse gate → /home/hapax/.gemini/antigravity-cli/hooks.json
# → exit 0  (no agy binary resolved, no worktree provisioned, no tmux/IDE launched)
```

The command is rooted at the `delta` worktree because, at capture time, the
canonical `~/projects/hapax-council` integrator was parked on a pre-#3802 branch
that does not yet carry `hooks/scripts/antigrav-hook-adapter.sh`. `delta` is a
permanent lane and the adapter lives in `main`, so the baked path is durable.
The wiring is self-healing: a later launch from any worktree that carries the
adapter re-points `hooks.json` at that worktree, and `wire_agy_hooks()` refuses
to clobber an existing Hapax `hooks.json`, so the gate never regresses to OFF.

## [1] LIVE wired gate config — `~/.gemini/antigravity-cli/hooks.json`

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "run_command|run_shell_command|write_to_file|create_file|delete_file|replace_file_content|multi_replace_file_content",
        "hooks": [
          { "type": "command", "command": "/home/hapax/projects/hapax-council--delta/hooks/scripts/antigrav-hook-adapter.sh /home/hapax/projects/hapax-council--delta/hooks/scripts/cc-task-gate.sh" }
        ]
      }
    ]
  }
}
```

## [2] agy's OWN runtime log proves it LOADED the live hook

From `~/.gemini/antigravity-cli/log/cli-20260531_195217.log` (an `agy` process,
PID 2993298, started after the wiring above):

```
I0531 19:52:18.021411 2993298 hooks_manager.go:45] loaded 1 named hooks from 1 hooks.json file(s)
```

agy's own `hooks_manager` confirms it read and registered the live `hooks.json`
at session start — not inferred from strace, but from agy's runtime log.

## [3] The registered command enforces the gate end-to-end

Driving a representative agy PreToolUse payload through the **exact command the
live `hooks.json` registers** (`antigrav-hook-adapter.sh → cc-task-gate.sh`),
with a clean environment built from scratch (witness role, no claimed task — so
no lane identity can soften the verdict):

```
registered command: /home/hapax/projects/hapax-council--delta/hooks/scripts/antigrav-hook-adapter.sh \
                    /home/hapax/projects/hapax-council--delta/hooks/scripts/cc-task-gate.sh
```

### [3a] Unauthorized agy `write_to_file` (protected path) → BLOCKED

```
$ printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"write_to_file","tool_input":{"file_path":"/etc/hapax-agy-witness.conf","content":"x"}}' \
    | env -i HOME="$HOME" PATH="$PATH" HAPAX_AGENT_ROLE=antigrav-witness bash -c "$LIVE_CMD"

cc-task-gate: BLOCKED — no claimed task for role 'antigrav-witness'.
  Claim a task before mutating files:
    cc-claim <task_id>
  ...
[verdict] exit=2  (non-zero = BLOCKED)
```

### [3b] Control: read-only agy `read_file` → ALLOWED

```
$ printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"read_file","tool_input":{"file_path":"/etc/hostname"}}' \
    | env -i HOME="$HOME" PATH="$PATH" HAPAX_AGENT_ROLE=antigrav-witness bash -c "$LIVE_CMD"

[verdict] exit=0  (0 = ALLOWED)
```

A blocked lane can still inspect state; only the matched mutation tools are gated.

## Why the witness is scripted-through-the-live-config

The task permits "invoke agy (headless / `agy exec`-style if available, else a
minimal scripted tool-call)". A fully agy-binary-driven capture was attempted via
`agy --print --dangerously-skip-permissions` but was **not pursued to completion**:
two operator-owned interactive agy sessions were live on this host (driving the
coordination reform), and `agy --print` shares `~/.gemini` conversation state, so
each headless prompt drifted into the operators' active context instead of
emitting the targeted gated tool call. Continuing to drive the shared agy binary
risked the operators' live sessions. Evidence [2] (agy loads the live hook) plus
[3] (the registered command enforces the gate) together constitute the
end-to-end proof, using the task-sanctioned scripted-tool-call form.

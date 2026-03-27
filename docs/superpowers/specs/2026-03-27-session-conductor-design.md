# Session Conductor Design Spec

**Date:** 2026-03-27
**Status:** Approved design, pending implementation
**Motivation:** 91 Claude Code sessions in 7 days with low coordination. Relay protocol went dormant. Same research repeated across sessions. Verbal instructions repeated 9-43x. Side sessions spawn without context or result tracking.

## Core Constraint

Everything must be **reactive and automatic**. The operator will not remember to trigger anything. All automation fires from hooks, timers, or system events — never from manual invocation.

## Architecture: Session Conductor

A deterministic Python sidecar process per Claude Code session. No LLM calls. Receives every hook event via Unix domain socket, maintains a live session model, and makes autonomous decisions: rewrite tool arguments, inject directives into conversation, or block actions.

### Process Lifecycle

```
Claude Code starts
  → SessionStart hook launches conductor:
    systemd-run --user --scope --unit=conductor-${SESSION_ID} \
      uv run python -m agents.session_conductor start \
        --session-id ${SESSION_ID} --cc-pid ${PPID}
  → Conductor writes /dev/shm/conductor-{session-id}.json (state)
  → Conductor opens /run/user/1000/conductor-{session-id}.sock (UDS)

Every tool call:
  → 3-line shim hook pipes event JSON to socket
  → Conductor processes, returns:
    {action: "allow|block|rewrite", message: "...", rewrite: {...}}
  → Shim prints message to stderr (injected into conversation)
  → Shim exits with appropriate code (0=allow, 2=block)

Claude Code stops:
  → Stop hook sends "shutdown" to conductor
  → Conductor writes final relay status, cleans up socket/state, exits
  → If CC crashes: conductor detects parent PID gone (ppid check every 30s),
    self-terminates
```

### State Model

```python
@dataclass
class SessionState:
    session_id: str
    pid: int
    started_at: datetime

    # Identity
    parent_session: str | None
    children: list[ChildSession]

    # Research tracking
    active_topics: dict[str, TopicState]

    # File tracking
    in_flight_files: set[str]

    # Epic pipeline
    epic_phase: EpicPhase | None

    # Relay
    last_relay_sync: datetime
    workstream_summary: str
```

State lives in `/dev/shm/` (volatile — dies with session). Persistent cross-session state lives in `~/.cache/hapax/relay/context/`.

### Communication Protocol

Hooks send JSON over UDS:

```json
{"event": "pre_tool_use", "tool": "browser_click", "input": {...}, "session_id": "..."}
```

Conductor responds:

```json
{"action": "rewrite", "rewrite": {"workspace": 10}, "message": "Redirected to workspace 10."}
```

Or for blocking:

```json
{"action": "block", "message": "Research round 4 on 'compositor-effects'. Converging (12→3→1). Loading prior findings instead.\n\n[prior findings content]"}
```

### Hook Shims

```bash
#!/bin/bash
# conductor-pre.sh
SOCK="/run/user/1000/conductor-${CLAUDE_SESSION_ID}.sock"
RESPONSE=$(echo "{\"event\":\"pre_tool_use\",\"input\":$(cat -)}" \
  | timeout 0.5 socat - UNIX-CONNECT:"$SOCK" 2>/dev/null)
[ $? -ne 0 ] && exit 0  # fail-open: conductor down = allow all
# parse response, print message, exit with action code
```

Fail-open design: conductor crash = session continues without automation.

### Hook Wiring (settings.json)

Two new entries with empty matcher (all tools), plus SessionStart and Stop:

```json
{
  "hooks": {
    "PreToolUse": [{ "matcher": "", "command": "hapax-council/hooks/scripts/conductor-pre.sh" }],
    "PostToolUse": [{ "matcher": "", "command": "hapax-council/hooks/scripts/conductor-post.sh" }],
    "SessionStart": [{ "command": "hapax-council/hooks/scripts/conductor-start.sh" }],
    "Stop": [{ "command": "hapax-council/hooks/scripts/conductor-stop.sh" }]
  }
}
```

### Performance Budget

Target: <10ms per hook call.

- UDS round-trip: ~1ms
- JSON parse + rule evaluation: ~5ms (deterministic, no LLM, no disk in hot path)
- File writes (relay sync, finding persistence): async background thread
- inotify watches: separate thread

---

## Rule 1: Workspace Topology Enforcement

### Config File

`~/.config/hapax/workspace-topology.yaml`:

```yaml
monitors:
  primary:
    name: "Dell S3422DWG"
    position: left
    resolution: 3440x1440
    purpose: work
  secondary:
    name: "Dell S2721DGF"
    position: right
    resolution: 2560x1440
    purpose: logos

workspaces:
  1: { monitor: primary, purpose: terminals }
  2: { monitor: primary, purpose: browser }
  3: { monitor: secondary, purpose: logos }
  10: { monitor: secondary, purpose: playwright-testing, ephemeral: true }

playwright:
  testing_workspace: 10
  screenshot_max_bytes: 500000
  never_switch_operator_focus: true

smoke_test:
  workspace: 10
  fullscreen: true
  launch_method: fuzzel
  screenshot_interval_ms: 2000
```

### Behavior

PreToolUse on any Playwright tool (`browser_navigate`, `browser_click`, `browser_snapshot`, etc.):

1. Verifies browser is on workspace 10
2. If not, issues `hyprctl dispatch movetoworkspacesilent 10` before allowing the tool call
3. `movetoworkspacesilent` = window moves, operator's focus does not
4. Screenshots: checks result size, downscales if over `screenshot_max_bytes`

This structurally prevents focus-stealing. The operator never needs to specify workspace or focus constraints.

---

## Rule 2: Research Convergence & Finding Persistence

### Topic Detection

PostToolUse on Agent tool calls. Topics extracted from agent prompt, normalized to slugs: "compositor effects" → `compositor-effects`. Matching: keyword overlap threshold against `active_topics` — if substantially similar to a prior round's prompt, counts as same topic.

### Convergence Tracking

```python
@dataclass
class TopicState:
    slug: str
    rounds: int
    findings_per_round: list[int]     # [12, 3, 1] = converging
    first_seen: datetime
    prior_file: Path                   # relay/context/{slug}.md
    blocked_at_round: int | None
```

After each Agent completes:

1. Count distinct findings in output (heuristic: bullet points, numbered items, headings)
2. Append to `findings_per_round`
3. Convergence test: last 2 rounds each found ≤30% of first round's distinct finding count (absolute count of bullet points/numbered items/headings)
4. On convergence: **block next research dispatch** on this topic with directive and loaded prior findings
5. **Hard cap**: 5th round blocked regardless of convergence math

### Finding Persistence

After each research Agent completes, the conductor appends a timestamped section to `~/.cache/hapax/relay/context/{slug}.md`:

```markdown
## 2026-03-27T12:30 — Round 2 (session abc123)
- Finding 1
- Finding 2
[key findings from agent output]
```

When any session researches a topic with an existing context file, the conductor prepends to the agent's prompt:

```
PRIOR RESEARCH EXISTS on this topic. Read and build on it — do not re-research from scratch.
---
[contents of relay/context/{slug}.md]
---
```

### Cross-Session Behavior

All sessions write to the same `relay/context/` directory. Child sessions' findings are visible to parent sessions via inotify watch. The 3-day compositor effects scenario becomes:

- Day 1: findings saved
- Day 2: prior findings injected automatically, round count continues
- Day 3: topic blocked with "3 prior sessions, 16 findings. Proceed to implementation."

---

## Rule 3: Session Spawning & Reunion

### Spawn Detection

Two signals:

1. **Explicit**: User message contains "break this out to another session" or "have another session fix this." Conductor writes a spawn manifest to `~/.cache/hapax/conductor/spawns/{timestamp}-{slug}.yaml`:

```yaml
parent_session: abc-123
topic: logos-api-bug
context: |
  [what's broken, what files are involved]
in_flight_files:
  - agents/hapax_voice/pipeline.py
  - agents/hapax_voice/salience_router.py
do_not_touch:
  - agents/hapax_voice/**
  - logos/engine/**
created: 2026-03-27T14:30:00
status: pending
```

2. **Observed**: New Claude Code process detected in same project directory. Conductor checks for pending spawn manifest within 10 minutes.

### Child Startup

Child conductor claims manifest (`status: claimed`), injects context into first tool interaction:

```
SPAWNED SESSION — fixing side issue for parent session.
Topic: logos-api-bug
Context: [from manifest]
DO NOT EDIT (parent has in-flight changes):
  - agents/hapax_voice/**
  - logos/engine/**
Complete the fix, PR it, and exit.
```

`do_not_touch` patterns become PreToolUse blocks on Edit/Write.

### Reunion

Child session ends → child conductor writes results to spawn manifest:

```yaml
status: completed
result: |
  Fixed empty stimmung vector. PR #382 merged.
  Files changed: logos/api/routes/cockpit.py, tests/logos/api/test_cockpit.py
```

Parent conductor detects completion (inotify on spawn manifest), injects on next tool call:

```
CHILD SESSION COMPLETED: logos-api-bug
Result: Fixed empty stimmung vector. PR #382 merged.
Files changed: logos/api/routes/cockpit.py
Action needed: rebase onto main to pick up the fix.
```

If child modified files the parent has read, adds stale-context warning.

### Unlinked Side Sessions

Side sessions spawned without explicit signal still benefit from finding persistence and relay sync. Spawn/reunion is an optimization for coordinated handoffs.

---

## Rule 4: Relay Sync Automation

### Automatic Status Updates

Conductor updates `~/.cache/hapax/relay/{role}.yaml` on three triggers:

1. **PR events**: PostToolUse detects `gh pr create` or `gh pr merge` → updates `completed:` list
2. **Topic shifts**: New research topic or file-edit pattern shift → updates `focus:` and `workstream:`
3. **Periodic**: Every 30 minutes, rewrites status file with current state (keeps `updated:` timestamp fresh)

### Queue Item Lifecycle

PR merged for work matching a queue item (by branch name or topic slug):

1. Sets `status: done` on queue item
2. Checks `depends_on` — unblocks dependent items by setting them to `offered`
3. Peer conductor picks up newly-offered items on next status read

### Convergence Detection

Reads peer status file every 10 minutes (or on inotify change):

- Same files being edited → `CONFLICTING` in convergence.log, warns operator
- Same topic researched → `IDENTICAL`, injects peer's findings
- Complementary work → `COMPLEMENTARY`, no action

---

## Rule 5: Epic Pipeline Automation

### Trigger Detection

Conductor detects epic entry when:
- Agent dispatch with research-oriented prompt, AND
- User's message matches "research any loose ends" pattern or variants

Activates pipeline tracker automatically.

### Phases

```python
class EpicPhase(Enum):
    RESEARCH = "research"
    DESIGN = "design"
    DESIGN_GAPS = "design_gaps"
    PLANNING = "planning"
    PLANNING_GAPS = "planning_gaps"
    IMPLEMENTATION = "implementation"
```

### Autonomous Phase Transitions

| Transition | Trigger | Gap Round Cap |
|---|---|---|
| RESEARCH → DESIGN | Research convergence detected or hard cap hit | N/A |
| DESIGN → DESIGN_GAPS | Design doc written to `docs/superpowers/specs/*.md` | 2 rounds |
| DESIGN_GAPS → PLANNING | Gap rounds converge or hit cap | N/A |
| PLANNING → PLANNING_GAPS | Plan file written | 2 rounds |
| PLANNING_GAPS → IMPLEMENTATION | Gap rounds converge or hit cap | N/A |

At each transition, conductor injects directive with all accumulated artifacts (research findings, design doc path, plan path).

---

## Rule 6: Smoke Test Standardization

### Trigger

Two signals:

1. **Post-PR**: PR just created → conductor injects "Initiating smoke test on workspace 10" and activates smoke test profile
2. **Keyword**: User message contains "smoke test" → profile activates

### Active Profile

Every Playwright tool call is rewritten:

- Workspace: 10 (from topology config)
- Fullscreen: true
- Launch method: fuzzel
- Screenshot sizing: auto-downscale to `screenshot_max_bytes`
- Focus protection: all workspace commands use `silent` variant
- Deactivation: 60 seconds with no Playwright tool calls

---

## Tier-2: Systemd Agents

Three standard agents using existing hapax-council agent pattern (Python module + manifest + systemd units). Independent of conductor.

### Hardware Watchdog

- **Schedule**: 30s timer
- **Checks**: USB device enumeration, V4L2 stream health, GStreamer pipeline state, GPU memory
- **Recovery**: USB rebind via sysfs → service restart → USB hub power-cycle (uhubctl) → ntfy
- **Output**: Prometheus metrics for pattern detection

### Shader QA

- **Schedule**: Event-driven (reactive engine watches shader/effect directories)
- **Behavior**: Renders each preset, computes SSIM against reference screenshots in `tests/visual/references/`
- **Reference capture**: `uv run python -m agents.shader_qa --capture-references`
- **Output**: `profiles/shader-qa.json`, conductor reads to inject regression warnings

### Boot Integrity

- **Schedule**: `OnBootSec=60`, no repeat
- **Checklist**: 6 cameras, systemd units, Docker containers, GPU, Logos API, bluetooth, waybar
- **Recovery**: Per-item automatic recovery, ntfy on unrecoverable
- **Output**: `profiles/boot-integrity.json`, health monitor integrates

---

## Directory Structure

```
hapax-council/
  agents/session_conductor/
    __main__.py              # Entry: start/stop/status subcommands
    state.py                 # SessionState dataclass + serialization
    protocol.py              # UDS server, event routing
    topology.py              # Workspace topology config loader
    rules/
      __init__.py
      focus.py               # Workspace topology enforcement
      convergence.py         # Research convergence + finding persistence
      epic.py                # Epic pipeline phase tracking
      relay.py               # Automatic relay status sync
      smoke.py               # Smoke test profile
      spawn.py               # Session spawning & reunion
  agents/hardware_watchdog/
    __main__.py
  agents/shader_qa/
    __main__.py
  agents/boot_integrity/
    __main__.py
  agents/manifests/
    session_conductor.yaml
    hardware_watchdog.yaml
    shader_qa.yaml
    boot_integrity.yaml
  hooks/scripts/
    conductor-start.sh
    conductor-stop.sh
    conductor-pre.sh
    conductor-post.sh
  systemd/units/
    hardware-watchdog.service
    hardware-watchdog.timer
    shader-qa.service         # triggered by reactive engine, not timer
    boot-integrity.service
    boot-integrity.timer

~/.config/hapax/
  workspace-topology.yaml

~/.cache/hapax/
  relay/context/              # Persistent research findings per topic
  conductor/spawns/           # Spawn manifests for parent-child sessions
```

## Failure Modes

| Failure | Behavior |
|---|---|
| Conductor crashes | Hooks fail-open (allow all). Session continues unautomated. |
| Conductor hangs | 500ms timeout on socket call → allow. |
| Socket doesn't exist | SessionStart not finished → skip. |
| Double-launch | PID file prevents. |
| Parent dies before child | Child detects orphaning, writes `status: orphaned`. Results persist via finding persistence. |
| Stale /dev/shm state | Conductor start checks PID liveness, removes dead state. |

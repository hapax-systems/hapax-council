# Claude Code Layer Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix rules drift, enrich session hook with profile + cycle mode context, add 5 new skills, establish cross-repo memory standard with drift enforcement, and remove the desktop-commander MCP server.

**Architecture:** All Claude Code configuration lives in `~/projects/hapax-system/` and is symlinked into `~/.claude/` by `install.sh`. Changes span two repos: `hapax-system` (rules, hooks, skills) and `ai-agents` (drift-detector check, CLAUDE.md memory section). No new Python modules — skills are markdown files that instruct Claude Code to run existing CLI tools and APIs.

**Tech Stack:** Bash (hooks), Markdown (skills/rules), Python (drift-detector check), jq (settings.json manipulation)

---

### Task 1: Fix system-context.md rules drift

**Files:**
- Modify: `~/projects/hapax-system/rules/system-context.md`

**Context:** This file is symlinked to `~/.claude/rules/hapax-system-context.md` and loaded into every Claude Code session. It's stale — missing 8 agents, has wrong module paths, missing cycle-mode system, and timer schedules need reconciling.

**Step 1: Update the agent table**

Replace the entire agent table in `~/projects/hapax-system/rules/system-context.md` with:

```markdown
## Management Agents (~/projects/hapax-council/)

Invoke: `cd ~/projects/hapax-council && uv run python -m agents.<name> [flags]`

| Agent | LLM? | Key Flags |
|-------|------|-----------|
| management_prep | Yes | `--person NAME`, `--team-snapshot`, `--overview` |
| meeting_lifecycle | Yes | `--prepare`, `--transcript FILE`, `--weekly-review` |
| briefing | Yes | `--hours N`, `--save` |
| profiler | Yes | `--auto`, `--digest`, `--source TYPE` |
| scout | Yes | |
| demo | Yes | `--topic TOPIC`, `--duration N`, `--voice`, `--audience NAME` |
| demo_eval | Yes | `--demo-dir PATH` |
| research | Yes | `--interactive` |
| code_review | Yes | `--file PATH`, `--diff` |
| digest | Yes | `--save` |
| health_monitor | No | `--fix`, `--history` |
| drift_detector | Yes | `--fix`, `--json` |
| knowledge_maint | No | `--summarize` |
| activity_analyzer | No | `--hours N`, `--json` |
| introspect | No | `--json` |
| query | No | `--collection NAME` |
| ingest | No | `--watch`, `--stats` |
| gdrive_sync | No | `--auth`, `--full-scan`, `--auto`, `--fetch ID`, `--stats` |
| gcalendar_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
| gmail_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
| youtube_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
| claude_code_sync | No | `--full-sync`, `--auto`, `--stats` |
| obsidian_sync | No | `--full-sync`, `--auto`, `--stats` |
| chrome_sync | No | `--full-sync`, `--auto`, `--stats` |
| audio_processor | No | `--process`, `--stats`, `--reprocess FILE` |
| hapax_voice | No | `--check`, `--config PATH` (daemon — runs as always-on service) |

Shared modules: `shared/google_auth.py` (OAuth2 token management for all Google agents), `shared/calendar_context.py` (calendar-aware context for briefing/prep agents).
```

Note the changes:
- Added 8 agents: `research`, `code_review`, `activity_analyzer`, `introspect`, `query`, `ingest`, `health_monitor` (renamed from `system_check`), `hapax_voice`
- Removed `system_check` (renamed to `health_monitor` long ago)
- Fixed shared module paths: `shared/` not `agents/shared/`

**Step 2: Update the timer table**

Replace the timer table with the current actual timers (from `systemctl --user list-timers`):

```markdown
## Management Timers (systemd user)

| Timer | Schedule | Purpose |
|-------|----------|---------|
| meeting-prep | Daily 06:30 | Auto-generate 1:1 prep docs |
| digest | Daily 06:45 | Content/knowledge digest |
| daily-briefing | Daily 07:00 | Morning briefing (consumes digest) |
| profile-update | Every 6h | Incremental operator profile |
| health-monitor | Every 15 min | Deterministic health checks + auto-fix |
| vram-watchdog | Every 30 min | GPU memory management |
| scout | Weekly Wed 10:00 | Horizon scan |
| drift-detector | Weekly Sun 03:00 | Documentation drift detection |
| knowledge-maint | Weekly Sun 04:30 | Qdrant dedup/pruning/stats |
| manifest-snapshot | Weekly Sun 02:30 | Infrastructure state snapshot |
| llm-backup | Weekly Sun 02:00 | Full stack backup |
| gdrive-sync | Every 2h | Google Drive RAG sync |
| gcalendar-sync | Every 30min | Google Calendar RAG sync |
| gmail-sync | Every 1h | Gmail metadata RAG sync |
| youtube-sync | Every 6h | YouTube subscriptions/likes sync |
| obsidian-webui-sync | Every 6h | Vault sync to Open WebUI |
| claude-code-sync | Every 2h | Claude Code transcript RAG sync |
| obsidian-sync | Every 30min | Obsidian vault RAG sync |
| chrome-sync | Every 1h | Chrome history + bookmarks sync |
| audio-recorder | Always on | Continuous mic recording (ffmpeg) |
| audio-processor | Every 30min | Audio segmentation + transcription + RAG |
| audio-archiver | Daily 03:00 | rclone move raw audio to Google Drive |
| hapax-voice | Always on | Voice interaction daemon (wake word, presence, TTS/STT) |
| bt-keepalive | Always on | Silent stream to iLoud BT monitors (prevents auto-standby) |

### Cycle Modes

Timer schedules contract during heavy development. `hapax-mode dev` installs systemd timer drop-in overrides for 9 timers (claude-code-sync, obsidian-sync, chrome-sync, gdrive-sync, profile-update, digest, daily-briefing, drift-detector, knowledge-maint). `hapax-mode prod` removes overrides. Mode file: `~/.cache/hapax/cycle-mode`. See `systemd/overrides/dev/` for dev schedules.
```

Changes: `profile-update` schedule corrected to "Every 6h", added `vram-watchdog`, added new `Cycle Modes` subsection.

**Step 3: Update Qdrant collections**

Replace:
```markdown
| samples | 768 | Audio sample metadata (planned) |
```

With nothing (remove the row). The `samples` collection is planned but not real.

**Step 4: Verify the file reads correctly**

Run: `cat ~/projects/hapax-system/rules/system-context.md | wc -l`
Expected: ~105-115 lines (slightly longer than before due to added agents and cycle mode section)

**Step 5: Commit**

```bash
cd ~/projects/hapax-system
git add rules/system-context.md
git commit -m "fix: update system-context.md to match current system state

Add 8 missing agents, fix shared module paths, correct timer schedules,
add cycle-mode section, remove planned-but-unbuilt samples collection."
```

---

### Task 2: Enrich session-context.sh hook

**Files:**
- Modify: `~/projects/hapax-system/hooks/scripts/session-context.sh`

**Context:** This hook runs at SessionStart and injects system state into Claude Code context. Currently shows: axioms, branch, health, docker, GPU, pending precedents. We're adding: profile summary, cycle mode, and auto-memory seeding.

**Step 1: Add profile summary injection**

Append the following after the GPU section (after line 53, before the axiom governance nudge section) in `~/projects/hapax-system/hooks/scripts/session-context.sh`:

```bash
# Operator profile summary (from distilled manifest)
PROFILE="$HOME/projects/ai-agents/profiles/operator.json"
if [ -f "$PROFILE" ]; then
  PROFILE_LINE="$(jq -r '
    (.goals.primary | map(select(.status == "active")) | length) as $goals |
    (.patterns | keys | join(", ")) as $patterns |
    "Profile: \($goals) active goals | Patterns: \($patterns)"
  ' "$PROFILE" 2>/dev/null || true)"
  if [ -n "$PROFILE_LINE" ]; then
    echo "$PROFILE_LINE"
  fi
fi
```

**Step 2: Add cycle mode injection**

Append after the profile summary block:

```bash
# Cycle mode
MODE_FILE="$HOME/.cache/hapax/cycle-mode"
if [ -f "$MODE_FILE" ]; then
  MODE="$(cat "$MODE_FILE" 2>/dev/null | tr -d '[:space:]')"
  if [ "$MODE" = "dev" ] || [ "$MODE" = "prod" ]; then
    MODE_AGE=$(( ($(date +%s) - $(stat -c %Y "$MODE_FILE")) ))
    if [ "$MODE_AGE" -lt 3600 ]; then
      AGE_STR="$((MODE_AGE / 60))min ago"
    elif [ "$MODE_AGE" -lt 86400 ]; then
      AGE_STR="$((MODE_AGE / 3600))h ago"
    else
      AGE_STR="$((MODE_AGE / 86400))d ago"
    fi
    echo "Cycle: $MODE (switched $AGE_STR)"
  fi
else
  echo "Cycle: prod (default)"
fi
```

**Step 3: Add auto-memory seeding**

Append at the very end of the script (after the axiom sweep age check):

```bash
# Seed auto-memory directory if missing
# Claude Code auto-memory path uses a hash of the working directory
if command -v claude 2>/dev/null | head -1 > /dev/null; then
  # Detect the project memory dir — Claude Code uses the working dir path
  WORK_DIR="$(pwd)"
  SANITIZED="$(echo "$WORK_DIR" | sed 's|/|-|g; s|^-||')"
  MEMORY_DIR="$HOME/.claude/projects/-${SANITIZED}/memory"
  if [ ! -d "$MEMORY_DIR" ]; then
    mkdir -p "$MEMORY_DIR"
    # Seed from repo's CLAUDE.md Project Memory section if it exists
    CLAUDE_MD="$WORK_DIR/CLAUDE.md"
    if [ -f "$CLAUDE_MD" ] && grep -q '## Project Memory' "$CLAUDE_MD"; then
      sed -n '/^## Project Memory/,/^## /p' "$CLAUDE_MD" | head -n -1 > "$MEMORY_DIR/MEMORY.md"
    else
      echo "# Project Memory" > "$MEMORY_DIR/MEMORY.md"
      echo "" >> "$MEMORY_DIR/MEMORY.md"
      echo "No project memory seeded yet. Add a \`## Project Memory\` section to CLAUDE.md." >> "$MEMORY_DIR/MEMORY.md"
    fi
  fi
fi
```

**Step 4: Verify the hook runs without errors**

Run: `bash ~/projects/hapax-system/hooks/scripts/session-context.sh`
Expected: Output includes all existing lines plus new `Profile:` and `Cycle:` lines. No errors.

**Step 5: Commit**

```bash
cd ~/projects/hapax-system
git add hooks/scripts/session-context.sh
git commit -m "feat: enrich session hook with profile summary, cycle mode, and auto-memory seed"
```

---

### Task 3: Create new skills

**Files:**
- Create: `~/projects/hapax-system/skills/profile/SKILL.md`
- Create: `~/projects/hapax-system/skills/calendar/SKILL.md`
- Create: `~/projects/hapax-system/skills/nudges/SKILL.md`
- Create: `~/projects/hapax-system/skills/cycle-mode/SKILL.md`

**Context:** Skills are markdown files in `hapax-system/skills/<name>/SKILL.md`. The install script auto-discovers them and symlinks to `~/.claude/commands/<name>.md`. Each skill has YAML frontmatter (`name`, `description`) and instructions for Claude Code. Follow the pattern of existing skills like `/status` and `/briefing`.

**Step 1: Create `/profile` skill**

Create directory and file `~/projects/hapax-system/skills/profile/SKILL.md`:

```markdown
---
name: profile
description: Inspect the operator profile. Use when the user asks about their profile, dimensions, facts, or runs /profile.
---

Show the operator profile summary and dimension breakdown.

**Default (no args):** Read the distilled manifest and show a summary:

```bash
cd ~/projects/hapax-council && jq '{
  name: .operator.name,
  goals: [.goals.primary[] | {name, status}],
  patterns: (.patterns | keys),
  constraints: (.constraints | length),
  neurocognitive: (.neurocognitive | length)
}' profiles/operator.json
```

Then read the full profile and show per-dimension fact counts:

```bash
cd ~/projects/hapax-council && uv run python -c "
import json
p = json.load(open('profiles/operator-profile.json'))
for dim, facts in sorted(p.get('dimensions', {}).items()):
    count = len(facts) if isinstance(facts, list) else len(facts) if isinstance(facts, dict) else 0
    print(f'  {dim}: {count} facts')
"
```

**With dimension arg** (e.g., `/profile neurocognitive`): Show the facts for that specific dimension from `profiles/operator-profile.json`.

**With `--refresh` flag:** Run the profiler to update:

```bash
cd ~/projects/hapax-council && eval "$(<.envrc)" && uv run python -m agents.profiler --auto
```
```

**Step 2: Create `/calendar` skill**

Create directory and file `~/projects/hapax-system/skills/calendar/SKILL.md`:

```markdown
---
name: calendar
description: Check calendar, upcoming meetings, and prep status. Use when the user asks about meetings, schedule, or runs /calendar.
---

Show calendar context and meeting prep status.

**Default (no args):** Show today's meetings and prep status:

```bash
cd ~/projects/hapax-council && eval "$(<.envrc)" && uv run python -c "
from shared.calendar_context import CalendarContext
ctx = CalendarContext()
print(f'Meetings today: {ctx.meeting_count_today()}')
for m in ctx.meetings_in_range(hours=24):
    print(f'  {m.start:%H:%M} - {m.title} ({m.attendees_str})')
needs_prep = ctx.meetings_needing_prep()
if needs_prep:
    print(f'\nNeeding prep ({len(needs_prep)}):')
    for m in needs_prep:
        print(f'  {m.start:%H:%M} {m.title}')
else:
    print('\nAll meetings prepped.')
"
```

Also check the meeting-prep timer:

```bash
systemctl --user status meeting-prep.timer --no-pager 2>/dev/null | head -5
```

**With person arg** (e.g., `/calendar Alice`): Show next meeting with that person:

```bash
cd ~/projects/hapax-council && eval "$(<.envrc)" && uv run python -c "
from shared.calendar_context import CalendarContext
ctx = CalendarContext()
m = ctx.next_meeting_with('$PERSON')
if m:
    print(f'Next meeting with $PERSON: {m.start:%Y-%m-%d %H:%M} - {m.title}')
else:
    print('No upcoming meeting with $PERSON found.')
"
```
```

**Step 3: Create `/nudges` skill**

Create directory and file `~/projects/hapax-system/skills/nudges/SKILL.md`:

```markdown
---
name: nudges
description: Review and act on active nudges from the cockpit. Use when the user asks about nudges, suggestions, or runs /nudges.
---

Show active nudges from the cockpit API.

**Default (no args):** List active nudges:

```bash
curl -s http://127.0.0.1:8051/api/nudges | jq '.nudges[] | {id: .id, text: .text, source: .source, priority: .priority, age: .age_human}'
```

If no nudges, report "No active nudges."

**Act on a nudge** (`/nudges act <id>`):

```bash
curl -s -X POST http://127.0.0.1:8051/api/nudges/$ID/act | jq .
```

**Dismiss a nudge** (`/nudges dismiss <id>`):

```bash
curl -s -X POST http://127.0.0.1:8051/api/nudges/$ID/dismiss | jq .
```

If the cockpit API is not running (connection refused), suggest:
`cd ~/projects/hapax-council && uv run python -m cockpit.api`
```

**Step 4: Create `/cycle-mode` skill**

Create directory and file `~/projects/hapax-system/skills/cycle-mode/SKILL.md`:

```markdown
---
name: cycle-mode
description: Check or switch the cycle mode (dev/prod). Use when the user asks about cycle mode, timer schedules, or runs /cycle-mode.
---

Check or switch the dev/prod cycle mode.

**Default (no args):** Show current mode and timer schedule:

```bash
cat ~/.cache/hapax/cycle-mode 2>/dev/null || echo "prod (default)"
```

Then show active timer schedules for the overridable timers:

```bash
systemctl --user show claude-code-sync.timer obsidian-sync.timer chrome-sync.timer profile-update.timer digest.timer daily-briefing.timer drift-detector.timer knowledge-maint.timer --property=TimersCalendar --no-pager 2>/dev/null
```

**Switch mode** (`/cycle-mode dev` or `/cycle-mode prod`):

```bash
~/.local/bin/hapax-mode $MODE
```

Report the resulting mode and timer schedule summary.
```

**Step 5: Verify skill directories exist**

Run: `ls ~/projects/hapax-system/skills/profile/SKILL.md ~/projects/hapax-system/skills/calendar/SKILL.md ~/projects/hapax-system/skills/nudges/SKILL.md ~/projects/hapax-system/skills/cycle-mode/SKILL.md`
Expected: All 4 files listed.

**Step 6: Fix demo symlink**

Check if the `/demo` skill is already being picked up by install.sh. The skill directory exists at `~/projects/hapax-system/skills/demo/` with `SKILL.md`, and install.sh auto-discovers all `skills/*/SKILL.md` directories. Verify:

Run: `ls -la ~/.claude/commands/demo.md 2>/dev/null || echo "missing"`

If missing, the symlink wasn't created. Run install.sh to fix:

```bash
cd ~/projects/hapax-system && bash install.sh
```

Then verify: `ls -la ~/.claude/commands/demo.md`

**Step 7: Commit**

```bash
cd ~/projects/hapax-system
git add skills/profile/SKILL.md skills/calendar/SKILL.md skills/nudges/SKILL.md skills/cycle-mode/SKILL.md
git commit -m "feat: add profile, calendar, nudges, and cycle-mode skills"
```

---

### Task 4: Cross-repo memory standard

**Files:**
- Modify: `~/projects/hapax-council/CLAUDE.md` (add Project Memory section)
- Modify: `~/projects/hapax-council/agents/drift_detector.py` (add Project Memory check)
- Create: `~/projects/hapax-council/tests/test_drift_detector_memory.py`

**Context:** Every hapax repo should have a `## Project Memory` section in its CLAUDE.md. This section contains stable institutional knowledge that persists across sessions. The drift-detector should enforce this across all 6 repos.

**Step 1: Write the test for the drift-detector check**

Create `~/projects/hapax-council/tests/test_drift_detector_memory.py`:

```python
"""Tests for drift_detector project memory enforcement check."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.drift_detector import check_project_memory


def test_flags_repo_missing_claude_md(tmp_path):
    """Repo with no CLAUDE.md should be flagged."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    with patch("agents.drift_detector.HAPAX_REPO_DIRS", [repo]):
        items = check_project_memory()
    assert len(items) == 1
    assert items[0].category == "missing_project_memory"
    assert "CLAUDE.md" in items[0].suggestion


def test_flags_repo_missing_memory_section(tmp_path):
    """Repo with CLAUDE.md but no Project Memory section should be flagged."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# Project\n\nSome content.\n")
    with patch("agents.drift_detector.HAPAX_REPO_DIRS", [repo]):
        items = check_project_memory()
    assert len(items) == 1
    assert items[0].category == "missing_project_memory"
    assert "Project Memory" in items[0].suggestion


def test_passes_repo_with_memory_section(tmp_path):
    """Repo with CLAUDE.md containing Project Memory section should pass."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# Project\n\n## Project Memory\n\n- Pattern A\n")
    with patch("agents.drift_detector.HAPAX_REPO_DIRS", [repo]):
        items = check_project_memory()
    assert len(items) == 0


def test_handles_nonexistent_repo(tmp_path):
    """Non-existent repo directory should be silently skipped."""
    fake = tmp_path / "does-not-exist"
    with patch("agents.drift_detector.HAPAX_REPO_DIRS", [fake]):
        items = check_project_memory()
    assert len(items) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_drift_detector_memory.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_project_memory'` or `AttributeError`

**Step 3: Implement the check in drift_detector.py**

Add near the top of `~/projects/hapax-council/agents/drift_detector.py`, after the existing imports from `shared.config` (around line 33), add the repo directory list:

```python
HAPAX_REPO_DIRS = [
    AI_AGENTS_DIR,
    HAPAXROMANA_DIR,
    HAPAX_SYSTEM_DIR,
    RAG_PIPELINE_DIR,
    COCKPIT_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
]
```

Then add the check function before `check_doc_freshness()` (around line 247):

```python
def check_project_memory() -> list[DriftItem]:
    """Check that all hapax repos have a ## Project Memory section in CLAUDE.md.

    This enforces the cross-repo memory standard so Claude Code has
    institutional knowledge seeded in every project.
    """
    items: list[DriftItem] = []
    home = str(HAPAX_HOME)

    for repo_dir in HAPAX_REPO_DIRS:
        if not repo_dir.is_dir():
            continue

        claude_md = repo_dir / "CLAUDE.md"
        short_path = str(repo_dir).replace(home, "~")

        if not claude_md.is_file():
            items.append(DriftItem(
                severity="medium",
                category="missing_project_memory",
                doc_file=f"{short_path}/CLAUDE.md",
                doc_claim="File does not exist",
                reality="All hapax repos must have a CLAUDE.md with ## Project Memory section",
                suggestion=f"Create {short_path}/CLAUDE.md with a ## Project Memory section",
            ))
            continue

        content = claude_md.read_text(errors="replace")
        if "## Project Memory" not in content:
            items.append(DriftItem(
                severity="medium",
                category="missing_project_memory",
                doc_file=f"{short_path}/CLAUDE.md",
                doc_claim="No ## Project Memory section found",
                reality="All hapax repos must have a ## Project Memory section for cross-session learning",
                suggestion=f"Add a ## Project Memory section to {short_path}/CLAUDE.md with stable patterns and conventions",
            ))

    return items
```

Then wire it into the main `run()` function. Find where `boundary_drift = check_cross_project_boundary()` is called (around line 512) and add after it:

```python
    memory_drift = check_project_memory()
```

And find where the deterministic items are combined (look for the list that aggregates `doc_freshness_drift`, `screen_context_drift`, `boundary_drift`) and add `memory_drift` to it.

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_drift_detector_memory.py -v`
Expected: 4 passed

**Step 5: Add Project Memory section to ai-agents CLAUDE.md**

Append the following to `~/projects/hapax-council/CLAUDE.md` (before the `# currentDate` line):

```markdown
## Project Memory

Stable patterns confirmed across multiple sessions:

- **pydantic-ai 1.63.0**: Uses `output_type` (not `result_type`) and `result.output` (not `result.data`)
- **Tests**: Use `unittest.mock` — no pytest fixtures in conftest. Each test file is self-contained. Currently 1524+ tests.
- **Profile facts**: JSONL format with fields: `dimension`, `key`, `value`, `confidence`, `source`, `evidence`. 13 dimensions defined in `shared/dimensions.py` (6 trait, 6 behavioral, 1 neurocognitive).
- **Sync agents**: All sync agent `_generate_profile_facts()` methods produce behavioral dimension facts only. Validated by `shared.dimensions.validate_behavioral_write()`.
- **Cockpit API**: FastAPI at `:8051` with routers in `cockpit/api/routes/`. CORS configured for hapax-logos at `:5173`.
- **Cycle modes**: `shared/cycle_mode.py` reads `~/.cache/hapax/cycle-mode`. Agents call `get_cycle_mode()` at invocation to adjust thresholds. CLI: `hapax-mode dev|prod`.
- **LLM calls**: All Tier 2 agent LLM calls route through LiteLLM at `:4000` via `shared.config.get_model()`. Never direct to providers.
- **Notifications**: Use `shared.notify.send_notification()` for ntfy + desktop. Topic: `hapax-alerts`.
```

**Step 6: Run full drift-detector tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_drift_detector_memory.py tests/test_drift_detector.py -v`
Expected: All tests pass.

**Step 7: Commit**

```bash
cd ~/projects/hapax-council
git add tests/test_drift_detector_memory.py agents/drift_detector.py CLAUDE.md
git commit -m "feat: add cross-repo project memory enforcement to drift-detector

Add check_project_memory() that verifies all 6 hapax repos have a
## Project Memory section in CLAUDE.md. Add Project Memory section
to ai-agents CLAUDE.md with stable patterns."
```

---

### Task 5: Remove desktop-commander MCP server

**Files:**
- Modify: `~/.claude/mcp_servers.json`

**Context:** The `desktop-commander` MCP server is redundant — the Bash tool provides identical functionality. MCP servers are configured in `~/.claude/mcp_servers.json` under the `mcpServers` key. The current servers in that file are: `desktop-commander`, `docker`, `git`, `midi`, `midi-files`, `postgres`, `qdrant`.

**Step 1: Remove desktop-commander from mcp_servers.json**

```bash
jq 'del(.mcpServers["desktop-commander"])' ~/.claude/mcp_servers.json > ~/.claude/mcp_servers.json.tmp && mv ~/.claude/mcp_servers.json.tmp ~/.claude/mcp_servers.json
```

**Step 2: Verify remaining servers**

Run: `jq '.mcpServers | keys' ~/.claude/mcp_servers.json`
Expected: `["docker", "git", "midi", "midi-files", "postgres", "qdrant"]`

**Step 3: No commit needed** — `mcp_servers.json` is machine-local config, not version-controlled.

---

### Task 6: Run install.sh and validate

**Files:**
- No files modified — validation only

**Step 1: Run install.sh to pick up new skills**

```bash
cd ~/projects/hapax-system && bash install.sh
```

Expected output should include new skills:
```
  Skill: /profile -> .../skills/profile/SKILL.md
  Skill: /calendar -> .../skills/calendar/SKILL.md
  Skill: /nudges -> .../skills/nudges/SKILL.md
  Skill: /cycle-mode -> .../skills/cycle-mode/SKILL.md
  Skill: /demo -> .../skills/demo/SKILL.md
```

**Step 2: Verify all symlinks**

Run: `ls -la ~/.claude/commands/ | grep -E 'profile|calendar|nudges|cycle-mode|demo'`
Expected: 5 symlinks pointing to hapax-system skills.

**Step 3: Verify session hook runs clean**

Run: `bash ~/projects/hapax-system/hooks/scripts/session-context.sh`
Expected: Output includes `Profile:`, `Cycle:`, plus all existing lines. No errors.

**Step 4: Run all tests in ai-agents**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_cycle_mode.py tests/test_cycle_mode_integration.py tests/test_cycle_mode_api.py tests/test_timer_overrides.py tests/test_drift_detector_memory.py -v`
Expected: All pass.

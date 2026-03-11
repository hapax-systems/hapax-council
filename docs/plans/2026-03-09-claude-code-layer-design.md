# Claude Code Layer Refresh Design

**Date**: 2026-03-09
**Status**: Approved
**Scope**: Fix rules drift, enrich session hook, add 5 skills, establish cross-repo memory standard, clean up MCP servers.

## Problem Statement

The Claude Code layer (rules, hooks, skills, MCP servers) was designed early and hasn't tracked system growth. Three major developments are invisible to Claude Code:

1. **Profile system** — 13 dimensions, 500+ facts, distilled manifest. Claude Code generates operator data via claude_code_sync but never receives profile context back.
2. **Cockpit API** — 17+ real-time state endpoints (health, nudges, briefing, profile, momentum, cycle mode). No integration.
3. **Calendar/meeting context** — Synced and queryable via `shared/calendar_context.py`. Not surfaced.

Additionally, `system-context.md` (read every session) has drifted: missing 7 agents, wrong module paths, stale timer schedules, no cycle-mode reference. No cross-session memory exists.

## Design Decisions

1. **Skill-heavy approach**: On-demand skills for situational context (profile, calendar, nudges, cycle-mode). No new MCP servers — `curl` through Bash covers edge cases.
2. **Light session hook enrichment**: Profile summary + cycle mode injected every session (always-relevant). Calendar/nudges are situational — skills only.
3. **Cross-repo memory standard**: Every hapax repo gets a `## Project Memory` section in CLAUDE.md. Drift-detector enforces. Auto-memory directory seeded from repo memory on first session.
4. **MCP cleanup**: Remove `desktop-commander` (Bash tool covers it). Keep `memory` + `qdrant` (distinct purposes: knowledge graph vs. vector search).

## Section 1: Rules Drift Fix

**File:** `hapax-system/rules/system-context.md`

Changes:
- **Agent table**: Add 7 missing agents: `activity_analyzer` (No, `--stats`), `introspect` (No, `--json`), `research` (Yes), `code_review` (Yes), `query` (Yes, `--collection NAME`), `ingest` (No, `--watch`, `--stats`), `hapax_voice` (No, `--check`, `--config PATH`). Total: 26.
- **Fix shared module paths**: `shared/google_auth.py` and `shared/calendar_context.py` (not `agents/shared/`).
- **Add cycle-mode section**: Reference `hapax-mode dev|prod` CLI, mode file at `~/.cache/hapax/cycle-mode`, 9 timer overrides in `systemd/overrides/dev/`.
- **Timer table**: Reconcile against actual systemd units. Add missing timers, fix stale schedules.
- **Qdrant collections**: Remove `samples` (planned, not real). 4 active collections: `documents`, `profile-facts`, `claude-memory`, `axiom-precedents`.

## Section 2: Session Hook Enrichment

**File:** `hapax-system/hooks/scripts/session-context.sh`

Add two injections after existing content:

### Profile summary (~8 lines bash, 1-2 lines output)

Read `profiles/operator.json` with `jq`. Extract active goals count, current focus areas, and one work pattern. Output:

```
Profile: 3 active goals | Focus: ai-agents, cockpit-web | Pattern: deep-work mornings
```

Falls back silently if file missing (profiler hasn't run yet).

### Cycle mode (~5 lines bash, 1 line output)

Read `~/.cache/hapax/cycle-mode` and compute age from mtime. Output:

```
Cycle: dev (switched 2h ago)
```

Or `Cycle: prod` when in default mode. Falls back to `Cycle: prod (default)` if file missing.

### Auto-memory seed (~10 lines bash, no output)

Check if auto-memory directory exists at `~/.claude/projects/<hash>/memory/`. If not, create it and seed `MEMORY.md` from the repo's CLAUDE.md `## Project Memory` section (if present). Silent operation — no output to session context.

## Section 3: New Skills

All in `hapax-system/skills/<name>/SKILL.md`, symlinked to `~/.claude/commands/` by install.sh.

### `/profile`

Inspect operator profile. Steps:
1. Read `profiles/operator.json` — show distilled manifest summary (goals, constraints, patterns)
2. Read `profiles/ryan.json` — show per-dimension fact counts, average confidence, oldest fact age
3. If arg provided (dimension name), drill into that dimension's facts
4. No LLM calls — read and format only

### `/calendar`

Calendar and meeting context. Steps:
1. Run `shared/calendar_context.py` via `uv run python -c` to surface:
   - Today's meeting count
   - Upcoming meetings (next 24h)
   - Meetings needing prep
2. If arg provided (person name), show next meeting with that person
3. Optionally check meeting-prep timer status via `systemctl --user status meeting-prep.timer`

### `/nudges`

Review active nudges. Steps:
1. `curl -s localhost:8051/api/nudges` — format and display active nudges (text, source, age)
2. If arg `act <id>` or `dismiss <id>`, POST to corresponding endpoint
3. Show nudge count and categories

### `/cycle-mode`

Cycle mode check and switch. Steps:
1. No args: show current mode, switched_at, active timer schedule summary
2. With arg `dev` or `prod`: run `hapax-mode <mode>`, show resulting state
3. Show which timers are overridden and their current schedules

### `/demo` (fix)

The skill file exists at `hapax-system/skills/demo/SKILL.md` but the symlink is missing from `~/.claude/commands/`. Ensure install.sh creates it. No new content needed.

## Section 4: Cross-Repo Memory Standard

### Repo memory (`## Project Memory` in CLAUDE.md)

Every hapax repo's CLAUDE.md includes a `## Project Memory` section with stable institutional knowledge:
- Key patterns and conventions confirmed in practice
- Architectural decisions and their rationale
- Known gotchas and debugging insights
- Links to design docs for major features

**Repos:** ai-agents, cockpit-web, hapax-vscode, rag-pipeline, hapaxromana, hapax-system (6 total).

### Auto-memory seeding

The session-context hook creates `~/.claude/projects/<hash>/memory/MEMORY.md` on first run if missing, seeded from the repo's `## Project Memory` section. This bootstraps machine-local auto-memory from version-controlled knowledge.

### Enforcement

Add a drift-detector check: scan all 6 hapax repos for CLAUDE.md with `## Project Memory` section. Flag repos missing it. This runs weekly with existing drift-detector schedule.

## Section 5: MCP Server Cleanup

**Remove:** `desktop-commander` — Bash tool provides identical functionality.

**Keep:** All others (11 remaining): context7, memory, sequential-thinking, filesystem, playwright, tavily, qdrant, docker, git, postgres.

**Action:** Update `~/.claude/settings.json` to remove desktop-commander entry. Update install.sh if it manages MCP server config.

## Section 6: Testing & Validation

- **Rules drift**: Verify updated system-context.md passes drift-detector run
- **Session hook**: Manual — start new session, confirm profile + cycle mode in output
- **Skills**: Manual — invoke each of 5 skills, confirm expected output
- **Auto-memory seed**: Manual — delete memory dir, start session, confirm it's created
- **Drift-detector check**: One new test verifying the Project Memory enforcement check flags missing sections
- **Install script**: Run install.sh, verify all symlinks correct and settings.json updated

## Implementation Phases

### Phase 1: Rules drift fix
- Update `hapax-system/rules/system-context.md`
- Commit

### Phase 2: Session hook enrichment
- Update `hapax-system/hooks/scripts/session-context.sh` (profile, cycle mode, auto-memory seed)
- Commit

### Phase 3: New skills
- Create 4 new skill files + fix demo symlink
- Update install.sh for new skills
- Commit

### Phase 4: Cross-repo memory standard
- Add `## Project Memory` to ai-agents CLAUDE.md
- Add drift-detector check for Project Memory sections
- Commit (other repos get their sections added separately)

### Phase 5: MCP server cleanup
- Remove desktop-commander from settings
- Update install.sh if needed
- Commit

### Phase 6: Validation
- Run install.sh
- Start fresh session, verify all changes
- Run drift-detector to confirm no new drift

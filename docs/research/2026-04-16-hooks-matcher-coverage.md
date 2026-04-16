---
title: hooks/scripts/*.sh matcher coverage verification
date: 2026-04-16
queue_item: '318'
epic: lrr
status: catalog
---

# hooks/scripts — matcher coverage

Each Claude Code PreToolUse hook's matcher + gated scope.

## Installed hooks (repo)

| Hook | First exec line |
|---|---|
| `axiom-audit.sh` | axiom-audit.sh — PostToolUse hook for axiom audit trail |
| `axiom-commit-scan.sh` | axiom-commit-scan.sh — PreToolUse hook for Bash tool |
| `axiom-patterns.sh` | axiom-patterns.sh — T0 violation patterns for axiom governance |
| `axiom-scan.sh` | axiom-scan.sh — PreToolUse hook for T0 axiom violation detection |
| `branch-switch-guard.sh` | branch-switch-guard.sh — PreToolUse hook that blocks branch CREATION |
| `cargo-check-rust.sh` | cargo-check-rust.sh — PostToolUse hook (Edit / Write / MultiEdit / NotebookEdit) |
| `conductor-post.sh` | conductor-post.sh — PostToolUse hook: pipe event to conductor UDS |
| `conductor-pre.sh` | conductor-pre.sh — PreToolUse hook: pipe event to conductor UDS |
| `conductor-start.sh` | conductor-start.sh — SessionStart hook: launch conductor sidecar |
| `conductor-stop.sh` | conductor-stop.sh — Stop hook: shutdown conductor sidecar |
| `conflict-marker-scan.sh` | conflict-marker-scan.sh — PostToolUse hook that detects conflict markers after git operations. |
| `docs-only-pr-warn.sh` | docs-only-pr-warn.sh — PreToolUse hook (Bash tool) |
| `doc-update-advisory.sh` | doc-update-advisory.sh — PostToolUse hook (advisory, non-blocking) |
| `gemini-session-adapter.sh` | gemini-session-adapter.sh — Wraps a Claude Code SessionStart/Stop hook |
| `gemini-tool-adapter.sh` | gemini-tool-adapter.sh — Translates Gemini CLI BeforeTool/AfterTool JSON |
| `llm-metadata-gate.sh` | no-op placeholder — original llm-metadata-gate not found |
| `no-stale-branches.sh` | no-stale-branches.sh — PreToolUse hook (Bash commands) |
| `pii-guard.sh` | pii-guard.sh — PreToolUse hook (Edit, Write) |
| `pip-guard.sh` | pip-guard.sh — PreToolUse hook that blocks direct pip usage. |
| `push-gate.sh` | push-gate.sh — PreToolUse hook that blocks git push, PR create/merge, |
| `registry-guard.sh` | registry-guard.sh — PreToolUse hook that blocks edits to protected |
| `relay-coordination-check.sh` | relay-coordination-check.sh — PreToolUse hook (Edit / Write / MultiEdit / NotebookEdit) |
| `safe-stash-guard.sh` | safe-stash-guard.sh — PreToolUse hook that blocks `git stash pop`. |
| `session-context.sh` | session-context.sh — SessionStart hook for hapax-system plugin |
| `session-summary.sh` | session-summary.sh — Stop hook for axiom audit summary |
| `skill-trigger-advisory.sh` | skill-trigger-advisory.sh — PostToolUse hook (advisory, non-blocking) |
| `sprint-tracker.sh` | sprint-tracker.sh — PostToolUse hook for R&D sprint measure completion detection. |
| `work-resolution-gate.sh` | work-resolution-gate.sh — PreToolUse hook |

## Active Claude Code settings.json PreToolUse matchers

```json
{
  "PreToolUse": [
    {
      "matcher": "Edit|Write|MultiEdit|NotebookEdit",
      "hooks": [
        {
          "type": "command",
          "command": "/home/hapax/projects/hapax-council/hooks/scripts/axiom-scan.sh"
        }
      ]
    },
    {
      "matcher": "Bash",
      "hooks": [
        {
          "type": "command",
          "command": "/home/hapax/projects/hapax-council/hooks/scripts/axiom-commit-scan.sh"
        }
      ]
    },
    {
      "matcher": "Bash",
      "hooks": [
        {
          "type": "command",
          "command": "/home/hapax/projects/hapax-council/hooks/scripts/pip-guard.sh"
        }
      ]
    },
    {
      "matcher": "Bash",
      "hooks": [
        {
          "type": "command",
          "command": "/home/hapax/projects/hapax-council/hooks/scripts/no-stale-branches.sh"
        }
      ]
    },
    {
      "matcher": "Edit|Write|MultiEdit|NotebookEdit",
      "hooks": [
        {
          "type": "command",
          "command": "/home/hapax/projects/hapax-council/hooks/scripts/work-resolution-gate.sh"
        }
      ]
    },
    {
      "matcher": "Edit|Write|MultiEdit|NotebookEdit",
      "hooks": [
        {
          "type": "command",
          "command": "/home/hapax/projects/hapax-council/hooks/scripts/registry-guard.sh"
        }
      ]
    },
    {
      "matcher": "Bash",
      "hooks": [
        {
```

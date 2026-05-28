#!/usr/bin/env bash
# subagent-git-safety.sh — SubagentStop hook.
#
# Event-level reflex for the documented subagent-git-safety failure mode:
# subagent commits are routinely lost when isolated worktrees are cleaned up
# (CLAUDE.md "Subagent Git Safety — MANDATORY"). The only prior coverage was
# the PostToolUse subagent-file-persistence-check.sh advisory; this fires the
# moment a subagent finishes, which is when verification must happen.
#
# Never blocks (the subagent has already stopped) — always exit 0. It prints
# a reminder, and surfaces any unpersisted work in the current worktree.
#
# Disable: HAPAX_SUBAGENT_GIT_SAFETY_OFF=1
set -euo pipefail

[ "${HAPAX_SUBAGENT_GIT_SAFETY_OFF:-0}" = "1" ] && exit 0

# Advisory hook — consume stdin even if jq is unavailable.
cat >/dev/null 2>&1 || true

worktree_note=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  dirty="$(git status --porcelain 2>/dev/null | grep -c '' || true)"
  branch="$(git symbolic-ref --short HEAD 2>/dev/null || echo 'detached')"
  ahead="0"
  if upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
    ahead="$(git rev-list --count "${upstream}..HEAD" 2>/dev/null || echo 0)"
  fi
  [ "${dirty:-0}" -gt 0 ] 2>/dev/null && worktree_note="${worktree_note} ${dirty} uncommitted change(s);"
  [ "${ahead:-0}" -gt 0 ] 2>/dev/null && worktree_note="${worktree_note} ${ahead} unpushed commit(s) on ${branch};"
fi

cat >&2 <<EOF
ADVISORY (subagent-git-safety): a subagent finished.
  If it wrote code that must persist, verify it now — before any worktree cleanup:
    ls <expected_files> && git log --oneline -3
  Subagent commits in isolated worktrees are routinely lost. Prefer direct
  implementation; if a subagent committed in an isolated worktree it MUST have
  pushed (git push -u origin HEAD) and reported the remote SHA.${worktree_note:+
  This worktree has:${worktree_note}}
EOF

exit 0

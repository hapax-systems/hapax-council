#!/usr/bin/env bash
# worktree-auto-push.sh — git post-commit hook for worktree directories.
# Auto-pushes commits to remote on non-main branches in worktree contexts.
# Prevents subagent work loss when worktrees are cleaned up.
#
# Install: ln -sf ~/projects/hapax-council/hooks/scripts/worktree-auto-push.sh \
#          ~/projects/hapax-council/.git/hooks/post-commit
#
# Only fires in worktree directories (not the main working tree).
# Only on non-main branches. Fire-and-forget (push failures are silent).

branch=$(git symbolic-ref --short HEAD 2>/dev/null || true)
[ -n "$branch" ] || exit 0
[ "$branch" != "main" ] || exit 0

# Detect worktree: gitdir differs from commondir
gitdir=$(git rev-parse --git-dir 2>/dev/null || true)
commondir=$(git rev-parse --git-common-dir 2>/dev/null || true)
[ -n "$gitdir" ] && [ -n "$commondir" ] || exit 0
[ "$gitdir" != "$commondir" ] || exit 0

# Fire-and-forget push — never block the commit
git push -u origin HEAD >/dev/null 2>&1 &
disown 2>/dev/null || true
exit 0

#!/usr/bin/env bash
# worktree-auto-push.sh — git post-commit hook for worktree directories.
# Historically auto-pushed commits to remote on non-main branches in worktree
# contexts. That is now opt-in only: background push is a release-adjacent
# mutation and must not bypass task/release gates by default.
#
# Install: ln -sf ~/projects/hapax-council/hooks/scripts/worktree-auto-push.sh \
#          ~/projects/hapax-council/.git/hooks/post-commit
#
# Only fires in worktree directories (not the main working tree).
# Only on non-main branches. Push failures warn on stderr but never block.

set -euo pipefail

branch=$(git symbolic-ref --short HEAD 2>/dev/null || true)
[ -n "$branch" ] || exit 0
[ "$branch" != "main" ] || exit 0

# Detect worktree: gitdir differs from commondir
gitdir=$(git rev-parse --git-dir 2>/dev/null || true)
commondir=$(git rev-parse --git-common-dir 2>/dev/null || true)
[ -n "$gitdir" ] && [ -n "$commondir" ] || exit 0
[ "$gitdir" != "$commondir" ] || exit 0

if [ "${HAPAX_WORKTREE_AUTO_PUSH:-0}" != "1" ]; then
  echo "worktree-auto-push: disabled by default for $branch; use governed git push" >&2
  exit 0
fi

# Push in background — warn on failure, never block
(
  if ! git push -u origin HEAD >/dev/null 2>&1; then
    echo "worktree-auto-push: WARNING: push failed for $branch (network or remote issue)" >&2
  fi
) &
disown 2>/dev/null || true
exit 0

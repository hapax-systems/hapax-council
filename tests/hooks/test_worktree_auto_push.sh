#!/usr/bin/env bash
# Test: worktree-auto-push post-commit hook.
# Creates a temp repo with a worktree, installs the hook, commits,
# and asserts the branch is not pushed unless explicit opt-in is present.
set -euo pipefail

HOOK_SCRIPT="$(cd "$(dirname "$0")/../.." && pwd)/hooks/scripts/worktree-auto-push.sh"
if [ ! -f "$HOOK_SCRIPT" ]; then
  echo "FAIL: hook script not found at $HOOK_SCRIPT" >&2
  exit 1
fi

cleanup() { rm -rf "$TMPDIR"; }
TMPDIR=$(mktemp -d)
trap cleanup EXIT

BARE="$TMPDIR/remote.git"
MAIN="$TMPDIR/main"
WT="$TMPDIR/worktree"

git init --bare "$BARE" >/dev/null 2>&1
git clone "$BARE" "$MAIN" >/dev/null 2>&1
cd "$MAIN"
git config user.email "test@test"
git config user.name "test"

echo "init" > file.txt
git add file.txt
git commit -m "initial" >/dev/null 2>&1
git push -u origin main >/dev/null 2>&1

git checkout -b test/worktree-branch >/dev/null 2>&1
echo "branch" > file.txt
git add file.txt
git commit -m "branch commit" >/dev/null 2>&1
git push -u origin test/worktree-branch >/dev/null 2>&1
git checkout main >/dev/null 2>&1

git worktree add "$WT" test/worktree-branch >/dev/null 2>&1

cp "$HOOK_SCRIPT" "$MAIN/.git/hooks/post-commit"
chmod +x "$MAIN/.git/hooks/post-commit"

cd "$WT"
echo "worktree change" > file.txt
git add file.txt
git commit -m "worktree commit" >/dev/null 2>&1

sleep 2

REMOTE_SHA=$(git ls-remote origin test/worktree-branch 2>/dev/null | awk '{print $1}')
LOCAL_SHA=$(git rev-parse HEAD)

if [ "$REMOTE_SHA" != "$LOCAL_SHA" ]; then
  echo "PASS: default worktree commit did not auto-push"
else
  echo "FAIL: default worktree commit auto-pushed remote=$REMOTE_SHA local=$LOCAL_SHA" >&2
  exit 1
fi

HAPAX_WORKTREE_AUTO_PUSH=1 "$HOOK_SCRIPT" 2>/dev/null
sleep 2
REMOTE_SHA=$(git ls-remote origin test/worktree-branch 2>/dev/null | awk '{print $1}')
if [ "$REMOTE_SHA" = "$LOCAL_SHA" ]; then
  echo "PASS: explicit opt-in pushed worktree branch"
else
  echo "FAIL: opt-in push failed remote=$REMOTE_SHA local=$LOCAL_SHA" >&2
  exit 1
fi

# Idempotency: re-running on same commit should not error
HAPAX_WORKTREE_AUTO_PUSH=1 "$HOOK_SCRIPT" 2>/dev/null
echo "PASS: idempotent re-run succeeded"

# Main branch: hook should be a no-op
cd "$MAIN"
echo "main change" > file.txt
git add file.txt
BEFORE_SHA=$(git ls-remote origin main 2>/dev/null | awk '{print $1}')
git commit -m "main commit" >/dev/null 2>&1
sleep 1
AFTER_SHA=$(git ls-remote origin main 2>/dev/null | awk '{print $1}')

if [ "$BEFORE_SHA" = "$AFTER_SHA" ]; then
  echo "PASS: main branch commit did not trigger push (not a worktree)"
else
  echo "FAIL: main branch was pushed by hook" >&2
  exit 1
fi

echo "ALL TESTS PASSED"

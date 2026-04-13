#!/usr/bin/env bash
# docs-only-pr-warn.sh — PreToolUse hook (Bash tool)
#
# Warns when a `git commit` on a feature branch contains only files that
# fall under ci.yml's paths-ignore filter. Such commits will hit branch
# protection limbo because ci.yml's `test` job (the gate) does not fire
# when only docs/md change.
#
# This hook NEVER blocks. It only prints a stderr advisory pointing at
# the canonical workaround (bundle a non-md carrier file). Operators may
# legitimately want a docs-only commit (e.g., resetting beta-standby,
# WIP). The hook just makes the impending wall visible.
#
# Trigger conditions (all must be true):
#   1. Tool is Bash
#   2. Command matches `git commit` (not amend-only metadata)
#   3. Inside a git work tree
#   4. Current branch is NOT main / master (the warning only matters on
#      branches that will become PRs)
#   5. Staged file list is non-empty
#   6. EVERY staged file matches one of the paths-ignore patterns:
#        docs/, *.md (root), lab-journal/, research/, axioms/**.md
#
# Fail-open: any error in JSON parsing, git execution, or path matching
# results in exit 0 (advisory mode — never block legitimate work).

set -euo pipefail

INPUT="$(cat)"

TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
[ "$TOOL" = "Bash" ] || exit 0

CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# Match `git commit` but not, say, `git rev-list --no-commit` or text in
# a quoted commit message that mentions the words "git commit". Strip
# quoted strings before matching.
CMD_STRIPPED="$(printf '%s' "$CMD" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g")"
echo "$CMD_STRIPPED" | grep -qE '\bgit\s+commit\b' || exit 0

git rev-parse --is-inside-work-tree &>/dev/null || exit 0

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
[ -z "$BRANCH" ] && exit 0
[ "$BRANCH" = "main" ] && exit 0
[ "$BRANCH" = "master" ] && exit 0
[ "$BRANCH" = "HEAD" ] && exit 0

# Get staged files. If the command includes -a / --all, also include
# unstaged tracked changes (which `git commit -a` would auto-stage).
STAGED="$(git diff --cached --name-only 2>/dev/null || true)"
if echo "$CMD_STRIPPED" | grep -qE '\bgit\s+commit\s+(-[^[:space:]]*a|--all)\b'; then
  UNSTAGED="$(git diff --name-only 2>/dev/null || true)"
  STAGED="$(printf '%s\n%s' "$STAGED" "$UNSTAGED" | sort -u | sed '/^$/d')"
fi

[ -z "$STAGED" ] && exit 0

# Test if every file matches one of the paths-ignore patterns from
# .github/workflows/ci.yml lines 7-12. Patterns:
#   docs/**           — any path under docs/
#   *.md              — root-level markdown only (docs/foo.md handled by docs/**)
#   lab-journal/**    — any path under lab-journal/
#   research/**       — any path under research/
#   axioms/**/*.md    — markdown anywhere under axioms/
#
# Note: ci.yml uses gitignore-style globs which are interpreted by
# GitHub Actions, not bash. Replicate the semantics manually.
ignored_path() {
  local p="$1"
  case "$p" in
    docs/*|docs) return 0 ;;
    lab-journal/*|lab-journal) return 0 ;;
    research/*|research) return 0 ;;
  esac
  # Root-level *.md (no slash in path)
  case "$p" in
    *.md)
      if ! echo "$p" | grep -q '/'; then
        return 0
      fi
      ;;
  esac
  # axioms/**/*.md
  case "$p" in
    axioms/*.md|axioms/*/*.md|axioms/*/*/*.md|axioms/*/*/*/*.md)
      return 0
      ;;
  esac
  return 1
}

ALL_IGNORED=true
NON_IGNORED_SAMPLE=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if ! ignored_path "$f"; then
    ALL_IGNORED=false
    NON_IGNORED_SAMPLE="$f"
    break
  fi
done <<< "$STAGED"

if [ "$ALL_IGNORED" != true ]; then
  # Mixed staged set — CI will fire normally. No advisory.
  exit 0
fi

# Every staged file is under paths-ignore. CI's test job will not fire
# and branch protection will block the PR from merging.
COUNT="$(printf '%s\n' "$STAGED" | wc -l)"
SAMPLE="$(printf '%s\n' "$STAGED" | head -3 | sed 's/^/    /')"

cat >&2 <<EOF
ADVISORY: Docs-only commit on feature branch '$BRANCH'.
  All $COUNT staged file(s) are under ci.yml paths-ignore (docs/**, *.md,
  lab-journal/**, research/**, axioms/**/*.md). The CI 'test' job will
  not fire and branch protection will block the PR from merging.

Sample staged files:
$SAMPLE

Workaround: bundle one non-markdown carrier file change. Examples:
  - PR #708 used '__all__ = [...]' in shared/impingement_consumer.py
  - PR #720 used '__all__ = [...]' in agents/reverie/debug_uniforms.py

See CLAUDE.md § Council-Specific Conventions for the canonical pattern.
This commit will still proceed; the advisory is informational.
EOF

exit 0

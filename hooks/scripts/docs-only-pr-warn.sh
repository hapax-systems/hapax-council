#!/usr/bin/env bash
# docs-only-pr-warn.sh — PreToolUse hook (Bash tool)
#
# Notices when a `git commit` on a feature branch contains only files handled
# by the docs-only CI sentinels. These commits now get lightweight success
# statuses for required checks; no carrier-file workaround is needed.
#
# This hook NEVER blocks. It only prints a stderr advisory confirming that
# branch protection will see the sentinel statuses. Operators may legitimately
# want a docs-only commit (e.g., resetting beta-standby, WIP).
#
# Trigger conditions (all must be true):
#   1. Tool is Bash
#   2. Command matches `git commit` (not amend-only metadata)
#   3. Inside a git work tree
#   4. Current branch is NOT main / master (the warning only matters on
#      branches that will become PRs)
#   5. Staged file list is non-empty
#   6. EVERY staged file matches one of the docs-only sentinel patterns:
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

# Test if every file matches one of the docs-only sentinel patterns from
# .github/workflows/ci.yml. Patterns:
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
    docs|docs/*|lab-journal|lab-journal/*|research|research/*) return 0 ;;
  esac
  # Root-level *.md (no slash in path)
  if [[ "$p" == *.md && "$p" != */* ]]; then
    return 0
  fi
  # axioms/**/*.md
  if [[ "$p" == axioms/*.md ]]; then
    return 0
  fi
  return 1
}

ALL_IGNORED=true
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if ! ignored_path "$f"; then
    ALL_IGNORED=false
    break
  fi
done <<< "$STAGED"

if [ "$ALL_IGNORED" != true ]; then
  # Mixed staged set — full CI will run normally. No advisory.
  exit 0
fi

# Every staged file is in the docs-only sentinel set. Required checks will
# appear on the PR and report lightweight success.
COUNT="$(printf '%s\n' "$STAGED" | wc -l)"
SAMPLE="$(printf '%s\n' "$STAGED" | head -3 | sed 's/^/    /')"

cat >&2 <<EOF
ADVISORY: Docs-only commit on feature branch '$BRANCH'.
  All $COUNT staged file(s) match the docs-only CI sentinel set (docs/**,
  root *.md, lab-journal/**, research/**, axioms/**/*.md). Required checks
  now run and report lightweight success; no carrier file is required.

Sample staged files:
$SAMPLE

This commit will still proceed; the advisory is informational.
EOF

exit 0

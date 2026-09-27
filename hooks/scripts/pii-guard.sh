#!/usr/bin/env bash
# pii-guard.sh — PreToolUse hook (Edit, Write)
#
# Blocks file writes that would introduce PII into tracked files.
# Checks for operator identity, location, family references, and
# sensitive personal data patterns.
#
# Only checks files that git would track (respects .gitignore).
# Only blocks on HIGH-confidence matches to avoid false positives.
set -euo pipefail

# Fail LOUD when jq is missing: without it tool_name parses empty, the
# case below never matches Edit/Write, and the hook exits 0 — silently
# letting PII through. A privacy gate that no-ops is worse than one that
# fails, so block instead of failing open.
if ! command -v jq >/dev/null 2>&1; then
  echo "pii-guard: BLOCKED — 'jq' is not installed; cannot parse hook input." >&2
  echo "Install jq before mutating tracked files. This gate fails closed." >&2
  exit 2
fi

# Fail LOUD when grep lacks PCRE (-P): every pattern below uses grep -P,
# which on a non-PCRE grep errors out — indistinguishable from a clean
# no-match, i.e. PII would pass undetected. Probe once, fail closed.
if ! printf 'probe' | grep -qP 'probe' 2>/dev/null; then
  echo "pii-guard: BLOCKED — 'grep -P' (PCRE) is unavailable." >&2
  echo "The PII patterns require PCRE. Install GNU grep with PCRE support." >&2
  echo "This gate fails closed rather than silently passing PII through." >&2
  exit 2
fi

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty')"

# Only gate file-mutating tools
case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

# Extract file path
file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null || true)"
[ -n "$file_path" ] || exit 0

# Skip files that aren't git-tracked or would be gitignored
if git rev-parse --is-inside-work-tree &>/dev/null; then
  # Allow writes to gitignored files (they won't reach GitHub)
  if git check-ignore -q "$file_path" 2>/dev/null; then
    exit 0
  fi
fi

# Skip non-content files (binary, images, etc.)
case "$file_path" in
  *.png|*.jpg|*.jpeg|*.gif|*.wav|*.mp3|*.mp4|*.db|*.sqlite) exit 0 ;;
esac

# Extract the new content being written
new_content="$(printf '%s' "$input" | jq -r '.tool_input.new_string // .tool_input.content // empty' 2>/dev/null || true)"
[ -n "$new_content" ] || exit 0

# --- PII Pattern Checks ---
# Each pattern must be HIGH confidence (no false positives on code/docs)

blocked=()

# The guard machinery must carry the name patterns it enforces. These four files
# are exempt from the name checks by exact repo-relative path (anchored at a path
# boundary, never a directory glob). They must stay inside the CI scanner's
# WHITELIST_GLOBS (pinned by tests/hooks/test_pii_guard.py).
LEGAL_NAME_EXEMPT_PATHS=(
  'hooks/scripts/pii-guard.sh'
  'scripts/check-legal-name-leaks.sh'
  'tests/hooks/test_pii_guard.py'
  'tests/scripts/test_check_legal_name_leaks.py'
)
# Exemption is decided on the path relative to the file's own git toplevel, by
# exact equality: another worktree of the repo matches, but a nested copy
# (vendor/hooks/scripts/pii-guard.sh) does not. No resolvable root: no exemption.
name_checks_exempt=0
abs_path="$(realpath -m -- "$file_path" 2>/dev/null || printf '%s' "$file_path")"
probe_dir="$(dirname "$abs_path")"
while [ ! -d "$probe_dir" ] && [ "$probe_dir" != "/" ]; do
  probe_dir="$(dirname "$probe_dir")"
done
if toplevel="$(git -C "$probe_dir" rev-parse --show-toplevel 2>/dev/null)" && [ -n "$toplevel" ]; then
  toplevel="$(realpath -m -- "$toplevel")"
  case "$abs_path" in
    "$toplevel"/*)
      rel_path="${abs_path#"$toplevel"/}"
      for exempt_path in "${LEGAL_NAME_EXEMPT_PATHS[@]}"; do
        [ "$rel_path" = "$exempt_path" ] && name_checks_exempt=1
      done
      ;;
  esac
fi

if [ "$name_checks_exempt" -eq 0 ]; then
  # Registered principals' given names, read from the gitignored local registry
  # (hooks/scripts/principal-name-map.sh). Absent registry: no names, surname
  # only. An unreadable or invalid registry fails closed. A matched name is never
  # printed. The exempt machinery never reads it.
  # shellcheck source=hooks/scripts/principal-name-map.sh
  source "$(dirname "${BASH_SOURCE[0]}")/principal-name-map.sh"
  names_status=0
  registry_names="$(principal_names)" || names_status=$?
  if [ "$names_status" -ne 0 ]; then
    echo "pii-guard: BLOCKED — the principal-name-map registry at $(principal_name_map_path) cannot be used (see above)." >&2
    echo "Repair it (a readable file of valid entries) or remove it. This gate fails closed." >&2
    exit 2
  fi

  # Operator full name (exact match only)
  if echo "$new_content" | grep -qiP 'Ryan\s+Kleeberger'; then
    blocked+=("Operator full name detected")
  fi

  # The family surname alone: it names every household member, registered as a
  # principal or not. Opaque principal IDs (principal-<letter><digit>) are NOT
  # sensitive and are never blocked: they are the vocabulary that replaces names.
  if echo "$new_content" | grep -qiP 'Kleeberger'; then
    blocked+=("Family surname detected")
  fi

  if [ -n "$registry_names" ]; then
    while IFS= read -r registry_name; do
      if printf '%s\n' "$new_content" | grep -qiwF -- "$registry_name"; then
        blocked+=("Registered principal given name detected (local registry; name withheld)")
        break
      fi
    done <<< "$registry_names"
  fi
fi

# Location data
if echo "$new_content" | grep -qP 'Minneapolis[- ]St\.?\s*Paul'; then
  blocked+=("Location data (Minneapolis-St. Paul)")
fi

# Home directory absolute paths (reveals username)
if echo "$new_content" | grep -qP '/home/hapax/'; then
  # Allow in infrastructure files that legitimately reference the home directory
  case "$file_path" in
    */.gitignore|*/CLAUDE.md|*/hooks/*|*/.claude/*|*/systemd/*|*/process-compose*|*/scripts/*) ;;
    *) blocked+=("Home directory path (/home/hapax/)") ;;
  esac
fi

# Engine audit / browsing data patterns
if echo "$new_content" | grep -qP 'rag-sources/(chrome|audio)/'; then
  blocked+=("Browsing/audio data path reference")
fi

if [ ${#blocked[@]} -gt 0 ]; then
  echo "BLOCKED: PII detected in content being written to $file_path:" >&2
  for msg in "${blocked[@]}"; do
    echo "  - $msg" >&2
  done
  echo "If this is intentional (e.g., in a gitignored file), add the file to .gitignore first." >&2
  exit 2
fi

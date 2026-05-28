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

# Operator full name (exact match only)
if echo "$new_content" | grep -qiP 'Ryan\s+Kleeberger'; then
  blocked+=("Operator full name detected")
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

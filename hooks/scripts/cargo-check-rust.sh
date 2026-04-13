#!/usr/bin/env bash
# cargo-check-rust.sh — PostToolUse hook (Edit / Write / MultiEdit / NotebookEdit)
#
# Runs `cargo check -p <crate>` whenever a .rs file under
# hapax-logos/crates/<crate>/src/ is edited. Catches compilation
# regressions in the post-edit reflex loop instead of waiting for CI to
# fail 7 minutes later.
#
# Performance:
#   - Tries `cargo check --offline` first (~1s incremental, no network).
#   - Falls back to network check only if offline fails.
#   - Per-crate debounce via /tmp/hapax-cargo-check-<crate>.lock
#     (30s window) to avoid re-checking on rapid sequential edits.
#
# Reporting:
#   - Silent on success.
#   - On failure: prints first 20 error/warning lines to stderr +
#     a pointer at the full diagnostic command.
#   - Always exit 0 (advisory mode — CI is the real gate).
#
# Disable via env var: HAPAX_CARGO_CHECK_HOOK=0

set -euo pipefail

[ "${HAPAX_CARGO_CHECK_HOOK:-1}" = "0" ] && exit 0

INPUT="$(cat)"

TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
case "$TOOL" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

# Extract the file path the tool wrote to. Different tools use
# different keys; fall through them.
EDIT_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // empty' 2>/dev/null)" || exit 0
[ -n "$EDIT_PATH" ] || exit 0

# Only fire on .rs files under a hapax-logos crate src directory.
case "$EDIT_PATH" in
  *hapax-logos/crates/*/src/*.rs) ;;
  *) exit 0 ;;
esac

# Find the crate name (the path component immediately after `crates/`).
CRATE="$(printf '%s' "$EDIT_PATH" | sed -nE 's|.*/hapax-logos/crates/([^/]+)/src/.*|\1|p')"
[ -n "$CRATE" ] || exit 0

# Find the workspace root (where hapax-logos/Cargo.toml lives).
WORKSPACE_ROOT="$(printf '%s' "$EDIT_PATH" | sed -nE 's|(.*/hapax-logos)/.*|\1|p')"
[ -n "$WORKSPACE_ROOT" ] || exit 0
[ -f "$WORKSPACE_ROOT/Cargo.toml" ] || exit 0

# Debounce: skip if we ran this crate's check in the last 30s.
LOCK_DIR="${TMPDIR:-/tmp}"
LOCK_FILE="$LOCK_DIR/hapax-cargo-check-${CRATE}.lock"
if [ -f "$LOCK_FILE" ]; then
  AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  if [ "$AGE" -lt 30 ]; then
    exit 0
  fi
fi

# Need cargo on PATH.
command -v cargo &>/dev/null || exit 0

# Try offline first. If it fails because the cargo registry needs a
# network refresh, retry online once.
CARGO_OUT="$(cd "$WORKSPACE_ROOT" && cargo check -p "$CRATE" --offline 2>&1)"
RC=$?

if [ "$RC" -ne 0 ] && printf '%s' "$CARGO_OUT" | grep -qE 'failed to download|registry.*not found|no matching package'; then
  CARGO_OUT="$(cd "$WORKSPACE_ROOT" && cargo check -p "$CRATE" 2>&1)"
  RC=$?
fi

# Touch debounce lock regardless of result (we tried, no need to retry
# in the next 30s window).
touch "$LOCK_FILE" 2>/dev/null || true

if [ "$RC" -eq 0 ]; then
  exit 0
fi

# Cargo check failed. Print the first ~20 error/warning lines plus a
# pointer at the full command so the operator can drill in.
ERR_LINES="$(printf '%s' "$CARGO_OUT" | grep -E '^(error|warning|  -->|note:)' | head -20 || true)"
[ -z "$ERR_LINES" ] && ERR_LINES="$(printf '%s' "$CARGO_OUT" | tail -20)"

cat >&2 <<EOF
ADVISORY: cargo check failed for crate '$CRATE' after edit to '$EDIT_PATH'.
$ERR_LINES

Run \`cd hapax-logos && cargo check -p $CRATE\` for the full diagnostic.
This is a post-edit advisory — CI will run the same check on push.
EOF

exit 0

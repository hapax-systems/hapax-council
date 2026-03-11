#!/usr/bin/env bash
# axiom-audit.sh — PostToolUse hook for axiom audit trail
# Logs every Edit/Write/MultiEdit to ~/.cache/axiom-audit/YYYY-MM-DD.jsonl
# Tracks session file writes and runs periodic cross-file axiom check.

INPUT="$(cat)"

AUDIT_DIR="$HOME/.cache/axiom-audit"
mkdir -p "$AUDIT_DIR"

AUDIT_FILE="$AUDIT_DIR/$(date +%Y-%m-%d).jsonl"

TOOL_NAME="$(echo "$INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null || echo unknown)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // "unknown"' 2>/dev/null || echo unknown)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo unknown)"

# Append audit entry
printf '{"timestamp":"%s","tool":"%s","file":"%s","session_id":"%s"}\n' \
  "$(date -Iseconds)" "$TOOL_NAME" "$FILE_PATH" "$SESSION_ID" >> "$AUDIT_FILE"

# Session accumulator — track files written per session
SESSION_FILE="$AUDIT_DIR/.session-${SESSION_ID}"
echo "$FILE_PATH" >> "$SESSION_FILE" 2>/dev/null || true
WRITE_COUNT=$(wc -l < "$SESSION_FILE" 2>/dev/null || echo 0)

# Every 10 writes, run cross-file axiom check via local LLM
if [ "$WRITE_COUNT" -gt 0 ] && [ $((WRITE_COUNT % 10)) -eq 0 ]; then
  # Collect first 30 lines of each unique file written this session
  CONTEXT=""
  SEEN=""
  while IFS= read -r f; do
    # Deduplicate
    case "$SEEN" in *"|$f|"*) continue ;; esac
    SEEN="$SEEN|$f|"
    if [ -f "$f" ]; then
      CONTEXT="${CONTEXT}--- ${f} ---\n$(head -30 "$f" 2>/dev/null || true)\n\n"
    fi
  done < "$SESSION_FILE"

  if [ -n "$CONTEXT" ]; then
    # Advisory check via local model — non-blocking, non-failing
    RESULT="$(printf '%b' "$CONTEXT" | timeout 10 aichat -m local-fast \
      "Do these files, taken together, introduce multi-user scaffolding, authentication, authorization, user management, or collaboration features? Answer only YES or NO with a one-line reason." \
      2>/dev/null || true)"
    if echo "$RESULT" | grep -qi "^YES"; then
      echo "WARNING: Session cross-check detected possible multi-action axiom concern across $WRITE_COUNT file writes." >&2
      echo "Reason: $RESULT" >&2
      echo "Files: $(sort -u "$SESSION_FILE" | tr '\n' ' ')" >&2
    fi
  fi
fi

exit 0

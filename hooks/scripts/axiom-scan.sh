#!/usr/bin/env bash
# axiom-scan.sh — PreToolUse hook for T0 axiom violation detection
# Reads Claude Code hook JSON from stdin, extracts file content being
# written/edited, scans for structural multi-user scaffolding patterns.
# Exit 2 + stderr reason on match. Exit 0 otherwise.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/axiom-patterns.sh"

INPUT="$(cat)"

# Extract content from tool input (Edit: new_string, Write: content, MultiEdit: edits[], NotebookEdit: new_source)
CONTENT="$(echo "$INPUT" | jq -r '
  .tool_input.new_string //
  .tool_input.content //
  .tool_input.new_content //
  .tool_input.new_source //
  ([.tool_input.edits[]?.new_string // empty] | join("\n")) //
  empty
' 2>/dev/null || true)"

# Nothing to scan
if [ -z "$CONTENT" ]; then
  exit 0
fi

FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // "unknown"' 2>/dev/null || echo unknown)"

# Skip scanning axiom enforcement files themselves (pattern definitions)
# and the regression-test fixtures that exercise those patterns. The
# tests must contain the very strings the hook looks for in order to
# verify it fires; without this exemption the hook would prevent
# itself from being tested.
case "$FILE_PATH" in
  *axiom-patterns.sh|*axiom-scan.sh|*axiom-commit-scan.sh)
    exit 0
    ;;
  *tests/hooks/test_axiom_scan.py|*tests/hooks/test_axiom_commit_scan.py|*tests/hooks/test_axiom_patterns.py)
    exit 0
    ;;
esac

# Determine if file is documentation (markdown, text, rst)
IS_DOC=false
case "$FILE_PATH" in
  *.md|*.txt|*.rst|*.adoc) IS_DOC=true ;;
esac

# Strip comments before scanning (full-line and trailing inline comments)
SCANNABLE="$(echo "$CONTENT" | sed -E \
  -e 's/^[[:space:]]*#[^!].*$//' \
  -e 's/[[:space:]]#[[:space:]].*$//' \
  -e 's/^[[:space:]]*\/\/.*$//' \
  -e 's/[[:space:]]\/\/[[:space:]].*$//' \
  -e 's/<!--.*-->//' \
  -e '/^[[:space:]]*$/d')"

# If stripping left nothing, skip
if [ -z "$SCANNABLE" ]; then
  exit 0
fi

for pattern in "${AXIOM_PATTERNS[@]}"; do
  # Skip class-name patterns for doc files (false positives on prose examples)
  if $IS_DOC; then
    case "$pattern" in
      'class '*) continue ;;
    esac
  fi

  MATCHED="$(echo "$SCANNABLE" | grep -Ei "$pattern" 2>/dev/null | head -1 || true)"
  if [ -n "$MATCHED" ]; then
    MATCHED="$(echo "$MATCHED" | sed 's/^[[:space:]]*//')"
    # Identify which axiom domain the pattern belongs to
    case "$pattern" in
      *feedback*|*to_say*|*FeedbackGenerator*|*CoachingRecommender*)
        DOMAIN="management_governance"
        IMPLS="mg-boundary-001, mg-boundary-002"
        DESC="This generates feedback/coaching language prohibited by management governance."
        RECOVERY="Keep the data aggregation but remove generated language. Surface patterns and open loops; let the operator formulate their own words."
        ;;
      *)
        DOMAIN="single_user"
        IMPLS="su-auth-001, su-feature-001, su-privacy-001, su-security-001, su-admin-001"
        DESC="This introduces multi-user scaffolding prohibited by axiom governance."
        # Sub-categorize recovery hint
        case "$pattern" in
          *[Aa]uth*|*[Pp]ermission*|*[Rr]ole*|*authenticate*|*authorize*|*login*|*logout*)
            RECOVERY="Remove auth/permission/role code entirely. The single user is always authorized. If protecting a dangerous operation, use a confirmation prompt instead."
            ;;
          *[Uu]ser*|*[Tt]enant*|*[Mm]ulti*)
            RECOVERY="Remove user/tenant abstraction. Reference the operator directly or use config values. There is exactly one user."
            ;;
          *[Ss]haring*|*[Cc]ollab*)
            RECOVERY="Remove sharing/collaboration features. If the goal is data export, implement direct file export instead."
            ;;
          *)
            RECOVERY="Remove the multi-user scaffolding. If the underlying goal is valid, reimplement assuming a single operator with full access."
            ;;
        esac
        ;;
    esac
    echo "Axiom violation (T0/$DOMAIN): pattern matched in $FILE_PATH" >&2
    echo "Matched: $MATCHED" >&2
    echo "$DESC" >&2
    echo "Relevant T0 implications: $IMPLS" >&2
    echo "Recovery: $RECOVERY" >&2

    ENFORCEMENT_DIR="/dev/shm/hapax-governance"
    mkdir -p "$ENFORCEMENT_DIR" 2>/dev/null || true
    TOOL_NAME="$(echo "$INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null || echo unknown)"
    TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"event_type":"axiom_blocked","timestamp":"%s","hook":"axiom-scan","domain":"%s","pattern":"%s","matched":"%s","file_path":"%s","description":"%s","recovery":"%s","tool":"%s"}\n' \
      "$TS" "$DOMAIN" "$(echo "$pattern" | sed 's/"/\\"/g')" "$(echo "$MATCHED" | sed 's/"/\\"/g')" \
      "$(echo "$FILE_PATH" | sed 's/"/\\"/g')" "$(echo "$DESC" | sed 's/"/\\"/g')" \
      "$(echo "$RECOVERY" | sed 's/"/\\"/g')" "$TOOL_NAME" \
      >> "$ENFORCEMENT_DIR/enforcement.jsonl" 2>/dev/null || true

    exit 2
  fi
done

exit 0

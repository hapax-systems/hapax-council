#!/usr/bin/env bash
# axiom-commit-scan.sh — PreToolUse hook for Bash tool
# Detects git commit/push commands and scans staged/branch diff for T0 violations.
# Exit 2 if violations found, exit 0 otherwise.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/axiom-patterns.sh"

INPUT="$(cat)"

COMMAND="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"

# Only interested in monitored commands
if [ -z "$COMMAND" ]; then
  exit 0
fi

# Detect git commit
if echo "$COMMAND" | grep -qE '\bgit\s+commit\b'; then
  DIFF="$(git diff --cached 2>/dev/null || true)"
  if [ -z "$DIFF" ]; then
    exit 0
  fi
  ADDED_LINES="$(echo "$DIFF" | grep '^+[^+]' | sed 's/^+//' || true)"

# Detect git push
elif echo "$COMMAND" | grep -qE '\bgit\s+push\b'; then
  BASE="$(git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null || true)"
  if [ -z "$BASE" ]; then
    exit 0
  fi
  DIFF="$(git diff "$BASE"...HEAD 2>/dev/null || true)"
  if [ -z "$DIFF" ]; then
    exit 0
  fi
  ADDED_LINES="$(echo "$DIFF" | grep '^+[^+]' | sed 's/^+//' || true)"

# Detect Bash file-writing commands (bypass protection)
elif echo "$COMMAND" | grep -qE '(sed\s+-i|tee\s|>\s|python\s+-c|perl\s+-[ip])'; then
  ADDED_LINES="$COMMAND"

# Detect curl/wget to non-localhost (corporate_boundary advisory)
elif echo "$COMMAND" | grep -qE '\b(curl|wget)\b'; then
  URL="$(echo "$COMMAND" | grep -oE 'https?://[^[:space:]"'"'"']+' | head -1)"
  if [ -z "$URL" ]; then
    exit 0
  fi
  # Allow localhost/127.0.0.1
  if echo "$URL" | grep -qE '^https?://(localhost|127\.0\.0\.1)'; then
    exit 0
  fi
  # Check if current directory has corporate_boundary marker
  if [ -f ".corporate-boundary" ]; then
    echo "Axiom advisory (T1/corporate_boundary): External API call detected" >&2
    echo "URL: $URL" >&2
    echo "Corporate boundary axiom requires sanctioned providers only (OpenAI, Anthropic)." >&2
    echo "If this is intentional, ensure the endpoint is employer-approved." >&2
  fi
  # Advisory only — never block
  exit 0

else
  # Not a monitored command — pass through
  exit 0
fi

if [ -z "$ADDED_LINES" ]; then
  exit 0
fi

# Strip comments before scanning (full-line and trailing inline comments)
ADDED_LINES="$(echo "$ADDED_LINES" | sed -E \
  -e 's/^[[:space:]]*#[^!].*$//' \
  -e 's/[[:space:]]#[[:space:]].*$//' \
  -e 's/^[[:space:]]*\/\/.*$//' \
  -e 's/[[:space:]]\/\/[[:space:]].*$//' \
  -e 's/<!--.*-->//' \
  -e '/^[[:space:]]*$/d')"

if [ -z "$ADDED_LINES" ]; then
  exit 0
fi

for pattern in "${AXIOM_PATTERNS[@]}"; do
  MATCHED="$(echo "$ADDED_LINES" | grep -Ei "$pattern" 2>/dev/null | head -1 || true)"
  if [ -n "$MATCHED" ]; then
    MATCHED="$(echo "$MATCHED" | sed 's/^[[:space:]]*//')"
    case "$pattern" in
      *feedback*|*to_say*|*FeedbackGenerator*|*CoachingRecommender*)
        DOMAIN="management_governance"
        DESC="This generates feedback/coaching language prohibited by management governance."
        RECOVERY="Keep the data aggregation but remove generated language. Surface patterns and open loops; let the operator formulate their own words."
        ;;
      *)
        DOMAIN="single_user"
        DESC="This introduces multi-user scaffolding prohibited by axiom governance."
        case "$pattern" in
          *[Aa]uth*|*[Pp]ermission*|*[Rr]ole*|*authenticate*|*authorize*|*login*|*logout*)
            RECOVERY="Remove auth/permission/role code entirely. The single user is always authorized."
            ;;
          *[Uu]ser*|*[Tt]enant*|*[Mm]ulti*)
            RECOVERY="Remove user/tenant abstraction. There is exactly one user."
            ;;
          *[Ss]haring*|*[Cc]ollab*)
            RECOVERY="Remove sharing/collaboration features."
            ;;
          *)
            RECOVERY="Remove the multi-user scaffolding. Reimplement assuming a single operator with full access."
            ;;
        esac
        ;;
    esac
    echo "Axiom violation in staged/branch changes (T0/$DOMAIN):" >&2
    echo "Matched: $MATCHED" >&2
    echo "$DESC" >&2
    echo "Recovery: $RECOVERY" >&2
    exit 2
  fi
done

exit 0

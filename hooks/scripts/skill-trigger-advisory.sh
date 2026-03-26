#!/usr/bin/env bash
# skill-trigger-advisory.sh — PostToolUse hook (advisory, non-blocking)
# Watches Bash command output for patterns and suggests relevant skills.
set -euo pipefail

INPUT="$(cat)" || exit 0
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
OUTPUT="$(echo "$INPUT" | jq -r '.tool_result.stdout // empty' 2>/dev/null)" || exit 0
STDERR_OUT="$(echo "$INPUT" | jq -r '.tool_result.stderr // empty' 2>/dev/null)" || exit 0
COMBINED="${OUTPUT}${STDERR_OUT}"

# /ci-watch — after gh pr create
if echo "$CMD" | grep -qE '\bgh\s+pr\s+create\b'; then
  PR_URL="$(echo "$OUTPUT" | grep -oP 'https://github\.com/\S+/pull/\d+' | head -1)"
  if [ -n "$PR_URL" ]; then
    PR_NUM="$(echo "$PR_URL" | grep -oP '\d+$')"
    echo "SKILL SUGGESTION: PR #${PR_NUM} created. Monitor CI with /ci-watch ${PR_NUM}" >&2
  fi
fi

# /diagnose — after systemctl shows failed
if echo "$CMD" | grep -qE '\bsystemctl\b'; then
  if echo "$COMBINED" | grep -qiE '(failed|inactive \(dead\)|could not be found|start-limit-hit)'; then
    SERVICE="$(echo "$CMD" | grep -oP '(?<=status\s)\S+' | head -1)"
    if [ -n "$SERVICE" ]; then
      echo "SKILL SUGGESTION: Service issue detected. Run /diagnose ${SERVICE}" >&2
    else
      echo "SKILL SUGGESTION: Systemd failure detected. Run /diagnose to investigate." >&2
    fi
  fi
fi

# /vram — after OOM or CUDA errors
if echo "$COMBINED" | grep -qiE '(out of memory|CUDA out of memory|OOM|RuntimeError.*memory)'; then
  echo "SKILL SUGGESTION: GPU memory issue detected. Run /vram to analyze usage." >&2
fi

# /disk-triage — after "No space left on device"
if echo "$COMBINED" | grep -qiE '(no space left on device|disk quota exceeded|ENOSPC)'; then
  echo "SKILL SUGGESTION: Disk space exhausted. Run /disk-triage for emergency cleanup." >&2
fi

# /conflict-resolve — after git operations showing conflicts
if echo "$CMD" | grep -qE '\bgit\s+(merge|rebase|cherry-pick|stash\s+apply)\b'; then
  if echo "$COMBINED" | grep -qE '(CONFLICT|Merge conflict|conflict marker)'; then
    echo "SKILL SUGGESTION: Merge conflicts detected. Run /conflict-resolve to fix." >&2
  fi
fi

# /deploy-check — before git push (advisory)
if echo "$CMD" | grep -qE '\bgit\s+push\b' && ! echo "$CMD" | grep -qE '\-\-dry\-run'; then
  echo "SKILL SUGGESTION: Pushing to remote. Consider running /deploy-check first." >&2
fi

# /ingest — after qdrant errors
if echo "$COMBINED" | grep -qiE '(qdrant.*error|collection.*not found|embedding.*failed)'; then
  echo "SKILL SUGGESTION: RAG/Qdrant issue detected. Run /ingest to check pipeline." >&2
fi

# /status — after docker issues
if echo "$CMD" | grep -qE '\bdocker\s+(compose|container)\b' && echo "$COMBINED" | grep -qiE '(error|unhealthy|restarting)'; then
  echo "SKILL SUGGESTION: Container issue detected. Run /status for full health check." >&2
fi

# /studio — after MIDI/audio errors
if echo "$COMBINED" | grep -qiE '(aconnect.*error|snd.*error|ALSA.*error|midi.*fail)'; then
  echo "SKILL SUGGESTION: Audio/MIDI issue detected. Run /studio to check infrastructure." >&2
fi

# /axiom-review — after agent runs that may create precedents
if echo "$CMD" | grep -qE 'uv run python -m agents\.'; then
  if [ -d "$HOME/.cache/logos/precedents" ]; then
    LAST_REVIEWED="$HOME/.cache/logos/.last-reviewed"
    if [ -f "$LAST_REVIEWED" ]; then
      PENDING=$(find "$HOME/.cache/logos/precedents/" -name "*.json" -newer "$LAST_REVIEWED" 2>/dev/null | wc -l)
    else
      PENDING=$(find "$HOME/.cache/logos/precedents/" -name "*.json" 2>/dev/null | wc -l)
    fi
    if [ "$PENDING" -gt 0 ]; then
      echo "SKILL SUGGESTION: ${PENDING} new axiom precedent(s) after agent run. Run /axiom-review." >&2
    fi
  fi
fi

exit 0

#!/usr/bin/env bash
# session-context.sh — SessionStart hook for hapax-system plugin
# Injects system state summary into Claude Code context.
# Injects system state summary into Claude Code context at session start.

echo '## System Context'

# Axiom status
AXIOM_COUNT="4"
AXIOM_NAMES="single_user, executive_function, corporate_boundary, management_governance"
if [ -d "$HOME/projects/hapax-council" ]; then
  RESULT="$(cd "$HOME/projects/hapax-council" && python3 -c "
import sys; sys.path.insert(0, '.')
from shared.axiom_registry import load_axioms
axs=load_axioms()
print('%d|%s' % (len(axs), ', '.join(a.id for a in axs)))
" 2>/dev/null || true)"
  if [ -n "$RESULT" ]; then
    AXIOM_COUNT="$(echo "$RESULT" | cut -d'|' -f1)"
    AXIOM_NAMES="$(echo "$RESULT" | cut -d'|' -f2)"
  fi
fi
echo "Axioms: $AXIOM_COUNT loaded ($AXIOM_NAMES)"

# Git context (worktree-aware)
GIT_DIR="$(git rev-parse --git-dir 2>/dev/null || true)"
GIT_COMMON="$(git rev-parse --git-common-dir 2>/dev/null || true)"
BRANCH="$(git branch --show-current 2>/dev/null || echo 'detached')"
LAST_COMMIT="$(git log --oneline -1 2>/dev/null || echo 'N/A')"

GIT_DIR_ABS=""
GIT_COMMON_ABS=""
if [ -n "$GIT_DIR" ] && [ -n "$GIT_COMMON" ]; then
  GIT_DIR_ABS="$(cd "$(dirname "$GIT_DIR")" && realpath "$(basename "$GIT_DIR")" 2>/dev/null || echo "$GIT_DIR")"
  GIT_COMMON_ABS="$(cd "$(dirname "$GIT_COMMON")" && realpath "$(basename "$GIT_COMMON")" 2>/dev/null || echo "$GIT_COMMON")"

  if [ "$GIT_DIR_ABS" != "$GIT_COMMON_ABS" ]; then
    PRIMARY_ROOT="$(dirname "$GIT_COMMON_ABS")"
    echo "Worktree: $BRANCH (linked to $PRIMARY_ROOT) | $LAST_COMMIT"
  else
    echo "Primary worktree ($BRANCH) | $LAST_COMMIT"
  fi
else
  echo "Branch: $BRANCH | Last commit: $LAST_COMMIT"
fi

# Active worktrees (only if more than one exists)
WT_COUNT="$(git worktree list 2>/dev/null | wc -l)"
if [ "$WT_COUNT" -gt 1 ]; then
  echo "Worktrees ($WT_COUNT):"
  git worktree list 2>/dev/null | while read -r path commit branch; do
    branch="${branch#[}"
    branch="${branch%]}"
    echo "  $path [$branch]"
  done
fi

# Concurrent Claude sessions in same repo
if [ -n "$GIT_COMMON_ABS" ]; then
  CONCURRENT=""
  CONCURRENT_COUNT=0
  MY_CLAUDE_PID="$PPID"

  while IFS= read -r pid; do
    [ "$pid" = "$MY_CLAUDE_PID" ] && continue
    cwd="$(readlink /proc/"$pid"/cwd 2>/dev/null)" || continue
    their_common="$(cd "$cwd" && git rev-parse --git-common-dir 2>/dev/null)" || continue
    their_common="$(realpath "$their_common" 2>/dev/null)"
    if [ "$their_common" = "$GIT_COMMON_ABS" ]; then
      their_branch="$(cd "$cwd" && git branch --show-current 2>/dev/null || echo 'detached')"
      CONCURRENT="${CONCURRENT}  PID $pid: $cwd [$their_branch]\n"
      CONCURRENT_COUNT=$((CONCURRENT_COUNT + 1))
    fi
  done < <(pgrep -af 'claude-code/bin/claude|/\.local/bin/claude' 2>/dev/null | awk '{print $1}')

  if [ "$CONCURRENT_COUNT" -gt 0 ]; then
    echo "CONCURRENT SESSIONS ($CONCURRENT_COUNT other):"
    printf "$CONCURRENT"

    # Same-branch conflict warning
    SAME_BRANCH=0
    while IFS= read -r pid; do
      [ "$pid" = "$MY_CLAUDE_PID" ] && continue
      cwd="$(readlink /proc/"$pid"/cwd 2>/dev/null)" || continue
      their_common="$(cd "$cwd" && git rev-parse --git-common-dir 2>/dev/null)" || continue
      their_common="$(realpath "$their_common" 2>/dev/null)"
      if [ "$their_common" = "$GIT_COMMON_ABS" ]; then
        their_branch="$(cd "$cwd" && git branch --show-current 2>/dev/null)"
        [ "$their_branch" = "$BRANCH" ] && SAME_BRANCH=$((SAME_BRANCH + 1))
      fi
    done < <(pgrep -af 'claude-code/bin/claude|/\.local/bin/claude' 2>/dev/null | awk '{print $1}')
    if [ "$SAME_BRANCH" -gt 0 ]; then
      echo "WARNING: $SAME_BRANCH other session(s) on branch '$BRANCH' — high conflict risk"
    fi
  fi
fi

# Health summary (from latest health-history.jsonl entry)
HEALTH_FILE="$HOME/projects/hapax-council/profiles/health-history.jsonl"
if [ -f "$HEALTH_FILE" ]; then
  LATEST="$(tail -1 "$HEALTH_FILE" 2>/dev/null || true)"
  if [ -n "$LATEST" ]; then
    STATUS="$(echo "$LATEST" | jq -r '.status // "unknown"' 2>/dev/null || echo unknown)"
    HEALTHY="$(echo "$LATEST" | jq -r '.healthy // 0' 2>/dev/null || echo 0)"
    TOTAL="$(echo "$LATEST" | jq -r '(.healthy + .degraded + .failed) // 0' 2>/dev/null || echo 0)"
    TS="$(echo "$LATEST" | jq -r '.timestamp // ""' 2>/dev/null || true)"
    echo "Health: $HEALTHY/$TOTAL $STATUS | Last run: ${TS:0:16}"
  fi
fi

# Drift summary (from latest drift-report.json)
DRIFT_REPORT="$HOME/projects/hapax-council/profiles/drift-report.json"
if [ -f "$DRIFT_REPORT" ]; then
  DRIFT_LINE="$(jq -r '
    (.drift_items | length) as $total |
    ([.drift_items[] | select(.severity == "high")] | length) as $high |
    if $total == 0 then "Drift: clean"
    else "Drift: \($total) items (\($high) high)"
    end
  ' "$DRIFT_REPORT" 2>/dev/null || true)"
  if [ -n "$DRIFT_LINE" ]; then
    echo "$DRIFT_LINE"
  fi
fi

# Docker containers
RUNNING="$(docker ps --format '{{.Names}}' 2>/dev/null | wc -l || echo 0)"
echo "Docker: $RUNNING containers running"

# GPU
GPU="$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
if [ -n "$GPU" ]; then
  USED="$(echo "$GPU" | awk -F', ' '{print $1}')"
  TOTAL="$(echo "$GPU" | awk -F', ' '{print $2}')"
  echo "GPU: ${USED}/${TOTAL} MiB used"
fi

# Operator profile summary (from distilled manifest)
PROFILE="$HOME/projects/hapax-council/profiles/operator.json"
if [ -f "$PROFILE" ]; then
  PROFILE_LINE="$(jq -r '
    (.goals.primary | map(select(.status == "active")) | length) as $goals |
    (.patterns | keys | join(", ")) as $patterns |
    "Profile: \($goals) active goals | Patterns: \($patterns)"
  ' "$PROFILE" 2>/dev/null || true)"
  if [ -n "$PROFILE_LINE" ]; then
    echo "$PROFILE_LINE"
  fi
fi

# Cycle mode
MODE_FILE="$HOME/.cache/hapax/cycle-mode"
if [ -f "$MODE_FILE" ]; then
  MODE="$(cat "$MODE_FILE" 2>/dev/null | tr -d '[:space:]')"
  if [ "$MODE" = "dev" ] || [ "$MODE" = "prod" ]; then
    MODE_AGE=$(( ($(date +%s) - $(stat -c %Y "$MODE_FILE")) ))
    if [ "$MODE_AGE" -lt 3600 ]; then
      AGE_STR="$((MODE_AGE / 60))min ago"
    elif [ "$MODE_AGE" -lt 86400 ]; then
      AGE_STR="$((MODE_AGE / 3600))h ago"
    else
      AGE_STR="$((MODE_AGE / 86400))d ago"
    fi
    echo "Cycle: $MODE (switched $AGE_STR)"
  fi
else
  echo "Cycle: prod (default)"
fi

# Axiom governance nudge (push-based — surfaces status every session)
PENDING_PRECEDENTS=0
if [ -d "$HOME/.cache/cockpit/precedents" ]; then
  LAST_REVIEWED="$HOME/.cache/cockpit/.last-reviewed"
  if [ -f "$LAST_REVIEWED" ]; then
    PENDING_PRECEDENTS=$(find "$HOME/.cache/cockpit/precedents/" -name "*.json" -newer "$LAST_REVIEWED" 2>/dev/null | wc -l)
  else
    PENDING_PRECEDENTS=$(find "$HOME/.cache/cockpit/precedents/" -name "*.json" 2>/dev/null | wc -l)
  fi
fi
if [ "$PENDING_PRECEDENTS" -gt 0 ]; then
  echo "Axioms: $PENDING_PRECEDENTS precedent(s) pending review (run /axiom-review)"
fi

LAST_SWEEP=$(ls -t "$HOME/.cache/axiom-audit"/baseline-*.json 2>/dev/null | head -1)
if [ -n "$LAST_SWEEP" ]; then
  SWEEP_AGE=$(( ($(date +%s) - $(stat -c %Y "$LAST_SWEEP")) / 86400 ))
  if [ "$SWEEP_AGE" -gt 7 ]; then
    echo "Axioms: Last compliance sweep was ${SWEEP_AGE} days ago (run /axiom-sweep)"
  fi
fi

# Scout recommendations (actionable items from latest horizon scan)
SCOUT_REPORT="$HOME/projects/hapax-council/profiles/scout-report.json"
if [ -f "$SCOUT_REPORT" ]; then
  SCOUT_LINE="$(jq -r '
    (.generated_at // "") as $ts |
    [.recommendations[] | select(.tier == "adopt" or .tier == "evaluate")] as $actionable |
    if ($actionable | length) == 0 then empty
    else
      (now - ($ts | fromdateiso8601)) / 86400 | floor | tostring as $age |
      if ($age | tonumber) > 8 then empty
      else
        ($actionable | group_by(.tier) | map(
          (.[0].tier) + ": " + (map(.component) | join(", "))
        ) | join(", ")) as $items |
        "Scout: \($actionable | length) actionable (\($items)) | \($age)d ago"
      end
    end
  ' "$SCOUT_REPORT" 2>/dev/null || true)"
  if [ -n "$SCOUT_LINE" ]; then
    echo "$SCOUT_LINE"
  fi
fi

# ── Context Restoration (cognitive state) ──

# Last Claude Code interaction in this project
CC_HISTORY="$HOME/.claude/history.jsonl"
if [ -f "$CC_HISTORY" ]; then
  WORK_DIR_ESCAPED="$(pwd | sed 's/[[\.*^$()+?{|\\]/\\&/g')"
  LAST_QUERY="$(tac "$CC_HISTORY" 2>/dev/null | jq -r --arg proj "$WORK_DIR_ESCAPED" 'select(.project | test($proj)) | .display' 2>/dev/null | head -1)"
  if [ -n "$LAST_QUERY" ] && [ "$LAST_QUERY" != "null" ]; then
    # Truncate to 120 chars for display
    if [ ${#LAST_QUERY} -gt 120 ]; then
      LAST_QUERY="${LAST_QUERY:0:117}..."
    fi
    echo "Last query: $LAST_QUERY"
  fi
fi

# Next meeting from calendar
if [ -d "$HOME/projects/hapax-council" ]; then
  NEXT_MTG="$(cd "$HOME/projects/hapax-council" && python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from shared.calendar_context import CalendarContext
    ctx = CalendarContext()
    mtgs = ctx.meetings_in_range(days=1)
    if mtgs:
        m = mtgs[0]
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(m.start.replace('Z', '+00:00'))
            t = dt.strftime('%H:%M')
        except Exception:
            t = m.start
        att = f' — {', '.join(m.attendees[:2])}' if m.attendees else ''
        print(f'{t} {m.summary} ({m.duration_minutes}min){att}')
    else:
        print('')
except Exception:
    print('')
" 2>/dev/null || true)"
  if [ -n "$NEXT_MTG" ]; then
    echo "Next meeting: $NEXT_MTG"
  fi
fi

# Open PRs in this repo
OPEN_PRS="$(gh pr list --state open --json number,title,headRefName 2>/dev/null | jq -r 'length' 2>/dev/null || echo 0)"
if [ "$OPEN_PRS" -gt 0 ] && [ "$OPEN_PRS" != "null" ]; then
  PR_SUMMARY="$(gh pr list --state open --json number,title --jq '.[] | "#\(.number) \(.title)"' 2>/dev/null | head -3)"
  echo "Open PRs ($OPEN_PRS):"
  echo "$PR_SUMMARY" | while read -r line; do echo "  $line"; done
fi

# Seed auto-memory directory if missing
WORK_DIR="$(pwd)"
SANITIZED="$(echo "$WORK_DIR" | sed 's|/|-|g; s|^-||')"
MEMORY_DIR="$HOME/.claude/projects/-${SANITIZED}/memory"
if [ ! -d "$MEMORY_DIR" ]; then
  mkdir -p "$MEMORY_DIR"
  # Seed from repo's CLAUDE.md Project Memory section if it exists
  CLAUDE_MD="$WORK_DIR/CLAUDE.md"
  if [ -f "$CLAUDE_MD" ] && grep -q '## Project Memory' "$CLAUDE_MD"; then
    awk '/^## Project Memory/{found=1} found{if(/^## / && !/^## Project Memory/)exit; print}' "$CLAUDE_MD" > "$MEMORY_DIR/MEMORY.md"
  else
    printf '# Project Memory\n\nNo project memory seeded yet. Add a `## Project Memory` section to CLAUDE.md.\n' > "$MEMORY_DIR/MEMORY.md"
  fi
fi

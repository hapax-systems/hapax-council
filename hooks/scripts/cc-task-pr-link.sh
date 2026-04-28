#!/usr/bin/env bash
# cc-task-pr-link.sh — PostToolUse hook for Bash (PR3 / H8 of cc-hygiene)
#
# When a session runs `gh pr create` and gh prints the new PR URL, this
# hook locates the active vault cc-task note and rewrites its frontmatter:
#   pr: N         — the new PR number
#   branch: ...   — the head branch the PR was opened from
#   status: pr_open
# and appends a Session-log line documenting the auto-link.
#
# Idempotent — if the active task already has a non-empty `pr:` value,
# the hook is a no-op (so re-runs don't double-write or clobber a manual
# value).
#
# Graceful — exits 0 with a stderr log line on every soft failure
# (no claim file, no PR URL in output, vault note missing, etc.).
# A PostToolUse hook MUST never block Bash invocations.
#
# Killswitch: HAPAX_CC_HYGIENE_OFF=1 (shared with PR1 sweeper + H9 watcher).
#
# Tested via tests/test_cc_task_pr_link_hook.py.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/agent-role.sh" ]]; then
  # shellcheck source=agent-role.sh
  # shellcheck disable=SC1091
  . "$SCRIPT_DIR/agent-role.sh"
fi

# --- 1. Killswitch (shared with PR1 sweeper) ---
if [[ "${HAPAX_CC_HYGIENE_OFF:-0}" == "1" ]]; then
  exit 0
fi

# --- 2. Read tool invocation from stdin ---
input="$(cat || true)"
if [[ -z "$input" ]]; then
  exit 0
fi

tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")"
[[ "$tool_name" == "Bash" ]] || exit 0

# --- 3. Match `gh pr create` invocation ---
bash_cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")"
if [[ -z "$bash_cmd" ]]; then
  exit 0
fi
case "$bash_cmd" in
  *"gh pr create"*) ;;
  *) exit 0 ;;
esac

# --- 4. Pull tool output (PostToolUse provides .tool_response in JSON,
#       Claude Code also exports CLAUDE_TOOL_OUTPUT for a subset of
#       integrations). Try both. ---
tool_output="$(printf '%s' "$input" | jq -r '.tool_response.output // .tool_response.stdout // .tool_response // empty' 2>/dev/null || echo "")"
if [[ -z "$tool_output" ]]; then
  tool_output="${CLAUDE_TOOL_OUTPUT:-}"
fi
if [[ -z "$tool_output" ]]; then
  echo "cc-task-pr-link: no tool output to parse, skipping" >&2
  exit 0
fi

# --- 5. Extract PR number from a github.com pull URL.
#       Pattern: https://github.com/<owner>/<repo>/pull/<N>
#       gh pr create prints the URL on its own line; we take the first match. ---
pr_url="$(printf '%s' "$tool_output" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -n1 || true)"
if [[ -z "$pr_url" ]]; then
  echo "cc-task-pr-link: no PR URL in output, skipping" >&2
  exit 0
fi
pr_number="$(printf '%s' "$pr_url" | sed -E 's#.*/pull/([0-9]+)$#\1#')"
if [[ -z "$pr_number" ]]; then
  echo "cc-task-pr-link: could not parse PR number from URL '$pr_url'" >&2
  exit 0
fi

# --- 6. Determine session role ---
role=""
for candidate in "${CLAUDE_ROLE:-}" "${HAPAX_AGENT_SLOT:-}" "${HAPAX_WORKTREE_ROLE:-}" "${HAPAX_AGENT_ROLE:-}" "${CODEX_ROLE:-}"; do
  case "$candidate" in
    alpha|beta|gamma|delta|epsilon)
      role="$candidate"
      break
      ;;
  esac
done
if [[ -n "$role" && ! -f "$HOME/.cache/hapax/cc-active-task-$role" ]]; then
  claim_candidates=()
  for r in alpha beta gamma delta epsilon; do
    f="$HOME/.cache/hapax/cc-active-task-$r"
    if [[ -f "$f" ]]; then
      claim_candidates+=("$r")
    fi
  done
  if [[ ${#claim_candidates[@]} -eq 1 ]]; then
    role="${claim_candidates[0]}"
  fi
fi
if [[ -z "$role" ]]; then
  # Same fallback as cc-task-gate: if exactly one relay yaml exists, use it.
  relay_dir="$HOME/.cache/hapax/relay"
  if [[ -d "$relay_dir" ]]; then
    candidates=()
    for r in alpha beta delta epsilon; do
      f="$relay_dir/$r.yaml"
      if [[ -f "$f" ]]; then
        candidates+=("$r")
      fi
    done
    if [[ ${#candidates[@]} -eq 1 ]]; then
      role="${candidates[0]}"
    fi
  fi
fi
if [[ -z "$role" ]] && declare -F hapax_agent_worktree_role >/dev/null 2>&1; then
  role="$(hapax_agent_worktree_role 2>/dev/null || true)"
fi
if [[ -z "$role" ]] && declare -F hapax_agent_role >/dev/null 2>&1; then
  role="$(hapax_agent_role 2>/dev/null || true)"
fi
if [[ -z "$role" ]]; then
  echo "cc-task-pr-link: cannot determine role; skipping" >&2
  exit 0
fi

# --- 7. Read claim file ---
claim_file="$HOME/.cache/hapax/cc-active-task-$role"
if [[ ! -f "$claim_file" ]]; then
  echo "cc-task-pr-link: no active claim for role '$role', skipping link" >&2
  exit 0
fi
task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
if [[ -z "$task_id" ]]; then
  echo "cc-task-pr-link: claim file empty for role '$role'" >&2
  exit 0
fi

# --- 8. Locate vault note ---
vault_root="$HOME/Documents/Personal/20-projects/hapax-cc-tasks"
note_path=""
for candidate in "$vault_root/active/$task_id-"*.md; do
  if [[ -f "$candidate" ]]; then
    note_path="$candidate"
    break
  fi
done
if [[ -z "$note_path" ]] && [[ -f "$vault_root/active/$task_id.md" ]]; then
  note_path="$vault_root/active/$task_id.md"
fi
if [[ -z "$note_path" ]]; then
  echo "cc-task-pr-link: vault note for '$task_id' not found in $vault_root/active/" >&2
  exit 0
fi

# --- 9. Determine branch name (best effort; fall back to "unknown") ---
branch_name=""
if command -v git &>/dev/null; then
  branch_name="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
fi
if [[ -z "$branch_name" ]] || [[ "$branch_name" == "HEAD" ]]; then
  branch_name="unknown"
fi

# --- 10. Rewrite frontmatter (idempotent: skip if pr already set) ---
if ! command -v python3 &>/dev/null; then
  echo "cc-task-pr-link: python3 missing; cannot rewrite frontmatter" >&2
  exit 0
fi

set +e
python3 - "$note_path" "$pr_number" "$branch_name" "$role" "$pr_url" <<'PYEOF'
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

note_path, pr_number, branch_name, role, pr_url = (
    Path(sys.argv[1]),
    sys.argv[2],
    sys.argv[3],
    sys.argv[4],
    sys.argv[5],
)
text = note_path.read_text(encoding="utf-8")

# Idempotency: if `pr:` already has a non-null/non-empty value, no-op.
m = re.search(r"^pr:\s*(.*)$", text, flags=re.MULTILINE)
if m:
    existing = m.group(1).strip()
    if existing and existing.lower() not in ("null", "none", "~", '""', "''"):
        # Already linked — preserve existing value, exit silently.
        sys.exit(0)

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Replace pr / branch / status frontmatter lines (single-substitution each).
def _replace_or_insert(body: str, key: str, value: str) -> str:
    pattern = rf"^{re.escape(key)}:\s*.*$"
    new_line = f"{key}: {value}"
    if re.search(pattern, body, flags=re.MULTILINE):
        return re.sub(pattern, new_line, body, count=1, flags=re.MULTILINE)
    # No existing key — insert before the closing frontmatter `---` line.
    fm_close = re.search(r"^---\s*$", body, flags=re.MULTILINE)
    if fm_close:
        # Look for the SECOND `---` (closing fence). The first `---` is at index 0.
        matches = list(re.finditer(r"^---\s*$", body, flags=re.MULTILINE))
        if len(matches) >= 2:
            close_idx = matches[1].start()
            return body[:close_idx] + new_line + "\n" + body[close_idx:]
    return body

text = _replace_or_insert(text, "pr", str(pr_number))
text = _replace_or_insert(text, "branch", branch_name)
text = _replace_or_insert(text, "status", "pr_open")
text = _replace_or_insert(text, "updated_at", now)

# Append annex line under "## Session log" if present.
log_line = (
    f"- {now} {role} auto-linked PR #{pr_number} ({pr_url}) "
    f"branch={branch_name} via cc-task-pr-link hook\n"
)
if "## Session log" in text:
    text = text.replace("## Session log\n", f"## Session log\n{log_line}", 1)
else:
    # No section — append a fresh one at end of file.
    text = text.rstrip() + "\n\n## Session log\n\n" + log_line

# Atomic write.
tmp = note_path.with_suffix(note_path.suffix + ".tmp")
tmp.write_text(text, encoding="utf-8")
tmp.replace(note_path)
print(f"cc-task-pr-link: linked task '{note_path.stem}' to PR #{pr_number}")
PYEOF
py_rc=$?
set -e
if [[ "$py_rc" -ne 0 ]]; then
  echo "cc-task-pr-link: python rewrite failed (rc=$py_rc); not blocking" >&2
fi

exit 0

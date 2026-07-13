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
# Idempotent — if the active task already has a different non-empty `pr:`
# value, the hook is a no-op so it never clobbers a manual link. If the
# existing value already matches the PR just created, the hook still advances
# the task to `status: pr_open`; pre-populated PR numbers should not leave
# ready PRs stuck in `claimed`.
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

shell_is_gh_pr_create() {
  local cmd="$1"
  python3 - "$cmd" <<'PYEOF' 2>/dev/null
import shlex
import sys

cmd = sys.argv[1]
try:
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    tokens = list(lexer)
except (TypeError, ValueError):
    tokens = (
        cmd.replace("&&", " && ")
        .replace("||", " || ")
        .replace(";", " ; ")
        .replace("|", " | ")
        .replace("(", " ( ")
        .replace(")", " ) ")
        .split()
    )

separators = {"&&", "||", ";", ";;", ";&", ";;&", "|", "(", ")"}


def base(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def gh_pr_create_at(index: int) -> bool:
    j = index + 1
    while j < len(tokens):
        tok = tokens[j]
        if tok in separators:
            return False
        if tok in {"-R", "--repo", "--hostname", "--config-dir"}:
            j += 2
            continue
        if tok.startswith(("--repo=", "--hostname=", "--config-dir=")):
            j += 1
            continue
        if tok.startswith("-"):
            j += 1
            continue
        return tok == "pr" and j + 1 < len(tokens) and tokens[j + 1] == "create"
    return False


for i, token in enumerate(tokens):
    if base(token) == "gh" and gh_pr_create_at(i):
        sys.exit(0)
sys.exit(1)
PYEOF
}

# --- 3. Match PR creation invocation ---
bash_cmd=""
case "$tool_name" in
  Bash)
    bash_cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")"
    [[ -n "$bash_cmd" ]] || exit 0
    shell_is_gh_pr_create "$bash_cmd" || exit 0
    ;;
  mcp__github__create_pull_request)
    ;;
  *)
    exit 0
    ;;
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
pr_url="$(printf '%s' "$tool_output" | grep -m1 -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' || true)"
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
# Resolve via the single resolver FIRST. This closes the cc-* gap: the legacy scans
# below only match greek alpha-epsilon + cx-*, so cc-*/vbe-*/antigrav lanes stranded
# at status 'claimed' (the PR never auto-linked). hapax_effective_role returns the
# session's actual role (cc-omnigent, cc-compstrat, ...); the scans below remain as a
# fallback for sessions where the resolver is empty/unavailable.
if declare -F hapax_effective_role >/dev/null 2>&1; then
  role="$(hapax_effective_role 2>/dev/null || true)"
fi
claim_exists_for_role() {
  local candidate="${1:-}"
  [[ -n "$candidate" && -f "$HOME/.cache/hapax/cc-active-task-$candidate" ]]
}

# Codex lanes have their own cc-active-task-cx-* claim files. Prefer an active
# Codex lane claim over inherited Claude slot variables from the parent shell.
for candidate in \
  "${HAPAX_AGENT_NAME:-}" \
  "${CODEX_THREAD_NAME:-}" \
  "${CODEX_SESSION_NAME:-}" \
  "${CODEX_SESSION:-}" \
  "${CODEX_ROLE:-}" \
  "${HAPAX_AGENT_ROLE:-}" \
  "${CLAUDE_ROLE:-}"; do
  case "$candidate" in
    cx-*)
      if claim_exists_for_role "$candidate"; then
        role="$candidate"
        break
      fi
      ;;
  esac
done

if [[ -z "$role" ]]; then
  for candidate in \
    "${HAPAX_AGENT_SLOT:-}" \
    "${HAPAX_WORKTREE_ROLE:-}" \
    "${HAPAX_AGENT_ROLE:-}" \
    "${CODEX_ROLE:-}" \
    "${CLAUDE_ROLE:-}"; do
    case "$candidate" in
      alpha|beta|gamma|delta|epsilon)
        if claim_exists_for_role "$candidate"; then
          role="$candidate"
          break
        fi
        ;;
    esac
  done
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

# --- 10. Rewrite frontmatter (idempotent: never overwrite a different PR) ---
if ! command -v python3 &>/dev/null; then
  echo "cc-task-pr-link: python3 missing; cannot rewrite frontmatter" >&2
  exit 0
fi

set +e
python3 - "$note_path" "$pr_number" "$branch_name" "$role" "$pr_url" \
  "$SCRIPT_DIR/../.." "$HOME/.cache/hapax" "$vault_root" <<'PYEOF'
import hashlib
import re
import stat
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
repo_root = Path(sys.argv[6]).resolve()
cache_dir = Path(sys.argv[7])
vault_root = Path(sys.argv[8])
sys.path.insert(0, str(repo_root))

from shared.sdlc_filesystem_transaction import (  # noqa: E402
    FileMutation,
    execute_filesystem_transaction,
)

metadata = note_path.lstat()
if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
    raise ValueError("task note is not a regular file")
raw = note_path.read_bytes()
text = raw.decode("utf-8")

# Idempotency: if `pr:` already has a different non-null/non-empty value, no-op.
# A matching existing value is safe and should still drive the status/branch/log
# transition. This covers sessions that pre-populate `pr:` before the PostToolUse
# hook observes `gh pr create`.
m = re.search(r"^pr:\s*(.*)$", text, flags=re.MULTILINE)
if m:
    existing = m.group(1).strip()
    if existing and existing.lower() not in ("null", "none", "~", '""', "''"):
        if existing != str(pr_number):
            # Already linked to another PR — preserve existing value, exit silently.
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

# The PostToolUse hook is an official task-note writer. Use the same stable
# ownership journal and target lock as cc-close so a concurrent move cannot be
# overwritten by recreating the stale active pathname.
execute_filesystem_transaction(
    cache_dir / "cc-ownership-txn.json",
    (
        FileMutation(
            path=note_path,
            content=text.encode("utf-8"),
            mode=stat.S_IMODE(metadata.st_mode),
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_mode=stat.S_IMODE(metadata.st_mode),
        ),
    ),
    allowed_roots=(cache_dir, vault_root),
)
print(f"cc-task-pr-link: linked task '{note_path.stem}' to PR #{pr_number}")
PYEOF
py_rc=$?
set -e
if [[ "$py_rc" -ne 0 ]]; then
  echo "cc-task-pr-link: python rewrite failed (rc=$py_rc); not blocking" >&2
fi

exit 0

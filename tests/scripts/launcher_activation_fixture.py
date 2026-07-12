"""Source-activation fixture for launcher admission tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_CLAIM_STUB = r"""#!/usr/bin/env bash
set -euo pipefail

delegate="${HAPAX_TEST_DELEGATE_CC_CLAIM:-}"
if [[ -z "$delegate" ]]; then
  case "${HAPAX_AGENT_INTERFACE:-}" in
    codex) delegate="${HAPAX_CODEX_HEADLESS_WORKDIR:-}/scripts/cc-claim" ;;
    claude)
      if [[ -n "${HAPAX_CLAUDE_HEADLESS_WORKDIR:-}" ]]; then
        delegate="$HAPAX_CLAUDE_HEADLESS_WORKDIR/scripts/cc-claim"
      elif [[ -n "${HAPAX_COUNCIL_DIR:-}" ]]; then
        delegate="$HAPAX_COUNCIL_DIR/scripts/cc-claim"
      else
        delegate="$HOME/projects/hapax-council--${HAPAX_AGENT_ROLE:-}/scripts/cc-claim"
      fi
      ;;
    vibe) delegate="${HAPAX_TEST_LAUNCHER_WORKDIR:-}/scripts/cc-claim" ;;
  esac
fi

# The remote protocol belongs to the activated helper. Worktree spies may
# observe ordinary claim/verify calls, but must not fake this boundary.
case "${1:-}" in
  --retire-terminal-projection)
    if [[ -n "${HAPAX_FAKE_CC_CLAIM_RETIRE_LOG:-}" ]]; then
      printf '%s\n' "${2:-}" >> "$HAPAX_FAKE_CC_CLAIM_RETIRE_LOG"
    fi
    exit "${HAPAX_FAKE_CC_CLAIM_RETIRE_RC:-0}"
    ;;
  --print-post-claim-task-sha256)
    printf '%s\n' "${HAPAX_FAKE_POST_CLAIM_TASK_SHA256:-9999999999999999999999999999999999999999999999999999999999999999}"
    exit 0
    ;;
  --materialize-remote-projection)
    task="${2:-}"
    role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
    sid="${HAPAX_SESSION_ID:-}"
    post_sha="${HAPAX_CLAIM_REMOTE_POST_CLAIM_TASK_SHA256:-}"
    [[ -n "$task" && -n "$role" && -n "$sid" && -n "$post_sha" ]] || exit 9
    cache="$HOME/.cache/hapax"
    mkdir -p "$cache"
    for key in "$role" "$role-$sid"; do
      printf '%s\n' "$task" > "$cache/cc-active-task-$key"
      printf '1234567890 %s\n' "$task" > "$cache/cc-claim-epoch-$key"
      printf '{}\n' > "$cache/cc-claim-dispatch-$key.json"
      chmod 600 "$cache/cc-active-task-$key" "$cache/cc-claim-epoch-$key" "$cache/cc-claim-dispatch-$key.json"
    done
    printf '%s\n' "$role" > "$cache/session-role-$sid"
    receipt="$cache/cc-claim-remote-projection-$role-$sid-$post_sha.json"
    printf '{}\n' > "$receipt"
    chmod 600 "$cache/session-role-$sid" "$receipt"
    exit 0
    ;;
esac

if [[ -n "$delegate" && -x "$delegate" && "$(readlink -f "$delegate")" != "$(readlink -f "$0")" ]]; then
  exec "$delegate" "$@"
fi

case "${1:-}" in
  --dispatch-protocol-version)
    printf '%s\n' 'hapax-claim-dispatch-v1'
    exit 0
    ;;
  --verify-dispatch-binding)
    exit "${HAPAX_FAKE_CC_CLAIM_VERIFY_RC:-0}"
    ;;
esac

task="${1:-}"
role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
sid="${HAPAX_SESSION_ID:-}"
[[ -n "$task" && -n "$role" && -n "$sid" ]] || exit 9
cache="$HOME/.cache/hapax"
mkdir -p "$cache"
for key in "$role" "$role-$sid"; do
  printf '%s\n' "$task" > "$cache/cc-active-task-$key"
  printf '1234567890 %s\n' "$task" > "$cache/cc-claim-epoch-$key"
  printf '{}\n' > "$cache/cc-claim-dispatch-$key.json"
done
"""

_REPO_ROOT = Path(__file__).resolve().parents[2]


def install_launcher_activation(home: Path) -> dict[str, str]:
    """Create a receipt-bound Git release and return launcher env overrides."""

    activation = home / ".cache" / "hapax" / "source-activation"
    staging = activation / "releases" / "staging"
    claim = staging / "scripts" / "cc-claim"
    claim.parent.mkdir(parents=True, exist_ok=True)
    claim.write_text(_CLAIM_STUB, encoding="utf-8")
    claim.chmod(0o755)
    shutil.copytree(_REPO_ROOT / "shared", staging / "shared")
    shutil.copytree(_REPO_ROOT / "packages" / "agentgov" / "src" / "agentgov", staging / "agentgov")
    subprocess.run(["git", "init", "-q", str(staging)], check=True)
    subprocess.run(
        ["git", "-C", str(staging), "add", "scripts/cc-claim", "shared", "agentgov"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(staging),
            "-c",
            "user.name=Launcher Test",
            "-c",
            "user.email=launcher-test@example.invalid",
            "commit",
            "-qm",
            "fixture activation",
        ],
        check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(staging), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    release = staging.with_name(head)
    staging.rename(release)
    worktree = activation / "worktree"
    worktree.symlink_to(release)
    receipt = activation / "current.json"
    receipt.write_text(
        json.dumps(
            {
                "active_source_head": head,
                "active_source_path": str(worktree),
                "active_source_target": str(release),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (activation / "last-success-sha").write_text(f"{head}\n", encoding="ascii")
    return {
        "HAPAX_SOURCE_ACTIVATION_WORKTREE": str(worktree),
        "HAPAX_SOURCE_ACTIVATION_RECEIPT": str(receipt),
    }


def activate_launcher_env(env: dict[str, str], home: Path) -> dict[str, str]:
    env.update(install_launcher_activation(home))
    return env


def install_launcher_activation_in_process(home: Path) -> None:
    os.environ.update(install_launcher_activation(home))

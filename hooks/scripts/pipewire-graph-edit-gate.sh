#!/usr/bin/env bash
# pipewire-graph-edit-gate.sh — P3 PreToolUse gate for audio graph files.
#
# Blocks direct Edit/Write/MultiEdit mutations to graph-owned PipeWire and
# WirePlumber conf files unless the session holds the short-lived
# hapax-pipewire-graph applier lease.
#
# This hook does not mutate PipeWire. It only reads the lease JSON at
# ~/.cache/hapax/pipewire-graph/applier.lock.
set -euo pipefail

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || true)"

case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

raw_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // empty' 2>/dev/null || true)"
[[ -n "$raw_path" ]] || exit 0

if [[ "${HAPAX_PIPEWIRE_GRAPH_EDIT_GATE:-1}" == "0" ]]; then
  exit 0
fi
if [[ "${HAPAX_PIPEWIRE_GRAPH_BYPASS:-0}" == "1" ]]; then
  echo "pipewire-graph-edit-gate: BYPASS active for $raw_path" >&2
  exit 0
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
home_dir="${HOME:-$repo_root}"

case "$raw_path" in
  /*) abs_path="$raw_path" ;;
  *) abs_path="$repo_root/$raw_path" ;;
esac

guarded=false
case "$abs_path" in
  "$home_dir"/.config/pipewire/pipewire.conf.d/*.conf) guarded=true ;;
  "$home_dir"/.config/wireplumber/wireplumber.conf.d/*.conf) guarded=true ;;
  "$repo_root"/config/pipewire/*.conf) guarded=true ;;
  "$repo_root"/config/wireplumber/*.conf) guarded=true ;;
esac

if [[ "$guarded" != "true" ]]; then
  exit 0
fi

owner="${HAPAX_AGENT_ROLE:-${HAPAX_AGENT_NAME:-${CODEX_ROLE:-${CODEX_THREAD_NAME:-${CLAUDE_ROLE:-${USER:-unknown}}}}}}"
owner="$(printf '%s' "$owner" | sed -E 's/[^A-Za-z0-9_.@:-]+/-/g; s/^-+//; s/-+$//')"
[[ -n "$owner" ]] || owner="unknown"

lock_root="${HAPAX_PIPEWIRE_GRAPH_LOCK_ROOT:-$home_dir/.cache/hapax/pipewire-graph}"
lock_path="$lock_root/applier.lock"

if [[ ! -f "$lock_path" ]]; then
  cat >&2 <<EOF
BLOCKED: PipeWire graph file edit requires applier lock.
target=$raw_path
owner=$owner
Use: scripts/hapax-pipewire-graph lock --owner "$owner"
Then rerun the edit before the lease expires. This P3 gate keeps graph edits
compiler/validator-mediated and prevents concurrent audio routing churn.
EOF
  exit 2
fi

python3 - "$lock_path" "$owner" "$raw_path" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

lock_path = Path(sys.argv[1])
owner = sys.argv[2]
target = sys.argv[3]
try:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
except Exception as exc:
    print(
        f"BLOCKED: PipeWire graph applier lock is unreadable for {target}: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(2)
if not isinstance(payload, dict):
    print(f"BLOCKED: PipeWire graph applier lock is malformed for {target}", file=sys.stderr)
    raise SystemExit(2)
lock_owner = str(payload.get("owner") or "")
expires_at = str(payload.get("expires_at") or "")
try:
    expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).astimezone(UTC)
except Exception:
    print(f"BLOCKED: PipeWire graph applier lock has invalid expires_at for {target}", file=sys.stderr)
    raise SystemExit(2)
if lock_owner != owner:
    print(
        "BLOCKED: PipeWire graph applier lock held by "
        f"{lock_owner!r}, not {owner!r}. target={target}",
        file=sys.stderr,
    )
    raise SystemExit(2)
if expires <= datetime.now(UTC):
    print(
        f"BLOCKED: PipeWire graph applier lock for {owner!r} expired at {expires_at}. "
        f"target={target}",
        file=sys.stderr,
    )
    raise SystemExit(2)
raise SystemExit(0)
PY

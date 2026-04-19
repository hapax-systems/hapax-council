#!/usr/bin/env bash
# pipewire-baseline-snapshot.sh — capture / diff PipeWire graph against a baseline.
#
# Per audit catalog §4.7: live PipeWire graph drift is hard to detect without
# a known-good baseline. This script either captures today's graph as the
# new baseline OR diffs the current graph against the most recent baseline.
#
# Usage:
#   pipewire-baseline-snapshot.sh capture
#       Save current graph state to docs/research/audio-baselines/YYYY-MM-DD.json
#   pipewire-baseline-snapshot.sh diff [<baseline-date>]
#       Diff current graph vs the named baseline (or the most recent one)
#
# Exit codes:
#   0  — capture OK, OR diff with no drift
#   1  — diff found drift (per-line delta on stderr)
#   2  — usage error / missing tools

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE_DIR="${REPO_ROOT}/docs/research/audio-baselines"

cmd="${1:-}"

usage() {
  echo "Usage: $(basename "$0") capture|diff [<baseline-date>]" >&2
  exit 2
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing tool: $1" >&2; exit 2; }
}

# pw-dump emits the full graph as JSON; we slim to the structural identity
# (node ids may shift across runs but names + types should be stable).
capture_graph() {
  require_tool pw-dump
  require_tool jq
  pw-dump 2>/dev/null | jq -S '
    [ .[]
      | select(.type == "PipeWire:Interface:Node" or .type == "PipeWire:Interface:Link")
      | {
          type: .type,
          name: (.info.props["node.name"] // .info.props["link.id"] // "<unnamed>"),
          media: (.info.props["media.class"] // null),
          target: (.info.props["link.output.node"] // null),
          source: (.info.props["link.input.node"] // null),
        }
    ] | sort_by(.type, .name)
  '
}

case "$cmd" in
  capture)
    mkdir -p "$BASELINE_DIR"
    out="${BASELINE_DIR}/$(date +%F).json"
    capture_graph > "$out"
    nodes=$(jq '[.[] | select(.type | endswith("Node"))] | length' "$out")
    links=$(jq '[.[] | select(.type | endswith("Link"))] | length' "$out")
    echo "captured $nodes nodes + $links links to $out"
    ;;
  diff)
    require_tool diff
    base_arg="${2:-}"
    if [ -n "$base_arg" ]; then
      base_file="${BASELINE_DIR}/${base_arg}.json"
    else
      base_file="$(ls -1 "$BASELINE_DIR"/*.json 2>/dev/null | sort | tail -1)"
    fi
    [ -n "$base_file" ] && [ -f "$base_file" ] || {
      echo "no baseline found in $BASELINE_DIR" >&2
      exit 2
    }
    cur=$(mktemp)
    trap 'rm -f "$cur"' EXIT
    capture_graph > "$cur"
    if diff -u "$base_file" "$cur" >/dev/null 2>&1; then
      echo "no drift vs $(basename "$base_file" .json)"
      exit 0
    fi
    echo "DRIFT vs $(basename "$base_file" .json):" >&2
    diff -u "$base_file" "$cur" >&2 || true
    exit 1
    ;;
  *)
    usage
    ;;
esac

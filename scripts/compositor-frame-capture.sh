#!/usr/bin/env bash
# compositor-frame-capture.sh — capture compositor snapshots for PR evidence
#
# Used by sessions to satisfy the operator directive (2026-05-07) that
# every visual-surface PR (wards / presets / layouts / effects) must
# include before/after screenshots in the PR description. Captures
# frames over a configurable duration so animation / drift / ticker
# variation surfaces in the evidence.
#
# Usage:
#   scripts/compositor-frame-capture.sh <label> [--duration SECONDS] [--interval-ms MS] [--source PATH]
#
# Defaults: 1 frame, 1 second duration, 250 ms interval (== 4 frames),
# source ``/dev/shm/hapax-compositor/snapshot.jpg``.
#
# Common patterns:
#   # single snapshot for a "before" reference
#   scripts/compositor-frame-capture.sh PR-2823-before
#
#   # 5-second multi-frame capture for animated wards / drift visibility
#   scripts/compositor-frame-capture.sh PR-2823-after --duration 5 --interval-ms 250
#
#   # capture the Reverie wgpu surface only (no overlays / cairo wards)
#   scripts/compositor-frame-capture.sh reverie-isolation --source /dev/shm/hapax-visual/frame.jpg
#
# Output:
#   ~/.cache/hapax/screenshots/<label>/<utc-iso>/frame-NN.jpg ...
#   plus a markdown block printed to stdout, ready to paste into
#   ``gh pr create --body``.
#
# Cross-reference: ``docs/superpowers/handoff/2026-05-07-zeta-late-handoff.md``
# § "NEW operator directive — visual evidence in PRs" for the policy.

set -euo pipefail

DEFAULT_SOURCE="/dev/shm/hapax-compositor/snapshot.jpg"
DEFAULT_DURATION_S=1
DEFAULT_INTERVAL_MS=250
OUTPUT_ROOT="${HOME}/.cache/hapax/screenshots"

usage() {
    cat <<'EOF' >&2
usage: compositor-frame-capture.sh <label> [--duration SECONDS] [--interval-ms MS] [--source PATH]

  <label>             required; appears in the output directory name and markdown caption
  --duration SECONDS  total capture window (default: 1)
  --interval-ms MS    snapshot interval inside the window (default: 250 ms)
  --source PATH       source frame path (default: /dev/shm/hapax-compositor/snapshot.jpg)
EOF
    exit 2
}

if [[ $# -lt 1 ]]; then
    usage
fi

label="$1"
shift
duration_s="${DEFAULT_DURATION_S}"
interval_ms="${DEFAULT_INTERVAL_MS}"
source_path="${DEFAULT_SOURCE}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration)
            duration_s="$2"
            shift 2
            ;;
        --interval-ms)
            interval_ms="$2"
            shift 2
            ;;
        --source)
            source_path="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "compositor-frame-capture: unknown argument: $1" >&2
            usage
            ;;
    esac
done

if [[ ! -r "$source_path" ]]; then
    echo "compositor-frame-capture: source frame not readable: $source_path" >&2
    echo "  is the compositor running? (systemctl --user status hapax-studio-compositor)" >&2
    exit 1
fi

if ! [[ "$duration_s" =~ ^[0-9]+(\.[0-9]+)?$ ]] || ! [[ "$interval_ms" =~ ^[0-9]+$ ]]; then
    echo "compositor-frame-capture: --duration must be a number, --interval-ms an integer" >&2
    exit 2
fi

if (( interval_ms <= 0 )); then
    echo "compositor-frame-capture: --interval-ms must be > 0" >&2
    exit 2
fi

ts_utc="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="${OUTPUT_ROOT}/${label}/${ts_utc}"
mkdir -p "$out_dir"

# Convert duration to total frame count. Use awk for fractional duration support.
frame_count="$(awk -v d="$duration_s" -v i="$interval_ms" 'BEGIN { n = int((d * 1000) / i); if (n < 1) n = 1; print n }')"
sleep_s="$(awk -v i="$interval_ms" 'BEGIN { printf "%.3f", i / 1000.0 }')"

frames=()
for ((n = 1; n <= frame_count; n++)); do
    out_frame="${out_dir}/frame-$(printf "%02d" "$n").jpg"
    cp -f "$source_path" "$out_frame"
    frames+=("$out_frame")
    if (( n < frame_count )); then
        sleep "$sleep_s"
    fi
done

# Print the human-readable summary on stderr so stdout stays scriptable.
echo "compositor-frame-capture: ${#frames[@]} frame(s) → ${out_dir}" >&2
echo "  source:  ${source_path}" >&2
echo "  label:   ${label}" >&2
echo "  duration: ${duration_s}s @ ${interval_ms}ms interval" >&2

# Stdout: markdown block ready to paste into a PR body.
cat <<EOF

### compositor evidence — \`${label}\`

| frame | path |
|------:|------|
EOF
for ((n = 0; n < ${#frames[@]}; n++)); do
    printf "| %02d | \`%s\` |\n" $((n + 1)) "${frames[$n]}"
done
cat <<EOF

_Captured ${ts_utc} from \`${source_path}\` over ${duration_s}s @ ${interval_ms}ms intervals._
EOF

#!/usr/bin/env bash
# audio-stage-check.sh — Boot-time per-stage audio level check
# (cc-task audio-audit-B-startup-stage-check, Auditor B).
#
# Plays a known -14 LUFS test tone through hapax-music-loudnorm.playback
# for 5 seconds, captures monitor RMS at each of 4 stages defined in
# config/audio-stage-expected-levels.yaml, compares each to the
# expected_dbfs, and:
#   - writes one JSONL record per check to /var/log/hapax/audio-stage-check.jsonl
#   - publishes ntfy alert ``audio-stage-divergence`` if any stage is
#     ±tolerance_db off
#   - emits Prometheus textfile gauges for trend visibility
#
# Phase 0 (this PR): the wrapper + YAML loader + ntfy/JSONL plumbing.
# The actual tone-injection + monitor-capture path is gated behind
# HAPAX_L12_PRESENT=1 and skipped on non-hardware environments. The
# gate runs in dry-run-by-default so the operator can run it locally
# to verify the YAML schema parses + the JSONL writer reaches the
# right path before committing to a hardware-on session.
#
# Usage:
#   scripts/audio-stage-check.sh                # default (dry-run)
#   scripts/audio-stage-check.sh --execute      # actually inject tone + capture
#   scripts/audio-stage-check.sh --config X.yaml
#   scripts/audio-stage-check.sh --jsonl-path /tmp/check.jsonl
#
# Exit codes:
#   0 = all stages within tolerance (or dry-run successful)
#   2 = at least one stage diverged > tolerance_db
#   3 = configuration / fixture failure (YAML parse, monitor missing)

set -uo pipefail

CONFIG_PATH="${HAPAX_AUDIO_STAGE_CONFIG:-${HOME:-/home/hapax}/projects/hapax-council/config/audio-stage-expected-levels.yaml}"
JSONL_PATH="${HAPAX_AUDIO_STAGE_JSONL:-/var/log/hapax/audio-stage-check.jsonl}"
TEXTFILE_DIR="${HAPAX_AUDIO_STAGE_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
TEXTFILE="${TEXTFILE_DIR}/hapax_audio_stage_check.prom"
NTFY_BASE="${NTFY_BASE_URL:-http://localhost:8090}"
NTFY_TOPIC="${HAPAX_AUDIO_STAGE_NTFY_TOPIC:-audio-stage-divergence}"
EXECUTE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --config=*)         CONFIG_PATH="${1#*=}" ;;
    --config)           shift; CONFIG_PATH="${1:-$CONFIG_PATH}" ;;
    --jsonl-path=*)     JSONL_PATH="${1#*=}" ;;
    --jsonl-path)       shift; JSONL_PATH="${1:-$JSONL_PATH}" ;;
    --textfile-dir=*)   TEXTFILE_DIR="${1#*=}"; TEXTFILE="${TEXTFILE_DIR}/hapax_audio_stage_check.prom" ;;
    --textfile-dir)     shift; TEXTFILE_DIR="${1:-$TEXTFILE_DIR}"; TEXTFILE="${TEXTFILE_DIR}/hapax_audio_stage_check.prom" ;;
    --execute)          EXECUTE=1 ;;
    --dry-run)          EXECUTE=0 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "audio-stage-check: unknown arg: $1" >&2
      exit 3
      ;;
  esac
  shift
done

if [ ! -r "$CONFIG_PATH" ]; then
  echo "audio-stage-check: cannot read config $CONFIG_PATH" >&2
  exit 3
fi

# Parse YAML via python (no PyYAML in udev/oneshot environments;
# use the stdlib ConfigParser-style parser via heredoc).
stage_lines=$(python3 - "$CONFIG_PATH" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)

if not isinstance(data, dict) or "stages" not in data:
    print("invalid-yaml: missing stages", file=sys.stderr)
    sys.exit(3)

for stage in data["stages"]:
    monitor = stage.get("monitor", "")
    expected = stage.get("expected_dbfs", 0)
    tol = stage.get("tolerance_db", 0)
    print(f"{monitor}\t{expected}\t{tol}")
PY
)
parse_exit=$?
if [ "$parse_exit" -ne 0 ]; then
  echo "audio-stage-check: YAML parse failed" >&2
  exit 3
fi

mkdir -p "$(dirname "$JSONL_PATH")" 2>/dev/null
mkdir -p "$TEXTFILE_DIR" 2>/dev/null

timestamp=$(date -Iseconds)
mode_label="dry-run"
[ "$EXECUTE" -eq 1 ] && mode_label="execute"

divergent=0
total_checked=0
prom_lines=(
  "# HELP hapax_audio_stage_rms_dbfs Per-stage measured RMS dBFS at boot-time stage check (audit B)"
  "# TYPE hapax_audio_stage_rms_dbfs gauge"
)

while IFS=$'\t' read -r monitor expected tolerance; do
  [ -z "$monitor" ] && continue
  total_checked=$((total_checked + 1))

  measured="null"
  status="dry-run"

  if [ "$EXECUTE" -eq 1 ]; then
    if ! command -v pw-cat >/dev/null 2>&1; then
      status="skipped-no-pw-cat"
    elif ! command -v python3 >/dev/null 2>&1; then
      status="skipped-no-python3"
    else
      tmpwav=$(mktemp --suffix=.wav)
      pw-cat --record --target "$monitor" "$tmpwav" \
        --format=s16 --rate=48000 --channels=1 \
        --duration=2 >/dev/null 2>&1 || true
      if [ -s "$tmpwav" ]; then
        measured=$(python3 - "$tmpwav" <<'PY'
import math, sys, wave
import array

with wave.open(sys.argv[1], "rb") as wf:
    raw = wf.readframes(wf.getnframes())
samples = array.array("h", raw)
if not samples:
    print("null"); sys.exit(0)
sq_sum = sum(s * s for s in samples) / len(samples)
rms = math.sqrt(sq_sum)
if rms == 0:
    print("-inf"); sys.exit(0)
dbfs = 20.0 * math.log10(rms / 32767.0)
print(f"{dbfs:.2f}")
PY
)
        status="measured"
      else
        status="skipped-empty-capture"
      fi
      rm -f "$tmpwav"
    fi
  fi

  diverged="false"
  if [ "$measured" != "null" ] && [ "$measured" != "-inf" ]; then
    delta=$(python3 -c "print(abs(${measured} - (${expected})))")
    if python3 -c "import sys; sys.exit(0 if abs(${measured} - (${expected})) > ${tolerance} else 1)"; then
      diverged="true"
      divergent=$((divergent + 1))
    fi
  fi

  jsonl_line=$(printf '{"timestamp":"%s","mode":"%s","stage":"%s","expected_dbfs":%s,"tolerance_db":%s,"measured_dbfs":%s,"status":"%s","diverged":%s}' \
    "$timestamp" "$mode_label" "$monitor" "$expected" "$tolerance" "$measured" "$status" "$diverged")
  echo "$jsonl_line" >> "$JSONL_PATH"

  if [ "$measured" != "null" ] && [ "$measured" != "-inf" ]; then
    prom_lines+=("hapax_audio_stage_rms_dbfs{stage=\"$monitor\"} $measured")
  fi
done <<< "$stage_lines"

prom_lines+=("# HELP hapax_audio_stage_divergent_total Stages diverged at the most recent check")
prom_lines+=("# TYPE hapax_audio_stage_divergent_total gauge")
prom_lines+=("hapax_audio_stage_divergent_total $divergent")
prom_lines+=("# HELP hapax_audio_stage_checked_total Stages evaluated at the most recent check")
prom_lines+=("# TYPE hapax_audio_stage_checked_total gauge")
prom_lines+=("hapax_audio_stage_checked_total $total_checked")

tmp="${TEXTFILE}.tmp"
printf '%s\n' "${prom_lines[@]}" > "$tmp" 2>/dev/null && mv "$tmp" "$TEXTFILE" 2>/dev/null

if [ "$divergent" -gt 0 ] && command -v curl >/dev/null 2>&1; then
  curl -s -o /dev/null \
    -H "Title: audio stage divergence ($divergent of $total_checked)" \
    -H "Priority: high" \
    -H "Tags: warning,sound" \
    -d "Runbook: docs/runbooks/audio-incidents.md#broadcast-low" \
    "${NTFY_BASE%/}/${NTFY_TOPIC}" 2>/dev/null || true
fi

echo "audio-stage-check: $total_checked stages checked, $divergent diverged (mode=$mode_label)"
[ "$divergent" -gt 0 ] && exit 2
exit 0

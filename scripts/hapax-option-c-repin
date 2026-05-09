#!/usr/bin/env bash
# option-c-repin.sh — Detect + correct Ryzen HDA Option-C pin drift.
#
# After every PipeWire restart, the Ryzen on-board HDA's analog-stereo
# output port retargets to the wrong sink slot — the operator hears
# system audio in the wrong ear, or both ears reversed. This script
# checks the active card profile against the canonical
# ``output:analog-stereo`` and re-pins it via pactl if drift is
# detected.
#
# Idempotent: no-op when the pin is already correct.
# Designed for periodic invocation by hapax-option-c-pin-watchdog.timer
# (every 30s).
#
# Emits a Prometheus textfile counter
# ``hapax_option_c_repin_total{outcome="repinned"|"already-correct"|"error"}``
# at $TEXTFILE_DIR (defaults to /var/lib/node_exporter/textfile_collector/),
# so dashboards can alert when drift fires unusually often (= a deeper
# Ryzen HDA driver bug, not just steady-state PipeWire restart noise).
#
# Usage:
#   scripts/option-c-repin.sh                # run once, exit 0/1/2
#   scripts/option-c-repin.sh --dry-run      # print what would change
#   scripts/option-c-repin.sh --force        # always re-pin regardless of state
#
# Exit codes:
#   0 = pin correct (or successfully repinned)
#   1 = drift detected but repin failed (pactl error)
#   2 = card not found (Ryzen HDA absent — boot/ordering issue)

set -uo pipefail

CANONICAL_PROFILE="output:analog-stereo"
# pactl exposes the AMD Ryzen on-board HDA as ``Ryzen HD Audio Controller``
# in ``device.product.name`` / ``device.description``. The legacy pattern
# ``Family 17h/19h HD Audio`` was a kernel-level designation that no
# longer surfaces through PulseAudio properties on current PipeWire +
# Linux 6.x stacks; matching it produced a false "card not found"
# (status=2) on every tick, even though the card is healthy and present.
# The override env var still wins so deployments on different silicon
# (e.g., Family 1Ah / Zen 5) can pin their own substring.
CARD_NAME_PATTERN="${HAPAX_OPTION_C_CARD_PATTERN:-Ryzen HD Audio Controller}"
TEXTFILE_DIR="${HAPAX_OPTION_C_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
TEXTFILE="${TEXTFILE_DIR}/hapax_option_c_repin.prom"
METRIC="hapax_option_c_repin_total"

DRY_RUN=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
    --force|-f)   FORCE=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "option-c-repin: unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# Increment-by-label counter via tmp+rename. Reads the current value
# from the existing textfile so the counter is monotonic across runs.
emit_metric() {
  local outcome="$1"
  mkdir -p "$TEXTFILE_DIR" 2>/dev/null || return 0

  local repinned=0 already=0 error=0
  if [ -f "$TEXTFILE" ]; then
    repinned=$(grep -E "^${METRIC}\{outcome=\"repinned\"\}" "$TEXTFILE" 2>/dev/null | awk '{print $2}' | tail -1)
    already=$(grep -E "^${METRIC}\{outcome=\"already-correct\"\}" "$TEXTFILE" 2>/dev/null | awk '{print $2}' | tail -1)
    error=$(grep -E "^${METRIC}\{outcome=\"error\"\}" "$TEXTFILE" 2>/dev/null | awk '{print $2}' | tail -1)
  fi
  repinned=${repinned:-0}
  already=${already:-0}
  error=${error:-0}

  case "$outcome" in
    repinned)        repinned=$((repinned + 1)) ;;
    already-correct) already=$((already + 1)) ;;
    error)           error=$((error + 1)) ;;
  esac

  local tmp="${TEXTFILE}.tmp"
  {
    echo "# HELP ${METRIC} Counts of Option-C pin-watchdog ticks by outcome (audit O3c)"
    echo "# TYPE ${METRIC} counter"
    echo "${METRIC}{outcome=\"repinned\"} ${repinned}"
    echo "${METRIC}{outcome=\"already-correct\"} ${already}"
    echo "${METRIC}{outcome=\"error\"} ${error}"
  } > "$tmp" 2>/dev/null && mv "$tmp" "$TEXTFILE" 2>/dev/null
}

if ! command -v pactl >/dev/null 2>&1; then
  echo "option-c-repin: pactl not found in PATH" >&2
  emit_metric error
  exit 2
fi

# Locate the Ryzen HDA card by name pattern. ``pactl list cards short``
# emits one line per card: index<TAB>name<TAB>module-name<TAB>profile.
card_line=$(pactl list cards short 2>/dev/null | grep -F "alsa_card.pci-" | grep -F "$CARD_NAME_PATTERN" | head -1)
if [ -z "$card_line" ]; then
  # Fallback: any alsa_card.pci-* card whose long-form contains the pattern.
  card_index=$(pactl list cards 2>/dev/null | awk -v pat="$CARD_NAME_PATTERN" '
    /^Card #/ { idx = $2 }
    $0 ~ pat  { print idx; exit }
  ')
  if [ -z "$card_index" ]; then
    echo "option-c-repin: Ryzen HDA card not found (pattern: $CARD_NAME_PATTERN)" >&2
    emit_metric error
    exit 2
  fi
  card_index=${card_index#"#"}
else
  card_index=$(echo "$card_line" | awk '{print $1}')
fi

current_profile=$(pactl list cards 2>/dev/null | awk -v idx="$card_index" '
  /^Card #/ { in_card = ($2 == "#" idx) }
  in_card && /^\tActive Profile:/ { sub(/^\tActive Profile: */, "", $0); print; exit }
')

if [ -z "$current_profile" ]; then
  echo "option-c-repin: could not read active profile for card $card_index" >&2
  emit_metric error
  exit 1
fi

if [ "$current_profile" = "$CANONICAL_PROFILE" ] && [ "$FORCE" -eq 0 ]; then
  echo "option-c-repin: already at $CANONICAL_PROFILE on card $card_index — no-op"
  emit_metric already-correct
  exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] would: pactl set-card-profile $card_index $CANONICAL_PROFILE"
  echo "[dry-run] current: $current_profile"
  exit 0
fi

if pactl set-card-profile "$card_index" "$CANONICAL_PROFILE" 2>/dev/null; then
  echo "option-c-repin: card $card_index repinned $current_profile → $CANONICAL_PROFILE"
  emit_metric repinned
  exit 0
fi

echo "option-c-repin: pactl set-card-profile failed on card $card_index" >&2
emit_metric error
exit 1

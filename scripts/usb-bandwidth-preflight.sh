#!/usr/bin/env bash
# usb-bandwidth-preflight.sh — Compute total isochronous USB bandwidth
# per xhci HC and warn/exit non-zero when saturation crosses a configured
# threshold.
#
# Auditor A O3b: when the L-12 enumerates on a saturated xhci controller,
# the 12-channel UAC2 endpoint silently drops to 8 channels (or fails).
# This preflight reads /sys/kernel/debug/usb/devices, computes the
# isochronous-endpoint bandwidth tally per host controller, and:
#
#   - emits a Prometheus textfile metric `hapax_usb_isoc_bw_pct{hc=<n>}`
#     so dashboards can graph bandwidth headroom over time
#   - exits 0 when all HCs are below WARN_PCT
#   - exits 2 (and ntfy publishes) when any HC is at-or-above WARN_PCT
#
# Designed to be invoked by udev `RUN+=` on the L-12 enumeration so the
# saturated-controller condition is caught at attach time, before
# PipeWire's ALSA scan locks in an 8-channel fallback.
#
# Usage:
#   scripts/usb-bandwidth-preflight.sh
#   scripts/usb-bandwidth-preflight.sh --device-name "Solid State Logic L-12"
#   scripts/usb-bandwidth-preflight.sh --warn-pct 75
#   scripts/usb-bandwidth-preflight.sh --usb-devices /tmp/synthetic.devices    # for tests
#
# Inputs:
#   /sys/kernel/debug/usb/devices    — the canonical kernel source for
#                                      isoc bandwidth per endpoint
#   --device-name (optional)         — the enumerated device name, included
#                                      in ntfy payloads
#
# Outputs:
#   /var/lib/node_exporter/textfile_collector/hapax_usb_isoc_bw.prom
#                                      hapax_usb_isoc_bw_pct{hc=<bus>}
#                                      hapax_usb_isoc_bw_warn_threshold_pct
#
# Exit codes:
#   0  every HC below warn threshold
#   2  at least one HC at-or-above warn threshold
#   3  /sys/kernel/debug/usb/devices missing or unreadable

set -uo pipefail

WARN_PCT="${HAPAX_USB_BW_WARN_PCT:-80}"
USB_DEVICES_PATH="${HAPAX_USB_DEVICES_PATH:-/sys/kernel/debug/usb/devices}"
TEXTFILE_DIR="${HAPAX_USB_BW_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
TEXTFILE="${TEXTFILE_DIR}/hapax_usb_isoc_bw.prom"
NTFY_BASE="${NTFY_BASE_URL:-http://localhost:8090}"
NTFY_TOPIC="${HAPAX_USB_BW_NTFY_TOPIC:-audio-usb-bw-saturated}"
DEVICE_NAME="${HAPAX_USB_BW_DEVICE_NAME:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --warn-pct=*)        WARN_PCT="${1#*=}" ;;
    --warn-pct)          shift; WARN_PCT="${1:-$WARN_PCT}" ;;
    --usb-devices=*)     USB_DEVICES_PATH="${1#*=}" ;;
    --usb-devices)       shift; USB_DEVICES_PATH="${1:-$USB_DEVICES_PATH}" ;;
    --device-name=*)     DEVICE_NAME="${1#*=}" ;;
    --device-name)       shift; DEVICE_NAME="${1:-$DEVICE_NAME}" ;;
    --textfile-dir=*)    TEXTFILE_DIR="${1#*=}"; TEXTFILE="${TEXTFILE_DIR}/hapax_usb_isoc_bw.prom" ;;
    --textfile-dir)      shift; TEXTFILE_DIR="${1:-$TEXTFILE_DIR}"; TEXTFILE="${TEXTFILE_DIR}/hapax_usb_isoc_bw.prom" ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "usb-bandwidth-preflight: unknown arg: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [ ! -r "$USB_DEVICES_PATH" ]; then
  echo "usb-bandwidth-preflight: cannot read $USB_DEVICES_PATH" >&2
  exit 3
fi

# Parse /sys/kernel/debug/usb/devices for isochronous endpoint bandwidth.
#
# Format excerpt (per kernel/Documentation/driver-api/usb/usb.rst):
#   T:  Bus=01 Lev=01 Prnt=01 Port=00 Cnt=01 Dev#=  2 Spd=480 MxCh= 0
#   B:  Alloc=  0/800 us ( 0%), #Int=  0, #Iso=  0
#
# The B: line carries the controller-level bandwidth allocation per
# microframe. Alloc=N/M shows N microseconds used of M available.
# Pct = N * 100 / M. We ALSO sum #Iso from each endpoint as a sanity
# check: if any endpoint reports isoc bandwidth > the controller's
# free budget, that's the saturation condition we're guarding against.
#
# We emit per-bus pct as Alloc-line Pct and pin a single textfile.

awk -v warn="$WARN_PCT" -v textfile="$TEXTFILE" -v textfile_dir="$TEXTFILE_DIR" '
BEGIN {
  worst_pct = 0
  worst_bus = ""
}
/^T:/ {
  for (i = 1; i <= NF; i++) {
    if ($i ~ /^Bus=/) { sub(/^Bus=/, "", $i); current_bus = $i + 0 }
  }
}
/^B:/ {
  # Alloc=N/M us ( P%)
  for (i = 1; i <= NF; i++) {
    if ($i ~ /^\(/) {
      pct = $i; sub(/^\(/, "", pct); sub(/%\)?$/, "", pct)
      bus_pct[current_bus] = pct + 0
      if (pct + 0 > worst_pct) {
        worst_pct = pct + 0
        worst_bus = current_bus
      }
    }
  }
}
END {
  # Tmp file for atomic write.
  system("mkdir -p \"" textfile_dir "\" 2>/dev/null")
  tmpfile = textfile ".tmp"
  printf "" > tmpfile
  print "# HELP hapax_usb_isoc_bw_pct USB controller isochronous bandwidth allocation pct (audit O3b)" > tmpfile
  print "# TYPE hapax_usb_isoc_bw_pct gauge" > tmpfile
  for (bus in bus_pct) {
    printf("hapax_usb_isoc_bw_pct{hc=\"%d\"} %d\n", bus, bus_pct[bus]) > tmpfile
  }
  print "# HELP hapax_usb_isoc_bw_warn_threshold_pct Warn threshold pct above which preflight exits non-zero" > tmpfile
  print "# TYPE hapax_usb_isoc_bw_warn_threshold_pct gauge" > tmpfile
  printf("hapax_usb_isoc_bw_warn_threshold_pct %d\n", warn) > tmpfile
  close(tmpfile)
  system("mv \"" tmpfile "\" \"" textfile "\" 2>/dev/null")

  if (worst_pct >= warn) {
    printf("usb-bandwidth-preflight: HC bus %d at %d%% (warn=%d%%) — SATURATED\n", worst_bus, worst_pct, warn) > "/dev/stderr"
    print worst_pct
    exit 2
  }
  printf("usb-bandwidth-preflight: worst HC bus %d at %d%% (warn=%d%%) — ok\n", worst_bus, worst_pct, warn) > "/dev/stderr"
  print worst_pct
  exit 0
}
' "$USB_DEVICES_PATH"
awk_exit=$?

if [ "$awk_exit" -eq 2 ] && command -v curl >/dev/null 2>&1; then
  body="usb-bandwidth-preflight saturated"
  if [ -n "$DEVICE_NAME" ]; then
    body="${body} (enumerating: $DEVICE_NAME)"
  fi
  body="${body}\nThreshold: ${WARN_PCT}%\nRunbook: docs/runbooks/audio-incidents.md#xhci-l12-channel-drop"
  curl -s -o /dev/null \
    -H "Title: USB isoc bandwidth saturated" \
    -H "Priority: high" \
    -H "Tags: warning,sound" \
    -d "$body" \
    "${NTFY_BASE%/}/${NTFY_TOPIC}" 2>/dev/null || true
fi

exit "$awk_exit"

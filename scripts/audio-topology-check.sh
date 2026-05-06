#!/usr/bin/env bash
# audio-topology-check.sh — verify live PipeWire graph matches the hapax
# audio topology documented in docs/runbooks/audio-topology.md.
#
# Exits 0 when the expected topology is present. Otherwise prints the
# specific deltas (missing / unexpected nodes) to stdout and exits non-zero.
# Suitable for ad-hoc operator use and for future health-monitor integration.
#
# Dependencies: pw-cli (pipewire-tools). Falls back to an explicit error
# when pw-cli is unavailable.
#
# ENV OVERRIDES (test harness):
#   AUDIO_TOPOLOGY_CHECK_PW_CLI    — override the pw-cli binary / script path.
#                                     The script invokes:
#                                       "$bin" list-objects Node
#                                     so the override must accept those args.
#   AUDIO_TOPOLOGY_CHECK_STRICT_HW — 1 to require Yeti + Cortado hardware
#                                     sources. Default 0 (warn only).
set -euo pipefail

PW_CLI="${AUDIO_TOPOLOGY_CHECK_PW_CLI:-pw-cli}"
STRICT_HW="${AUDIO_TOPOLOGY_CHECK_STRICT_HW:-0}"

if ! command -v "$PW_CLI" >/dev/null 2>&1 && [[ ! -x "$PW_CLI" ]]; then
    echo "ERROR: pw-cli not found (PW_CLI='$PW_CLI'). Install pipewire or set AUDIO_TOPOLOGY_CHECK_PW_CLI." >&2
    exit 3
fi

# Capture pw-cli output once.
if ! pw_output="$("$PW_CLI" list-objects Node 2>/dev/null)"; then
    echo "ERROR: '$PW_CLI list-objects Node' failed. Is PipeWire running under this user scope?" >&2
    exit 3
fi

if [[ -z "${pw_output//[[:space:]]/}" ]]; then
    echo "ERROR: pw-cli returned no Node objects. PipeWire likely not running." >&2
    exit 3
fi

REQUIRED_NODES=(
    "echo_cancel_capture"
)

OPTIONAL_NODES=(
    "yeti_cancelled"
    "echo_cancel_sink"
    "hapax-ytube-ducked"
)

HARDWARE_NODES=(
    "Blue_Microphones_Yeti"
)

missing_required=()
missing_optional=()
missing_hardware=()

for node in "${REQUIRED_NODES[@]}"; do
    if ! printf '%s\n' "$pw_output" | grep -qF "$node"; then
        missing_required+=("$node")
    fi
done

for node in "${OPTIONAL_NODES[@]}"; do
    if ! printf '%s\n' "$pw_output" | grep -qF "$node"; then
        missing_optional+=("$node")
    fi
done

for node in "${HARDWARE_NODES[@]}"; do
    if ! printf '%s\n' "$pw_output" | grep -qF "$node"; then
        missing_hardware+=("$node")
    fi
done

status=0

if [[ ${#missing_required[@]} -gt 0 ]]; then
    echo "MISSING (required): ${missing_required[*]}"
    echo "  -> Install config/pipewire/hapax-echo-cancel.conf and restart pipewire/wireplumber."
    status=1
fi

if [[ ${#missing_optional[@]} -gt 0 ]]; then
    echo "MISSING (optional): ${missing_optional[*]}"
fi

if [[ ${#missing_hardware[@]} -gt 0 ]]; then
    msg="MISSING (hardware): ${missing_hardware[*]}"
    if [[ "$STRICT_HW" == "1" ]]; then
        echo "$msg"
        status=2
    else
        echo "WARN $msg — strict mode off; continuing."
    fi
fi

if [[ $status -eq 0 && ${#missing_optional[@]} -eq 0 && ${#missing_hardware[@]} -eq 0 ]]; then
    echo "OK: audio topology matches expected (echo_cancel_capture + aliases + hardware sources present)."
elif [[ $status -eq 0 ]]; then
    echo "OK: required topology present. Optional / hardware deltas listed above."
fi

exit "$status"

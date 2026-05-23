#!/usr/bin/env bash
# Source this before launching DarkPlaces renderer processes.
set -euo pipefail

_darkplaces_guard_sourced=0
if (return 0 2>/dev/null); then
    _darkplaces_guard_sourced=1
fi

_darkplaces_guard_finish() {
    local code="$1"
    if [ "$_darkplaces_guard_sourced" -eq 1 ]; then
        return "$code"
    fi
    exit "$code"
}

if [ "${HAPAX_DARKPLACES_RUNTIME_ACK:-}" = "1" ]; then
    _darkplaces_guard_finish 0
fi

if [ -e "$HOME/.config/hapax/enable-darkplaces-runtime" ]; then
    _darkplaces_guard_finish 0
fi

cat >&2 <<'EOF'
DarkPlaces runtime launch is contained.

The host hard-reset on 2026-05-23 after the Screwm GL renderer was activated.
The next boot reported an AMD data-fabric sync-flood reset reason. Re-enable
only in an attended hardware-validation session by creating:

  ~/.config/hapax/enable-darkplaces-runtime

or by setting HAPAX_DARKPLACES_RUNTIME_ACK=1 for a single command.
EOF
_darkplaces_guard_finish 78

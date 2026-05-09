#!/usr/bin/env bash
# hapax-systemd-reconcile — detect systemd user units that are `linked`
# to ~/.config/systemd/user/ but have no corresponding file under the
# council repo's systemd/units/. Classic drift hazard: a unit deleted
# from the repo (git rm) but still live on the host.
#
# Usage:
#   hapax-systemd-reconcile          # dry-run: list drift, take no action
#   hapax-systemd-reconcile --apply  # disable + unlink drifted units
#   hapax-systemd-reconcile --quiet  # suppress per-unit chatter
#
# Acceptance criterion from D-21: running --apply disables a drifted
# unit (e.g. a deleted .timer that's still `linked enabled`), and
# running the script twice is a no-op after the first apply.
#
# Exit codes:
#   0 — no drift OR --apply completed successfully
#   1 — drift detected in dry-run (signals to CI / operator)
#   2 — usage / environment error
#
# Reference:
#   docs/superpowers/handoff/2026-04-20-delta-wsjf-reorganization.md §4.9 D-21
#   docs/research/2026-04-20-six-hour-audit.md §8.4

set -euo pipefail

APPLY=0
QUIET=0
for arg in "$@"; do
    case "$arg" in
        --apply)
            APPLY=1
            ;;
        --quiet)
            QUIET=1
            ;;
        -h|--help)
            cat <<HELP
Usage: hapax-systemd-reconcile [--apply] [--quiet]

  --apply   Disable + unlink drifted units. Without this flag, runs
            dry-run and reports drift only.
  --quiet   Suppress per-unit chatter.

Drift = systemd user unit is "linked" to ~/.config/systemd/user/ but
has no matching file under ~/projects/hapax-council/systemd/units/.
HELP
            exit 0
            ;;
        *)
            echo "unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

# Portable repo path — the script is callable from anywhere via a symlink in
# ~/.local/bin; locate the repo relative to the real script source, not the
# symlink invocation path.
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
REAL_SCRIPT_SOURCE="$(readlink -f "$SCRIPT_SOURCE" 2>/dev/null || true)"
if [ -z "$REAL_SCRIPT_SOURCE" ]; then
    REAL_SCRIPT_SOURCE="$SCRIPT_SOURCE"
    while [ -L "$REAL_SCRIPT_SOURCE" ]; do
        SOURCE_DIR="$(cd -P "$(dirname "$REAL_SCRIPT_SOURCE")" && pwd)"
        REAL_SCRIPT_SOURCE="$(readlink "$REAL_SCRIPT_SOURCE")"
        case "$REAL_SCRIPT_SOURCE" in
            /*) ;;
            *) REAL_SCRIPT_SOURCE="$SOURCE_DIR/$REAL_SCRIPT_SOURCE" ;;
        esac
    done
fi

SCRIPT_DIR="$(cd -P "$(dirname "$REAL_SCRIPT_SOURCE")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_UNITS="$REPO_ROOT/systemd/units"

if [ ! -d "$REPO_UNITS" ]; then
    echo "error: $REPO_UNITS not found — cannot reconcile" >&2
    exit 2
fi

# Collect linked unit names (second column = "linked").
mapfile -t LINKED < <(
    systemctl --user list-unit-files --full --no-pager 2>/dev/null \
        | awk '$2=="linked"{print $1}'
)

if [ "${#LINKED[@]}" -eq 0 ]; then
    [ "$QUIET" -eq 0 ] && echo "no linked user units — nothing to reconcile"
    exit 0
fi

DRIFT=()
for unit in "${LINKED[@]}"; do
    # Template units (foo@.service) map to foo@.service in the repo.
    # Concrete instance units (foo@x.service) also reconcile against
    # the template file.
    template="${unit/@*./@.}"
    if [ -f "$REPO_UNITS/$unit" ] || [ -f "$REPO_UNITS/$template" ]; then
        continue
    fi
    DRIFT+=("$unit")
done

if [ "${#DRIFT[@]}" -eq 0 ]; then
    [ "$QUIET" -eq 0 ] && echo "✓ no drift — ${#LINKED[@]} linked units all have repo backing"
    exit 0
fi

echo "Detected ${#DRIFT[@]} drifted unit(s) (linked but absent from $REPO_UNITS):"
for unit in "${DRIFT[@]}"; do
    echo "  • $unit"
done

if [ "$APPLY" -eq 0 ]; then
    echo ""
    echo "Dry-run only — re-run with --apply to disable + unlink."
    exit 1
fi

echo ""
echo "Applying reconciliation..."
FAILED=()
for unit in "${DRIFT[@]}"; do
    [ "$QUIET" -eq 0 ] && echo "disabling + unlinking: $unit"
    if ! systemctl --user disable --now "$unit" 2>/dev/null; then
        # disable failures are non-fatal — unit may already be disabled;
        # continue to unlink.
        [ "$QUIET" -eq 0 ] && echo "  (disable returned non-zero; continuing to unlink)"
    fi
    symlink="$HOME/.config/systemd/user/$unit"
    if [ -L "$symlink" ] || [ -f "$symlink" ]; then
        if ! rm -f "$symlink"; then
            FAILED+=("$unit")
            continue
        fi
    fi
done

systemctl --user daemon-reload 2>/dev/null || true

if [ "${#FAILED[@]}" -gt 0 ]; then
    echo "Failed to fully reconcile ${#FAILED[@]}: ${FAILED[*]}" >&2
    exit 1
fi

echo "✓ reconciled ${#DRIFT[@]} unit(s); daemon-reload issued."
exit 0

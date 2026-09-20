#!/usr/bin/env bash
# hapax-systemd-reconcile — detect systemd user units that are `linked`
# to ~/.config/systemd/user/ but have no corresponding file under the
# council repo's systemd/units/. Classic drift hazard: a unit deleted
# from the repo (git rm) but still live on the host.
#
# Also asserts that every `hapax-*.timer` reported `enabled` is `is-active`.
# `enabled` is not `running`: a monotonic timer (OnBootSec + OnUnitActiveSec)
# computes its next elapse from the triggered service activating, so a missed
# activation leaves it with no next elapse point and it deactivates. It cannot
# recover on its own, and `systemctl list-timers` renders a dead timer as a
# bare `-` for NEXT, indistinguishable from one merely not due. That is how
# hapax-pr-review-dispatch.timer sat dead for four weeks while both its
# consumers polled on cadence for output nothing was producing.
#
# The timer assertion is deliberately a report, not a repair — starting a unit
# is a runtime act and belongs to a runtime task with its own authorization.
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
#   0 — no drift and no dead timers, OR --apply completed successfully
#   1 — drift detected in dry-run, and/or an enabled timer is not running
#       (signals to CI / operator). --apply cannot clear the timer half:
#       it repairs drift and reports dead timers, so the exit stays 1.
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

Drift = systemd user unit is "linked" to ~/.config/systemd/user/ or exists
as a Hapax unit symlink there but has no matching file under
~/projects/hapax-council/systemd/units/.
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
REPO_UNITS="${HAPAX_SYSTEMD_REPO_UNITS:-$REPO_ROOT/systemd/units}"
USER_UNIT_DIR="${HAPAX_SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
SYSTEMCTL="${HAPAX_SYSTEMCTL:-systemctl}"

if [ ! -d "$REPO_UNITS" ]; then
    echo "error: $REPO_UNITS not found — cannot reconcile" >&2
    exit 2
fi

# --------------------------------------------------------------------------
# Enumerate the unit files ONCE, and refuse if systemd cannot be asked.
#
# Both checks below read this list, so this is the single point where the
# whole script's input set is established. It must not fail open: a run that
# could not interrogate systemd has assessed nothing, and reporting "no drift"
# or a silent pass would be the same lie this script exists to catch — a check
# whose input set excludes the deciding state. Refuse loudly instead, naming
# the command to re-run.
#
# Unit names are filtered by the readers below rather than by a systemctl
# pattern argument, so the scope holds regardless of what the invocation asks.
# --------------------------------------------------------------------------
if ! UNIT_FILES="$($SYSTEMCTL --user list-unit-files --full --no-pager --no-legend 2>/dev/null)"; then
    echo "error: could not enumerate systemd user units — nothing was assessed" >&2
    echo "  no drift check and no timer liveness check ran; this is not a pass." >&2
    echo "  recheck: $SYSTEMCTL --user list-unit-files --full --no-pager" >&2
    echo "  if that fails too, there is no systemd user session here and this" >&2
    echo "  host is not one the reconciler can speak for." >&2
    exit 2
fi

# --------------------------------------------------------------------------
# `enabled` is not `running`.
#
# Scope is narrow on purpose. Only `enabled`/`enabled-runtime` timers are
# asserted: `disabled` and inactive is the operator's intent, `static` units
# have no [Install] section to be enabled by, and a `.service` is expected to
# be inactive between oneshot runs.
# --------------------------------------------------------------------------
DEAD_TIMERS=()
DEAD_TIMER_STATES=()

collect_dead_timers() {
    local unit state active_state

    while read -r unit state _; do
        case "$unit" in
            hapax-*.timer) ;;
            *) continue ;;
        esac
        case "$state" in
            enabled|enabled-runtime) ;;
            *) continue ;;
        esac
        # is-active prints the state and exits non-zero when it is not active.
        # The exit status is the assertion; the printed state is the evidence.
        if active_state="$($SYSTEMCTL --user is-active "$unit" 2>/dev/null)"; then
            continue
        fi
        DEAD_TIMERS+=("$unit")
        DEAD_TIMER_STATES+=("${active_state:-unknown}")
    done <<<"$UNIT_FILES"
}

# Reports every enabled-but-not-running timer by name. Returns 1 if any were
# found, so callers can fold it into their exit status.
report_dead_timers() {
    local i
    [ "${#DEAD_TIMERS[@]}" -gt 0 ] || return 0

    echo ""
    echo "Detected ${#DEAD_TIMERS[@]} enabled timer(s) that are not running:"
    for i in "${!DEAD_TIMERS[@]}"; do
        echo "  • ${DEAD_TIMERS[$i]} (enabled, ${DEAD_TIMER_STATES[$i]})"
    done
    echo ""
    echo "An enabled timer that is not active has no next elapse point and will"
    echo "not recover on its own — it stays dead until something starts it, and"
    echo "its consumers keep polling for output nothing is producing."
    echo ""
    echo "Next action — starting a unit is a runtime act, so this needs a task"
    echo "carrying runtime_mutation_authorized, not this reconciler:"
    for i in "${!DEAD_TIMERS[@]}"; do
        echo "  $SYSTEMCTL --user start ${DEAD_TIMERS[$i]}"
    done
    echo "Then confirm it took: $SYSTEMCTL --user list-timers --all"
    echo "A timer that goes inactive again has the monotonic shape"
    echo "(OnBootSec + OnUnitActiveSec) and wants an OnCalendar schedule, which"
    echo "can recover from a missed activation."
    return 1
}

collect_dead_timers

# Collect linked unit names (second column = "linked") plus any Hapax unit
# symlink present in the user unit directory. Broken symlinks can disappear
# from `systemctl list-unit-files`, so filesystem discovery is the repair path.
mapfile -t LINKED < <(printf '%s\n' "$UNIT_FILES" | awk '$2=="linked"{print $1}')

if [ -d "$USER_UNIT_DIR" ]; then
    for symlink in "$USER_UNIT_DIR"/*.service "$USER_UNIT_DIR"/*.timer "$USER_UNIT_DIR"/*.target "$USER_UNIT_DIR"/*.path; do
        [ -L "$symlink" ] || continue
        name="$(basename "$symlink")"
        case "$name" in
            hapax-*|logos-*|tabbyapi-*) LINKED+=("$name") ;;
            *) ;;
        esac
    done
fi

if [ "${#LINKED[@]}" -gt 0 ]; then
    mapfile -t LINKED < <(printf '%s\n' "${LINKED[@]}" | sort -u)
fi

if [ "${#LINKED[@]}" -eq 0 ]; then
    [ "$QUIET" -eq 0 ] && echo "no linked user units — nothing to reconcile"
    report_dead_timers || exit 1
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
    report_dead_timers || exit 1
    exit 0
fi

echo "Detected ${#DRIFT[@]} drifted unit(s) (linked but absent from $REPO_UNITS):"
for unit in "${DRIFT[@]}"; do
    echo "  • $unit"
done

if [ "$APPLY" -eq 0 ]; then
    echo ""
    echo "Dry-run only — re-run with --apply to disable + unlink."
    report_dead_timers || true
    exit 1
fi

echo ""
echo "Applying reconciliation..."
FAILED=()
for unit in "${DRIFT[@]}"; do
    [ "$QUIET" -eq 0 ] && echo "disabling + unlinking: $unit"
    if ! $SYSTEMCTL --user disable --now "$unit" 2>/dev/null; then
        # disable failures are non-fatal — unit may already be disabled;
        # continue to unlink.
        [ "$QUIET" -eq 0 ] && echo "  (disable returned non-zero; continuing to unlink)"
    fi
    symlink="$USER_UNIT_DIR/$unit"
    if [ -L "$symlink" ] || [ -f "$symlink" ]; then
        if ! rm -f "$symlink"; then
            FAILED+=("$unit")
            continue
        fi
    fi
done

$SYSTEMCTL --user daemon-reload 2>/dev/null || true

if [ "${#FAILED[@]}" -gt 0 ]; then
    echo "Failed to fully reconcile ${#FAILED[@]}: ${FAILED[*]}" >&2
    report_dead_timers || true
    exit 1
fi

echo "✓ reconciled ${#DRIFT[@]} unit(s); daemon-reload issued."
# --apply repairs drift; it does not start timers. A dead timer therefore
# survives a successful apply, and the estate is not reconciled until one of
# them is started under a runtime task.
report_dead_timers || exit 1
exit 0

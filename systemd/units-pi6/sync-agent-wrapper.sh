#!/bin/bash
# Sync agent wrapper for Pi6
# Usage: sync-agent-wrapper.sh <agent_module> [pre-sync-sources...]
#
# Handles rsync pre-pull of source files from workstation,
# runs the agent, then rsyncs output back.
set -euo pipefail

AGENT="$1"
shift
# Overridable, and corrected: this was pinned at .80, which stopped answering when the
# workstation renumbered to .50. Nothing reported it, because every rsync below ended in
# `|| true` — the timers fired, the units exited 0, and no bytes moved for an unknown
# number of months. A sync that cannot reach its source must say so.
WORKSTATION="${HAPAX_SYNC_WORKSTATION:-192.168.68.50}"
# Roots, overridable for the same reason the address is. A script with its paths welded to one
# machine cannot be exercised anywhere, and this file's entire defect history is behaviour that
# nothing ever ran. Production defaults are unchanged.
SYNC_HOME="${HAPAX_SYNC_HOME:-/home/hapax}"
COUNCIL_DIR="${HAPAX_SYNC_COUNCIL_DIR:-$SYNC_HOME/projects/hapax-council}"
VENV="$COUNCIL_DIR/.venv-sync/bin/python"
AGENT_DASH="${AGENT//_/-}"
MIN_DISK_MB=500

# ONE PATH, SET BEFORE THE FIRST THING THAT NEEDS IT.
#
# This export used to sit between the pre-sync pull and the post-sync push, so the two halves of
# the same script resolved `rsync` out of two different environments — systemd's minimal default
# for the pull, this pinned list for the push. Nothing depended on the difference in production,
# where both find /usr/bin/rsync, but a script whose environment changes halfway through is one
# whose failures cannot be reproduced from either half. Hoisted, and overridable like the roots
# above so the transfers can be exercised at all.
export PATH="${HAPAX_SYNC_PATH:-/home/hapax/.local/bin:/usr/local/bin:/usr/bin:/bin}"

# Pre-flight: check disk space
avail_kb=$(df --output=avail / | tail -1)
avail_mb=$((avail_kb / 1024))
if [ "$avail_mb" -lt "$MIN_DISK_MB" ]; then
  echo "FATAL: Only ${avail_mb}MB free on / (need ${MIN_DISK_MB}MB). Aborting." >&2
  exit 1
fi

# Pre-sync: pull source files from workstation if specified.
#
# These are FATAL on failure, deliberately. The agent's whole job is to process what it
# pulls; running it against a stale local copy produces output that looks current and is
# not, which is worse than not running. The previous `|| true` is how a dead workstation
# address went unnoticed.
for src in "$@"; do
  dest_dir=$(dirname "${SYNC_HOME}/$src")
  mkdir -p "$dest_dir"
  if ! rsync -a --timeout=10 "hapax@${WORKSTATION}:~/${src}" "${SYNC_HOME}/${src}"; then
    echo "FATAL: cannot pull ${src} from ${WORKSTATION}; refusing to run ${AGENT} on stale input." >&2
    echo "Next: confirm ${WORKSTATION} is reachable (ping, then ssh hapax@${WORKSTATION} true). If the workstation address changed, set HAPAX_SYNC_WORKSTATION in the unit. Nothing retries this automatically; the next timer tick is the retry." >&2
    exit 1
  fi
done

# Run the agent
export GNUPGHOME="/home/hapax/.gnupg"
export PASSWORD_STORE_DIR="/home/hapax/.password-store"
export PYTHONPATH="$COUNCIL_DIR"
cd "$COUNCIL_DIR"
"$VENV" -m "agents.${AGENT}" --auto

# Post-sync: push agent-specific rag-sources and cache back to workstation.
#
# Also fatal. The agent ran; if its output never lands, the run accomplished nothing and a
# zero exit says otherwise. Reported as a distinct failure from the pre-sync case, because
# the two mean different things: bad input versus lost output.
push_failed=0
rsync -a --timeout=30 "${SYNC_HOME}/documents/rag-sources/${AGENT_DASH}/" \
  "hapax@${WORKSTATION}:~/documents/rag-sources/${AGENT_DASH}/" || push_failed=1
rsync -a --timeout=30 "${SYNC_HOME}/.cache/${AGENT_DASH}/" \
  "hapax@${WORKSTATION}:~/.cache/${AGENT_DASH}/" || push_failed=1
if [ "$push_failed" -ne 0 ]; then
  echo "FATAL: ${AGENT} produced output but it could not be pushed to ${WORKSTATION}." >&2
  echo "Next: the work is done and held locally under ${SYNC_HOME}/documents/rag-sources/${AGENT_DASH}/ and ${SYNC_HOME}/.cache/${AGENT_DASH}/ — it is not lost. Confirm ${WORKSTATION} is reachable; the next timer tick pushes the same directories again." >&2
  exit 1
fi

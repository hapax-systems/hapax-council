#!/bin/bash
# Sync agent wrapper for Pi6
# Usage: sync-agent-wrapper.sh <agent_module> [pre-sync-sources...]
#
# Handles rsync pre-pull of source files from workstation,
# runs the agent, then rsyncs output back.
set -euo pipefail

AGENT="$1"
shift
WORKSTATION="192.168.68.80"
COUNCIL_DIR="/home/hapax/projects/hapax-council"
VENV="$COUNCIL_DIR/.venv-sync/bin/python"
AGENT_DASH="${AGENT//_/-}"
MIN_DISK_MB=500

# Pre-flight: check disk space
avail_kb=$(df --output=avail / | tail -1)
avail_mb=$((avail_kb / 1024))
if [ "$avail_mb" -lt "$MIN_DISK_MB" ]; then
  echo "FATAL: Only ${avail_mb}MB free on / (need ${MIN_DISK_MB}MB). Aborting." >&2
  exit 1
fi

# Pre-sync: pull source files from workstation if specified
for src in "$@"; do
  dest_dir=$(dirname "/home/hapax/$src")
  mkdir -p "$dest_dir"
  rsync -a --timeout=10 "hapax@${WORKSTATION}:~/${src}" "/home/hapax/${src}" 2>/dev/null || true
done

# Run the agent
export PATH="/home/hapax/.local/bin:/usr/local/bin:/usr/bin:/bin"
export GNUPGHOME="/home/hapax/.gnupg"
export PASSWORD_STORE_DIR="/home/hapax/.password-store"
export PYTHONPATH="$COUNCIL_DIR"
cd "$COUNCIL_DIR"
"$VENV" -m "agents.${AGENT}" --auto

# Post-sync: push agent-specific rag-sources and cache back to workstation
rsync -a --timeout=30 "/home/hapax/documents/rag-sources/${AGENT_DASH}/" "hapax@${WORKSTATION}:~/documents/rag-sources/${AGENT_DASH}/" 2>/dev/null || true
rsync -a --timeout=30 "/home/hapax/.cache/${AGENT_DASH}/" "hapax@${WORKSTATION}:~/.cache/${AGENT_DASH}/" 2>/dev/null || true

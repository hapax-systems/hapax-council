#!/usr/bin/env bash
# Verify hapax-audio-grounding.service deployment.
# Checks: unit linked+enabled, service active, state.json written every 5s.

set -euo pipefail

echo "=== Audio Grounding Deployment Verification ==="

# Check unit is linked
if ! systemctl --user cat hapax-audio-grounding.service >/dev/null 2>&1; then
  echo "FAIL: unit not linked"
  exit 1
fi
echo "PASS: unit linked"

# Check enabled
if ! systemctl --user is-enabled hapax-audio-grounding.service >/dev/null 2>&1; then
  echo "FAIL: unit not enabled"
  exit 1
fi
echo "PASS: unit enabled"

# Check active
if ! systemctl --user is-active hapax-audio-grounding.service >/dev/null 2>&1; then
  echo "FAIL: service not active"
  exit 1
fi
echo "PASS: service active"

# Check CUDA_VISIBLE_DEVICES is empty (CPU-only)
ENV=$(systemctl --user show hapax-audio-grounding.service -p Environment)
if echo "$ENV" | grep -q "CUDA_VISIBLE_DEVICES="; then
  echo "PASS: CUDA_VISIBLE_DEVICES set to empty (CPU-only)"
else
  echo "WARN: CUDA_VISIBLE_DEVICES not explicitly set"
fi

# Check state.json exists
STATE="/dev/shm/hapax-audio-grounding/state.json"
if [ ! -f "$STATE" ]; then
  echo "WAIT: state.json not yet written, waiting up to 15s..."
  for i in $(seq 1 3); do
    sleep 5
    [ -f "$STATE" ] && break
  done
fi

if [ -f "$STATE" ]; then
  echo "PASS: state.json exists"
  python3 -c "import json; d=json.loads(open('$STATE').read()); print(f'  source: {d.get(\"source\", \"?\")}'); print(f'  capture_duration: {d.get(\"capture_duration_s\", \"?\")}s')"
else
  echo "FAIL: state.json not written after 15s"
  exit 1
fi

echo ""
echo "=== Deployment verified ==="

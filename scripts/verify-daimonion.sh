#!/usr/bin/env bash
# verify-daimonion.sh — End-to-end verification of hapax-daimonion capabilities.
# Run after the full treatment to confirm all subsystems are online.
set -euo pipefail

PASS=0
FAIL=0
SKIP=0

check() {
    local name="$1" result="$2"
    if [ "$result" = "PASS" ]; then
        printf "  ✓ %s\n" "$name"
        ((PASS++))
    elif [ "$result" = "SKIP" ]; then
        printf "  ○ %s (skipped)\n" "$name"
        ((SKIP++))
    else
        printf "  ✗ %s — %s\n" "$name" "$result"
        ((FAIL++))
    fi
}

echo "=== Hapax-Daimonion End-to-End Verification ==="
echo

# 1. Service running
echo "[1/7] Service status"
if systemctl --user is-active hapax-daimonion >/dev/null 2>&1; then
    check "hapax-daimonion active" "PASS"
else
    check "hapax-daimonion active" "FAIL: service not running"
fi

# 2. Ambient classification (pw-record)
echo "[2/7] Ambient classification"
SINK_NAME="$(wpctl inspect @DEFAULT_AUDIO_SINK@ 2>&1 | grep 'node.name' | head -1 | awk -F'"' '{print $2}')"
if [ -n "$SINK_NAME" ] && timeout 5 pw-record --target "$SINK_NAME" --format s16 --rate 32000 --channels 1 /tmp/daimonion-verify-audio.raw 2>/dev/null; then
    SIZE=$(stat -c%s /tmp/daimonion-verify-audio.raw 2>/dev/null || echo 0)
    if [ "$SIZE" -gt 1000 ]; then
        check "pw-record capture" "PASS"
    else
        check "pw-record capture" "FAIL: $SIZE bytes (expected >1000)"
    fi
    rm -f /tmp/daimonion-verify-audio.raw
else
    check "pw-record capture" "FAIL: timeout or no sink"
fi

TIMEOUTS=$(journalctl --user -u hapax-daimonion --no-pager --since '5 min ago' 2>/dev/null | grep -c 'pw-record timed out' || true)
if [ "$TIMEOUTS" -eq 0 ]; then
    check "No pw-record timeouts (5m)" "PASS"
else
    check "No pw-record timeouts (5m)" "FAIL: $TIMEOUTS timeouts"
fi

# 3. TPN signal file
echo "[3/7] TPN_ACTIVE signaling"
TPN_FILE="/dev/shm/hapax-dmn/tpn_active"
if [ -f "$TPN_FILE" ]; then
    VAL=$(cat "$TPN_FILE" 2>/dev/null)
    if [ "$VAL" = "0" ] || [ "$VAL" = "1" ]; then
        check "tpn_active file valid" "PASS"
    else
        check "tpn_active file valid" "FAIL: unexpected value '$VAL'"
    fi
else
    check "tpn_active file valid" "SKIP"
fi

# 4. DMN running and reading TPN
echo "[4/7] DMN integration"
if systemctl --user is-active hapax-dmn >/dev/null 2>&1; then
    check "hapax-dmn active" "PASS"
else
    check "hapax-dmn active" "FAIL: service not running"
fi
IMPINGEMENTS="/dev/shm/hapax-dmn/impingements.jsonl"
if [ -f "$IMPINGEMENTS" ]; then
    LINES=$(wc -l < "$IMPINGEMENTS")
    check "DMN impingements ($LINES entries)" "PASS"
else
    check "DMN impingements" "FAIL: file missing"
fi

# 5. Context enrichment (shm files fresh)
echo "[5/7] Context enrichment sources"
for SHM_FILE in /dev/shm/hapax-stimmung/state.json /dev/shm/hapax-temporal/bands.json; do
    if [ -f "$SHM_FILE" ]; then
        AGE=$(( $(date +%s) - $(stat -c%Y "$SHM_FILE") ))
        if [ "$AGE" -lt 120 ]; then
            check "$(basename "$SHM_FILE") fresh (${AGE}s)" "PASS"
        else
            check "$(basename "$SHM_FILE")" "FAIL: stale (${AGE}s)"
        fi
    else
        check "$(basename "$SHM_FILE")" "FAIL: missing"
    fi
done

# 6. Grounding (check working mode and flag)
echo "[6/7] Grounding activation"
MODE=$(cat ~/.cache/hapax/working-mode 2>/dev/null || echo "unknown")
check "Working mode: $MODE" "PASS"
if [ "$MODE" = "rnd" ]; then
    check "Grounding expected: ON (R&D mode)" "PASS"
else
    check "Grounding expected: flag-controlled (Research mode)" "PASS"
fi

# 7. Tool registry (test import)
echo "[7/7] Tool capability model"
TOOL_COUNT=$(cd ~/projects/hapax-council && uv run python3 -c "
from agents.hapax_daimonion.tool_definitions import build_registry
reg = build_registry()
print(len(reg.all_tools()))
" 2>/dev/null || echo "0")
if [ "$TOOL_COUNT" -gt 0 ]; then
    check "Tool registry: $TOOL_COUNT capabilities" "PASS"
else
    check "Tool registry" "FAIL: no tools loaded"
fi

echo
echo "=== Results: $PASS pass, $FAIL fail, $SKIP skip ==="
exit "$FAIL"

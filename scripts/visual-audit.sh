#!/usr/bin/env bash
# Visual audit — exercises every terrain view via WS relay and validates content.
# Requires: hapax-logos running with command relay on :8052, grim, hyprctl
set -uo pipefail

PASS=0; FAIL=0; WARNINGS=()
DIR="/tmp/logos-visual-audit-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DIR"
ID=0

pass() { ((PASS++)); printf "  ✓ %s\n" "$1"; }
fail() { ((FAIL++)); WARNINGS+=("$1"); printf "  ✗ %s\n" "$1"; }

# Pre-flight
if ! ss -tlnp 2>/dev/null | grep -q ':8052 '; then
    echo "ABORT: command relay not listening on :8052 (hapax-logos not running?)"
    exit 1
fi

if ! command -v grim &>/dev/null; then
    echo "ABORT: grim not installed"
    exit 1
fi

send() {
    local cmd="$1" args="$2"
    ((ID++))
    python3 -c "
import asyncio, websockets, json
async def go():
    async with websockets.connect('ws://127.0.0.1:8052/ws/commands') as ws:
        msg = {'type': 'execute', 'id': str($ID), 'command': '$cmd', 'args': $args}
        await ws.send(json.dumps(msg))
        try:
            await asyncio.wait_for(ws.recv(), timeout=3)
        except:
            pass
asyncio.run(go())
" 2>/dev/null
}

shot() {
    sleep 1.5
    local geom
    geom=$(hyprctl clients -j 2>/dev/null | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    if 'logos' in c.get('class','').lower():
        x,y = c['at']; w,h = c['size']
        print(f'{x},{y} {w}x{h}')
" 2>/dev/null)
    if [[ -n "$geom" ]]; then
        grim -g "$geom" "$DIR/$1" 2>/dev/null
    else
        echo "  (window not found, skipping screenshot)"
    fi
}

check_size() {
    local name="$1" file="$DIR/$2" min_kb="${3:-10}"
    if [[ -f "$file" ]]; then
        local size_kb=$(( $(stat -c %s "$file") / 1024 ))
        if [[ "$size_kb" -ge "$min_kb" ]]; then
            pass "$name (${size_kb}KB)"
        else
            fail "$name too small (${size_kb}KB < ${min_kb}KB)"
        fi
    else
        fail "$name — screenshot missing"
    fi
}

echo "=== Logos Visual Audit ==="
echo "Screenshots: $DIR"
echo ""

# ── API Data Availability ──
echo "[API data]"
nudge_count=$(curl -s http://localhost:8051/api/nudges 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
[[ "$nudge_count" -gt 0 ]] && pass "nudges: $nudge_count" || fail "nudges: 0 (agents haven't run)"

flow_nodes=$(curl -s http://localhost:8051/api/flow/state 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('nodes',[])))" 2>/dev/null || echo "0")
[[ "$flow_nodes" -gt 5 ]] && pass "flow: $flow_nodes nodes" || fail "flow: $flow_nodes nodes"

cameras=$(curl -s http://localhost:8051/api/studio/cameras 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else len(d.get('cameras',{})))" 2>/dev/null || echo "0")
[[ "$cameras" -gt 0 ]] && pass "cameras: $cameras" || fail "cameras: 0"

presets=$(curl -s http://localhost:8051/api/studio/presets 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else len(d.get('presets',d.get('built_in',[]))))" 2>/dev/null || echo "0")
[[ "$presets" -gt 10 ]] && pass "presets: $presets" || fail "presets: $presets"

# ── Reset to surface ──
for r in horizon field ground watershed bedrock; do
    send "terrain.focus" "{\"region\": \"$r\", \"depth\": \"surface\"}"
done
sleep 1

# ── Surface default ──
echo ""
echo "[Surface default]"
shot "surface.png"
check_size "surface" "surface.png"

# ── Each region at each depth ──
echo ""
echo "[Region depth transitions]"
for region in horizon field ground watershed bedrock; do
    for depth in stratum core; do
        send "terrain.focus" "{\"region\": \"$region\", \"depth\": \"$depth\"}"
        shot "${region}-${depth}.png"
        check_size "$region/$depth" "${region}-${depth}.png"
    done
    send "terrain.focus" "{\"region\": \"$region\", \"depth\": \"surface\"}"
    sleep 0.3
done

# ── Split view ──
echo ""
echo "[Split view]"
send "split.open" '{"region": "ground"}'
shot "split-studio.png"
check_size "split/studio" "split-studio.png"
send "split.close" '{}'

# ── Overlays ──
echo ""
echo "[Overlays]"
send "overlay.set" '{"name": "investigation"}'
shot "investigation.png"
check_size "investigation" "investigation.png"
send "overlay.clear" '{}'

# ── Reset and final ──
for r in horizon field ground watershed bedrock; do
    send "terrain.focus" "{\"region\": \"$r\", \"depth\": \"surface\"}"
done
shot "final.png"

# ── Summary ──
echo ""
echo "========================================"
echo "  VISUAL AUDIT: Pass=$PASS Fail=$FAIL"
echo "  Screenshots: $DIR"
echo "========================================"
if [[ ${#WARNINGS[@]} -gt 0 ]]; then
    echo ""
    echo "FAILURES:"
    for w in "${WARNINGS[@]}"; do echo "  - $w"; done
fi
exit "$FAIL"

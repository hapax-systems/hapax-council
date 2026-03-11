#!/bin/bash
set -euo pipefail

# Live smoke tests for hapax-voice daemon
# Requires: daemon running, socat installed

SOCKET="/run/user/1000/hapax-voice.sock"
PASS=0
FAIL=0

pass() { echo "  ✓ $1"; ((PASS++)); }
fail() { echo "  ✗ $1"; ((FAIL++)); }

check_log() {
    local seconds=$1
    local pattern=$2
    journalctl --user -u hapax-voice --since "${seconds} sec ago" --no-pager 2>/dev/null | grep -q "$pattern"
}

echo "=== Hapax Voice Daemon Smoke Tests ==="
echo ""

# --- Prerequisite checks ---
echo "Prerequisites:"

if systemctl --user is-active hapax-voice.service >/dev/null 2>&1; then
    pass "Daemon is running"
else
    fail "Daemon is not running"
    echo "  Start with: systemctl --user start hapax-voice.service"
    exit 1
fi

if [ -S "$SOCKET" ]; then
    pass "Hotkey socket exists"
else
    fail "Hotkey socket missing at $SOCKET"
    exit 1
fi

if command -v socat >/dev/null 2>&1; then
    pass "socat available"
else
    fail "socat not installed (apt install socat)"
    exit 1
fi

echo ""

# --- Surface 8: Hotkey commands ---
echo "Surface 8: Hotkey Commands"

echo "status" | socat - UNIX-CONNECT:"$SOCKET" 2>/dev/null || true
sleep 1
if check_log 3 "Status:"; then
    pass "status command received"
else
    fail "status command not received"
fi

# --- Surface 3: Session lifecycle ---
echo ""
echo "Surface 3: Session Lifecycle"

echo "open" | socat - UNIX-CONNECT:"$SOCKET" 2>/dev/null || true
sleep 2
if check_log 5 "session_lifecycle.*opened"; then
    pass "session opened via hotkey"
else
    if check_log 5 "opened.*hotkey\|Voice conversation opened"; then
        pass "session opened via hotkey"
    else
        fail "session did not open"
    fi
fi

echo "close" | socat - UNIX-CONNECT:"$SOCKET" 2>/dev/null || true
sleep 2
if check_log 5 "session_lifecycle.*closed\|Voice conversation closed"; then
    pass "session closed via hotkey"
else
    fail "session did not close"
fi

# --- Surface 1: Wake word (manual) ---
echo ""
echo "Surface 1: Wake Word (requires manual test)"
echo "  → Say 'Hapax' near the microphone"
echo "  → Verify: chime plays, session opens, pipeline starts"
echo "  → Check: journalctl --user -u hapax-voice -f | grep -i 'wake\|session\|pipeline'"

# --- Surface 2: Voice round-trip (manual) ---
echo ""
echo "Surface 2: Voice Round-Trip (requires manual test)"
echo "  → After wake word, speak a question"
echo "  → Verify: STT transcription appears in logs"
echo "  → Verify: LLM response generated"
echo "  → Verify: TTS audio plays through speakers"
echo "  → Check: journalctl --user -u hapax-voice -f"

# --- Surface 7: Notification delivery ---
echo ""
echo "Surface 7: Notifications"

if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/hapax-alerts 2>/dev/null | grep -q "200"; then
    pass "ntfy endpoint reachable"
else
    fail "ntfy endpoint not reachable"
fi

# --- Surface 5: Desktop state ---
echo ""
echo "Surface 5: Desktop (Hyprland)"

if check_log 300 "Connected to Hyprland event socket"; then
    pass "Hyprland event socket connected"
else
    fail "Hyprland event socket not connected"
fi

# --- Surface 6: Perception/Governor ---
echo ""
echo "Surface 6: Perception → Governor"

if check_log 300 "FrameGate directive"; then
    pass "Governor producing directives"
else
    fail "No governor directives in recent logs"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ $FAIL -gt 0 ]; then
    exit 1
fi

#!/usr/bin/env bash
# Production visual audit for the post-Tauri Logos stack.
#
# Validates that the livestream surface is owned by logos-api +
# studio-compositor/OBS/V4L2, and that retired Tauri/WebKit listener ports are
# absent. This intentionally does not send commands through the old :8052 relay.
set -uo pipefail

PASS=0
FAIL=0
WARNINGS=()

pass() { ((PASS++)); printf "  ok  %s\n" "$1"; }
fail() { ((FAIL++)); WARNINGS+=("$1"); printf "  fail %s\n" "$1"; }

port_listening() {
    local port="$1"
    ss -ltnp 2>/dev/null | grep -q ":${port} "
}

retired_processes() {
    python3 - <<'PY'
import os
import subprocess

for line in subprocess.check_output(["ps", "-eo", "pid=,comm=,args="], text=True).splitlines():
    parts = line.strip().split(None, 2)
    if len(parts) < 3:
        continue
    pid_text, command_name, args = parts
    try:
        pid = int(pid_text)
    except ValueError:
        continue
    if pid in {os.getpid(), os.getppid()}:
        continue
    normalized_args = " ".join(args.split())
    if command_name in {"hapax-logos", "WebKitWebProcess", "vite"}:
        print(line)
        continue
    if "pnpm tauri dev" in normalized_args or "pnpm dev" in normalized_args:
        print(line)
        continue
    if "/vite/bin/vite" in normalized_args or " node_modules/.bin/vite" in normalized_args:
        print(line)
PY
}

camera_count() {
    curl -fsS "http://127.0.0.1:8051/api/studio/cameras" 2>/dev/null \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d.get("cameras"); assert isinstance(c, (dict, list)); print(len(c))' 2>/dev/null \
        || echo "-1"
}

echo "=== Hapax Production Visual Audit ==="
echo ""

echo "[Retired Tauri/WebKit surface]"
retired_process_output="$(retired_processes)"
if [[ -n "$retired_process_output" ]]; then
    fail "retired Tauri/WebKit/Vite process is running"
else
    pass "no retired Tauri/WebKit/Vite processes"
fi

for port in 8052 8053 8054 5173; do
    if port_listening "$port"; then
        fail "retired listener :$port is active"
    else
        pass "retired listener :$port absent"
    fi
done

echo ""
echo "[Central surfaces]"
if port_listening 8051; then
    pass "logos-api :8051 listening"
else
    fail "logos-api :8051 not listening"
fi

camera_count="$(camera_count)"
if [[ "$camera_count" -ge 0 ]]; then
    pass "studio cameras endpoint via logos-api responded: $camera_count registered"
else
    fail "studio cameras endpoint via logos-api unavailable or malformed"
fi

egress_state=$(curl -fsS "http://127.0.0.1:8051/api/studio/egress/state" 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state", "unknown"))' 2>/dev/null \
    || echo "unknown")
if [[ "$egress_state" != "unknown" ]]; then
    pass "livestream egress resolver responded: $egress_state"
else
    fail "livestream egress resolver unavailable"
fi

if [[ -e /dev/video42 ]]; then
    pass "OBS/V4L2 compositor output present at /dev/video42"
else
    fail "OBS/V4L2 compositor output /dev/video42 missing"
fi

echo ""
echo "PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
    printf "\nFailures:\n"
    printf "  - %s\n" "${WARNINGS[@]}"
    exit 1
fi

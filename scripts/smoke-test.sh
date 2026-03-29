#!/usr/bin/env bash
# Hapax System Smoke Test
# Tiers: T1 infrastructure, T2 API, T3 data flow, T4 visual, T5 integration
set -uo pipefail

PASS=0; FAIL=0; WARN=0; SKIP=0
FAILURES=()
WARNINGS=()

pass() { ((PASS++)); printf "  ✓ %s\n" "$1"; }
fail() { ((FAIL++)); FAILURES+=("$1"); printf "  ✗ %s\n" "$1"; }
warn() { ((WARN++)); WARNINGS+=("$1"); printf "  ~ %s\n" "$1"; }
skip() { ((SKIP++)); printf "  - %s (skipped)\n" "$1"; }

# --- T1: Infrastructure ---
echo "=== T1: Infrastructure ==="

echo "[Docker]"
# Core containers from docker/docker-compose.yml + infrastructure
EXPECTED_CONTAINERS=(litellm qdrant postgres langfuse redis clickhouse minio n8n ntfy prometheus grafana)
for c in "${EXPECTED_CONTAINERS[@]}"; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "$c"; then
        pass "docker: $c running"
    else
        fail "docker: $c not running"
    fi
done

echo "[Systemd - critical services]"
CRITICAL_SERVICES=(logos-api hapax-imagination hapax-daimonion visual-layer-aggregator)
for svc in "${CRITICAL_SERVICES[@]}"; do
    status=$(systemctl --user is-active "$svc" 2>/dev/null || echo "inactive")
    if [[ "$status" == "active" ]]; then
        pass "systemd: $svc active"
    elif [[ "$status" == "activating" ]]; then
        warn "systemd: $svc activating"
    else
        fail "systemd: $svc $status"
    fi
done

echo "[Systemd - failed units]"
failed_count=$(systemctl --user --state=failed --no-legend 2>/dev/null | wc -l)
if [[ "$failed_count" -eq 0 ]]; then
    pass "systemd: no failed units"
else
    warn "systemd: $failed_count failed unit(s)"
    systemctl --user --state=failed --no-legend 2>/dev/null | while read -r line; do
        printf "    %s\n" "$line"
    done
fi

echo "[GPU]"
gpu_info=$(nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>/dev/null || echo "")
if [[ -n "$gpu_info" ]]; then
    used=$(echo "$gpu_info" | cut -d',' -f1 | tr -d ' ')
    total=$(echo "$gpu_info" | cut -d',' -f2 | tr -d ' ')
    util=$(echo "$gpu_info" | cut -d',' -f3 | tr -d ' ')
    pct=$((used * 100 / total))
    if [[ "$pct" -lt 90 ]]; then
        pass "GPU: ${used}/${total} MiB (${pct}%), util ${util}%"
    else
        warn "GPU: ${used}/${total} MiB (${pct}%) — high usage"
    fi
else
    fail "GPU: nvidia-smi unavailable"
fi

# --- T2: API Surface ---
echo ""
echo "=== T2: API Surface (logos-api :8051) ==="

API="http://localhost:8051/api"

probe() {
    local name="$1" path="$2" expect="${3:-200}"
    code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 5 "$API$path" 2>/dev/null) || code="000"
    if [[ "$code" == "000" ]]; then
        fail "API $name (connection failed)"
    elif echo " $expect " | grep -q " $code "; then
        pass "API $name ($code)"
    else
        fail "API $name (got $code, expected $expect)"
    fi
}

echo "[Core data endpoints]"
probe "agents"          "/agents"
probe "agents/current"  "/agents/runs/current"
probe "profile"         "/profile"
probe "working-mode"    "/working-mode"
probe "governance/heartbeat" "/governance/heartbeat"

echo "[Engine & flow]"
probe "engine/status"   "/engine/status"
probe "engine/rules"    "/engine/rules"
probe "flow/state"      "/flow/state"

echo "[Studio & visual]"
probe "studio"          "/studio"
probe "studio/presets"  "/studio/presets"
probe "studio/cameras"  "/studio/cameras"
probe "studio/perception" "/studio/perception"

echo "[Consent & governance]"
probe "consent/contracts" "/consent/contracts"
probe "consent/coverage"  "/consent/coverage"
probe "governance/coverage" "/governance/coverage"
probe "governance/authority" "/governance/authority"

echo "[Scout & nudges]"
probe "scout"           "/scout"
probe "nudges"          "/nudges"

echo "[Chat]"
probe "chat/models"     "/chat/models"
probe "chat/sessions"   "/chat/sessions" "200 405"

# --- T3: Data Flow (shared memory freshness) ---
echo ""
echo "=== T3: Data Flow (shared memory) ==="

check_shm() {
    local name="$1" path="$2" max_age_s="${3:-7200}"
    if [[ ! -e "$path" ]]; then
        fail "shm: $name missing ($path)"
        return
    fi
    age=$(( $(date +%s) - $(stat -c %Y "$path") ))
    if [[ "$age" -lt "$max_age_s" ]]; then
        pass "shm: $name (${age}s old)"
    else
        warn "shm: $name stale (${age}s, max ${max_age_s}s)"
    fi
}

check_shm "stimmung state"     "/dev/shm/hapax-stimmung/state.json"        120
check_shm "visual frame"       "/dev/shm/hapax-visual/frame.jpg"           30
check_shm "temporal bands"     "/dev/shm/hapax-temporal/bands.json"        600
check_shm "pipeline plan"      "/dev/shm/hapax-imagination/pipeline/plan.json" 3600
# compositor state.json only exists when studio-compositor is actively running
if [[ -f /dev/shm/hapax-compositor/state.json ]]; then
    check_shm "compositor state"   "/dev/shm/hapax-compositor/state.json"      120
else
    skip "compositor state (not active)"
fi

echo "[Sensor feeds]"
sensor_count=0
stale_sensors=0
for f in /dev/shm/hapax-sensors/*.json; do
    [[ -f "$f" ]] || continue
    ((sensor_count++))
    age=$(( $(date +%s) - $(stat -c %Y "$f") ))
    if [[ "$age" -gt 28800 ]]; then
        ((stale_sensors++))
    fi
done
if [[ "$sensor_count" -eq 0 ]]; then
    warn "shm: no sensor feeds found"
elif [[ "$stale_sensors" -eq 0 ]]; then
    pass "shm: $sensor_count sensor feeds, all fresh"
else
    warn "shm: $stale_sensors/$sensor_count sensor feeds stale"
fi

# --- T4: Visual Pipeline ---
echo ""
echo "=== T4: Visual Pipeline (hapax-imagination) ==="

echo "[Pipeline state]"
if systemctl --user is-active hapax-imagination &>/dev/null; then
    # Check frame output is being written
    if [[ -f /dev/shm/hapax-visual/frame.jpg ]]; then
        size=$(stat -c %s /dev/shm/hapax-visual/frame.jpg)
        age=$(( $(date +%s) - $(stat -c %Y /dev/shm/hapax-visual/frame.jpg) ))
        if [[ "$age" -lt 15 && "$size" -gt 1000 ]]; then
            pass "visual: frame.jpg live (${size}B, ${age}s old)"
        elif [[ "$age" -lt 60 ]]; then
            warn "visual: frame.jpg delayed (${age}s old)"
        else
            fail "visual: frame.jpg stale (${age}s old)"
        fi
    else
        fail "visual: frame.jpg missing"
    fi

    # Check plan.json validity
    if [[ -f /dev/shm/hapax-imagination/pipeline/plan.json ]]; then
        passes=$(python3 -c "import json; print(len(json.load(open('/dev/shm/hapax-imagination/pipeline/plan.json'))['passes']))" 2>/dev/null || echo "0")
        if [[ "$passes" -gt 0 ]]; then
            pass "visual: plan.json valid ($passes passes)"
        else
            fail "visual: plan.json empty or invalid"
        fi
    else
        fail "visual: plan.json missing"
    fi

    # Check journal for recent panics
    panics=$(journalctl --user -u hapax-imagination --since "5min ago" --no-pager 2>/dev/null | grep -c "panicked" || true)
    panics=${panics:-0}
    panics=$(echo "$panics" | tr -d '[:space:]')
    if [[ "$panics" -eq 0 ]]; then
        pass "visual: no panics in last 5min"
    else
        fail "visual: $panics panic(s) in last 5min"
    fi
else
    skip "visual pipeline (service not running)"
fi

echo "[Preset hot-reload]"
if systemctl --user is-active hapax-imagination &>/dev/null; then
    # Record current preset pass count
    before=$(python3 -c "import json; print(len(json.load(open('/dev/shm/hapax-imagination/pipeline/plan.json'))['passes']))" 2>/dev/null || echo "0")

    # Activate a different preset
    result=$(curl -s -X POST "$API/studio/presets/clean/activate" 2>/dev/null)
    if echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('status')=='ok' else 1)" 2>/dev/null; then
        sleep 2
        after=$(python3 -c "import json; print(len(json.load(open('/dev/shm/hapax-imagination/pipeline/plan.json'))['passes']))" 2>/dev/null || echo "0")
        if [[ "$after" -gt 0 && "$after" != "$before" ]]; then
            pass "visual: hot-reload works (${before} -> ${after} passes)"
        elif [[ "$after" -gt 0 ]]; then
            pass "visual: hot-reload works ($after passes)"
        else
            fail "visual: hot-reload failed (plan empty after switch)"
        fi

        # Restore ambient
        curl -s -X POST "$API/studio/presets/ambient/activate" >/dev/null 2>&1
        sleep 1
    else
        fail "visual: preset activation API failed"
    fi

    # Check service survived the reload
    if systemctl --user is-active hapax-imagination &>/dev/null; then
        pass "visual: service survived hot-reload"
    else
        fail "visual: service crashed during hot-reload"
    fi
else
    skip "preset hot-reload (service not running)"
fi

# --- T5: Integration ---
echo ""
echo "=== T5: Integration ==="

echo "[LiteLLM gateway]"
# LiteLLM /health requires API key — 401 means reachable but unauthenticated, which is fine for smoke test
litellm_code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://localhost:4000/health" 2>/dev/null) || litellm_code="000"
if [[ "$litellm_code" == "200" || "$litellm_code" == "401" ]]; then
    pass "litellm: council gateway reachable ($litellm_code)"
else
    fail "litellm: council gateway ($litellm_code)"
fi

# Officium LiteLLM (:4100) is in the officium project's docker-compose, not council's
litellm_off_code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 "http://localhost:4100/health" 2>/dev/null) || litellm_off_code="000"
if [[ "$litellm_off_code" == "200" || "$litellm_off_code" == "401" ]]; then
    pass "litellm: officium gateway reachable ($litellm_off_code)"
elif [[ "$litellm_off_code" == "000" ]]; then
    warn "litellm: officium gateway not running (separate project)"
else
    fail "litellm: officium gateway ($litellm_off_code)"
fi

echo "[Qdrant vector DB]"
qdrant_code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://localhost:6333/collections" 2>/dev/null) || true
if [[ "$qdrant_code" == "200" ]]; then
    collections=$(curl -s "http://localhost:6333/collections" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('result',{}).get('collections',[])))" 2>/dev/null || echo "?")
    pass "qdrant: healthy ($collections collections)"
else
    fail "qdrant: unreachable ($qdrant_code)"
fi

echo "[Ollama local inference]"
ollama_code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://localhost:11434/api/tags" 2>/dev/null) || true
if [[ "$ollama_code" == "200" ]]; then
    models=$(curl -s "http://localhost:11434/api/tags" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
    pass "ollama: healthy ($models models)"
else
    fail "ollama: unreachable ($ollama_code)"
fi

echo "[Officium API]"
off_code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://localhost:8050/api/agents" 2>/dev/null) || true
if [[ "$off_code" == "200" ]]; then
    pass "officium-api: healthy"
else
    warn "officium-api: ($off_code)"
fi

echo "[Langfuse observability]"
langfuse_code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://localhost:3000" 2>/dev/null) || true
if [[ "$langfuse_code" == "200" || "$langfuse_code" == "302" ]]; then
    pass "langfuse: reachable ($langfuse_code)"
else
    fail "langfuse: unreachable ($langfuse_code)"
fi

echo "[ntfy notifications]"
ntfy_code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://localhost:8090" 2>/dev/null) || true
if [[ "$ntfy_code" == "200" || "$ntfy_code" == "301" || "$ntfy_code" == "302" ]]; then
    pass "ntfy: reachable"
else
    warn "ntfy: ($ntfy_code)"
fi

# --- Summary ---
echo ""
echo "========================================"
TOTAL=$((PASS + FAIL + WARN + SKIP))
echo "  SMOKE TEST RESULTS"
echo "  Pass: $PASS  Fail: $FAIL  Warn: $WARN  Skip: $SKIP  Total: $TOTAL"
echo "========================================"

if [[ ${#FAILURES[@]} -gt 0 ]]; then
    echo ""
    echo "FAILURES:"
    for f in "${FAILURES[@]}"; do
        echo "  - $f"
    done
fi

if [[ ${#WARNINGS[@]} -gt 0 ]]; then
    echo ""
    echo "WARNINGS:"
    for w in "${WARNINGS[@]}"; do
        echo "  - $w"
    done
fi

exit "$FAIL"

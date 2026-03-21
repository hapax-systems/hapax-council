#!/usr/bin/env fish
# experiment-check.fish — validate all workstation optimizations before a SCED session

set -g pass_count 0
set -g fail_count 0

function check
    set -l label $argv[1]
    set -l result $argv[2]
    set -l expected $argv[3]
    if test "$result" = "$expected"
        echo "  [PASS] $label"
        set -g pass_count (math $pass_count + 1)
    else
        echo "  [FAIL] $label (got: $result, expected: $expected)"
        set -g fail_count (math $fail_count + 1)
    end
end

echo "=== Experiment Readiness Check ==="
echo ""

# Python runtime
echo "Python Runtime:"
set -l uvloop_ok (uv run python -c "import uvloop; print('ok')" 2>/dev/null)
check "uvloop importable" "$uvloop_ok" "ok"

# GPU
echo "GPU:"
set -l gpu_clock (nvidia-smi --query-gpu=clocks.gr --format=csv,noheader,nounits 2>/dev/null | string trim)
check "GPU clock locked at 1800 MHz" "$gpu_clock" "1800"

set -l power_limit (nvidia-smi --query-gpu=power.limit --format=csv,noheader,nounits 2>/dev/null | string trim)
check "Power limit 350W" "$power_limit" "350.00"

# Ollama
echo "Ollama:"
set -l ollama_parallel (systemctl show ollama --property=Environment 2>/dev/null | grep -oP 'OLLAMA_NUM_PARALLEL=\K[^ "]*')
check "OLLAMA_NUM_PARALLEL=1" "$ollama_parallel" "1"

set -l ollama_keepalive (systemctl show ollama --property=Environment 2>/dev/null | grep -oP 'OLLAMA_KEEP_ALIVE=\K[^ "]*')
check "OLLAMA_KEEP_ALIVE=24h" "$ollama_keepalive" "24h"

set -l ollama_ctx (systemctl show ollama --property=Environment 2>/dev/null | grep -oP 'OLLAMA_CONTEXT_LENGTH=\K[^ "]*')
check "OLLAMA_CONTEXT_LENGTH=4096" "$ollama_ctx" "4096"

# PipeWire
echo "PipeWire:"
set -l pw_quantum (pw-cli info 0 2>/dev/null | grep 'default.clock.quantum =' | string replace -r '.*"(\d+)"' '$1')
check "PipeWire quantum=128" "$pw_quantum" "128"

# Sysctl
echo "Sysctl:"
set -l dirty_bytes (sysctl -n vm.dirty_bytes 2>/dev/null)
check "vm.dirty_bytes=134217728" "$dirty_bytes" "134217728"

set -l dirty_bg (sysctl -n vm.dirty_background_bytes 2>/dev/null)
check "vm.dirty_background_bytes=33554432" "$dirty_bg" "33554432"

# Redis
echo "Redis:"
set -l redis_policy (docker exec redis redis-cli -a redissecret CONFIG GET maxmemory-policy 2>/dev/null | tail -1)
check "Redis maxmemory-policy=noeviction" "$redis_policy" "noeviction"

# Qdrant
echo "Qdrant:"
set -l qdrant_healthy (docker inspect --format='{{.State.Health.Status}}' qdrant 2>/dev/null)
check "Qdrant healthy" "$qdrant_healthy" "healthy"

# IRQ affinity
echo "IRQ Affinity:"
set -l irq_banned (systemctl show irqbalance --property=Environment 2>/dev/null | grep -oP 'IRQBALANCE_BANNED_CPUS=\K[^ "]*')
check "IRQ CPUs 14-15 banned" "$irq_banned" "0000c000"

echo ""
echo "=== Results: $pass_count passed, $fail_count failed ==="

if test $fail_count -gt 0
    echo "EXPERIMENT NOT READY — fix failures above before starting a session."
    exit 1
else
    echo "All checks passed. Workstation ready for experiment."
    exit 0
end

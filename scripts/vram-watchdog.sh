#!/usr/bin/env bash
# VRAM watchdog — prevent GPU memory exhaustion.
#
# Actions at thresholds:
#   >85%: Unload idle Ollama models (keep_alive=0)
#   >90%: Kill duplicate voice/compositor processes (keep newest)
#   >95%: Emergency — unload ALL Ollama models and notify
#
# Runs every 30s via systemd timer.
set -uo pipefail

LOG_TAG="vram-watchdog"
log() { logger -t "$LOG_TAG" "$1"; echo "$(date +%H:%M:%S) $1"; }

# Get VRAM usage
USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)

if [ -z "$USED" ] || [ -z "$TOTAL" ] || [ "$TOTAL" -eq 0 ]; then
    exit 0
fi

PCT=$((USED * 100 / TOTAL))
FREE=$((TOTAL - USED))

if [ "$PCT" -lt 85 ]; then
    exit 0
fi

log "VRAM at ${PCT}% (${USED}/${TOTAL} MiB, ${FREE} MiB free)"

# ── 85%+ : Unload idle Ollama models ──
if [ "$PCT" -ge 85 ]; then
    models=$(curl -sf http://127.0.0.1:11434/api/ps 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
for m in d.get('models', []):
    print(m['name'])
" 2>/dev/null)

    if [ -n "$models" ]; then
        for model in $models; do
            curl -sf -X POST http://127.0.0.1:11434/api/generate \
                -d "{\"model\":\"${model}\",\"keep_alive\":0}" >/dev/null 2>&1
            log "Unloaded Ollama model: $model"
        done
    fi
fi

# ── 90%+ : Kill duplicate GPU processes (keep newest per type) ──
if [ "$PCT" -ge 90 ]; then
    # Find duplicate voice daemons — keep the one systemd tracks
    VOICE_PID=$(systemctl --user show hapax-daimonion.service -p MainPID --value 2>/dev/null || echo 0)

    for pid in $(nvidia-smi --query-compute-apps=pid,name --format=csv,noheader 2>/dev/null | grep hapax_daimonion | cut -d, -f1 | tr -d ' '); do
        if [ "$pid" != "$VOICE_PID" ] && [ "$pid" != "0" ]; then
            log "Killing duplicate voice daemon PID $pid (systemd tracks $VOICE_PID)"
            kill "$pid" 2>/dev/null || true
        fi
    done

    # Find duplicate studio compositors — keep newest
    COMPOSITOR_PIDS=$(nvidia-smi --query-compute-apps=pid,name --format=csv,noheader 2>/dev/null | grep studio_compositor | cut -d, -f1 | tr -d ' ' | sort -n)
    COMPOSITOR_COUNT=$(echo "$COMPOSITOR_PIDS" | grep -c .)
    if [ "$COMPOSITOR_COUNT" -gt 1 ]; then
        echo "$COMPOSITOR_PIDS" | head -n $((COMPOSITOR_COUNT - 1)) | while read -r pid; do
            log "Killing duplicate compositor PID $pid"
            kill "$pid" 2>/dev/null || true
        done
    fi

    # Kill rogue GPU processes — anything not in the allowlist
    # Allowlist: hapax_daimonion, studio_compositor, video_processor, ollama_llama_server
    ALLOWLIST="hapax_daimonion|studio_compositor|video_processor|ollama_llama_server"
    while IFS=, read -r pid name; do
        pid=$(echo "$pid" | tr -d ' ')
        name=$(echo "$name" | tr -d ' ')
        [ -z "$pid" ] && continue
        if ! echo "$name" | grep -qE "$ALLOWLIST"; then
            log "Killing rogue GPU process PID $pid ($name) — not in allowlist"
            kill "$pid" 2>/dev/null || true
        fi
    done < <(nvidia-smi --query-compute-apps=pid,name --format=csv,noheader 2>/dev/null)
fi

# ── 95%+ : Emergency — force unload everything and alert ──
if [ "$PCT" -ge 95 ]; then
    log "EMERGENCY: VRAM at ${PCT}% — force unloading all Ollama models"
    # Unload all via Ollama API
    curl -sf http://127.0.0.1:11434/api/ps 2>/dev/null | python3 -c "
import sys, json, subprocess
d = json.load(sys.stdin)
for m in d.get('models', []):
    subprocess.run(['curl', '-sf', '-X', 'POST', 'http://127.0.0.1:11434/api/generate',
        '-d', json.dumps({'model': m['name'], 'keep_alive': 0})],
        capture_output=True)
" 2>/dev/null

    notify-send -u critical "VRAM Emergency" "GPU at ${PCT}% (${FREE}MiB free) — models unloaded" 2>/dev/null || true
fi

#!/usr/bin/env bash
# Automated cache cleanup — runs weekly via systemd timer.
# Keeps disk usage in steady state by pruning reproducible caches.
set -euo pipefail

LOG_TAG="cache-cleanup"
log() { logger -t "$LOG_TAG" "$1"; echo "$(date +%H:%M:%S) $1"; }

log "Starting cache cleanup"

# 1. Docker build cache (fully reclaimable)
BEFORE=$(docker system df --format '{{.Size}}' 2>/dev/null | head -1)
docker builder prune -f --filter "until=168h" >/dev/null 2>&1 || true
log "Docker build cache pruned (was: $BEFORE)"

# 2. Docker dangling images
docker image prune -f >/dev/null 2>&1 || true
log "Docker dangling images pruned"

# 3. uv package cache
uv cache prune --force 2>/dev/null || true
log "uv cache pruned"

# 4. pacman package cache — keep only 1 version
if command -v paccache &>/dev/null; then
    sudo paccache -rk1 2>/dev/null || true
    log "pacman cache pruned (keeping 1 version)"
fi

# 5. Remove worktree .venvs that haven't been touched in 7+ days
for venv in /home/hapax/projects/*--*/.venv; do
    if [ -d "$venv" ]; then
        age_days=$(( ($(date +%s) - $(stat -c %Y "$venv" 2>/dev/null || echo 0)) / 86400 ))
        if [ "$age_days" -gt 7 ]; then
            size=$(du -sh "$venv" 2>/dev/null | cut -f1)
            rm -rf "$venv"
            log "Removed stale worktree venv: $venv ($size, ${age_days}d old)"
        fi
    fi
done

# 6. Leaked audio temp files (pacat captures not cleaned up)
wav_count=$(find /tmp -name "tmp*.wav" -user hapax -mmin +5 2>/dev/null | wc -l)
if [ "$wav_count" -gt 0 ]; then
    wav_size=$(find /tmp -name "tmp*.wav" -user hapax -mmin +5 -printf "%s\n" 2>/dev/null | awk '{t+=$1} END {printf "%.0f", t/1024/1024}')
    find /tmp -name "tmp*.wav" -user hapax -mmin +5 -delete 2>/dev/null || true
    log "Removed $wav_count leaked wav files (${wav_size}MB)"
fi
# Leaked webcam temp dirs
find /tmp -name "webcam-*" -type d -user hapax -mmin +10 -exec rm -rf {} + 2>/dev/null || true

# 7. Chrome crash reports and shader cache
rm -rf /home/hapax/.config/google-chrome/Crash\ Reports/ 2>/dev/null || true
rm -rf /home/hapax/.config/google-chrome/ShaderCache/ 2>/dev/null || true
rm -rf /home/hapax/.config/google-chrome/GrShaderCache/ 2>/dev/null || true

# 7. Python __pycache__ cleanup (stale bytecode from old code)
find /home/hapax/projects -name "__pycache__" -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true

# 8. Perception minutes log — keep 7 days
PERCEPTION_LOG="$HOME/.cache/hapax-voice/perception-minutes.jsonl"
if [ -f "$PERCEPTION_LOG" ]; then
    cutoff=$(date -d "7 days ago" +%s)
    before_lines=$(wc -l < "$PERCEPTION_LOG")
    # Keep lines with timestamp >= cutoff (JSON field "timestamp")
    python3 -c "
import json, sys
cutoff = float(sys.argv[1])
kept = 0
for line in open(sys.argv[2]):
    try:
        if json.loads(line).get('timestamp', 0) >= cutoff:
            sys.stdout.write(line)
            kept += 1
    except (json.JSONDecodeError, ValueError):
        pass
" "$cutoff" "$PERCEPTION_LOG" > "${PERCEPTION_LOG}.tmp" && mv "${PERCEPTION_LOG}.tmp" "$PERCEPTION_LOG"
    after_lines=$(wc -l < "$PERCEPTION_LOG")
    pruned=$((before_lines - after_lines))
    if [ "$pruned" -gt 0 ]; then
        log "Pruned $pruned old perception minute entries (kept $after_lines)"
    fi
fi

# 9. Systemd journal vacuum (keep 7 days)
journalctl --user --vacuum-time=7d >/dev/null 2>&1 || true
sudo journalctl --vacuum-time=7d >/dev/null 2>&1 || true

# Report
AVAIL=$(df -h / | awk 'NR==2{print $4}')
USE_PCT=$(df -h / | awk 'NR==2{print $5}')
log "Cleanup complete. Disk: ${AVAIL} free (${USE_PCT} used)"

# Alert if still above 90%
USE_NUM=${USE_PCT%\%}
if [ "$USE_NUM" -gt 90 ]; then
    log "WARNING: Disk still above 90% after cleanup"
    # Send notification
    notify-send -u critical "Disk Space" "Root filesystem at ${USE_PCT} (${AVAIL} free) after cleanup" 2>/dev/null || true
fi

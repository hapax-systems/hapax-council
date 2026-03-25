#!/usr/bin/env bash
# Video recording retention — manages disk space for continuous camera capture.
#
# Two-phase lifecycle:
#   1. UNPROCESSED files: kept for RETAIN_HOURS (default 12h)
#      - Audio/video processing pipelines should ingest during this window
#      - Valuable segments get uploaded to gdrive before expiry
#   2. PROCESSED files (marked with .processed sidecar): deleted after PROCESSED_RETAIN_HOURS (6h)
#
# Disk pressure override: if root >=85%, shrink unprocessed window to PRESSURE_HOURS (6h)
#
# To mark a file as processed (pipeline should do this):
#   touch /path/to/segment.mkv.processed
#
# Runs via systemd timer every hour.
set -uo pipefail

VIDEO_DIR="$HOME/video-recording"
RETAIN_HOURS=12
PROCESSED_RETAIN_HOURS=6
PRESSURE_HOURS=6
CRITICAL_HOURS=3
EMERGENCY_HOURS=1
LOG_TAG="video-retention"

log() { logger -t "$LOG_TAG" "$1"; echo "$(date +%H:%M:%S) $1"; }

[ -d "$VIDEO_DIR" ] || exit 0

# Check disk pressure — tiered response
USE_PCT=$(df --output=pcent / | tail -1 | tr -d " %")
if [ "$USE_PCT" -ge 97 ]; then
    EFFECTIVE_RETAIN=$EMERGENCY_HOURS
    log "Disk at ${USE_PCT}% — EMERGENCY retention (${EFFECTIVE_RETAIN}h)"
elif [ "$USE_PCT" -ge 95 ]; then
    EFFECTIVE_RETAIN=$CRITICAL_HOURS
    log "Disk at ${USE_PCT}% — critical retention (${EFFECTIVE_RETAIN}h)"
elif [ "$USE_PCT" -ge 85 ]; then
    EFFECTIVE_RETAIN=$PRESSURE_HOURS
    log "Disk at ${USE_PCT}% — pressure retention (${EFFECTIVE_RETAIN}h)"
else
    EFFECTIVE_RETAIN=$RETAIN_HOURS
fi

BEFORE_SIZE=$(du -sb "$VIDEO_DIR" 2>/dev/null | cut -f1)
deleted=0
skipped=0

# Delete PROCESSED files older than PROCESSED_RETAIN_HOURS
while IFS= read -r -d '' sidecar; do
    original="${sidecar%.processed}"
    if [ -f "$original" ]; then
        rm -f "$original" "$sidecar"
        deleted=$((deleted + 1))
    else
        rm -f "$sidecar"
    fi
done < <(find "$VIDEO_DIR" -type f -name "*.processed" -mmin +$((PROCESSED_RETAIN_HOURS * 60)) -print0 2>/dev/null)

# Delete UNPROCESSED files older than retention window
while IFS= read -r -d '' file; do
    # Skip if there's a .processed sidecar (handled above)
    [ -f "${file}.processed" ] && continue
    rm -f "$file"
    deleted=$((deleted + 1))
done < <(find "$VIDEO_DIR" -type f \( -name "*.mkv" -o -name "*.mp4" -o -name "*.ts" \) -mmin +$((EFFECTIVE_RETAIN * 60)) -print0 2>/dev/null)

# Count files approaching retention window (within 2h of expiry) — warning for unprocessed
approaching=0
if [ "$EFFECTIVE_RETAIN" -gt 2 ]; then
    while IFS= read -r -d '' file; do
        [ -f "${file}.processed" ] && continue
        approaching=$((approaching + 1))
    done < <(find "$VIDEO_DIR" -type f \( -name "*.mkv" -o -name "*.mp4" -o -name "*.ts" \) -mmin +$(( (EFFECTIVE_RETAIN - 2) * 60 )) -not -mmin +$((EFFECTIVE_RETAIN * 60)) -print0 2>/dev/null)
fi

# Remove empty directories
find "$VIDEO_DIR" -mindepth 1 -type d -empty -delete 2>/dev/null || true

# Sweep leaked tmp-wav files (pacat orphans — runs every 15min alongside video retention)
TMP_WAV_DIR="$HOME/.cache/hapax/tmp-wav"
if [ -d "$TMP_WAV_DIR" ]; then
    leaked=$(find "$TMP_WAV_DIR" -name "tmp*.wav" -mmin +5 2>/dev/null | wc -l)
    if [ "$leaked" -gt 0 ]; then
        leaked_mb=$(find "$TMP_WAV_DIR" -name "tmp*.wav" -mmin +5 -printf "%s\n" 2>/dev/null | awk '{t+=$1} END {printf "%.0f", t/1048576}')
        find "$TMP_WAV_DIR" -name "tmp*.wav" -mmin +5 -delete 2>/dev/null || true
        log "Cleaned $leaked leaked wav files (${leaked_mb}MB)"
    fi
    # Kill orphan pacat processes (>2 concurrent is abnormal)
    orphan_pacat=$(pgrep -f "pacat --record" -c 2>/dev/null || echo 0)
    if [ "$orphan_pacat" -gt 2 ]; then
        pkill -f "pacat --record" 2>/dev/null || true
        log "Killed $orphan_pacat orphan pacat --record processes"
    fi
fi

AFTER_SIZE=$(du -sb "$VIDEO_DIR" 2>/dev/null | cut -f1)
FREED_MB=$(( (BEFORE_SIZE - AFTER_SIZE) / 1048576 ))
CURRENT_GB=$(( AFTER_SIZE / 1073741824 ))

if [ "$deleted" -gt 0 ]; then
    log "Deleted $deleted files, freed ${FREED_MB}MB (${CURRENT_GB}GB remaining, retention=${EFFECTIVE_RETAIN}h)"
fi

if [ "$approaching" -gt 0 ]; then
    log "WARNING: $approaching unprocessed files expire in <6h — run ingestion pipeline"
fi

# Report total
total_files=$(find "$VIDEO_DIR" -type f \( -name "*.mkv" -o -name "*.mp4" -o -name "*.ts" \) 2>/dev/null | wc -l)
processed_files=$(find "$VIDEO_DIR" -type f -name "*.processed" 2>/dev/null | wc -l)
log "Status: ${total_files} segments (${processed_files} processed), ${CURRENT_GB}GB on disk"

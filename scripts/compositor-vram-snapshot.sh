#!/usr/bin/env bash
# compositor-vram-snapshot.sh — one-shot VRAM attribution snapshot
#
# Captures a single point-in-time view of GPU memory usage broken down by
# process, plus the studio_compositor + reverie pool gauges from the
# Prometheus exporter. Intended as a quick diagnostic when investigating
# compositor or imagination VRAM regressions.
#
# Usage: scripts/compositor-vram-snapshot.sh
#
# Cross-reference: docs/research/2026-04-14-compositor-vram-attribution.md
# for the full W5.11 attribution analysis.

set -euo pipefail

METRICS_URL="${METRICS_URL:-http://127.0.0.1:9482/metrics}"

echo "=== VRAM by process (nvidia-smi --query-compute-apps) ==="
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv

echo
echo "=== Per-GPU totals ==="
nvidia-smi --query-gpu=index,name,memory.total,memory.used --format=csv

echo
echo "=== Studio compositor self-reported gauges ==="
if curl -sf "${METRICS_URL}" > /tmp/compositor-metrics.txt; then
    grep -E '^(studio_compositor_gpu_vram_bytes|studio_compositor_memory_footprint_bytes|reverie_pool_(reuse_ratio|total_textures|total_acquires|total_allocations|bucket_count))' \
        /tmp/compositor-metrics.txt | sort
    rm -f /tmp/compositor-metrics.txt
else
    echo "WARN: could not reach ${METRICS_URL} — is the compositor running?"
fi

echo
echo "=== Process identification (top compositor / daimonion / imagination PIDs) ==="
ps -eo pid,etime,comm,cmd 2>/dev/null \
    | grep -E "studio_compositor|hapax_daimonion|hapax-imagination|studio_person_detector" \
    | grep -v grep \
    | head -10

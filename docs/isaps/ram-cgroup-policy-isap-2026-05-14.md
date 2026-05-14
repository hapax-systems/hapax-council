# ISAP: RAM, Swap, and Service Cgroup Policy

**Date**: 2026-05-14
**Status**: Research Complete, Implementation Proposed
**Request**: REQ-20260513155814-ram-swap-cgroup-policy
**Authority Case**: CASE-INFRA-GOV-001

## Current State (measured 2026-05-14T00:42Z)

### Memory Configuration

- **RAM**: 128G total
- **zram**: 32G, zstd compression
- **earlyoom**: active, OOMScoreAdjust=-1000
- **Memory used**: 48G RAM, 18G/32G swap

### Memory Consumers (by category)

| Category | RSS | Count | Notes |
|----------|-----|-------|-------|
| Python/Agent processes | 15.3G | 62 | Includes 4+ .venv instances |
| Antigravity IDE | 2.5G | 1 | Language server 1.4G |
| OBS | 2.4G | 1 | 205M in swap |
| TabbyAPI | 2.5G | 1 | LLM inference |
| Chrome | 2.4G | ~8 | Multiple tabs |
| Docker containers | 2.9G | 37 | 24 orphaned github-mcp |
| ollama | 1.0G | 1 | No MemoryMax |
| MinIO | 1.4G | 1 | Object store |
| clickhouse | 869M | 1 | Analytics |

### Current Cgroup Limits

| Service | MemoryMax | MemoryHigh | Assessment |
|---------|-----------|------------|------------|
| studio-compositor | 16G | none | No backpressure |
| hapax-daimonion | 16G | 12G | Only service with MemoryHigh |
| hapax-backup-local | 2G | none | OK |
| ollama (system) | none | none | NO LIMITS |
| docker (system) | none | none | NO LIMITS |

### Critical Findings

1. **62 Python processes** consuming 15.3G
2. **24 orphaned github-mcp containers** from stale Codex/Gemini sessions
3. **No limits on ollama** — model loads can spike without bound
4. **earlyoom has no service-aware priority** — may kill compositor before expendable batch jobs

## Proposed Cgroup Tiers

### Tier 1: Critical Runtime (protect)
- studio-compositor: MemoryMax=8G MemoryHigh=6G OOMScoreAdjust=-500
- hapax-daimonion: MemoryMax=8G MemoryHigh=6G OOMScoreAdjust=-500

### Tier 2: Important (prefer-keep)
- ollama: MemoryMax=16G MemoryHigh=12G OOMScoreAdjust=-200

### Tier 3: Expendable (kill-first)
- backup services: MemoryMax=2G OOMScoreAdjust=500

## Immediate Actions (no PR needed)

1. Kill 24 orphaned containers
2. Set ollama MemoryMax=16G via systemctl edit
3. Add MemoryHigh=6G to compositor via systemctl --user edit

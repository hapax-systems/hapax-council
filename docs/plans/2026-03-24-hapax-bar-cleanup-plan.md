# Hapax Bar — Cleanup Implementation Plan

**Date:** 2026-03-24
**Design:** hapax-bar-cleanup-design.md

## Phase 1: Delete Dead Code

Delete 12 files. Run tests to verify nothing breaks.

Files: bar.py, reactive.py, clock.py, idle.py, network.py, health.py, gpu.py, docker.py, sysinfo.py, systemd.py, cost.py, privacy.py

## Phase 2: Fix Bugs

1. **Stimmung double read** — consolidate perception reads in _read_visual_layer()
2. **Voice orb radius** — scale from 6 to 10px based on widget height  
3. **Session panel comment** — document why "alpha" is correct
4. **Missing CSS** — add temporal-ribbon and cost-whisper rules

## Phase 3: Seam Refresh Pattern

1. Add `refresh()` to each seam panel
2. SeamWindow.toggle() calls refresh() on all children when opening
3. TemporalPanel.refresh() recalculates session duration + calendar
4. MetricsPanel.refresh() reads latest cached health/GPU
5. Store data provider references on panels at creation

## Estimated Scope

| Phase | Lines Deleted | Lines Added |
|-------|-------------|-------------|
| 1 | ~800 | 0 |
| 2 | ~15 | ~30 |
| 3 | ~10 | ~40 |
| **Total** | **~825** | **~70** |

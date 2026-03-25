# Data Source Validation — Audit Resolution and Remaining Gaps

**Status:** Design (validation specification)
**Date:** 2026-03-25
**Builds on:** Background Data Architecture (Phases 1-4), System-Wide Data Audit

---

## 1. Audit Summary

A comprehensive audit of all data sources flowing through Hapax was conducted on 2026-03-25. The system operates 22 active data sources across three tiers, 41 systemd timers, 9 Qdrant collections, and 11 profile dimensions.

**Finding: The data infrastructure is healthy.** All sync agents run on schedule, perception is continuous, RAG covers 246K documents, and stimmung updates in real-time. The background data architecture (Phases 1-4) closed all 10 cross-system wiring gaps identified in the original audit.

## 2. Issues Investigated and Resolved

### 2.1 Dead Qdrant Collections — FALSE ALARM

`operator-patterns` was flagged as empty (0 points). Investigation revealed it is actively managed by `PatternStore.ensure_collection()` in `shared/pattern_consolidation.py` and is referenced by health checks and spec audits. The collection is correct at 0 points — pattern extraction has not yet triggered.

`claude-memory` and `samples` were removed from `EXPECTED_COLLECTIONS` in Phase 1 (PR #318). The physical collections still exist in Qdrant but are not referenced by any code. They can be dropped at any time via the Qdrant API but are harmless.

### 2.2 Watch Biometrics Staleness — FALSE ALARM

Watch data at `~/hapax-state/watch/` was reported as 12h stale. Investigation found data is 5.8h old — within normal bounds for overnight periods when the watch is charging. The `hapax-watch-receiver` service is active and healthy on port 8042. The rolling window contains 1,895 heart rate readings. The Pixel Watch 4 device ID "pw4" connects and posts sensor data normally during waking hours.

### 2.3 Weekly Timer "Failures" — NOT YET DUE

Five weekly timers (drift-detector, knowledge-maint, manifest-snapshot, stack-maintenance, llm-backup) showed "never run." All five are scheduled for Sunday mornings. The system was set up on Monday 2026-03-23 — the first Sunday window (2026-03-29) has not arrived yet. All timers are enabled with `Persistent=true` and will fire on schedule. The watchdog scripts exist at `~/.local/bin/` and are valid bash wrappers.

### 2.4 Stimmung resource_pressure Staleness — BY DESIGN

The `resource_pressure` stimmung dimension was 11h stale. This is correct behavior: the dimension only updates when GPU VRAM exceeds 80%. During normal operation with no VRAM pressure, the dimension remains at 0.0 with increasing staleness. Stale dimensions are excluded from stance computation by design (`_STALE_THRESHOLD_S = 120.0` in `shared/stimmung.py`).

### 2.5 Grounding Quality Staleness — EXPECTED

`grounding_quality` was 12h stale in stimmung. GQI is computed by the voice daemon during active conversations only. With no voice session active overnight, staleness is expected and correct. The Phase 1 fix (PR #318) wired the GQI read path in the visual layer aggregator — it will refresh when the next voice session occurs.

## 3. Remaining Gaps (Low Priority)

### 3.1 Declared-but-Unimplemented Dimension Sources

Five profile dimension sources are declared in `shared/dimensions.py` but have no producing agent:

| Source | Dimension | Nature |
|--------|-----------|--------|
| `interview` | identity, neurocognitive, values, communication_style, relationships | Aspirational — interview system not yet designed |
| `micro_probes` | neurocognitive | Aspirational — micro-assessment framework not designed |
| `vault_contacts` | relationships | Requires obsidian_sync extension to extract contacts |
| `shell_history` | tool_usage | Requires new sync agent for fish/bash history |
| `workspace_vision` | energy_and_attention | Partially covered by screen_context; full vision requires camera pipeline |

These are design aspirations, not broken wiring. They represent features that will be built when their dimensions become priorities. No immediate action required.

### 3.2 Missing Agent Manifests

33 of 61 agents lack manifest YAML files. This does not affect data flow — agents run via systemd timers and module invocations regardless of manifest presence. Manifests provide operational metadata (purpose, autonomy tier, RACI, CLI spec) consumed by the agent registry for querying and health checks. Adding manifests is an operational completeness task, not a data wiring fix.

### 3.3 Physical Qdrant Cleanup

`claude-memory` and `samples` collections physically exist in Qdrant with 0 points but are not referenced by any code after Phase 1 removal from `EXPECTED_COLLECTIONS`. They can be dropped for hygiene:

```bash
curl -X DELETE http://localhost:6333/collections/claude-memory
curl -X DELETE http://localhost:6333/collections/samples
```

## 4. Conclusion

No data source wiring work remains. All 15 items from the background data architecture are implemented and merged (PRs #318-#321). All sync agents are healthy. All timers are on schedule. Stimmung, perception, and profile pipelines are operational. The system is ready for new feature work.

# Voice Context Enrichment — Goals, Health, and Nudges in the Cognitive Loop

**Status:** Design (voice daemon enhancement)
**Date:** 2026-03-25
**Builds on:** Background Data Architecture, Voice Daemon Reference Architecture

---

## 1. Problem Statement

The voice daemon is the most sophisticated consumer of background data in Hapax, but it operates in a context vacuum for three categories:

1. It does not know the operator's active goals.
2. It does not know about system health degradation.
3. It does not know about pending nudges or open action loops.

This means the voice cannot relate responses to operator objectives, cannot warn about system issues, and cannot proactively surface urgent items.

## 2. Injection Architecture

All new data enters the VOLATILE band of the conversation pipeline's system context, between the existing policy section and the phenomenal context section. Three new sections are added:

```
VOLATILE band (rebuilt every turn):
  1. Policy (existing)
  2. Environment (existing)
  3. [NEW] Operator Goals
  4. [NEW] System Health
  5. [NEW] Open Loops (Nudges)
  6. Phenomenal Context (existing)
  7. Salience Context (existing)
  8. Grounding Directive (existing)
  9. Effort Level (existing)
```

Each new section:

- Has a callback function registered in `VoiceDaemon._precompute_pipeline_dependencies()`
- Returns a string (empty string = omitted from context)
- Is wrapped in try/except (non-fatal on failure)
- Has a token budget cap
- Has a staleness guard (skip if data too old)

## 3. Goals Injection

**Source:** `logos.data.goals.collect_goals()` returns `GoalSnapshot`
**Band:** VOLATILE (refreshed per turn but goals change slowly)
**Token budget:** 40-80 tokens
**Staleness:** None (goals do not expire; stale flag computed at collection)

Format:

```
## Operator Goals (3 active)
- [primary] Goal Name — progress summary
- [secondary] Goal Name — progress summary
- ⚠ Stale: Goal Name (no activity 12d)
```

Implementation:

```python
def _render_goals() -> str:
    try:
        from logos.data.goals import collect_goals
        snapshot = collect_goals()
        if not snapshot.goals:
            return ""
        active = [g for g in snapshot.goals if g.status in ("active", "ongoing")]
        if not active:
            return ""
        lines = [f"## Operator Goals ({len(active)} active)"]
        for g in active[:5]:
            prefix = "⚠ " if g.stale else ""
            lines.append(f"- {prefix}[{g.category}] {g.name}")
        return "\n".join(lines)
    except Exception:
        return ""
```

## 4. Health Injection

**Source:** Last line of `profiles/health-history.jsonl` (synchronous read)
**Band:** VOLATILE
**Token budget:** 20-40 tokens
**Staleness:** Skip if health data >120s old
**Condition:** Only inject when status != "healthy" (saves tokens when nominal)

Format (only when degraded or failed):

```
⚠ System: degraded (97✓ 3⚠ 1✗). Failed: docker.redis, gpu.temperature
```

Implementation:

```python
def _render_health() -> str:
    try:
        import json, time
        from pathlib import Path
        path = Path("profiles/health-history.jsonl")
        if not path.exists():
            return ""
        last_line = path.read_text().strip().split("\n")[-1]
        data = json.loads(last_line)
        # Staleness check
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(data["timestamp"])
        age_s = (datetime.now(timezone.utc) - ts).total_seconds()
        if age_s > 120:
            return ""
        if data["status"] == "healthy":
            return ""  # Don't clutter context when healthy
        failed = data.get("failed_checks", [])
        msg = f"⚠ System: {data['status']} ({data['healthy']}✓ {data['degraded']}⚠ {data['failed']}✗)"
        if failed:
            msg += f". Failed: {', '.join(f[:30] for f in failed[:3])}"
        return msg
    except Exception:
        return ""
```

## 5. Nudges Injection

**Source:** `logos.data.nudges.collect_nudges(max_nudges=3)` returns `list[Nudge]`
**Band:** VOLATILE
**Token budget:** 60-100 tokens (3 nudges max)
**Staleness:** Computed fresh each call
**Cache strategy:** Nudge collection involves 12 sub-collectors. Cache result for 30s, refresh in background.

Format:

```
## Open Loops (3)
- [critical] Container redis failing — restart or investigate
- [high] Profile 14h stale — run profiler
- [medium] 3 drift items need attention
```

Implementation:

```python
_nudge_cache: list | None = None
_nudge_cache_time: float = 0.0

def _render_nudges() -> str:
    global _nudge_cache, _nudge_cache_time
    try:
        now = time.monotonic()
        if _nudge_cache is None or (now - _nudge_cache_time) > 30:
            from logos.data.nudges import collect_nudges
            _nudge_cache = collect_nudges(max_nudges=3)
            _nudge_cache_time = now
        if not _nudge_cache:
            return ""
        lines = [f"## Open Loops ({len(_nudge_cache)})"]
        for n in _nudge_cache:
            lines.append(f"- [{n.priority_label}] {n.title}")
        return "\n".join(lines)
    except Exception:
        return ""
```

## 6. Temporal Bands Verification

**Current path:** `/dev/shm/hapax-temporal/bands.json`
**Reader:** `phenomenal_context.py` line 40, staleness check at 30s
**Status:** Working. No changes needed.

The ring_depth=0 issue from the audit was a startup transient (ring needs at least 2 snapshots). After approximately 5 seconds of aggregator runtime, temporal bands populate correctly. No fix required.

## 7. Registration in Voice Daemon

In `VoiceDaemon._precompute_pipeline_dependencies()`, register three new callbacks:

```python
self._goals_fn = _render_goals
self._health_fn = _render_health
self._nudges_fn = _render_nudges
```

In `ConversationPipeline._update_system_context()`, inject after the policy section:

```python
# After policy (line 540), before phenomenal context (line 553):
for fn_name, fn in [("goals", self._goals_fn),
                     ("health", self._health_fn),
                     ("nudges", self._nudges_fn)]:
    if fn is not None and not _lockdown:
        try:
            section = fn()
            if section:
                updated += "\n\n" + section
        except Exception:
            log.debug("%s context fn failed (non-fatal)", fn_name, exc_info=True)
```

## 8. Experiment Freeze Compliance

All injections are in the VOLATILE band. Under `experiment_flags.volatile_lockdown`, they are frozen at session start (same as policy, environment, salience). No deviation record is needed. The existing lockdown mechanism covers new VOLATILE sections automatically.

## 9. Token Budget Verification

| Section | Current | New | Total |
|---------|---------|-----|-------|
| System prompt base | 400 | 400 | 400 |
| Thread | 100-200 | 100-200 | 100-200 |
| Policy | 50-100 | 50-100 | 50-100 |
| Environment | 60-80 | 60-80 | 60-80 |
| **Goals** | 0 | **40-80** | 40-80 |
| **Health** | 0 | **0-40** | 0-40 |
| **Nudges** | 0 | **0-100** | 0-100 |
| Phenomenal | 80-150 | 80-150 | 80-150 |
| Salience | 50-100 | 50-100 | 50-100 |
| Grounding + Effort | 40-60 | 40-60 | 40-60 |
| **Total** | 780-1290 | **920-1510** | — |

Worst case adds approximately 220 tokens. This is well within the model context budget. Health contributes 0 tokens when the system is healthy (the common case).

## 10. Files Changed

**Modified:**

- `agents/hapax_voice/conversation_pipeline.py` — add 3 injection points in VOLATILE band
- `agents/hapax_voice/__main__.py` — register 3 callbacks, pass to pipeline

**New:**

- `agents/hapax_voice/context_enrichment.py` — `_render_goals`, `_render_health`, `_render_nudges` functions

No new dependencies. The `logos.data` modules are already importable from the voice daemon context.

## 11. What This Does NOT Do

- Does not change model routing (salience router unchanged).
- Does not change the grounding ledger (repair thresholds unchanged).
- Does not add proactive voice initiation (voice still responds, does not initiate).
- Does not change the STABLE band (system prompt, thread unchanged).
- Health injection is passive context, not an interrupt mechanism (that is Phase 2 item 3, deferred).

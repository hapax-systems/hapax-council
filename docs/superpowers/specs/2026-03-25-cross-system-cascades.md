# Cross-System Cascades — Wiring Effects Between Subsystems

**Status:** Implemented
**Date:** 2026-03-25
**Builds on:** Background Data Architecture, Voice Context Enrichment

---

## 1. Problem Statement

Effects do not propagate between Hapax subsystems. When the reactive engine fires a rule, the effect terminates at the rule boundary. When an operator correction is recorded in Qdrant, the profiler does not learn from it. When knowledge gaps are computed, the nudge system does not surface them. When a voice session is active, the content scheduler continues ambient injection at full density. Each subsystem operates as a silo.

The result is a system that observes correctly but fails to act on its observations across module boundaries. Data flows inward (ingestion, perception, enrichment) but does not flow laterally (subsystem A's output becoming subsystem B's input). This specification defines four concrete integration points — referred to as "wires" — that close these lateral gaps.

## 2. Four Wires

### Wire 1: Reactive Engine → Stimmung (Scoped)

The general case of reactive cascades (engine → stimmung → nudge → profile) exceeds the complexity budget for Phase 3. This wire is scoped to a single concrete case: biometric stress transitions should refresh the `operator_stress` stimmung dimension.

**Current behavior.** `_handle_biometric_state_change()` emits a telemetry event and terminates. The `visual_layer_aggregator` reads biometric data on a 3-second tick and computes stimmung dimensions independently.

**Observation.** The cascade already occurs — the `visual_layer_aggregator`'s periodic tick reads biometric state and feeds it into stimmung computation. The latency ceiling is 3 seconds, which is acceptable for ambient perception. The actual gap, if one exists, is whether the `operator_stress` stimmung dimension reads from the correct source (the watch backend's stress data) or whether it is hardcoded or reading a stale path.

**Scoped fix.** Verify that `visual_layer_aggregator.py`'s `operator_stress` dimension correctly reads from the watch backend's stress data. If the dimension reads the wrong path or is hardcoded, correct the source reference. If the path is already correct, Wire 1 requires no code change; the integration is functional with 3-second latency.

### Wire 2: Corrections → Profile Learning

Operator corrections recorded in the `operator-corrections` Qdrant collection represent direct signal about classification errors and preference drift. The profiler does not currently consume this data.

**Design.** Add `read_correction_facts()` to `profiler_sources.py`, following the established pattern of `read_flow_facts()`. The function queries the `operator-corrections` collection for entries within a rolling 30-day window, aggregates by dimension, and produces structured profile facts when a minimum threshold (n >= 2) is met.

```python
def read_correction_facts(days_back: int = 30) -> list[dict]:
    """Extract profile facts from operator corrections in Qdrant."""
    from shared.config import get_qdrant_client, EMBED_FN
    from datetime import UTC, datetime, timedelta

    client = get_qdrant_client()
    cutoff = datetime.now(UTC) - timedelta(days=days_back)

    # Query recent corrections
    results = client.scroll(
        collection_name="operator-corrections",
        scroll_filter=...,  # filter by timestamp > cutoff
        limit=200,
    )

    # Aggregate by dimension
    corrections_by_dim: dict[str, list] = {}
    for point in results[0]:
        dim = point.payload.get("dimension", "other")
        corrections_by_dim.setdefault(dim, []).append(point.payload)

    # Produce facts
    facts = []
    for dim, corrections in corrections_by_dim.items():
        n = len(corrections)
        if n < 2:
            continue
        facts.append({
            "key": f"correction.{dim}.frequency",
            "value": f"{n} corrections in {days_back}d for {dim} classification",
            "dimension": "energy_and_attention",
            "confidence": min(0.8, n / 20),
            "source": f"corrections:{days_back}d",
            "evidence": f"{n} corrections across {dim}",
        })
    return facts
```

**Integration point.** `profiler.py`'s `load_structured_facts()` calls `read_correction_facts()` after the existing `flow_facts` block and merges the returned facts into the structured fact set.

### Wire 3: Knowledge Gaps → Nudges

The knowledge sufficiency subsystem (`logos/data/knowledge_sufficiency.py`) already computes gaps and provides a conversion function to nudge format. The nudge collector does not call it.

**Design.** Add `_collect_knowledge_gap_nudges()` to `logos/data/nudges.py` and wire it into the main `collect_nudges()` function.

```python
def _collect_knowledge_gap_nudges(nudges: list) -> None:
    try:
        from logos.data.knowledge_sufficiency import collect_knowledge_gaps, gaps_to_nudges
        report = collect_knowledge_gaps()
        if report.gaps:
            nudges.extend(gaps_to_nudges(report.gaps))
    except Exception:
        log.warning("Knowledge gap nudge collection failed", exc_info=True)
```

The function is defensive: failure in gap computation does not block other nudge sources. The `gaps_to_nudges()` function handles priority assignment and deduplication internally.

### Wire 4: Content Scheduler ↔ Voice

The `SchedulerContext` model already declares a `voice_active: bool` field (line 252 of `content_scheduler.py`). It is hardcoded to `False`. During active voice sessions, the content scheduler continues injecting ambient content at normal density, competing with conversation for operator attention.

**Design.** Two changes:

1. **Source the signal.** In `visual_layer_aggregator.py`, read voice session state from `perception-state.json` (which contains a `voice_session` field populated by the voice daemon) and set `context.voice_active` before calling `scheduler.tick()`.

```python
# Read voice session state from perception
perception = self._read_perception_state()
context.voice_active = perception.get("voice_session", {}).get("active", False)
```

2. **Act on the signal.** In `content_scheduler.py`'s `tick()` method, when `voice_active` is `True`, override effective density to `DisplayDensity.PRESENTING` (minimal ambient injection during conversation).

```python
if context.voice_active:
    # Reduce to minimal injection during voice conversation
    effective_density = DisplayDensity.PRESENTING
```

This ensures the ground surface defers to voice interaction without requiring the voice daemon to explicitly coordinate with the scheduler.

## 3. Files Changed

**Wire 1 (scoped verification):** NO-OP — verified correct. `operator_stress` reads from watch HRV/EDA/frustration via `visual_layer_aggregator.py` → `stimmung.py`. Formula: `0.4*hrv_drop + 0.3*eda + 0.3*frustration`. Tests exist in `test_stimmung.py`.

**Wire 2 (corrections → profile):**
- `agents/profiler_sources.py` — added `read_correction_facts()` (Qdrant scroll, 30d window, n≥2 threshold)
- `agents/profiler.py` — wired into `load_structured_facts()` after flow journal bridge

**Wire 3 (knowledge gaps → nudges):** NO-OP — already implemented. `_collect_knowledge_sufficiency_nudges()` exists at `logos/data/nudges.py:450`, called from `collect_nudges()` at line 667.

**Wire 4 (voice-aware scheduling):**
- `agents/visual_layer_aggregator.py` — already populates `context.voice_active` from `self._voice_session.active` (line 1699)
- `agents/content_scheduler.py` — added `voice_active → PRESENTING` density override in `_compute_density()`

**Tests:**
- `tests/test_cross_system_cascades.py` — 7 tests covering Wire 2 (5) and Wire 4 (2)

## 4. Scope Exclusions

This specification does not:

- Add a post-phase hook to the reactive engine. Full reactive cascades exceed the Phase 3 complexity budget.
- Alter the reactive engine's rule evaluation order or priority model.
- Introduce new Qdrant collections. All data sources referenced here already exist.
- Modify the voice daemon. Voice session state is read passively from `perception-state.json`, which the voice daemon already maintains. Phase 2 voice context enrichment handled daemon-side changes.
- Implement bidirectional feedback loops. Each wire is unidirectional: source → consumer. Circular dependencies between subsystems are explicitly avoided.

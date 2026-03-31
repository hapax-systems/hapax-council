# Apperception Event Source Completion — Design Spec

**Date**: 2026-03-31
**Sub-project**: 2 of 3 (Core Hardening → Event Source Completion → UI + Observability)
**Depends on**: Sub-project 1 (store wiring, liveness signal)
**Scope**: Wire the 3 unwired cascade event sources: `performance`, `cross_resonance`, `pattern_shift`.

## Context

The ApperceptionCascade handles 7 event source types. Only 4 are wired in `ApperceptionTick._collect_events()`: `prediction_error`, `correction`, `stimmung_event`, `absence`. Three sources (`performance`, `cross_resonance`, `pattern_shift`) are defined in the cascade logic (polarity mappings, integration targets, valence computation) but no event producer exists. The cascade correctly processes them if events arrive — the gap is purely in event collection.

## Design Principle

All event sources read from `/dev/shm` or filesystem — no in-process coupling. The apperception tick remains a standalone, filesystem-driven loop. New sources follow the same pattern: read a file, check staleness, emit CascadeEvent if threshold met.

## A. Performance Events (from Stimmung Dimensions)

### Data Source

`/dev/shm/hapax-stimmung/state.json` — already read by `_read_stimmung_stance()`. Contains 10 dimensions, each with `{value, trend, freshness_s}`. The `value` field is 0.0 (good) to 1.0 (bad). Stimmung refreshes every ~60s.

### Event Logic

Add to `_collect_events()` after the stimmung transition check:

```python
# 5. Performance deltas (from stimmung dimensions)
if stimmung_data is not None:
    for dim_name, dim in stimmung_data.items():
        if not isinstance(dim, dict) or "value" not in dim:
            continue
        value = dim["value"]
        baseline = _STIMMUNG_BASELINES.get(dim_name)
        if baseline is None:
            continue
        delta = value - baseline
        if abs(delta) > 0.15:  # significance threshold
            events.append(
                CascadeEvent(
                    source="performance",
                    text=f"{dim_name}: {value:.2f} (baseline {baseline:.2f}, delta {delta:+.2f})",
                    magnitude=min(abs(delta), 1.0),
                    metadata={"baseline": baseline, "dimension": dim_name},
                )
            )
```

### Baselines

Hardcoded baselines derived from stimmung dimension semantics (all on 0.0=good, 1.0=bad scale):

```python
_STIMMUNG_BASELINES: dict[str, float] = {
    "health": 0.1,                  # expect near-zero (most checks healthy)
    "resource_pressure": 0.3,       # 80% VRAM = 0.0, 87% = 0.3 (normal GPU load)
    "error_rate": 0.05,             # <5% error rate is normal
    "processing_throughput": 0.2,   # 400/500 events/min is normal
    "perception_confidence": 0.1,   # expect fresh, confident perception
    "llm_cost_pressure": 0.15,     # ~$7.50/day is typical R&D spend
}
```

Biometric and cognitive dimensions excluded — those are operator state, not system performance. Only infrastructure dimensions produce performance events.

### Dedup

Use `_last_perf_snapshot: dict[str, float]` to track last-emitted value per dimension. Only emit if value changed by >0.1 since last emission. Reset snapshot every 300s to allow re-emission of sustained deltas.

### Changes to `_read_stimmung_stance()`

Refactor to return the full stimmung dict (not just stance string). Update callers accordingly:

```python
def _read_stimmung(self) -> tuple[str, dict | None]:
    """Read stimmung state. Returns (stance, full_data)."""
    try:
        raw = json.loads(STIMMUNG_FILE.read_text(encoding="utf-8"))
        return raw.get("overall_stance", "nominal"), raw
    except Exception:
        return "nominal", None
```

### Cascade Mapping

Already handled: `_SOURCE_POLARITY["performance"] = 0.0`, with valence computed as `(magnitude - baseline) * 1.0`. Integration target: `processing_quality`. The metadata `baseline` field is used in `_step_valence()` at line 408.

## B. Cross-Resonance Events (from AV Correlator)

### Data Source

The AV correlator is a CLI tool that writes to Qdrant `studio_moments` collection. It does NOT write to `/dev/shm`. To maintain the apperception tick's filesystem-only contract, we need a lightweight bridge.

### Bridge Design

Add a new SHM file written by the VLA (which already runs the perception loop):

**Path**: `/dev/shm/hapax-apperception/cross-resonance.json`

**Producer**: VLA already tracks audio classification (`_audio_label`) and video classifications (`_video_labels`). When audio and video agree on activity type (e.g., both indicate "production_session"), that's cross-modal resonance.

Add to VLA's `_compute_and_write()` (runs every ~3s):

```python
def _write_cross_resonance(self) -> None:
    """Write cross-modal agreement signal to /dev/shm for apperception."""
    audio = self._audio_label  # e.g., "sample-session"
    video = self._video_labels  # dict[role, category]
    if not audio or not video:
        return

    # Check if any video classification resonates with audio
    resonance_score = 0.0
    matching_roles: list[str] = []
    for role, category in video.items():
        if self._labels_resonate(audio, category):
            resonance_score = max(resonance_score, 0.7)
            matching_roles.append(role)

    payload = {
        "resonance_score": resonance_score,
        "audio_label": audio,
        "matching_roles": matching_roles,
        "timestamp": time.time(),
    }
    # Write atomically
    path = APPERCEPTION_DIR / "cross-resonance.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.rename(path)
```

`_labels_resonate()` reuses the AV correlator's boost rules (lines 58-74 of av_correlator.py) but simplified to a boolean: do audio and video classifications match any boost rule?

### Event Logic in ApperceptionTick

```python
# 6. Cross-modal resonance
CROSS_RESONANCE_FILE = APPERCEPTION_DIR / "cross-resonance.json"

try:
    cr = json.loads(CROSS_RESONANCE_FILE.read_text(encoding="utf-8"))
    cr_ts = cr.get("timestamp", 0)
    if (time.time() - cr_ts) <= 30:
        score = cr.get("resonance_score", 0.0)
        if score > 0.3:
            events.append(
                CascadeEvent(
                    source="cross_resonance",
                    text=f"audio-video agreement: {cr.get('audio_label', '?')} "
                         f"({len(cr.get('matching_roles', []))} cameras)",
                    magnitude=score,
                )
            )
except Exception:
    pass
```

### Cascade Mapping

Already handled: `_SOURCE_POLARITY["cross_resonance"] = 0.3` (affirming — multimodal agreement is positive). Integration target: `cross_modal_integration`.

## C. Pattern Shift Events (from BOCPD + Pattern Store)

### Data Source

Two subsystems need to connect:

1. **BOCPD** detects change points in `{flow_score, audio_energy, heart_rate}` signals. Results are ephemeral in VLA memory (`_last_change_points`).
2. **PatternStore** holds if-then patterns with confidence scores. VLA searches every 60s or on activity change.

A pattern shift occurs when: BOCPD detects a change point AND the current activity either confirms or contradicts an active pattern.

### Bridge Design

Add a new SHM file written by the VLA:

**Path**: `/dev/shm/hapax-apperception/pattern-shifts.json`

**Producer**: In VLA's pattern search callback (runs every 60s or on activity change, lines 577-605 of aggregator.py), after searching patterns:

```python
def _write_pattern_shifts(self, matches: list[PatternMatch]) -> None:
    """Write pattern confirmation/contradiction signals for apperception."""
    shifts: list[dict] = []

    for match in matches:
        if match.score < 0.3:
            continue

        # Check if recent change points relate to this pattern
        recent_cps = [
            cp for cp in self._last_change_points
            if time.time() - cp.get("timestamp", 0) < 120
        ]

        # Pattern confirmed if score > 0.6 and no contradicting change point
        confirmed = match.score > 0.6 and not any(
            cp.get("signal_name") in match.pattern.condition
            for cp in recent_cps
        )
        # Pattern contradicted if change point detected in pattern's signal
        contradicted = any(
            cp.get("signal_name") in match.pattern.condition
            and cp.get("probability", 0) > 0.7
            for cp in recent_cps
        )

        if confirmed or contradicted:
            shifts.append({
                "pattern_id": match.pattern.id,
                "prediction": match.pattern.prediction[:80],
                "confidence": match.pattern.confidence,
                "confirmed": confirmed,
                "timestamp": time.time(),
            })

    if shifts:
        payload = {"shifts": shifts, "timestamp": time.time()}
        path = APPERCEPTION_DIR / "pattern-shifts.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.rename(path)
```

### Event Logic in ApperceptionTick

```python
# 7. Pattern shifts
PATTERN_SHIFT_FILE = APPERCEPTION_DIR / "pattern-shifts.json"

try:
    ps = json.loads(PATTERN_SHIFT_FILE.read_text(encoding="utf-8"))
    ps_ts = ps.get("timestamp", 0)
    if (time.time() - ps_ts) <= 60:  # longer window — patterns update every 60s
        for shift in ps.get("shifts", []):
            events.append(
                CascadeEvent(
                    source="pattern_shift",
                    text=f"pattern {'confirmed' if shift.get('confirmed') else 'contradicted'}: "
                         f"{shift.get('prediction', '?')}",
                    magnitude=shift.get("confidence", 0.5),
                    metadata={
                        "confirmed": shift.get("confirmed", False),
                        "dimension": "pattern_recognition",
                    },
                )
            )
except Exception:
    pass
```

### Cascade Mapping

Already handled: `_SOURCE_POLARITY["pattern_shift"] = 0.0` (neutral), with metadata-driven valence: `confirmed=True → +0.5`, `confirmed=False → -0.5`. Integration target: `pattern_recognition`.

## File Change Summary

| File | Action |
|------|--------|
| `shared/apperception_tick.py` | Add performance, cross_resonance, pattern_shift event collection; refactor _read_stimmung; add baselines dict |
| `agents/_apperception_tick.py` | Mirror |
| `agents/visual_layer_aggregator/aggregator.py` | Add `_write_cross_resonance()` and `_write_pattern_shifts()` methods; call from existing hooks |
| `tests/test_apperception_events.py` | Add tests for 3 new event types (9 tests: threshold, staleness, dedup per source) |
| `tests/test_apperception_tick_io.py` | Add tests for new SHM file reads (corrupted, missing, stale) |

## New /dev/shm Paths

| Path | Writer | Reader | Cadence |
|------|--------|--------|---------|
| `/dev/shm/hapax-apperception/cross-resonance.json` | VLA `_compute_and_write()` | ApperceptionTick | ~3s |
| `/dev/shm/hapax-apperception/pattern-shifts.json` | VLA `_write_pattern_shifts()` | ApperceptionTick | ~60s |

Both use atomic `.tmp` → rename pattern. Both read with 30s/60s staleness checks.

## Testing

9 new tests in `test_apperception_events.py`:
- `test_performance_above_baseline` — delta > 0.15 → event emitted
- `test_performance_within_baseline` — delta < 0.15 → no event
- `test_performance_dedup` — same value twice → only one event
- `test_cross_resonance_above_threshold` — score > 0.3 → event emitted
- `test_cross_resonance_stale` — timestamp > 30s → no event
- `test_cross_resonance_no_agreement` — score 0.0 → no event
- `test_pattern_shift_confirmed` — confirmed=True → positive cascade
- `test_pattern_shift_contradicted` — confirmed=False → negative cascade
- `test_pattern_shift_stale` — timestamp > 60s → no event

3 additional I/O edge case tests in `test_apperception_tick_io.py`:
- `test_cross_resonance_corrupted_json`
- `test_pattern_shifts_missing_file`
- `test_performance_non_dict_dimension`

## Out of Scope

- Modifying AV correlator internals
- Adding new BOCPD signals
- Pattern consolidation LLM pipeline changes
- Any stimmung dimension threshold changes

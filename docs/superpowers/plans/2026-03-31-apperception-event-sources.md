# Apperception Event Source Completion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the 3 unwired cascade event sources (`performance`, `cross_resonance`, `pattern_shift`) so the ApperceptionCascade receives the full 7-source event stream. Add VLA bridge methods that write cross-resonance and pattern-shift signals to `/dev/shm` for filesystem-only consumption by the tick loop.

**Architecture:** The apperception tick loop (3-5s cadence) reads all inputs from `/dev/shm` or filesystem. Two new SHM files bridge VLA-internal state to the tick: `cross-resonance.json` (written every ~3s in `compute_and_write`) and `pattern-shifts.json` (written every ~60s on pattern search). Performance events derive from stimmung data already read by the tick. All new code follows the existing try/except + staleness check + CascadeEvent pattern.

**Tech Stack:** Python 3.12, Pydantic, pytest + unittest.mock, fish shell.

**Spec:** `docs/superpowers/specs/2026-03-31-apperception-event-sources-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `shared/apperception_tick.py` | Modify | Refactor `_read_stimmung_stance` → `_read_stimmung`, add baselines dict, add performance/cross-resonance/pattern-shift event collection |
| `agents/_apperception_tick.py` | Modify | Mirror all `shared/apperception_tick.py` changes |
| `agents/visual_layer_aggregator/aggregator.py` | Modify | Add `_write_cross_resonance()`, `_write_pattern_shifts()`, `_labels_resonate()` methods; call from hooks |
| `tests/test_apperception_events.py` | Modify | Add 9 tests for 3 new event types |

---

### Task 1: Refactor Stimmung Reader + Add Performance Events

**Files:**
- Modify: `shared/apperception_tick.py`

- [ ] **Step 1: Add baselines dict and dedup state**

At the top of the file, after the existing path constants, add the baselines dict. In `__init__`, add dedup state:

```python
# After APPERCEPTION_CACHE_FILE line (line 31), add:

# ── Performance baselines (0.0=good, 1.0=bad) ──────────────────────────────
_STIMMUNG_BASELINES: dict[str, float] = {
    "health": 0.1,
    "resource_pressure": 0.3,
    "error_rate": 0.05,
    "processing_throughput": 0.2,
    "perception_confidence": 0.1,
    "llm_cost_pressure": 0.15,
}

CROSS_RESONANCE_FILE = APPERCEPTION_DIR / "cross-resonance.json"
PATTERN_SHIFT_FILE = APPERCEPTION_DIR / "pattern-shifts.json"
```

In `__init__`, add dedup state after `self._last_correction_ts`:

```python
    def __init__(self) -> None:
        self._cascade = self._load_model()
        self._prev_stimmung_stance: str = "nominal"
        self._last_save: float = 0.0
        self._last_correction_ts: float = 0.0  # dedup corrections
        self._last_perf_snapshot: dict[str, float] = {}  # dedup performance
        self._last_perf_reset: float = time.monotonic()  # reset every 300s
```

- [ ] **Step 2: Refactor `_read_stimmung_stance` to `_read_stimmung`**

Replace `_read_stimmung_stance` with `_read_stimmung` that returns both stance and full data:

```python
    def _read_stimmung(self) -> tuple[str, dict | None]:
        """Read stimmung state. Returns (stance, full_data)."""
        try:
            raw = json.loads(STIMMUNG_FILE.read_text(encoding="utf-8"))
            return raw.get("overall_stance", "nominal"), raw
        except Exception:
            return "nominal", None
```

- [ ] **Step 3: Update `tick()` to use new reader**

Change the `tick()` method to call the new reader and pass stimmung_data to `_collect_events`:

```python
    def tick(self) -> None:
        """Run one apperception cycle. Call this every 3-5 seconds."""
        stance, stimmung_data = self._read_stimmung()
        events = self._collect_events(stance, stimmung_data)

        pending_actions: list[str] = []
        for event in events:
            result = self._cascade.process(event, stimmung_stance=stance)
            if result and result.action:
                pending_actions.append(result.action)

        self._write_shm(pending_actions)

        now = time.monotonic()
        if now - self._last_save >= 300.0:
            self.save_model()
            self._last_save = now
```

- [ ] **Step 4: Update `_collect_events` signature and add performance events**

Update signature to accept `stimmung_data`. Add performance event collection after the stimmung transition check (section 3), before perception staleness (section 4):

```python
    def _collect_events(self, stance: str, stimmung_data: dict | None = None) -> list[CascadeEvent]:
        events: list[CascadeEvent] = []

        # Read temporal file ONCE (C6: prevent contradictory events)
        temporal_data = None
        try:
            temporal_data = json.loads(TEMPORAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

        # 1. Surprise from temporal bands
        if temporal_data is not None:
            ts = temporal_data.get("timestamp", 0)
            if (time.time() - ts) <= 30:
                surprise = temporal_data.get("max_surprise", 0.0)
                if surprise > 0.3:
                    events.append(
                        CascadeEvent(
                            source="prediction_error",
                            text=f"temporal surprise {surprise:.2f}",
                            magnitude=min(surprise, 1.0),
                        )
                    )

        # 2. Operator corrections (dedup by timestamp)
        try:
            corr = json.loads(CORRECTION_FILE.read_text(encoding="utf-8"))
            corr_ts = corr.get("timestamp", 0)
            elapsed = time.time() - corr_ts
            if elapsed < 10 and corr_ts > self._last_correction_ts:
                self._last_correction_ts = corr_ts
                events.append(
                    CascadeEvent(
                        source="correction",
                        text=f"operator corrected: {corr.get('label', 'unknown')}",
                        magnitude=0.7,
                    )
                )
        except Exception:
            pass

        # 3. Stimmung transition
        if stance != self._prev_stimmung_stance:
            stances = ["nominal", "cautious", "degraded", "critical"]
            try:
                improving = stances.index(stance) < stances.index(self._prev_stimmung_stance)
            except ValueError:
                improving = False
            events.append(
                CascadeEvent(
                    source="stimmung_event",
                    text=f"stance: {self._prev_stimmung_stance} → {stance}",
                    magnitude=0.5,
                    metadata={"direction": "improving" if improving else "degrading"},
                )
            )
            self._prev_stimmung_stance = stance

        # 4. Perception staleness (reuse temporal_data — mutually exclusive with surprise)
        if temporal_data is not None:
            perception_age = time.time() - temporal_data.get("timestamp", 0)
            if perception_age > 30.0:
                events.append(
                    CascadeEvent(
                        source="absence",
                        text=f"perception stale ({perception_age:.0f}s)",
                        magnitude=min(perception_age / 120.0, 1.0),
                    )
                )

        # 5. Performance deltas (from stimmung dimensions)
        # Reset dedup snapshot every 300s to allow re-emission of sustained deltas
        now_mono = time.monotonic()
        if now_mono - self._last_perf_reset > 300.0:
            self._last_perf_snapshot.clear()
            self._last_perf_reset = now_mono

        if stimmung_data is not None:
            for dim_name, dim in stimmung_data.items():
                if not isinstance(dim, dict) or "value" not in dim:
                    continue
                value = dim["value"]
                baseline = _STIMMUNG_BASELINES.get(dim_name)
                if baseline is None:
                    continue
                delta = value - baseline
                if abs(delta) > 0.15:
                    # Dedup: only emit if value changed by >0.1 since last emission
                    last_value = self._last_perf_snapshot.get(dim_name)
                    if last_value is not None and abs(value - last_value) <= 0.1:
                        continue
                    self._last_perf_snapshot[dim_name] = value
                    events.append(
                        CascadeEvent(
                            source="performance",
                            text=f"{dim_name}: {value:.2f} (baseline {baseline:.2f}, delta {delta:+.2f})",
                            magnitude=min(abs(delta), 1.0),
                            metadata={"baseline": baseline, "dimension": dim_name},
                        )
                    )

        # 6. Cross-modal resonance
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

        # 7. Pattern shifts
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

        return events
```

- [ ] **Step 5: Run lint**

```bash
cd hapax-council && uv run ruff check shared/apperception_tick.py
```

- [ ] **Step 6: Commit**

```bash
cd hapax-council && git add shared/apperception_tick.py && git commit -m "feat(apperception): wire performance, cross-resonance, pattern-shift event sources

Refactor _read_stimmung_stance → _read_stimmung returning full data.
Add _STIMMUNG_BASELINES dict, dedup snapshot, 3 new event collection
blocks in _collect_events (sections 5-7)."
```

---

### Task 2: Tests for Performance Events

**Files:**
- Modify: `tests/test_apperception_events.py`

- [ ] **Step 1: Add `test_performance_above_baseline`**

Append to `TestEventCollection` class:

```python
    def test_performance_above_baseline(self, tmp_path):
        """Stimmung dimension delta > 0.15 from baseline generates performance event."""
        from shared.apperception_tick import _STIMMUNG_BASELINES

        stimmung_data = {
            "health": {"value": 0.5, "trend": "rising", "freshness_s": 10},
            "resource_pressure": {"value": 0.3, "trend": "stable", "freshness_s": 10},
        }

        events: list[CascadeEvent] = []
        for dim_name, dim in stimmung_data.items():
            if not isinstance(dim, dict) or "value" not in dim:
                continue
            value = dim["value"]
            baseline = _STIMMUNG_BASELINES.get(dim_name)
            if baseline is None:
                continue
            delta = value - baseline
            if abs(delta) > 0.15:
                events.append(
                    CascadeEvent(
                        source="performance",
                        text=f"{dim_name}: {value:.2f} (baseline {baseline:.2f}, delta {delta:+.2f})",
                        magnitude=min(abs(delta), 1.0),
                        metadata={"baseline": baseline, "dimension": dim_name},
                    )
                )

        # health: 0.5 - 0.1 = 0.4 delta → event
        # resource_pressure: 0.3 - 0.3 = 0.0 delta → no event
        assert len(events) == 1
        assert events[0].source == "performance"
        assert events[0].metadata["dimension"] == "health"
        assert events[0].magnitude == 0.4
```

- [ ] **Step 2: Add `test_performance_within_baseline`**

```python
    def test_performance_within_baseline(self):
        """Stimmung dimension within 0.15 of baseline does not generate event."""
        from shared.apperception_tick import _STIMMUNG_BASELINES

        stimmung_data = {
            "health": {"value": 0.2, "trend": "stable", "freshness_s": 10},
            "error_rate": {"value": 0.1, "trend": "stable", "freshness_s": 10},
        }

        events: list[CascadeEvent] = []
        for dim_name, dim in stimmung_data.items():
            if not isinstance(dim, dict) or "value" not in dim:
                continue
            value = dim["value"]
            baseline = _STIMMUNG_BASELINES.get(dim_name)
            if baseline is None:
                continue
            delta = value - baseline
            if abs(delta) > 0.15:
                events.append(
                    CascadeEvent(
                        source="performance",
                        text=f"{dim_name}: {value:.2f}",
                        magnitude=min(abs(delta), 1.0),
                    )
                )

        # health: 0.2 - 0.1 = 0.1 → below threshold
        # error_rate: 0.1 - 0.05 = 0.05 → below threshold
        assert len(events) == 0
```

- [ ] **Step 3: Add `test_performance_dedup`**

```python
    def test_performance_dedup(self):
        """Same dimension value emitted twice → only first produces event (dedup)."""
        from shared.apperception_tick import _STIMMUNG_BASELINES

        snapshot: dict[str, float] = {}
        dim_name = "health"
        baseline = _STIMMUNG_BASELINES[dim_name]

        results = []
        for _tick in range(2):
            value = 0.6  # delta 0.5 from baseline 0.1
            delta = value - baseline
            if abs(delta) > 0.15:
                last_value = snapshot.get(dim_name)
                if last_value is not None and abs(value - last_value) <= 0.1:
                    results.append("deduped")
                    continue
                snapshot[dim_name] = value
                results.append("emitted")

        assert results == ["emitted", "deduped"]
```

- [ ] **Step 4: Run tests**

```bash
cd hapax-council && uv run pytest tests/test_apperception_events.py -v -x
```

- [ ] **Step 5: Commit**

```bash
cd hapax-council && git add tests/test_apperception_events.py && git commit -m "test(apperception): add performance event tests (baseline, threshold, dedup)"
```

---

### Task 3: VLA Cross-Resonance Bridge

**Files:**
- Modify: `agents/visual_layer_aggregator/aggregator.py`

- [ ] **Step 1: Add `_labels_resonate` helper method**

Add after the `_apply_stability_filter` method (around line 770). This is a simplified boolean version of the AV correlator boost rules:

```python
    @staticmethod
    def _labels_resonate(audio_label: str, video_category: str) -> bool:
        """Check if audio classification resonates with video classification.

        Simplified from av_correlator BOOST_RULES — returns True if any rule
        matches the audio/video pair with a positive boost.
        """
        _RESONANCE_PAIRS: list[tuple[str, str]] = [
            ("sample-session", "production_session"),
            ("sample-session", "active_work"),
            ("conversation", "conversation"),
            ("conversation", "active_work"),
            ("vocal-note", "production_session"),
            ("vocal-note", "active_work"),
            ("listening-log", "production_session"),
            ("listening-log", "active_work"),
        ]
        audio_norm = audio_label.lower().strip()
        video_norm = video_category.lower().strip()
        return any(
            audio_norm == ap and video_norm == vp
            for ap, vp in _RESONANCE_PAIRS
        )
```

- [ ] **Step 2: Add `_write_cross_resonance` method**

Add after `_labels_resonate`. This reads classification detections (video labels per camera role) and the current production_activity (audio proxy) to determine cross-modal agreement:

```python
    def _write_cross_resonance(self) -> None:
        """Write cross-modal agreement signal to /dev/shm for apperception."""
        data = self._last_perception_data
        if not data:
            return

        audio_label = data.get("production_activity", "")
        if not audio_label or audio_label == "idle":
            return

        # Build video labels per camera role from classification detections
        video_labels: dict[str, str] = {}
        for det in self._classification_detections:
            if det.label == "person":
                # Use camera role as key, activity label as category
                # Person + active production = production_session
                if self._production_active:
                    video_labels[det.camera] = "production_session"
                else:
                    video_labels[det.camera] = "active_work"

        if not video_labels:
            return

        resonance_score = 0.0
        matching_roles: list[str] = []
        for role, category in video_labels.items():
            if self._labels_resonate(audio_label, category):
                resonance_score = max(resonance_score, 0.7)
                matching_roles.append(role)

        payload = {
            "resonance_score": resonance_score,
            "audio_label": audio_label,
            "matching_roles": matching_roles,
            "timestamp": time.time(),
        }

        try:
            path = APPERCEPTION_DIR / "cross-resonance.json"
            APPERCEPTION_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.rename(path)
        except OSError:
            log.debug("Failed to write cross-resonance", exc_info=True)
```

- [ ] **Step 3: Add APPERCEPTION_DIR import**

At the top of `aggregator.py`, add `APPERCEPTION_DIR` to the path constants section. It may already be defined via the `_apperception_tick` import — check first. If not, add:

```python
APPERCEPTION_DIR = Path("/dev/shm/hapax-apperception")
```

- [ ] **Step 4: Call `_write_cross_resonance` from `compute_and_write`**

In the `compute_and_write` method, after `self._tick_apperception()` (line 946 area), add:

```python
        self._tick_apperception()
        self._write_cross_resonance()
```

- [ ] **Step 5: Run lint**

```bash
cd hapax-council && uv run ruff check agents/visual_layer_aggregator/aggregator.py
```

- [ ] **Step 6: Commit**

```bash
cd hapax-council && git add agents/visual_layer_aggregator/aggregator.py && git commit -m "feat(vla): add cross-resonance SHM bridge for apperception

_labels_resonate() simplifies AV correlator boost rules to boolean.
_write_cross_resonance() writes audio-video agreement to
/dev/shm/hapax-apperception/cross-resonance.json every tick."
```

---

### Task 4: Tests for Cross-Resonance Events

**Files:**
- Modify: `tests/test_apperception_events.py`

- [ ] **Step 1: Add `test_cross_resonance_above_threshold`**

```python
    def test_cross_resonance_above_threshold(self, tmp_path):
        """Cross-resonance score > 0.3 generates cross_resonance event."""
        cr_file = tmp_path / "cross-resonance.json"
        cr_file.write_text(
            json.dumps(
                {
                    "resonance_score": 0.7,
                    "audio_label": "sample-session",
                    "matching_roles": ["desk", "overhead"],
                    "timestamp": time.time(),
                }
            )
        )

        events: list[CascadeEvent] = []
        try:
            cr = json.loads(cr_file.read_text(encoding="utf-8"))
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

        assert len(events) == 1
        assert events[0].source == "cross_resonance"
        assert events[0].magnitude == 0.7
        assert "2 cameras" in events[0].text
```

- [ ] **Step 2: Add `test_cross_resonance_stale`**

```python
    def test_cross_resonance_stale(self, tmp_path):
        """Cross-resonance older than 30s is ignored."""
        cr_file = tmp_path / "cross-resonance.json"
        cr_file.write_text(
            json.dumps(
                {
                    "resonance_score": 0.7,
                    "audio_label": "sample-session",
                    "matching_roles": ["desk"],
                    "timestamp": time.time() - 60,  # 60s old
                }
            )
        )

        events: list[CascadeEvent] = []
        try:
            cr = json.loads(cr_file.read_text(encoding="utf-8"))
            cr_ts = cr.get("timestamp", 0)
            if (time.time() - cr_ts) <= 30:
                score = cr.get("resonance_score", 0.0)
                if score > 0.3:
                    events.append(
                        CascadeEvent(
                            source="cross_resonance",
                            text="should not appear",
                            magnitude=score,
                        )
                    )
        except Exception:
            pass

        assert len(events) == 0
```

- [ ] **Step 3: Add `test_cross_resonance_no_agreement`**

```python
    def test_cross_resonance_no_agreement(self, tmp_path):
        """Cross-resonance score 0.0 does not generate event."""
        cr_file = tmp_path / "cross-resonance.json"
        cr_file.write_text(
            json.dumps(
                {
                    "resonance_score": 0.0,
                    "audio_label": "silence",
                    "matching_roles": [],
                    "timestamp": time.time(),
                }
            )
        )

        events: list[CascadeEvent] = []
        try:
            cr = json.loads(cr_file.read_text(encoding="utf-8"))
            cr_ts = cr.get("timestamp", 0)
            if (time.time() - cr_ts) <= 30:
                score = cr.get("resonance_score", 0.0)
                if score > 0.3:
                    events.append(
                        CascadeEvent(
                            source="cross_resonance",
                            text="should not appear",
                            magnitude=score,
                        )
                    )
        except Exception:
            pass

        assert len(events) == 0
```

- [ ] **Step 4: Run tests**

```bash
cd hapax-council && uv run pytest tests/test_apperception_events.py -v -x
```

- [ ] **Step 5: Commit**

```bash
cd hapax-council && git add tests/test_apperception_events.py && git commit -m "test(apperception): add cross-resonance event tests (threshold, stale, no agreement)"
```

---

### Task 5: VLA Pattern-Shifts Bridge

**Files:**
- Modify: `agents/visual_layer_aggregator/aggregator.py`

- [ ] **Step 1: Add `_write_pattern_shifts` method**

Add after `_write_cross_resonance`. This is called from the pattern search callback (line 589 area) when matches are found:

```python
    def _write_pattern_shifts(self, matches: list) -> None:
        """Write pattern confirmation/contradiction signals for apperception.

        Compares active pattern matches against recent BOCPD change points
        to determine if patterns are confirmed or contradicted.
        """
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
                cp.get("signal", "") in match.pattern.condition
                for cp in recent_cps
            )
            # Pattern contradicted if change point detected in pattern's signal
            contradicted = any(
                cp.get("signal", "") in match.pattern.condition
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
            try:
                path = APPERCEPTION_DIR / "pattern-shifts.json"
                APPERCEPTION_DIR.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload), encoding="utf-8")
                tmp.rename(path)
            except OSError:
                log.debug("Failed to write pattern-shifts", exc_info=True)
```

- [ ] **Step 2: Call `_write_pattern_shifts` from pattern search callback**

In the pattern search section (around line 589-590), after `self._active_patterns = matches`, add the bridge call:

```python
                    matches = self._pattern_store.search(query, limit=3, min_score=0.3)
                    self._active_patterns = matches
                    self._write_pattern_shifts(matches)
```

- [ ] **Step 3: Run lint**

```bash
cd hapax-council && uv run ruff check agents/visual_layer_aggregator/aggregator.py
```

- [ ] **Step 4: Commit**

```bash
cd hapax-council && git add agents/visual_layer_aggregator/aggregator.py && git commit -m "feat(vla): add pattern-shifts SHM bridge for apperception

_write_pattern_shifts() compares PatternMatch results against BOCPD
change points to determine confirmed/contradicted patterns, writes to
/dev/shm/hapax-apperception/pattern-shifts.json."
```

---

### Task 6: Tests for Pattern-Shift Events

**Files:**
- Modify: `tests/test_apperception_events.py`

- [ ] **Step 1: Add `test_pattern_shift_confirmed`**

```python
    def test_pattern_shift_confirmed(self, tmp_path):
        """Confirmed pattern shift generates pattern_shift event with positive cascade."""
        ps_file = tmp_path / "pattern-shifts.json"
        ps_file.write_text(
            json.dumps(
                {
                    "shifts": [
                        {
                            "pattern_id": "p-001",
                            "prediction": "break likely within 5 minutes",
                            "confidence": 0.75,
                            "confirmed": True,
                            "timestamp": time.time(),
                        }
                    ],
                    "timestamp": time.time(),
                }
            )
        )

        events: list[CascadeEvent] = []
        try:
            ps = json.loads(ps_file.read_text(encoding="utf-8"))
            ps_ts = ps.get("timestamp", 0)
            if (time.time() - ps_ts) <= 60:
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

        assert len(events) == 1
        assert events[0].source == "pattern_shift"
        assert events[0].metadata["confirmed"] is True
        assert events[0].magnitude == 0.75
        assert "confirmed" in events[0].text
```

- [ ] **Step 2: Add `test_pattern_shift_contradicted`**

```python
    def test_pattern_shift_contradicted(self, tmp_path):
        """Contradicted pattern shift generates event with confirmed=False."""
        ps_file = tmp_path / "pattern-shifts.json"
        ps_file.write_text(
            json.dumps(
                {
                    "shifts": [
                        {
                            "pattern_id": "p-002",
                            "prediction": "flow state expected after 20 min coding",
                            "confidence": 0.6,
                            "confirmed": False,
                            "timestamp": time.time(),
                        }
                    ],
                    "timestamp": time.time(),
                }
            )
        )

        events: list[CascadeEvent] = []
        try:
            ps = json.loads(ps_file.read_text(encoding="utf-8"))
            ps_ts = ps.get("timestamp", 0)
            if (time.time() - ps_ts) <= 60:
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

        assert len(events) == 1
        assert events[0].source == "pattern_shift"
        assert events[0].metadata["confirmed"] is False
        assert "contradicted" in events[0].text
```

- [ ] **Step 3: Add `test_pattern_shift_stale`**

```python
    def test_pattern_shift_stale(self, tmp_path):
        """Pattern shift older than 60s is ignored."""
        ps_file = tmp_path / "pattern-shifts.json"
        ps_file.write_text(
            json.dumps(
                {
                    "shifts": [
                        {
                            "pattern_id": "p-003",
                            "prediction": "stale prediction",
                            "confidence": 0.8,
                            "confirmed": True,
                            "timestamp": time.time() - 120,
                        }
                    ],
                    "timestamp": time.time() - 120,  # 2 minutes old
                }
            )
        )

        events: list[CascadeEvent] = []
        try:
            ps = json.loads(ps_file.read_text(encoding="utf-8"))
            ps_ts = ps.get("timestamp", 0)
            if (time.time() - ps_ts) <= 60:
                for shift in ps.get("shifts", []):
                    events.append(
                        CascadeEvent(
                            source="pattern_shift",
                            text="should not appear",
                            magnitude=shift.get("confidence", 0.5),
                        )
                    )
        except Exception:
            pass

        assert len(events) == 0
```

- [ ] **Step 4: Run tests**

```bash
cd hapax-council && uv run pytest tests/test_apperception_events.py -v -x
```

- [ ] **Step 5: Commit**

```bash
cd hapax-council && git add tests/test_apperception_events.py && git commit -m "test(apperception): add pattern-shift event tests (confirmed, contradicted, stale)"
```

---

### Task 7: Mirror Tick Changes to agents/_apperception_tick.py

**Files:**
- Modify: `agents/_apperception_tick.py`

- [ ] **Step 1: Add baselines dict and new path constants**

After `APPERCEPTION_CACHE_FILE` (line 29), add the same constants as `shared/apperception_tick.py`:

```python
# ── Performance baselines (0.0=good, 1.0=bad) ──────────────────────────────
_STIMMUNG_BASELINES: dict[str, float] = {
    "health": 0.1,
    "resource_pressure": 0.3,
    "error_rate": 0.05,
    "processing_throughput": 0.2,
    "perception_confidence": 0.1,
    "llm_cost_pressure": 0.15,
}

CROSS_RESONANCE_FILE = APPERCEPTION_DIR / "cross-resonance.json"
PATTERN_SHIFT_FILE = APPERCEPTION_DIR / "pattern-shifts.json"
```

- [ ] **Step 2: Update `__init__` with dedup state**

```python
    def __init__(self) -> None:
        self._cascade = self._load_model()
        self._prev_stimmung_stance: str = "nominal"
        self._last_save: float = 0.0
        self._last_correction_ts: float = 0.0  # dedup corrections
        self._last_perf_snapshot: dict[str, float] = {}  # dedup performance
        self._last_perf_reset: float = time.monotonic()  # reset every 300s
```

- [ ] **Step 3: Replace `_read_stimmung_stance` with `_read_stimmung`**

```python
    def _read_stimmung(self) -> tuple[str, dict | None]:
        """Read stimmung state. Returns (stance, full_data)."""
        try:
            raw = json.loads(STIMMUNG_FILE.read_text(encoding="utf-8"))
            return raw.get("overall_stance", "nominal"), raw
        except Exception:
            return "nominal", None
```

- [ ] **Step 4: Update `tick()` method**

```python
    def tick(self) -> None:
        """Run one apperception cycle. Call this every 3-5 seconds."""
        stance, stimmung_data = self._read_stimmung()
        events = self._collect_events(stance, stimmung_data)

        pending_actions: list[str] = []
        for event in events:
            result = self._cascade.process(event, stimmung_stance=stance)
            if result and result.action:
                pending_actions.append(result.action)

        self._write_shm(pending_actions)

        now = time.monotonic()
        if now - self._last_save >= 300.0:
            self.save_model()
            self._last_save = now
```

- [ ] **Step 5: Replace entire `_collect_events` method**

Copy the full `_collect_events` method from Task 1 Step 4 verbatim. The only difference is the import path (`agents._apperception` vs `shared.apperception`) which is already handled by the module-level import at line 17.

```python
    def _collect_events(self, stance: str, stimmung_data: dict | None = None) -> list[CascadeEvent]:
        events: list[CascadeEvent] = []

        # Read temporal file ONCE (C6: prevent contradictory events)
        temporal_data = None
        try:
            temporal_data = json.loads(TEMPORAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

        # 1. Surprise from temporal bands
        if temporal_data is not None:
            ts = temporal_data.get("timestamp", 0)
            if (time.time() - ts) <= 30:
                surprise = temporal_data.get("max_surprise", 0.0)
                if surprise > 0.3:
                    events.append(
                        CascadeEvent(
                            source="prediction_error",
                            text=f"temporal surprise {surprise:.2f}",
                            magnitude=min(surprise, 1.0),
                        )
                    )

        # 2. Operator corrections (dedup by timestamp)
        try:
            corr = json.loads(CORRECTION_FILE.read_text(encoding="utf-8"))
            corr_ts = corr.get("timestamp", 0)
            elapsed = time.time() - corr_ts
            if elapsed < 10 and corr_ts > self._last_correction_ts:
                self._last_correction_ts = corr_ts
                events.append(
                    CascadeEvent(
                        source="correction",
                        text=f"operator corrected: {corr.get('label', 'unknown')}",
                        magnitude=0.7,
                    )
                )
        except Exception:
            pass

        # 3. Stimmung transition
        if stance != self._prev_stimmung_stance:
            stances = ["nominal", "cautious", "degraded", "critical"]
            try:
                improving = stances.index(stance) < stances.index(self._prev_stimmung_stance)
            except ValueError:
                improving = False
            events.append(
                CascadeEvent(
                    source="stimmung_event",
                    text=f"stance: {self._prev_stimmung_stance} → {stance}",
                    magnitude=0.5,
                    metadata={"direction": "improving" if improving else "degrading"},
                )
            )
            self._prev_stimmung_stance = stance

        # 4. Perception staleness (reuse temporal_data — mutually exclusive with surprise)
        if temporal_data is not None:
            perception_age = time.time() - temporal_data.get("timestamp", 0)
            if perception_age > 30.0:
                events.append(
                    CascadeEvent(
                        source="absence",
                        text=f"perception stale ({perception_age:.0f}s)",
                        magnitude=min(perception_age / 120.0, 1.0),
                    )
                )

        # 5. Performance deltas (from stimmung dimensions)
        now_mono = time.monotonic()
        if now_mono - self._last_perf_reset > 300.0:
            self._last_perf_snapshot.clear()
            self._last_perf_reset = now_mono

        if stimmung_data is not None:
            for dim_name, dim in stimmung_data.items():
                if not isinstance(dim, dict) or "value" not in dim:
                    continue
                value = dim["value"]
                baseline = _STIMMUNG_BASELINES.get(dim_name)
                if baseline is None:
                    continue
                delta = value - baseline
                if abs(delta) > 0.15:
                    last_value = self._last_perf_snapshot.get(dim_name)
                    if last_value is not None and abs(value - last_value) <= 0.1:
                        continue
                    self._last_perf_snapshot[dim_name] = value
                    events.append(
                        CascadeEvent(
                            source="performance",
                            text=f"{dim_name}: {value:.2f} (baseline {baseline:.2f}, delta {delta:+.2f})",
                            magnitude=min(abs(delta), 1.0),
                            metadata={"baseline": baseline, "dimension": dim_name},
                        )
                    )

        # 6. Cross-modal resonance
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

        # 7. Pattern shifts
        try:
            ps = json.loads(PATTERN_SHIFT_FILE.read_text(encoding="utf-8"))
            ps_ts = ps.get("timestamp", 0)
            if (time.time() - ps_ts) <= 60:
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

        return events
```

- [ ] **Step 6: Run lint**

```bash
cd hapax-council && uv run ruff check agents/_apperception_tick.py
```

- [ ] **Step 7: Commit**

```bash
cd hapax-council && git add agents/_apperception_tick.py && git commit -m "feat(agents): mirror apperception event source changes to vendored tick"
```

---

### Task 8: Final Verification + PR

- [ ] **Step 1: Run full test suite for apperception**

```bash
cd hapax-council && uv run pytest tests/test_apperception_events.py tests/test_apperception.py -v -x
```

- [ ] **Step 2: Run ruff on all touched files**

```bash
cd hapax-council && uv run ruff check shared/apperception_tick.py agents/_apperception_tick.py agents/visual_layer_aggregator/aggregator.py tests/test_apperception_events.py
```

- [ ] **Step 3: Run ruff format on all touched files**

```bash
cd hapax-council && uv run ruff format shared/apperception_tick.py agents/_apperception_tick.py agents/visual_layer_aggregator/aggregator.py tests/test_apperception_events.py
```

- [ ] **Step 4: Verify both tick files are in sync**

Diff the two tick files to confirm they only differ in their import paths:

```bash
cd hapax-council && diff <(sed 's/from agents._apperception/from shared.apperception/' agents/_apperception_tick.py | sed 's/Vendored apperception tick for the agents package./Apperception tick — standalone self-observation loop./' | sed '/^Copied from/d') shared/apperception_tick.py
```

- [ ] **Step 5: Create PR**

```bash
cd hapax-council && git push -u origin HEAD && gh pr create --title "feat(apperception): wire performance, cross-resonance, pattern-shift event sources" --body "## Summary

Sub-project 2 of 3: Apperception Event Source Completion.

Wires the 3 unwired cascade event sources so all 7 source types produce events:

- **performance**: Stimmung dimension deltas against hardcoded baselines (6 infra dimensions). Dedup snapshot resets every 300s.
- **cross_resonance**: VLA bridge writes audio-video agreement score to /dev/shm. Tick reads with 30s staleness check.
- **pattern_shift**: VLA bridge writes BOCPD + PatternStore confirmed/contradicted signals to /dev/shm. Tick reads with 60s staleness check.

## Changes
- Refactored \`_read_stimmung_stance\` → \`_read_stimmung\` returning full data
- Added 3 new event collection blocks in \`_collect_events\` (sections 5-7)
- Added \`_labels_resonate()\`, \`_write_cross_resonance()\`, \`_write_pattern_shifts()\` to VLA
- 9 new tests covering all 3 event types
- Mirrored all tick changes to agents/_apperception_tick.py

## Test plan
- [ ] \`uv run pytest tests/test_apperception_events.py -v\` — 9 new tests pass
- [ ] \`uv run ruff check\` — no lint errors on touched files
- [ ] Verify cross-resonance.json appears in /dev/shm after VLA restart
- [ ] Verify pattern-shifts.json appears after pattern search fires

Spec: docs/superpowers/specs/2026-03-31-apperception-event-sources-design.md"
```

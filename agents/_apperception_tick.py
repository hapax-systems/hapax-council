"""Vendored apperception tick for the agents package.

Copied from shared/apperception_tick.py. Standalone self-observation loop.
Reads events from shm-based subsystems (temporal bands, corrections,
stimmung) and feeds them through the ApperceptionCascade.

All inputs come from the filesystem — no in-process state dependencies.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from agents._apperception import ApperceptionCascade, ApperceptionStore, CascadeEvent, SelfModel

log = logging.getLogger("apperception_tick")

# ── Paths ────────────────────────────────────────────────────────────────────

TEMPORAL_FILE = Path("/dev/shm/hapax-temporal/bands.json")
STIMMUNG_FILE = Path("/dev/shm/hapax-stimmung/state.json")
CORRECTION_FILE = Path("/dev/shm/hapax-compositor/activity-correction.json")
APPERCEPTION_DIR = Path("/dev/shm/hapax-apperception")
APPERCEPTION_FILE = APPERCEPTION_DIR / "self-band.json"
APPERCEPTION_CACHE_DIR = Path.home() / ".cache" / "hapax-apperception"
APPERCEPTION_CACHE_FILE = APPERCEPTION_CACHE_DIR / "self-model.json"

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


class ApperceptionTick:
    """Standalone apperception tick — reads shm, runs cascade, writes shm.

    All inputs from the filesystem. No in-process state dependencies.
    Can be driven by any tick loop (aggregator, daemon, or standalone).
    """

    def __init__(self) -> None:
        self._cascade = self._load_model()
        self._prev_stimmung_stance: str = "nominal"
        # _last_save and _last_flush use time.monotonic() (interval measurement).
        # Event timestamps and SHM payload use time.time() (wall clock for consumers).
        # These serve different purposes and should NOT be unified.
        self._last_save: float = 0.0
        self._last_flush: float = 0.0
        self._last_correction_ts: float = 0.0  # dedup corrections
        self._last_perf_snapshot: dict[str, float] = {}  # dedup performance
        self._last_perf_reset: float = time.monotonic()  # reset every 300s
        self._tick_seq: int = 0
        self._store = ApperceptionStore()
        try:
            self._store.ensure_collection()
        except Exception:
            log.debug("Failed to ensure apperception collection", exc_info=True)

    def tick(self) -> None:
        """Run one apperception cycle. Call this every 3-5 seconds."""
        self._tick_seq += 1
        stance, stimmung_data = self._read_stimmung()
        events = self._collect_events(stance, stimmung_data)

        pending_actions: list[str] = []
        for event in events:
            result = self._cascade.process(event, stimmung_stance=stance)
            if result:
                self._store.add(result)
                if result.action:
                    pending_actions.append(result.action)

        self._write_shm(pending_actions, event_count=len(events))

        now = time.monotonic()
        if now - self._last_flush >= 60.0:
            try:
                self._store.flush()
            except Exception:
                log.debug("Failed to flush apperception store", exc_info=True)
            self._last_flush = now

        if now - self._last_save >= 300.0:
            self.save_model()
            self._last_save = now

    def save_model(self) -> None:
        """Persist self-model to cache. Call on shutdown."""
        try:
            self._store.flush()
        except Exception:
            log.debug("Failed to flush store on save", exc_info=True)
        try:
            APPERCEPTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            data = self._cascade.model.to_dict()
            tmp = APPERCEPTION_CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.rename(APPERCEPTION_CACHE_FILE)
        except OSError:
            log.debug("Failed to persist self-model", exc_info=True)

    @property
    def model(self) -> SelfModel:
        return self._cascade.model

    # ── Event collection (all from filesystem) ───────────────────────

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

    # ── Filesystem I/O ───────────────────────────────────────────────

    def _read_stimmung(self) -> tuple[str, dict | None]:
        """Read stimmung state. Returns (stance, full_data)."""
        try:
            raw = json.loads(STIMMUNG_FILE.read_text(encoding="utf-8"))
            return raw.get("overall_stance", "nominal"), raw
        except Exception:
            return "nominal", None

    def _write_shm(self, pending_actions: list[str], event_count: int = 0) -> None:
        try:
            payload = {
                "self_model": self._cascade.model.to_dict(),
                "pending_actions": pending_actions,
                "timestamp": time.time(),
                "tick_seq": self._tick_seq,
                "events_this_tick": event_count,
            }
            APPERCEPTION_DIR.mkdir(parents=True, exist_ok=True)
            tmp = APPERCEPTION_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.rename(APPERCEPTION_FILE)
        except OSError:
            log.debug("Failed to write apperception state", exc_info=True)

    def _load_model(self) -> ApperceptionCascade:
        model = SelfModel()
        try:
            if APPERCEPTION_CACHE_FILE.exists():
                data = json.loads(APPERCEPTION_CACHE_FILE.read_text(encoding="utf-8"))
                model = SelfModel.from_dict(data)
                log.info("Loaded self-model from cache (%d dimensions)", len(model.dimensions))
        except Exception:
            log.debug("Failed to load self-model cache, starting fresh", exc_info=True)
        return ApperceptionCascade(self_model=model)

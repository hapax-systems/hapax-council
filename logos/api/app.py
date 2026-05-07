"""FastAPI application for the logos API.

Serves data from logos/data/ collectors over HTTP.
Consumed by the Tauri desktop app and Vite dev server.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

try:
    from logos import _langfuse_config  # noqa: F401
except Exception:
    pass  # langfuse optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from logos.api.cache import start_refresh_loop
from logos.api.sessions import agent_run_manager
from logos.api.witness_rail import start_logos_witness_producer

_log = logging.getLogger(__name__)


# Phase 6d-i.B drift signal bridge. Adapts logos/data/drift.py's
# DriftSummary into the _DriftSource Protocol that
# drift_significant_observation expects. Saturation point of 10 high-
# severity items lines up with the "operator burnt by drift" threshold
# the session-context hook has surfaced (~16 high items at audit time).
class LogosDriftBridge:
    """Bridge collect_drift() → drift_score() Protocol for SystemDegradedEngine."""

    def drift_score(self) -> float:
        from logos.data.drift import collect_drift

        summary = collect_drift()
        if summary is None:
            return 0.0
        high = sum(1 for i in summary.items if i.severity.upper() == "HIGH")
        return min(1.0, high / 10.0)


# Phase 6d-i.B GPU pressure bridge. Reads the same infra-snapshot.json
# that logos/data/gpu.py:collect_vram() consumes, but synchronously so
# the Protocol stays sync (gpu_pressure_observation is called inside
# the SystemDegradedEngine tick loop without awaiting). The snapshot
# is host-written by the health monitor; missing/stale file → (0, 0)
# which the adapter treats as "pressure unknown" (False, instrument
# fault tolerance).
class LogosGpuBridge:
    """Bridge infra-snapshot.json gpu block → gpu_memory_used_total() Protocol."""

    def gpu_memory_used_total(self) -> tuple[int, int]:
        import json

        from logos._config import PROFILES_DIR

        try:
            data = json.loads((PROFILES_DIR / "infra-snapshot.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return (0, 0)
        # Schema guard: a writer producing valid JSON whose root is null,
        # a list, a string, or a number raises AttributeError on
        # ``data.get(\"gpu\")``. Coerce to {} so the GPU-mem accessor
        # falls back to (0, 0) instead of crashing the API endpoint.
        # Same shape as the other recent SHM-read fixes.
        if not isinstance(data, dict):
            return (0, 0)
        gpu_raw = data.get("gpu") or {}
        gpu = gpu_raw if isinstance(gpu_raw, dict) else {}
        return (int(gpu.get("used_mb", 0)), int(gpu.get("total_mb", 0)))


# Phase 6a-i.B perception-state bridge. Reads the daimonion-side
# perception-state.json (atomic write-then-rename by
# ``agents.hapax_daimonion._perception_state_writer``) for the
# OperatorActivityEngine signal stream. Wires ``keyboard_active``
# (#1389) + ``desk_active`` (#1391) + ``desktop_focus_changed_recent``
# (this PR). Remaining 2 activity signals (midi_clock_active,
# watch_movement) wire in follow-up PRs as their adapter contracts land.
#
# Missing/stale file → ``None`` from every accessor, which the engine
# treats as "skip this signal" (no positive nor negative evidence) per
# the ``ClaimEngine.tick`` contract — the alternative (assume idle on
# missing file) would let a daimonion crash spuriously decay the
# posterior to IDLE.
#
# Stateful: ``desktop_focus_changed_recent`` tracks the prior tick's
# ``active_window_class`` so the bridge instance must persist across
# ticks. Lifespan creates a single instance and reuses it, matching
# the SystemDegradedEngine bridge pattern.
class LogosPerceptionStateBridge:
    """Bridge perception-state.json → activity-signal Protocol for OAE."""

    # ``desk_activity`` is a string enum from the contact-mic DSP
    # gesture classifier. Anything other than these idle states counts
    # as engaged-with-the-desk activity. Centralised so the mapping is
    # reviewable in one place when tuning later.
    _DESK_IDLE_STATES: frozenset[str] = frozenset({"idle", "none"})

    def __init__(self) -> None:
        # Prior-tick focus state — None until the first observation
        # lands. Used by ``desktop_focus_changed_recent`` to compute
        # focus-change evidence across ticks. Reset by a fresh instance.
        self._last_window_class: str | None = None
        self._has_observed_window: bool = False

    def _load(self) -> dict | None:
        """Load perception-state.json as a dict, or None on any failure.

        Validates the JSON root is a mapping. Callers
        (``keyboard_active``, ``desk_active``) use ``\"key\" in data``
        and ``data[\"key\"]`` lookups — a writer producing valid JSON
        whose root is a list, string, or number would pass the
        ``in`` check (with surprising semantics) and then crash on the
        item-access. Same shape as the other recent SHM-read fixes.
        """
        import json
        from pathlib import Path

        path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
        try:
            data = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def keyboard_active(self) -> bool | None:
        data = self._load()
        if data is None or "keyboard_active" not in data:
            return None
        return bool(data["keyboard_active"])

    def desk_active(self) -> bool | None:
        data = self._load()
        if data is None or "desk_activity" not in data:
            return None
        activity = str(data["desk_activity"]).lower()
        return activity not in self._DESK_IDLE_STATES

    def desktop_focus_changed_recent(self) -> bool | None:
        """True iff active_window_class differs from the prior tick.

        First observation returns None — no prior state to compare. The
        engine treats None as skip-this-signal so the first tick after
        startup contributes neither positive nor negative evidence on
        this signal. Subsequent ticks return True (changed) or False
        (unchanged) and update the cached prior. Missing file or
        missing field returns None and does NOT advance prior state —
        a transient daimonion outage shouldn't cause a spurious
        focus-change report on recovery.
        """
        data = self._load()
        if data is None or "active_window_class" not in data:
            return None
        current = str(data["active_window_class"])
        if not self._has_observed_window:
            self._last_window_class = current
            self._has_observed_window = True
            return None
        changed = current != self._last_window_class
        self._last_window_class = current
        return changed

    def midi_clock_active(self) -> bool | None:
        """True iff the OXI One MIDI clock transport is PLAYING.

        ``MidiClockBackend.contribute()`` publishes a ``midi_clock_transport``
        behavior carrying the ``TransportState`` enum name (PLAYING /
        STOPPED). The perception-state writer surfaces it under the same
        key so this bridge can read it without a separate publisher.

        Returns None when the perception-state file is missing the field
        (daimonion not yet writing it, e.g. mido unavailable). The Bayesian
        engine treats None as skip-this-signal — no evidence contributed.
        Empty string also returns None (default value before any tick).
        """
        data = self._load()
        if data is None or "midi_clock_transport" not in data:
            return None
        transport = str(data["midi_clock_transport"])
        if not transport:
            return None
        return transport == "PLAYING"

    # ``activity.json`` updated_at older than this is treated as stale —
    # operator removed the watch, BLE dropped, sync agent died, etc. The
    # cutoff is loose (10 min) because watch movement is a low-frequency
    # ground-truth signal: long stretches of stillness are normal during
    # focused desk work and should not be conflated with sensor outage.
    _WATCH_STALENESS_S: float = 600.0
    # ``activity.json`` ``state`` enum from hapax-watch (Pixel Watch).
    # Anything other than these idle states counts as movement. Mirrors
    # the ``_DESK_IDLE_STATES`` pattern above so the mapping is editable
    # in one place.
    _WATCH_IDLE_STATES: frozenset[str] = frozenset({"STILL", "RESTING", "SEDENTARY"})

    def watch_movement(self) -> bool | None:
        """True iff the Pixel Watch reports a non-idle activity state.

        Reads ``~/hapax-state/watch/activity.json`` (written by the
        ``hapax-watch-receiver`` HTTP endpoint). The file shape is::

            {"source": "pixel_watch_4",
             "updated_at": "2026-04-25T19:30:00.000+00:00",
             "state": "WALKING"}

        Mapping:
        - state in {STILL, RESTING, SEDENTARY} → False (real negative
          evidence: watch live, body not moving — same shape as
          ``keyboard_active`` False on idle)
        - any other state → True (WALKING / RUNNING / EXERCISING / etc.)
        - missing file or corrupt JSON → None
        - ``updated_at`` older than ``_WATCH_STALENESS_S`` (10 min) →
          None. Watch movement is a low-frequency signal and stale data
          is uninformative; the BLE link dropping shouldn't decay the
          posterior toward IDLE on a still-engaged operator.
        """
        import json
        from datetime import UTC, datetime
        from pathlib import Path

        path = Path.home() / "hapax-state" / "watch" / "activity.json"
        try:
            data = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict) or "state" not in data:
            return None
        # Staleness check — fail-soft on missing/malformed timestamp.
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            try:
                ts = datetime.fromisoformat(updated_at)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                age_s = (datetime.now(UTC) - ts).total_seconds()
                if age_s > self._WATCH_STALENESS_S:
                    return None
            except ValueError:
                # Malformed timestamp: treat as stale rather than trust it.
                return None
        state = str(data["state"]).upper()
        if not state:
            return None
        return state not in self._WATCH_IDLE_STATES


# Phase 6b-i bridge for the four mood-arousal signals. Per-backend
# rolling-quantile calibration is now live (audit-3-fix-4, Phase A).
# Each accessor reads perception-state.json and compares against a
# 30-min rolling baseline via shared.mood_calibration.RollingQuantile.
class LogosStimmungBridge:
    """Bridge stimmung-derived signals → MoodArousalEngine signal Protocol.

    Phase A mood-arousal calibration (audit-3-fix-4). Each accessor reads
    live data from perception-state.json and compares against rolling
    baselines via ``RollingQuantile``.

    Staleness contract: if the perception-state data is >120s old or
    the rolling quantile has insufficient samples, the accessor returns
    ``None`` (skip-signal per ClaimEngine.tick semantics).
    """

    # BPM cutoff for midi_clock_bpm_high. Operator-configurable via env.
    _BPM_CUTOFF: float = float(__import__("os").environ.get("HAPAX_MOOD_AROUSAL_BPM_CUTOFF", "120"))

    def __init__(self) -> None:
        from shared.mood_calibration import RollingQuantile

        # 30-min rolling window, q80 threshold, min 10 observations
        self._rms_quantile = RollingQuantile(
            window_s=1800.0, quantile=0.8, min_samples=10, stale_s=120.0
        )
        self._onset_quantile = RollingQuantile(
            window_s=1800.0, quantile=0.8, min_samples=10, stale_s=120.0
        )
        # HR: 30-day window is too long for rolling deque; use a simpler
        # 30-min baseline median + 1.5×MAD. RollingQuantile(q=0.5) gives
        # the median; we track MAD separately via a second quantile.
        self._hr_baseline = RollingQuantile(
            window_s=1800.0, quantile=0.5, min_samples=10, stale_s=120.0
        )

    def _load(self) -> dict | None:
        import json
        from pathlib import Path

        path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _is_fresh(self, data: dict) -> bool:
        """Check if perception state is <120s old."""
        import time

        ts = data.get("timestamp", 0)
        if not ts:
            return False
        return (time.time() - float(ts)) < 120.0

    def ambient_audio_rms_high(self) -> bool | None:
        """True if room mic RMS is above the operator's 30-min q80.

        Reads ``audio_energy_rms`` from perception-state.json. Observes
        each tick into the rolling quantile tracker, then compares the
        current value against q80.
        """
        data = self._load()
        if data is None or not self._is_fresh(data):
            return None
        rms = data.get("audio_energy_rms")
        if rms is None:
            return None
        rms = float(rms)
        self._rms_quantile.observe(rms)
        return self._rms_quantile.is_above_quantile(rms)

    def contact_mic_onset_rate_high(self) -> bool | None:
        """True if Cortado MKIII onset rate is above the operator's 30-min q80.

        Reads ``desk_onset_rate`` from perception-state.json. Observes
        each tick into the rolling quantile tracker, then compares.
        """
        data = self._load()
        if data is None or not self._is_fresh(data):
            return None
        onset_rate = data.get("desk_onset_rate")
        if onset_rate is None:
            return None
        onset_rate = float(onset_rate)
        self._onset_quantile.observe(onset_rate)
        return self._onset_quantile.is_above_quantile(onset_rate)

    def midi_clock_bpm_high(self) -> bool | None:
        """True if MIDI clock tempo exceeds the BPM cutoff (default 120).

        Reads ``midi_clock_transport`` from perception-state.json.
        Returns ``None`` when transport is not PLAYING (no tempo signal).
        The BPM is read from the timeline_mapping behavior if available,
        otherwise from the ``midi_tempo_bpm`` key.

        Configurable via ``HAPAX_MOOD_AROUSAL_BPM_CUTOFF`` env var.
        """
        data = self._load()
        if data is None or not self._is_fresh(data):
            return None
        transport = data.get("midi_clock_transport", "")
        if transport != "PLAYING":
            return None
        bpm = data.get("midi_tempo_bpm")
        if bpm is None:
            return None
        return float(bpm) > self._BPM_CUTOFF

    def hr_bpm_above_baseline(self) -> bool | None:
        """True if heart rate is above 30-min median + 1.5×MAD.

        Reads ``heart_rate_bpm`` from perception-state.json. Uses the
        rolling median from RollingQuantile(q=0.5) as the baseline.
        HR above median + 15 BPM is considered elevated (simplified
        MAD approximation for a 1.5×MAD threshold).
        """
        data = self._load()
        if data is None or not self._is_fresh(data):
            return None
        hr = data.get("heart_rate_bpm")
        if hr is None or int(hr) == 0:
            return None
        hr = float(hr)
        self._hr_baseline.observe(hr)
        median = self._hr_baseline.current_quantile()
        if median is None:
            return None
        # Simplified: above median + 15 BPM threshold
        # (approximation of median + 1.5×MAD for typical HR distributions)
        return hr > median + 15.0


# Phase 6b-ii bridge for the four mood-valence signals. Per-backend
# calibration is now live (audit-3-fix-4, Phase B). Each accessor reads
# from watch state files and perception-state.json with staleness gating.
class LogosMoodValenceBridge:
    """Bridge health/voice signals → MoodValenceEngine signal Protocol.

    Phase B mood-valence calibration (audit-3-fix-4). Reads from:
    - ``~/hapax-state/watch/hrv.json`` (HRV RMSSD)
    - ``~/hapax-state/watch/skin_temp.json`` (skin temperature)
    - ``~/hapax-state/watch/phone_health_summary.json`` (sleep data)
    - perception-state.json (voice pitch — via sst_pipeline)

    Staleness contract: accessors return ``None`` when data is >120s old
    or missing entirely (skip-signal per ClaimEngine.tick semantics).
    """

    # Staleness threshold for watch state files (seconds)
    _STALE_S: float = 120.0

    def __init__(self) -> None:
        from shared.mood_calibration import RollingQuantile

        # HRV baseline: 30-min rolling median
        self._hrv_baseline = RollingQuantile(
            window_s=1800.0, quantile=0.5, min_samples=10, stale_s=120.0
        )
        # Skin temp: 6-hour rolling tracker for drop detection
        self._skin_temp_tracker = RollingQuantile(
            window_s=21600.0, quantile=0.5, min_samples=10, stale_s=300.0
        )

    def _load_watch_file(self, filename: str) -> dict | None:
        """Load a watch state JSON file, return None if missing/corrupt."""
        import json
        from pathlib import Path

        path = Path.home() / "hapax-state" / "watch" / filename
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _is_watch_fresh(self, data: dict) -> bool:
        """Check if watch state file is <120s old via updated_at."""
        from datetime import UTC, datetime

        updated = data.get("updated_at")
        if not isinstance(updated, str):
            return False
        try:
            ts = datetime.fromisoformat(updated)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - ts).total_seconds()
            return age < self._STALE_S
        except ValueError:
            return False

    def hrv_below_baseline(self) -> bool | None:
        """True if HRV RMSSD is below the 30-min rolling median.

        Reads ``~/hapax-state/watch/hrv.json``. When current RMSSD
        falls below the rolling median, valence evidence is negative
        (operator may be stressed or fatigued).
        """
        data = self._load_watch_file("hrv.json")
        if data is None or not self._is_watch_fresh(data):
            return None
        current = data.get("current", {})
        rmssd = current.get("rmssd_ms")
        if rmssd is None:
            return None
        rmssd = float(rmssd)
        self._hrv_baseline.observe(rmssd)
        median = self._hrv_baseline.current_quantile()
        if median is None:
            return None
        return rmssd < median

    def skin_temp_drop(self) -> bool | None:
        """True if skin temp has dropped >0.3°C from the 6-hour median.

        Reads ``~/hapax-state/watch/skin_temp.json``. A drop in skin
        temperature correlates with stress or vasoconstriction.
        """
        data = self._load_watch_file("skin_temp.json")
        if data is None or not self._is_watch_fresh(data):
            return None
        current = data.get("current", {})
        temp_c = current.get("temp_c")
        if temp_c is None:
            return None
        temp_c = float(temp_c)
        self._skin_temp_tracker.observe(temp_c)
        median = self._skin_temp_tracker.current_quantile()
        if median is None:
            return None
        return temp_c < (median - 0.3)

    def sleep_debt_high(self) -> bool | None:
        """True if sleep quality score is below 0.6 (indicating sleep debt).

        Reads ``sleep_quality`` from perception-state.json. The watch
        backend computes a 0.0-1.0 score where 7h sleep = 1.0 and
        <6h sleep starts dropping significantly.
        """
        import json
        import time
        from pathlib import Path

        path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
        try:
            data = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        ts = data.get("timestamp", 0)
        if not ts or (time.time() - float(ts)) > self._STALE_S:
            return None
        quality = data.get("sleep_quality")
        if quality is None:
            return None
        return float(quality) < 0.6

    def voice_pitch_elevated(self) -> bool | None:
        """True if operator voice pitch exceeds the 30-min session baseline.

        Reads ``/dev/shm/hapax-daimonion/operator-voice-pitch.json``,
        written by the daimonion audio loop from numeric F0 samples only.
        The bootstrap fallback needs 5 voiced operator samples; missing,
        stale, or warming-up data returns ``None``.
        """
        from agents.hapax_daimonion.voice_pitch_baseline import (
            operator_voice_pitch_is_elevated,
        )

        return operator_voice_pitch_is_elevated()


# Phase 6b-iii bridge for the four mood-coherence signals. Per-backend
# calibration is now live (audit-3-fix-4, Phase C). Each accessor reads
# from watch state files with staleness gating.
class LogosMoodCoherenceBridge:
    """Bridge health-volatility signals → MoodCoherenceEngine signal Protocol.

    Phase C mood-coherence calibration (audit-3-fix-4). Reads from:
    - ``~/hapax-state/watch/hrv.json`` (HRV variability)
    - ``~/hapax-state/watch/skin_temp.json`` (skin temp volatility)
    - perception-state.json (accelerometer jerk)

    Staleness contract: accessors return ``None`` when data is >120s old
    or missing entirely (skip-signal per ClaimEngine.tick semantics).
    """

    _STALE_S: float = 120.0

    def __init__(self) -> None:
        from shared.mood_calibration import RollingQuantile

        # HRV variability: track 1h window to compute CV
        self._hrv_var_tracker = RollingQuantile(
            window_s=3600.0, quantile=0.5, min_samples=10, stale_s=120.0
        )
        # Skin temp volatility: 1h window for CV
        self._skin_temp_vol_tracker = RollingQuantile(
            window_s=3600.0, quantile=0.5, min_samples=10, stale_s=300.0
        )

    def _load_watch_file(self, filename: str) -> dict | None:
        """Load a watch state JSON file, return None if missing/corrupt."""
        import json
        from pathlib import Path

        path = Path.home() / "hapax-state" / "watch" / filename
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _is_watch_fresh(self, data: dict) -> bool:
        """Check if watch state file is <120s old via updated_at."""
        from datetime import UTC, datetime

        updated = data.get("updated_at")
        if not isinstance(updated, str):
            return False
        try:
            ts = datetime.fromisoformat(updated)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - ts).total_seconds()
            return age < self._STALE_S
        except ValueError:
            return False

    def hrv_variability_high(self) -> bool | None:
        """True if HRV coefficient of variation > 30% over the last hour.

        Reads ``~/hapax-state/watch/hrv.json`` window_1h stats. High HRV
        variability suggests autonomic incoherence (sympathetic/para-
        sympathetic oscillation).
        """
        data = self._load_watch_file("hrv.json")
        if data is None or not self._is_watch_fresh(data):
            return None
        window = data.get("window_1h", {})
        mean = window.get("mean")
        min_val = window.get("min")
        max_val = window.get("max")
        readings = window.get("readings", 0)
        if mean is None or readings < 5 or float(mean) <= 0:
            return None
        # Approximate CV from min/max/mean: (max-min) / (2*mean) as a
        # rough coefficient of variation proxy. True CV requires stddev
        # but the 1h window only provides min/max/mean.
        spread = float(max_val) - float(min_val)
        cv_approx = spread / (2.0 * float(mean))
        return cv_approx > 0.30

    def respiration_irregular(self) -> bool | None:
        """True if respiration-rate variance is high in the 1h window.

        Reads ``~/hapax-state/watch/respiration.json`` produced by
        ``agents.watch_receiver`` from phone/watch respiration-rate samples.
        Irregularity uses the same min/max/mean CV proxy as HRV variability:
        ``(max - min) / (2 * mean) > 0.20``. Missing, stale, or underfilled
        windows return ``None`` so the positive-only signal does not subtract.
        """
        data = self._load_watch_file("respiration.json")
        if data is None or not self._is_watch_fresh(data):
            return None
        window = data.get("window_1h", {})
        mean = window.get("mean")
        min_val = window.get("min")
        max_val = window.get("max")
        readings = window.get("readings", 0)
        if mean is None or min_val is None or max_val is None or readings < 5:
            return None
        if float(mean) <= 0:
            return None
        spread = float(max_val) - float(min_val)
        cv_approx = spread / (2.0 * float(mean))
        return cv_approx > 0.20

    def movement_jitter_high(self) -> bool | None:
        """True if accelerometer jerk / motion variance is high.

        Reads ``physiological_load`` from perception-state.json as a proxy
        for movement jitter. High physiological load correlates with
        fidgeting, restlessness, or physical exertion — all coherence-
        reducing signals.
        """
        import json
        import time
        from pathlib import Path

        path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
        try:
            data = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        ts = data.get("timestamp", 0)
        if not ts or (time.time() - float(ts)) > self._STALE_S:
            return None
        load = data.get("physiological_load")
        if load is None:
            return None
        # Physiological load > 0.6 indicates high exertion/movement
        return float(load) > 0.6

    def skin_temp_volatility_high(self) -> bool | None:
        """True if skin temperature CV > 10% over the last hour.

        Reads ``~/hapax-state/watch/skin_temp.json``. Rapid skin
        temperature fluctuations suggest autonomic dysregulation or
        environmental temperature stress.
        """
        data = self._load_watch_file("skin_temp.json")
        if data is None or not self._is_watch_fresh(data):
            return None
        current = data.get("current", {})
        temp_c = current.get("temp_c")
        if temp_c is None:
            return None
        temp_c = float(temp_c)
        self._skin_temp_vol_tracker.observe(temp_c)
        median = self._skin_temp_vol_tracker.current_quantile()
        if median is None or median <= 0:
            return None
        # Use deviation from median as volatility proxy
        deviation = abs(temp_c - median) / median
        return deviation > 0.10


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_refresh_loop()

    # Recover stale insight queries from prior shutdown
    try:
        from logos.data.insight_queries import recover_stale

        recover_stale()
    except Exception:
        _log.exception("Insight query recovery failed (continuing)")

    # Verify Qdrant collection schemas (non-fatal)
    try:
        from logos._qdrant_schema import log_collection_issues

        await log_collection_issues()
    except Exception:
        _log.exception("Qdrant schema verification failed (continuing)")

    # Initialize effect graph runtime (pure Python — no GPU/GStreamer needed)
    try:
        from pathlib import Path as _Path

        from agents.effect_graph.compiler import GraphCompiler
        from agents.effect_graph.modulator import UniformModulator
        from agents.effect_graph.registry import ShaderRegistry
        from agents.effect_graph.runtime import GraphRuntime
        from logos.api.routes.studio import set_graph_runtime, set_shader_registry

        _shader_nodes_dir = _Path(__file__).parent.parent.parent / "agents" / "shaders" / "nodes"
        _registry = ShaderRegistry(_shader_nodes_dir)
        _compiler = GraphCompiler(_registry)
        _modulator = UniformModulator()
        _runtime = GraphRuntime(registry=_registry, compiler=_compiler, modulator=_modulator)

        set_graph_runtime(_runtime)
        set_shader_registry(_registry)
        _log.info(
            "Effect graph runtime: %d node types loaded (API-local)", len(_registry.node_types)
        )
    except Exception:
        _log.exception("Effect graph runtime failed to initialize (continuing without it)")

    # Start event bus
    from logos.api.routes.events import set_event_bus
    from logos.event_bus import EventBus, set_global_bus

    event_bus = EventBus(maxlen=500)
    app.state.event_bus = event_bus
    set_event_bus(event_bus)
    set_global_bus(event_bus)

    # Start reactive engine
    try:
        from logos.engine import ReactiveEngine
        from logos.engine.reactive_rules import register_rules

        engine = ReactiveEngine(event_bus=event_bus)
        register_rules(engine.registry)
        await engine.start()
        app.state.engine = engine

        # Wire revocation propagator to carrier registry
        from logos._revocation_wiring import get_revocation_propagator

        app.state.revocation_propagator = get_revocation_propagator()
    except Exception:
        _log.exception("Reactive engine failed to start (continuing without it)")
        engine = None

    # Phase 6d-i.B wire-in: SystemDegradedEngine observes (1) the
    # ReactiveEngine watcher's consumer-queue depth and (2) the drift
    # detector's high-severity item count (post-#1379) and exposes a
    # Bayesian posterior for downstream consumers (DMN governor,
    # narration cadence, recruitment pipeline). Sourced from #1357
    # (engine + signal contract) + #1362 (queue-depth adapter) +
    # #1377 (drift / gpu / director adapters). Remaining 2 signals
    # (gpu / director_cadence) wire in subsequent PRs as their
    # production sources land daimonion-side.
    sde = None
    if engine is not None:
        try:
            from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine

            sde = SystemDegradedEngine()
            app.state.system_degraded_engine = sde
        except Exception:
            _log.exception("SystemDegradedEngine wire-in failed (continuing without it)")

    # Phase 6a-i.B OperatorActivityEngine observes the daimonion-side
    # perception-state.json. Five accessors wired (keyboard_active,
    # desk_active, desktop_focus_changed_recent, midi_clock_active,
    # watch_movement). Posterior + state exposed at
    # GET /api/engine/operator_activity for the DMN governor +
    # narration-cadence consumers.
    oae = None
    try:
        from agents.hapax_daimonion.operator_activity_engine import OperatorActivityEngine

        oae = OperatorActivityEngine()
        app.state.operator_activity_engine = oae
    except Exception:
        _log.exception("OperatorActivityEngine wire-in failed (continuing without it)")

    # Phase 6b-i MoodArousalEngine observes four stimmung-derived
    # arousal signals (ambient room mic RMS, contact mic onset rate,
    # MIDI clock BPM, watch HR vs baseline). All four signal accessors
    # on LogosStimmungBridge are now calibrated against rolling baselines
    # (audit-3-fix-4, Phase A) and return live True/False/None values.
    # None is returned when perception data is stale (>120s) or the
    # rolling baseline has insufficient samples (<10 observations).
    mae = None
    try:
        from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine

        mae = MoodArousalEngine()
        app.state.mood_arousal_engine = mae
    except Exception:
        _log.exception("MoodArousalEngine wire-in failed (continuing without it)")

    # Phase 6b-ii MoodValenceEngine observes four health/voice valence
    # signals (HRV vs baseline, skin temp drop, sleep debt, voice pitch
    # elevated). All four signal accessors on LogosMoodValenceBridge are
    # calibrated with stale/warm-up ``None`` semantics. Posterior + state
    # are exposed at GET /api/engine/mood_valence for the DMN governor.
    mve = None
    try:
        from agents.hapax_daimonion.mood_valence_engine import MoodValenceEngine

        mve = MoodValenceEngine()
        app.state.mood_valence_engine = mve
    except Exception:
        _log.exception("MoodValenceEngine wire-in failed (continuing without it)")

    # Phase 6b-iii MoodCoherenceEngine observes four health-volatility
    # coherence signals (HRV CV, respiration variance, movement jitter,
    # skin temp volatility). All four signal accessors on
    # LogosMoodCoherenceBridge are calibrated with stale/warm-up ``None``
    # semantics. Posterior + state are exposed at
    # GET /api/engine/mood_coherence for the DMN governor.
    mce = None
    try:
        from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine

        mce = MoodCoherenceEngine()
        app.state.mood_coherence_engine = mce
    except Exception:
        _log.exception("MoodCoherenceEngine wire-in failed (continuing without it)")

    # Start chronicle sampler and periodic trim
    import asyncio

    from shared.chronicle import trim as chronicle_trim
    from shared.chronicle_sampler import run_sampler

    async def _chronicle_trim_loop():
        while True:
            try:
                chronicle_trim()
            except Exception:
                _log.debug("Chronicle trim failed", exc_info=True)
            await asyncio.sleep(60)

    async def _system_degraded_tick_loop():
        """1s-cadence tick — observes queue depth + drift + gpu pressure + contributes."""
        from agents.hapax_daimonion.backends.drift_significant import (
            drift_significant_observation,
        )
        from agents.hapax_daimonion.backends.engine_queue_depth import (
            queue_depth_observation,
        )
        from agents.hapax_daimonion.backends.gpu_pressure import (
            gpu_pressure_observation,
        )

        drift_bridge = LogosDriftBridge()
        gpu_bridge = LogosGpuBridge()

        while True:
            try:
                if engine is not None and sde is not None:
                    obs: dict[str, bool | None] = {}
                    obs.update(queue_depth_observation(engine.watcher))
                    obs.update(drift_significant_observation(drift_bridge))
                    obs.update(gpu_pressure_observation(gpu_bridge))
                    sde.contribute(obs)
            except Exception:
                _log.debug("SystemDegradedEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    async def _operator_activity_tick_loop():
        """1s-cadence tick — observes keyboard_active + contributes to OAE."""
        from agents.hapax_daimonion.backends.operator_activity_observation import (
            operator_activity_observation,
        )

        perception_bridge = LogosPerceptionStateBridge()

        while True:
            try:
                if oae is not None:
                    oae.contribute(operator_activity_observation(perception_bridge))
            except Exception:
                _log.debug("OperatorActivityEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    async def _mood_arousal_tick_loop():
        """1s-cadence tick — observes 4 mood-arousal signals + contributes to MAE."""
        from agents.hapax_daimonion.backends.mood_arousal_observation import (
            mood_arousal_observation,
        )

        stimmung_bridge = LogosStimmungBridge()

        while True:
            try:
                if mae is not None:
                    mae.contribute(mood_arousal_observation(stimmung_bridge))
            except Exception:
                _log.debug("MoodArousalEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    async def _mood_valence_tick_loop():
        """1s-cadence tick — observes 4 mood-valence signals + contributes to MVE."""
        from agents.hapax_daimonion.backends.mood_valence_observation import (
            mood_valence_observation,
        )

        valence_bridge = LogosMoodValenceBridge()

        while True:
            try:
                if mve is not None:
                    mve.contribute(mood_valence_observation(valence_bridge))
            except Exception:
                _log.debug("MoodValenceEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    async def _mood_coherence_tick_loop():
        """1s-cadence tick — observes 4 mood-coherence signals + contributes to MCE."""
        from agents.hapax_daimonion.backends.mood_coherence_observation import (
            mood_coherence_observation,
        )

        coherence_bridge = LogosMoodCoherenceBridge()

        while True:
            try:
                if mce is not None:
                    mce.contribute(mood_coherence_observation(coherence_bridge))
            except Exception:
                _log.debug("MoodCoherenceEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    _sampler_task = asyncio.create_task(run_sampler())
    _trim_task = asyncio.create_task(_chronicle_trim_loop())
    _sde_task = asyncio.create_task(_system_degraded_tick_loop()) if sde is not None else None
    _oae_task = asyncio.create_task(_operator_activity_tick_loop()) if oae is not None else None
    _mae_task = asyncio.create_task(_mood_arousal_tick_loop()) if mae is not None else None
    _mve_task = asyncio.create_task(_mood_valence_tick_loop()) if mve is not None else None
    _mce_task = asyncio.create_task(_mood_coherence_tick_loop()) if mce is not None else None
    _witness_task = start_logos_witness_producer(app)

    yield

    _witness_task.cancel()
    _sampler_task.cancel()
    _trim_task.cancel()
    if _sde_task is not None:
        _sde_task.cancel()
    if _oae_task is not None:
        _oae_task.cancel()
    if _mae_task is not None:
        _mae_task.cancel()
    if _mve_task is not None:
        _mve_task.cancel()
    if _mce_task is not None:
        _mce_task.cancel()
    if engine is not None:
        await engine.stop()
    await agent_run_manager.shutdown()


app = FastAPI(
    title="logos-api",
    description="Logos dashboard API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",  # Tauri desktop app
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# OTel: extract incoming trace context + create server spans
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
except Exception:
    pass  # OTel instrumentation is optional

# Prometheus metrics: request count, latency histograms, error rates
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
except Exception:
    pass  # Prometheus is optional

from logos.api.routes.accommodations import router as accommodations_router
from logos.api.routes.agents import router as agents_router
from logos.api.routes.art_50_credentials import router as art_50_credentials_router
from logos.api.routes.awareness import router as awareness_router
from logos.api.routes.cbip import router as cbip_router
from logos.api.routes.chat import router as chat_router
from logos.api.routes.chronicle import router as chronicle_router
from logos.api.routes.consent import router as consent_router
from logos.api.routes.copilot import router as copilot_router
from logos.api.routes.data import router as data_router
from logos.api.routes.demos import router as demos_router
from logos.api.routes.dmn import router as dmn_router
from logos.api.routes.engine import router as engine_router
from logos.api.routes.events import router as events_router
from logos.api.routes.exploration import router as exploration_router
from logos.api.routes.flow import router as flow_router
from logos.api.routes.fortress import router as fortress_router
from logos.api.routes.governance import router as governance_router
from logos.api.routes.logos import router as logos_router
from logos.api.routes.mail_monitor import router as mail_monitor_router
from logos.api.routes.nudges import router as nudges_router
from logos.api.routes.orientation import router as orientation_router
from logos.api.routes.payment_rails import router as payment_rails_router
from logos.api.routes.payment_rails import stripe_webhook_router
from logos.api.routes.pi import router as pi_router
from logos.api.routes.predictions import router as predictions_router
from logos.api.routes.profile import router as profile_router
from logos.api.routes.query import router as query_router
from logos.api.routes.scout import router as scout_router
from logos.api.routes.sprint import router as sprint_router
from logos.api.routes.stimmung import router as stimmung_router
from logos.api.routes.stream import router as stream_router
from logos.api.routes.studio import router as studio_router
from logos.api.routes.studio_compositor import router as studio_compositor_router
from logos.api.routes.studio_effects import router as studio_effects_router
from logos.api.routes.vault import router as vault_router
from logos.api.routes.working_mode import router as working_mode_router
from logos.api.routes.x402 import router as x402_router

app.include_router(data_router)
app.include_router(nudges_router)
app.include_router(agents_router)
app.include_router(art_50_credentials_router)
app.include_router(chat_router)
app.include_router(profile_router)
app.include_router(accommodations_router)
app.include_router(copilot_router)
app.include_router(demos_router)
app.include_router(working_mode_router)
app.include_router(scout_router)
app.include_router(query_router)
app.include_router(engine_router)
app.include_router(consent_router)
app.include_router(governance_router)
app.include_router(studio_router)
app.include_router(studio_effects_router)
app.include_router(studio_compositor_router)
app.include_router(cbip_router)
app.include_router(logos_router)
app.include_router(mail_monitor_router)
app.include_router(flow_router)
app.include_router(fortress_router)
app.include_router(pi_router)
app.include_router(sprint_router)
app.include_router(stimmung_router)
app.include_router(stream_router)
app.include_router(dmn_router)
app.include_router(events_router)
app.include_router(exploration_router)
app.include_router(orientation_router)
app.include_router(awareness_router)
app.include_router(vault_router)
app.include_router(chronicle_router)
app.include_router(predictions_router)
app.include_router(x402_router)
app.include_router(payment_rails_router)
app.include_router(stripe_webhook_router)

# Mount HLS segment directory for live stream serving
# Override .ts MIME type: Starlette defaults to Qt Linguist (text/vnd.trolltech.linguist)
# but HLS transport stream segments need video/mp2t.
import mimetypes as _mimetypes

_mimetypes.add_type("video/mp2t", ".ts")

from pathlib import Path as _Path

_HLS_DIR = _Path.home() / ".cache" / "hapax-compositor" / "hls"
_HLS_DIR.mkdir(parents=True, exist_ok=True)
from starlette.staticfiles import StaticFiles as _StaticFiles

app.mount("/api/studio/hls", _StaticFiles(directory=_HLS_DIR), name="hls-stream")


@app.get("/")
async def root():
    return {
        "name": "logos-api",
        "version": "0.2.0",
        "docs": "/docs",
        "app": "/app/",
    }


from pathlib import Path

SPA_DIR = Path(__file__).parent / "static"
if SPA_DIR.is_dir():
    from starlette.responses import FileResponse
    from starlette.staticfiles import StaticFiles

    @app.get("/app/{path:path}")
    async def spa_catchall(path: str):
        index = SPA_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return {"error": "SPA not built"}

    app.mount("/static", StaticFiles(directory=SPA_DIR), name="spa")

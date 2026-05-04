"""IR presence perception backend — multi-Pi NoIR fusion.

FAST tier backend that reads Pi NoIR state files and contributes 14 signals.
Fuses reports from up to 3 Pis (desk, room, overhead) with role-based priority:
  - Person detection: any() across Pis
  - Gaze/posture/biometrics: prefer desk Pi (+0.1 confidence bonus), fall back by confidence
  - Hand activity: prefer overhead Pi, fall back to first available
  - Screen looking: gaze == "at-screen" AND screens detected in same report
  - Motion: max across all Pis
  - Brightness: average across all Pis
"""

from __future__ import annotations

import logging
import time
from collections import deque as _deque
from pathlib import Path

from agents.hapax_daimonion.ir_signals import IR_ROLES, read_all_ir_reports
from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior
from shared.control_signal import ControlSignal, publish_health

log = logging.getLogger(__name__)


def _compute_brightness_delta(history: _deque[float], current: float) -> float:
    """Compute brightness delta: current vs rolling 30-sample average."""
    if len(history) < 10:
        return 0.0
    avg = sum(history) / len(history)
    return current - avg


_SIGNALS: frozenset[str] = frozenset(
    {
        "ir_person_detected",
        "ir_person_count",
        "ir_motion_delta",
        "ir_gaze_zone",
        "ir_head_pose_yaw",
        "ir_posture",
        "ir_hand_activity",
        "ir_screen_looking",
        "ir_drowsiness_score",
        "ir_blink_rate",
        "ir_heart_rate_bpm",
        "ir_heart_rate_conf",
        "ir_brightness",
        "ir_brightness_delta",
        "ir_hand_zone",
        # Phase 4 of `ir-perception-replace-zones-with-vlm-classification`:
        # the rich-vocabulary hand-activity classifier output, threaded
        # through from the freshest Pi report. None when no Pi report
        # carries the field yet (older Pi-edge daemons) — consumers
        # fall back to the legacy zone/activity enums.
        "ir_hand_semantics",
    }
)

IR_STALE_S = 10.0  # Pi reports older than this are discarded (P3 staleness safety)

_DESK_CONFIDENCE_BONUS = 0.1

# #143 — cadence-aware staleness cutoffs.
# Each Pi reports its current cadence state; we accept reports up to
# ``_STALE_MULTIPLIER`` times the Pi's post interval before declaring stale.
# QUIESCENT Pis (10s interval) tolerate ~50s staleness; HOT Pis (500ms) tighten
# to the 3s floor.
_STALE_MULTIPLIER: float = 5.0
_MIN_STALE_S: float = 3.0
_MAX_STALE_S: float = 60.0


def _staleness_cutoff_for(cadence_interval_s: float | None) -> float:
    """Scale the staleness cutoff with the reported cadence interval.

    Used by ``IrPresenceBackend._read_with_cadence_staleness`` to interpret
    staleness relative to the Pi's actual post rate, not a fixed assumption.
    """
    if cadence_interval_s is None or cadence_interval_s <= 0:
        return IR_STALE_S
    cutoff = cadence_interval_s * _STALE_MULTIPLIER
    return max(_MIN_STALE_S, min(_MAX_STALE_S, cutoff))


def _ingest_camera_salience_reports(reports: dict[str, dict[str, object]]) -> int:
    """Push fresh IR reports into the camera salience broker singleton."""
    ingested = 0
    try:
        from shared.camera_salience_producer_adapters import ir_to_envelope
        from shared.camera_salience_singleton import broker as _camera_broker

        singleton = _camera_broker()
        for role, report in reports.items():
            envelope = ir_to_envelope(report, pi_name=role)
            if envelope is None:
                continue
            singleton.ingest(envelope)
            ingested += 1
    except Exception:
        log.debug("camera salience IR ingest failed", exc_info=True)
    return ingested


class IrPresenceBackend:
    """PerceptionBackend that fuses Pi NoIR state files into 14 signals."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self._state_dir = state_dir
        # Exploration tracking (spec §8, kappa=0.020, T_patience=180s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="ir_presence",
            edges=["person_detected", "motion_delta"],
            traces=["report_freshness", "person_count"],
            neighbors=["stimmung", "perception"],
            kappa=0.020,
            t_patience=180.0,
            sigma_explore=0.02,
        )
        self._brightness_history: _deque[float] = _deque(maxlen=30)
        self._b_brightness_delta: Behavior[float] = Behavior(0.0)
        self._prev_person: float = 0.0
        self._prev_motion: float = 0.0
        self._behaviors: dict[str, Behavior] = {
            "ir_person_detected": Behavior(False),
            "ir_person_count": Behavior(0),
            "ir_motion_delta": Behavior(0.0),
            "ir_gaze_zone": Behavior("unknown"),
            "ir_head_pose_yaw": Behavior(0.0),
            "ir_posture": Behavior("unknown"),
            "ir_hand_activity": Behavior("none"),
            "ir_screen_looking": Behavior(False),
            "ir_drowsiness_score": Behavior(0.0),
            "ir_blink_rate": Behavior(0.0),
            "ir_heart_rate_bpm": Behavior(0),
            "ir_heart_rate_conf": Behavior(0.0),
            "ir_brightness": Behavior(0.0),
            "ir_hand_zone": Behavior("none"),
            "ir_hand_semantics": Behavior(None),
        }

    @property
    def name(self) -> str:
        return "ir_presence"

    @property
    def provides(self) -> frozenset[str]:
        return _SIGNALS

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        return True

    def start(self) -> None:
        log.info("IR presence backend started (state_dir=%s)", self._state_dir)

    def stop(self) -> None:
        log.info("IR presence backend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        reports = self._read_with_cadence_staleness()
        _ingest_camera_salience_reports(reports)
        self._fuse(reports, now)
        for key, behavior in self._behaviors.items():
            behaviors[key] = behavior

        # Publish perceptual control signal: freshness = fraction of Pi roles reporting
        freshness = len(reports) / len(IR_ROLES) if IR_ROLES else 0.0
        signal = ControlSignal(component="ir_perception", reference=1.0, perception=freshness)
        publish_health(signal)

        # Track IR brightness rolling delta for body-heat proxy
        brightness = float(self._behaviors.get("ir_brightness", Behavior(0.0)).value or 0.0)
        self._brightness_history.append(brightness)
        delta = _compute_brightness_delta(self._brightness_history, brightness)
        self._b_brightness_delta.update(delta, now)
        behaviors["ir_brightness_delta"] = self._b_brightness_delta

        # Exploration signal: track habituation to IR signals
        _person_val = self._behaviors.get("ir_person_detected", Behavior(False)).value
        person = float(_person_val) if _person_val is not None else 0.0
        motion = float(self._behaviors.get("ir_motion_delta", Behavior(0.0)).value or 0.0)
        self._exploration.feed_habituation("person_detected", person, self._prev_person, 0.2)
        self._exploration.feed_habituation("motion_delta", motion, self._prev_motion, 0.1)
        self._exploration.feed_interest("report_freshness", freshness, 0.3)
        person_count = int(self._behaviors.get("ir_person_count", Behavior(0)).value)
        self._exploration.feed_interest("person_count", float(person_count), 0.5)
        self._exploration.feed_error(1.0 - freshness)
        self._exploration.compute_and_publish()
        self._prev_person = person
        self._prev_motion = motion

        # Control law: 0 Pis reporting → safe defaults
        _ir_error = len(reports) == 0
        self._cl_errors = getattr(self, "_cl_errors", 0)
        self._cl_ok = getattr(self, "_cl_ok", 0)
        self._cl_degraded = getattr(self, "_cl_degraded", False)
        if _ir_error:
            self._cl_errors += 1
            self._cl_ok = 0
        else:
            self._cl_errors = 0
            self._cl_ok += 1

        if self._cl_errors >= 3 and not self._cl_degraded:
            # Force safe defaults — already handled in _fuse when reports is empty,
            # but mark degraded to suppress downstream trust
            self._cl_degraded = True
            log.warning("Control law [ir_perception]: degrading — all signals to safe defaults")

        if self._cl_ok >= 5 and self._cl_degraded:
            self._cl_degraded = False
            log.info("Control law [ir_perception]: recovered")

    def _read_with_cadence_staleness(self) -> dict[str, dict[str, object]]:
        """Load Pi NoIR reports, scaling the staleness cutoff per Pi.

        #143 — fetch each report with a permissive ceiling, then re-filter per
        role using the cadence state declared inside the report. QUIESCENT Pis
        tolerate ~50s staleness; HOT Pis tighten to the 3s floor.
        """
        raw = read_all_ir_reports(state_dir=self._state_dir, max_age_seconds=_MAX_STALE_S)
        kept: dict[str, dict[str, object]] = {}
        for role, report in raw.items():
            cadence_interval = report.get("cadence_interval_s")
            cadence_interval_f: float | None
            try:
                cadence_interval_f = (
                    float(cadence_interval) if cadence_interval is not None else None
                )
            except (TypeError, ValueError):
                cadence_interval_f = None
            cutoff = _staleness_cutoff_for(cadence_interval_f)
            age = self._report_age(role)
            if age is None or age <= cutoff:
                kept[role] = report
            else:
                log.debug(
                    "IR %s STALE under cadence-aware cutoff (age=%.1fs > %.1fs, state=%s)",
                    role,
                    age,
                    cutoff,
                    report.get("cadence_state", "?"),
                )
        return kept

    def _report_age(self, role: str) -> float | None:
        """Best-effort age of a report based on state-file mtime."""
        from agents.hapax_daimonion.ir_signals import IR_STATE_DIR

        state_dir = self._state_dir or IR_STATE_DIR
        path = state_dir / f"{role}.json"
        try:
            return time.time() - path.stat().st_mtime
        except OSError:
            return None

    def _fuse(self, reports: dict[str, dict[str, object]], now: float) -> None:
        """Fuse all Pi reports into behavior values."""
        if not reports:
            # No IR data → neutral (None), not negative (False).  SCM control
            # law §2.1 Level 3: "set ALL IR signals to defaults."  Defaults must
            # be neutral so broken/stale IR doesn't drag Bayesian presence down.
            self._behaviors["ir_person_detected"].update(None, now)
            self._behaviors["ir_person_count"].update(0, now)
            self._behaviors["ir_motion_delta"].update(0.0, now)
            self._behaviors["ir_gaze_zone"].update("unknown", now)
            self._behaviors["ir_head_pose_yaw"].update(0.0, now)
            self._behaviors["ir_posture"].update("unknown", now)
            self._behaviors["ir_hand_activity"].update("none", now)
            self._behaviors["ir_hand_zone"].update("none", now)
            self._behaviors["ir_hand_semantics"].update(None, now)
            self._behaviors["ir_screen_looking"].update(False, now)
            self._behaviors["ir_drowsiness_score"].update(0.0, now)
            self._behaviors["ir_blink_rate"].update(0.0, now)
            self._behaviors["ir_heart_rate_bpm"].update(0, now)
            self._behaviors["ir_heart_rate_conf"].update(0.0, now)
            self._behaviors["ir_brightness"].update(0.0, now)
            return

        # --- Person detection: any() across Pis ---
        all_persons: list[dict[str, object]] = []
        for report in reports.values():
            all_persons.extend(report.get("persons", []))
        if all_persons:
            self._behaviors["ir_person_detected"].update(True, now)
        else:
            # No detections = neutral (None), not negative (False).  The YOLOv8n
            # model is trained on only 30 NIR frames and regularly misses the
            # operator.  Until retrained (IR remediation Batch 2), "no detection"
            # means "I don't know," not "nobody is there."
            self._behaviors["ir_person_detected"].update(None, now)
        self._behaviors["ir_person_count"].update(len(all_persons), now)

        # --- Motion: max across all Pis ---
        motion = max(
            (report.get("motion_delta", 0.0) for report in reports.values()),
            default=0.0,
        )
        self._behaviors["ir_motion_delta"].update(motion, now)

        # --- Brightness: average across all Pis ---
        brightness_vals = [report.get("ir_brightness", 0.0) for report in reports.values()]
        avg_brightness = sum(brightness_vals) / len(brightness_vals) if brightness_vals else 0.0
        self._behaviors["ir_brightness"].update(avg_brightness, now)

        # --- Best person for gaze/posture/biometrics (prefer desk +0.1 bonus) ---
        best_person, best_report = self._pick_best_person(reports)

        if best_person is not None:
            self._behaviors["ir_gaze_zone"].update(best_person.get("gaze_zone", "unknown"), now)
            self._behaviors["ir_head_pose_yaw"].update(
                float(best_person.get("head_pose_yaw", 0.0)), now
            )
            self._behaviors["ir_posture"].update(best_person.get("posture", "unknown"), now)
        else:
            self._behaviors["ir_gaze_zone"].update("unknown", now)
            self._behaviors["ir_head_pose_yaw"].update(0.0, now)
            self._behaviors["ir_posture"].update("unknown", now)

        # --- Screen looking: gaze == "at-screen" AND screens in same report ---
        screen_looking = False
        if best_person is not None and best_report is not None:
            gaze = best_person.get("gaze_zone", "")
            screens = best_report.get("screens", [])
            screen_looking = gaze == "at-screen" and len(screens) > 0
        self._behaviors["ir_screen_looking"].update(screen_looking, now)

        # --- Hand activity: prefer overhead, fall back to first available ---
        hand_activity = self._pick_hand_activity(reports)
        self._behaviors["ir_hand_activity"].update(hand_activity, now)
        hand_zone = self._pick_hand_zone(reports)
        self._behaviors["ir_hand_zone"].update(hand_zone, now)
        # Phase 4 of `ir-perception-replace-zones-with-vlm-classification`:
        # rich-vocabulary classifier output threaded through from the
        # freshest Pi report. None when no Pi yet carries the field.
        hand_semantics = self._pick_hand_semantics(reports)
        self._behaviors["ir_hand_semantics"].update(hand_semantics, now)

        # --- Biometrics from best person's report (desk preferred) ---
        bio = best_report.get("biometrics", {}) if best_report else {}
        self._behaviors["ir_heart_rate_bpm"].update(bio.get("heart_rate_bpm", 0), now)
        self._behaviors["ir_heart_rate_conf"].update(bio.get("heart_rate_confidence", 0.0), now)
        self._behaviors["ir_drowsiness_score"].update(bio.get("drowsiness_score", 0.0), now)
        self._behaviors["ir_blink_rate"].update(bio.get("blink_rate", 0.0), now)

    def _pick_best_person(
        self, reports: dict[str, dict[str, object]]
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        """Select the highest-confidence person across all Pis.

        Desk Pi gets a +0.1 confidence bonus. Returns (person_dict, report_dict).
        """
        best: dict[str, object] | None = None
        best_report: dict[str, object] | None = None
        best_conf = -1.0

        for role, report in reports.items():
            bonus = _DESK_CONFIDENCE_BONUS if role == "desk" else 0.0
            for person in report.get("persons", []):
                conf = float(person.get("confidence", 0.0)) + bonus
                if conf > best_conf:
                    best_conf = conf
                    best = person
                    best_report = report

        return best, best_report

    def _pick_hand_activity(self, reports: dict[str, dict[str, object]]) -> str:
        """Pick hand activity, preferring overhead Pi."""
        # Prefer overhead
        if "overhead" in reports:
            overhead = reports["overhead"]
            hands = list(overhead.get("hands", [])) if isinstance(overhead, dict) else []
            if hands and isinstance(hands[0], dict):
                return str(hands[0].get("activity", "none"))

        # Fall back to first available
        for report in reports.values():
            hands = list(report.get("hands", [])) if isinstance(report, dict) else []
            if hands and isinstance(hands[0], dict):
                return str(hands[0].get("activity", "none"))

        return "none"

    def _pick_hand_zone(self, reports: dict[str, dict[str, object]]) -> str:
        """Pick hand zone, preferring overhead Pi."""
        if "overhead" in reports:
            overhead = reports["overhead"]
            hands = list(overhead.get("hands", [])) if isinstance(overhead, dict) else []
            if hands and isinstance(hands[0], dict):
                return str(hands[0].get("zone", "none"))
        for report in reports.values():
            hands = list(report.get("hands", [])) if isinstance(report, dict) else []
            if hands and isinstance(hands[0], dict):
                return str(hands[0].get("zone", "none"))
        return "none"

    def _pick_hand_semantics(
        self, reports: dict[str, dict[str, object]]
    ) -> dict[str, object] | None:
        """Pick hand_semantics from the freshest Pi report (overhead first).

        Returns ``None`` when no Pi report carries the field — older
        Pi-edge daemons that haven't been redeployed with Phase 3 do
        not include ``hand_semantics`` in their JSON. Consumers fall
        back to the legacy zone/activity enums in that case.

        Selection mirrors :meth:`_pick_hand_zone` / :meth:`_pick_hand_activity`
        — overhead Pi has the canonical hand view; other Pis are a
        fallback only.
        """
        if "overhead" in reports:
            overhead = reports["overhead"]
            if isinstance(overhead, dict):
                semantics = overhead.get("hand_semantics")
                if isinstance(semantics, dict):
                    return semantics
        for report in reports.values():
            if isinstance(report, dict):
                semantics = report.get("hand_semantics")
                if isinstance(semantics, dict):
                    return semantics
        return None

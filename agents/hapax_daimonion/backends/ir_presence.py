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
from pathlib import Path

from agents.hapax_daimonion.ir_signals import IR_ROLES, read_all_ir_reports
from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior
from shared.control_signal import ControlSignal, publish_health

log = logging.getLogger(__name__)

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
        "ir_hand_zone",
    }
)

IR_STALE_S = 10.0  # Pi reports older than this are discarded (P3 staleness safety)

_DESK_CONFIDENCE_BONUS = 0.1


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
        reports = read_all_ir_reports(state_dir=self._state_dir, max_age_seconds=IR_STALE_S)
        self._fuse(reports, now)
        for key, behavior in self._behaviors.items():
            behaviors[key] = behavior

        # Publish perceptual control signal: freshness = fraction of Pi roles reporting
        freshness = len(reports) / len(IR_ROLES) if IR_ROLES else 0.0
        signal = ControlSignal(component="ir_perception", reference=1.0, perception=freshness)
        publish_health(signal)

        # Exploration signal: track habituation to IR signals
        person = float(self._behaviors.get("ir_person_detected", Behavior(False)).value)
        motion = float(self._behaviors.get("ir_motion_delta", Behavior(0.0)).value)
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

    def _fuse(self, reports: dict[str, dict[str, object]], now: float) -> None:
        """Fuse all Pi reports into behavior values."""
        if not reports:
            self._behaviors["ir_person_detected"].update(False, now)
            self._behaviors["ir_person_count"].update(0, now)
            self._behaviors["ir_motion_delta"].update(0.0, now)
            self._behaviors["ir_gaze_zone"].update("unknown", now)
            self._behaviors["ir_head_pose_yaw"].update(0.0, now)
            self._behaviors["ir_posture"].update("unknown", now)
            self._behaviors["ir_hand_activity"].update("none", now)
            self._behaviors["ir_hand_zone"].update("none", now)
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
        person_detected = len(all_persons) > 0
        self._behaviors["ir_person_detected"].update(person_detected, now)
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

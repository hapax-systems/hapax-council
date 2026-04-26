"""Task #136 — operator-tracking hero camera with creative shot bias.

``FollowModeController`` fuses IR fleet presence signals with the camera
classification metadata published by the compositor (task #135) to pick
a hero camera that follows the operator through the room. The scoring
function deliberately mixes:

* ``ambient_priority``        — the compositor's per-camera editorial weight
* operator-visible bonus      — when the camera declares ``operator_visible``
* ontology match bonus        — when the camera's subject_ontology aligns
                                with the inferred operator location
* repetition penalty          — the camera was already the hero in the last
                                30 s; prefer a cut to a different angle
* mode-activity bonus         — director activity "demonstrate" + operator
                                at desk → boost the overhead shot ("show the
                                work") so the bias is creative, not
                                mechanical

The output (``FollowModeRecommendation``) is published atomically to
``/dev/shm/hapax-compositor/follow-mode-recommendation.json``. The
hero-override consumer (``agents.studio_compositor.state``) falls back
to this file when no manual override is set, at which point a
``hapax_follow_mode_cuts_total{from_role,to_role}`` counter is bumped.

Feature flag: ``HAPAX_FOLLOW_MODE_ACTIVE`` gates the publisher (ON by
default per directive ``feedback_features_on_by_default`` 2026-04-25;
opt out with ``HAPAX_FOLLOW_MODE_ACTIVE=0``). The controller *always*
computes the recommendation so tests and observability work even when
the flag is off; it just marks ``active=False`` and the hero-override
consumer refuses to fall back to it. Manual hero-override always wins.

See docs/superpowers/plans/... task #136.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── paths ──────────────────────────────────────────────────────────────────

_CAMERA_CLASSIFICATIONS_PATH = Path("/dev/shm/hapax-compositor/camera-classifications.json")
_FOLLOW_MODE_RECOMMENDATION_PATH = Path("/dev/shm/hapax-compositor/follow-mode-recommendation.json")
_NARRATIVE_STATE_PATH = Path("/dev/shm/hapax-director/narrative-state.json")
_IR_STATE_DIR_DEFAULT = Path.home() / "hapax-state" / "pi-noir"

# ── scoring weights ────────────────────────────────────────────────────────

# Location-match bonus is strong (3.0) so it can pivot the hero from
# the brio-operator default even though brio has a higher
# ambient_priority. Repetition penalty is the same magnitude so a
# settled hero is edged out by an equally-scored alternative, which
# produces the cut-rotation behaviour the operator asked for.
_LOCATION_MATCH_BONUS = 3.0
_OPERATOR_VISIBLE_BONUS = 0.3
_REPETITION_PENALTY = 3.0
_DEMO_DESK_OVERHEAD_BONUS = 2.0

# Rolling history window in seconds. "Repetition" = camera was the hero
# within this many seconds.
_HISTORY_WINDOW_S = 30.0

# IR report freshness cutoff. Mirrors ir_presence backend's IR_STALE_S
# (10 s). Stale reports don't count as presence signal.
_IR_STALE_S = 10.0

# TTL the controller attaches to published recommendations so the
# hero-override consumer can age them out without a separate sweeper.
_RECOMMENDATION_TTL_S = 15.0

# Feature-flag env var. Off by default; operator flips to "1" to activate.
_FEATURE_FLAG_ENV = "HAPAX_FOLLOW_MODE_ACTIVE"


# Ontology hints per inferred operator location. Cameras whose
# ``subject_ontology`` intersects the hint set get the location-match
# bonus. These are intentionally broad (match more than one camera) so
# the controller has a pool of candidates to pick from per location;
# the tie-breaker is then ambient_priority + operator_visible.
_LOCATION_ONTOLOGY_HINTS: dict[str, frozenset[str]] = {
    "desk": frozenset({"hands", "mpc", "desk"}),
    "room": frozenset({"room"}),
    "overhead": frozenset({"hands", "mpc", "desk"}),
}


@dataclass(frozen=True, slots=True)
class CameraClassification:
    """Typed view of the dict published by the compositor."""

    role: str
    semantic_role: str
    subject_ontology: tuple[str, ...]
    angle: str
    operator_visible: bool
    ambient_priority: int


@dataclass(frozen=True, slots=True)
class FollowModeRecommendation:
    """What the controller recommends at this tick."""

    camera_role: str
    confidence: float
    reason: str
    ts: float
    active: bool
    operator_location: str | None = None
    activity: str | None = None


@dataclass(slots=True)
class _HistoryEntry:
    role: str
    ts: float


@dataclass(slots=True)
class FollowModeController:
    """Computes and (when active) publishes follow-mode recommendations.

    The controller is deliberately stateless across restarts: the 30 s
    history window lives in memory. At service restart the first cut
    pays no repetition penalty, which is correct behaviour — the
    operator can't tell that the compositor crashed and restarted, so
    picking the "obvious" camera is better than a random different one.
    """

    ir_state_dir: Path = field(default=_IR_STATE_DIR_DEFAULT)
    classifications_path: Path = field(default=_CAMERA_CLASSIFICATIONS_PATH)
    recommendation_path: Path = field(default=_FOLLOW_MODE_RECOMMENDATION_PATH)
    narrative_state_path: Path = field(default=_NARRATIVE_STATE_PATH)
    history: deque[_HistoryEntry] = field(default_factory=lambda: deque(maxlen=64))

    # ── location inference ────────────────────────────────────────────────

    def _infer_operator_location(self, now: float) -> tuple[str | None, float]:
        """Return ``(location, confidence)`` from the IR fleet.

        ``location`` is one of ``"desk"``, ``"room"``, ``"overhead"``, or
        ``None`` when no Pi reports presence. ``confidence`` is 0..1 and
        tracks how strong the signal is (fraction of Pis reporting + a
        modest motion kicker).
        """
        best_role: str | None = None
        best_score = 0.0
        fresh_count = 0
        for role in ("desk", "room", "overhead"):
            path = self.ir_state_dir / f"{role}.json"
            data = _read_ir_report(path, now)
            if data is None:
                continue
            fresh_count += 1
            persons = data.get("persons") or []
            motion = float(data.get("motion_delta") or 0.0)
            score = 0.0
            if isinstance(persons, list) and len(persons) > 0:
                score += 1.0 + 0.2 * len(persons)
            # Motion is a weaker hint but still useful when YOLO
            # misses the operator (common — model trained on 30 frames).
            score += min(motion, 0.5) * 0.5
            if score > best_score:
                best_score = score
                best_role = role
        if best_role is None:
            return None, 0.0
        # Confidence: 0.4 for at least one hit, ramp up with additional
        # Pis reporting, clamp at 1.0. The motion component bumps it.
        confidence = min(1.0, 0.4 + 0.2 * fresh_count + 0.1 * best_score)
        return best_role, confidence

    # ── activity inference ────────────────────────────────────────────────

    def _read_director_activity(self) -> str | None:
        """Return the director's current activity (e.g. 'demonstrate') or None."""
        try:
            raw = self.narrative_state_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        activity = payload.get("activity")
        return str(activity) if isinstance(activity, str) else None

    # ── classifications ───────────────────────────────────────────────────

    def _read_classifications(self) -> list[CameraClassification]:
        try:
            raw = self.classifications_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        cams: list[CameraClassification] = []
        for role, meta in payload.items():
            if not isinstance(meta, dict):
                continue
            cams.append(
                CameraClassification(
                    role=str(role),
                    semantic_role=str(meta.get("semantic_role") or "unspecified"),
                    subject_ontology=tuple(meta.get("subject_ontology") or []),
                    angle=str(meta.get("angle") or "unspecified"),
                    operator_visible=bool(meta.get("operator_visible")),
                    ambient_priority=int(meta.get("ambient_priority") or 5),
                )
            )
        return cams

    # ── scoring ────────────────────────────────────────────────────────────

    def _score_camera(
        self,
        cam: CameraClassification,
        operator_location: str | None,
        activity: str | None,
        now: float,
    ) -> tuple[float, list[str]]:
        """Return ``(score, reasons)``. Reasons are ordered contributions."""
        reasons: list[str] = []
        score = float(cam.ambient_priority)
        reasons.append(f"priority={cam.ambient_priority}")

        if cam.operator_visible:
            score += _OPERATOR_VISIBLE_BONUS
            reasons.append(f"operator_visible+{_OPERATOR_VISIBLE_BONUS}")

        if operator_location is not None:
            hints = _LOCATION_ONTOLOGY_HINTS.get(operator_location, frozenset())
            # Special-case c920-overhead for the "overhead" location:
            # its top-down angle is the only camera whose vantage is
            # literally "above the operator's head", and it's the
            # canonical ontology match even if its subject_ontology
            # doesn't contain the word "overhead".
            ontology_match = bool(set(cam.subject_ontology) & hints)
            role_match_overhead = operator_location == "overhead" and cam.role == "c920-overhead"
            role_match_room = operator_location == "room" and cam.role in {
                "c920-room",
                "brio-room",
            }
            if ontology_match or role_match_overhead or role_match_room:
                score += _LOCATION_MATCH_BONUS
                reasons.append(f"location={operator_location}+{_LOCATION_MATCH_BONUS}")

        # Mode-activity boost: demonstrate + operator at desk → show the
        # overhead ("show the work") angle even though brio-operator
        # would score higher by priority.
        if (
            activity == "demonstrate"
            and operator_location == "desk"
            and cam.role == "c920-overhead"
        ):
            score += _DEMO_DESK_OVERHEAD_BONUS
            reasons.append(f"demo_desk_overhead+{_DEMO_DESK_OVERHEAD_BONUS}")

        # Repetition penalty: was cam the hero within the window?
        if _was_recent_hero(self.history, cam.role, now, _HISTORY_WINDOW_S):
            score -= _REPETITION_PENALTY
            reasons.append(f"repetition-{_REPETITION_PENALTY}")

        return score, reasons

    # ── public API ─────────────────────────────────────────────────────────

    def compute(self, now: float | None = None) -> FollowModeRecommendation | None:
        """Compute the recommendation without publishing.

        Returns ``None`` when camera-classifications.json hasn't been
        published yet (controller has nothing to recommend).
        """
        ts = time.time() if now is None else now
        cams = self._read_classifications()
        if not cams:
            return None
        location, loc_confidence = self._infer_operator_location(ts)
        activity = self._read_director_activity()

        best: tuple[float, CameraClassification, list[str]] | None = None
        for cam in cams:
            score, reasons = self._score_camera(cam, location, activity, ts)
            if best is None or score > best[0]:
                best = (score, cam, reasons)
        if best is None:  # pragma: no cover — empty cams caught above
            return None
        score, cam, reasons = best

        # Confidence is the location-confidence modulated by the margin
        # between the winner and runner-up. When no location is
        # inferred we still have a recommendation (fallback to ambient
        # priorities) but confidence is low.
        runner_up = max(
            (self._score_camera(c, location, activity, ts)[0] for c in cams if c.role != cam.role),
            default=score,
        )
        margin = max(0.0, score - runner_up)
        base_confidence = loc_confidence if location is not None else 0.25
        confidence = min(1.0, base_confidence * (1.0 + 0.15 * margin))

        active = _feature_flag_active()
        reason_str = ", ".join(reasons) or "priority"
        return FollowModeRecommendation(
            camera_role=cam.role,
            confidence=round(confidence, 3),
            reason=reason_str,
            ts=ts,
            active=active,
            operator_location=location,
            activity=activity,
        )

    def tick(self, now: float | None = None) -> FollowModeRecommendation | None:
        """Compute a recommendation and, when active, publish it.

        The hero-override consumer only honours the recommendation when
        ``active=True``, so the flag-off path still computes + returns the
        payload (useful for operators wanting to dry-run the controller
        before flipping the flag) but leaves the file absent so
        hero-override behaviour is unchanged.
        """
        rec = self.compute(now=now)
        if rec is None:
            return None
        self._record_hero(rec.camera_role, rec.ts)
        if rec.active:
            _publish(self.recommendation_path, rec)
        else:
            # When inactive we still write the file so operators can
            # inspect what the controller *would* have recommended —
            # but the consumer checks active=False and refuses to fall
            # back. A disabled follow-mode should be observable, not
            # silent.
            _publish(self.recommendation_path, rec)
        return rec

    def _record_hero(self, role: str, ts: float) -> None:
        """Record ``role`` as the hero at ``ts`` and prune stale entries."""
        self.history.append(_HistoryEntry(role=role, ts=ts))
        cutoff = ts - _HISTORY_WINDOW_S
        while self.history and self.history[0].ts < cutoff:
            self.history.popleft()


# ── helpers ───────────────────────────────────────────────────────────────


def _feature_flag_active() -> bool:
    """ON by default per directive ``feedback_features_on_by_default``
    (2026-04-25). Opt out by setting ``HAPAX_FOLLOW_MODE_ACTIVE`` to
    ``0`` / ``false`` / ``off`` / ``no``.
    """
    raw = os.environ.get(_FEATURE_FLAG_ENV, "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _read_ir_report(path: Path, now: float) -> dict[str, Any] | None:
    """Read and freshness-gate a Pi NoIR state file."""
    try:
        age = now - path.stat().st_mtime
    except (FileNotFoundError, OSError):
        return None
    if age > _IR_STALE_S:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _was_recent_hero(history: deque[_HistoryEntry], role: str, now: float, window: float) -> bool:
    cutoff = now - window
    for entry in history:
        if entry.ts < cutoff:
            continue
        if entry.role == role:
            return True
    return False


def _publish(path: Path, rec: FollowModeRecommendation) -> None:
    """Atomic tmp+rename publish of the recommendation."""
    payload = {
        "camera_role": rec.camera_role,
        "confidence": rec.confidence,
        "reason": rec.reason,
        "ts": rec.ts,
        "active": rec.active,
        "operator_location": rec.operator_location,
        "activity": rec.activity,
        "ttl_s": _RECOMMENDATION_TTL_S,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.debug("follow-mode-recommendation publish failed", exc_info=True)


def read_follow_mode_recommendation(
    path: Path = _FOLLOW_MODE_RECOMMENDATION_PATH,
    now: float | None = None,
) -> FollowModeRecommendation | None:
    """Read and freshness-gate the published recommendation.

    Returns ``None`` when the file is absent, expired (``ts + ttl_s <
    now``), or ``active=False``. The hero-override consumer calls this
    to decide whether to fall back to follow-mode's suggestion.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    ts = float(payload.get("ts") or 0.0)
    ttl_s = float(payload.get("ttl_s") or _RECOMMENDATION_TTL_S)
    now_ts = time.time() if now is None else now
    if ts <= 0.0 or (now_ts - ts) > ttl_s:
        return None
    if not bool(payload.get("active")):
        return None
    camera_role = payload.get("camera_role")
    if not isinstance(camera_role, str) or not camera_role:
        return None
    return FollowModeRecommendation(
        camera_role=camera_role,
        confidence=float(payload.get("confidence") or 0.0),
        reason=str(payload.get("reason") or ""),
        ts=ts,
        active=True,
        operator_location=(
            str(payload["operator_location"])
            if isinstance(payload.get("operator_location"), str)
            else None
        ),
        activity=(str(payload["activity"]) if isinstance(payload.get("activity"), str) else None),
    )

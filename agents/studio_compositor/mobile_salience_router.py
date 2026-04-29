"""Mobile ward salience router for the portrait substream."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from agents.studio_compositor.mobile_layout import MobileLayout, load_mobile_layout

log = logging.getLogger(__name__)

RECENT_RECRUITMENT_PATH = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
NARRATIVE_STATE_PATH = Path("/dev/shm/hapax-director/narrative-state.json")
YOUTUBE_VIEWER_COUNT_PATH = Path("/dev/shm/hapax-compositor/youtube-viewer-count.txt")
MOBILE_SALIENCE_PATH = Path("/dev/shm/hapax-compositor/mobile-salience.json")
MAX_SOURCE_AGE_S = 30.0


class MobileSalienceRouter:
    """Select up to three mobile-visible wards from current salience signals."""

    _INTERVAL_S: float = 2.0

    def __init__(
        self,
        layout_path: Path | None = None,
        *,
        output_path: Path = MOBILE_SALIENCE_PATH,
        recruitment_path: Path = RECENT_RECRUITMENT_PATH,
        narrative_path: Path = NARRATIVE_STATE_PATH,
        viewer_count_path: Path = YOUTUBE_VIEWER_COUNT_PATH,
        now: Any = time.time,
    ) -> None:
        self.layout: MobileLayout = load_mobile_layout(layout_path)
        self.output_path = output_path
        self.recruitment_path = recruitment_path
        self.narrative_path = narrative_path
        self.viewer_count_path = viewer_count_path
        self._now = now
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mobile-salience")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("mobile salience tick failed")
            self._stop.wait(self._INTERVAL_S)

    def _tick(self) -> dict[str, Any]:
        """Compute and publish one salience snapshot."""

        recruitment = self._read_json_if_fresh(self.recruitment_path)
        narrative = self._read_json_if_fresh(self.narrative_path)
        viewer_count = self._read_viewer_count_if_fresh(self.viewer_count_path)

        scores = {
            ward: self._score_ward(ward, recruitment, narrative)
            for ward in self.layout.ward_candidates
        }
        selected = [
            ward
            for ward, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
            if score > 0.0
        ][: self.layout.ward_zone.max_wards]
        payload: dict[str, Any] = {
            "selected_wards": selected,
            "viewer_count": viewer_count,
            "scores": scores,
            "density_mode": "normal_density"
            if selected
            else self.layout.ward_zone.fallback_density,
            "claim_posture": self.layout.metadata_footer.claim_posture,
            "ts": self._now(),
        }
        self._write_json_atomic(self.output_path, payload)
        return payload

    def _score_ward(self, ward_name: str, recruitment: dict, narrative: dict) -> float:
        """Score a ward with the spec formula.

        Missing or stale inputs arrive here as empty dicts, so the score
        naturally falls to zero instead of holding stale control state.
        """

        recruitment_activity = _score_from_state(recruitment, ward_name)
        narrative_relevance = _score_from_state(narrative, ward_name)
        recency = _recency_from_state(recruitment, ward_name, self._now())
        return round(
            max(
                0.0,
                min(1.0, 0.6 * recruitment_activity + 0.3 * narrative_relevance + 0.1 * recency),
            ),
            6,
        )

    def _read_json_if_fresh(self, path: Path) -> dict:
        try:
            stat = path.stat()
        except OSError:
            return {}
        if self._now() - stat.st_mtime > MAX_SOURCE_AGE_S:
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.debug("mobile salience read failed for %s", path, exc_info=True)
            return {}
        return data if isinstance(data, dict) else {}

    def _read_viewer_count_if_fresh(self, path: Path) -> int:
        try:
            stat = path.stat()
        except OSError:
            return 0
        if self._now() - stat.st_mtime > MAX_SOURCE_AGE_S:
            return 0
        try:
            return max(0, int(path.read_text(encoding="utf-8").strip() or "0"))
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.rename(path)


def _score_from_state(state: dict, ward_name: str) -> float:
    for mapping_key in (
        "wards",
        "ward_scores",
        "mobile_relevance",
        "narrative_relevance",
        "relevance",
        "scores",
    ):
        mapping = state.get(mapping_key)
        if isinstance(mapping, dict):
            value = mapping.get(ward_name)
            if isinstance(value, dict):
                for key in ("score", "activity", "salience", "relevance", "value"):
                    if key in value:
                        return _coerce_unit(value.get(key))
            if value is not None:
                return _coerce_unit(value)

    for list_key in ("entries", "items", "candidates", "selected_wards"):
        entries = state.get(list_key)
        if not isinstance(entries, list):
            continue
        for idx, entry in enumerate(entries):
            if isinstance(entry, str) and entry == ward_name:
                return max(0.0, 1.0 - (idx * 0.15))
            if not isinstance(entry, dict):
                continue
            if _entry_name(entry) != ward_name:
                continue
            for key in ("score", "activity", "recruitment_activity", "salience", "relevance"):
                if key in entry:
                    return _coerce_unit(entry.get(key))
            return max(0.0, 1.0 - (idx * 0.15))

    value = state.get(ward_name)
    if value is not None:
        return _coerce_unit(value)
    return 0.0


def _recency_from_state(state: dict, ward_name: str, now: float) -> float:
    for mapping_key in ("last_seen", "last_seen_at", "ward_timestamps", "timestamps"):
        mapping = state.get(mapping_key)
        if isinstance(mapping, dict) and ward_name in mapping:
            return _timestamp_recency(mapping.get(ward_name), now)
    for list_key in ("entries", "items", "candidates"):
        entries = state.get(list_key)
        if not isinstance(entries, list):
            continue
        for idx, entry in enumerate(entries):
            if isinstance(entry, str) and entry == ward_name:
                return max(0.0, 1.0 - (idx * 0.15))
            if isinstance(entry, dict) and _entry_name(entry) == ward_name:
                for key in ("ts", "timestamp", "updated_at", "last_seen_at"):
                    if key in entry:
                        return _timestamp_recency(entry.get(key), now)
                return max(0.0, 1.0 - (idx * 0.15))
    return 0.0


def _timestamp_recency(value: Any, now: float) -> float:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return 0.0
    age = max(0.0, now - ts)
    if age > MAX_SOURCE_AGE_S:
        return 0.0
    return 1.0 - (age / MAX_SOURCE_AGE_S)


def _entry_name(entry: dict[str, Any]) -> str:
    for key in ("ward", "ward_name", "source", "source_id", "id", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _coerce_unit(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))

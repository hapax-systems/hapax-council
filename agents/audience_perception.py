"""agents/audience_perception.py — Audience state perception daemon.

Polls audience metrics and writes to /dev/shm/hapax-perception/audience.json.
Reads a manual override first, then the YouTube viewer-count producer's
SHM output, and enriches every sample with BKT concept-mastery pressure.
The viewer-count producer owns the direct YouTube Data API call; this
daemon turns that public metric into the planner/audience perception
shape consumed by the narrative density layer.

``avg_watch_time_s`` and ``subscriber_delta`` are UNSENSED stubs on the live
(``youtube_api``) and ``fallback`` paths — the YouTube viewer-count producer
exposes only the concurrent viewer count, not retention or subscriber deltas.
Per invariant I2 the open value-leg is DECLARED (each emitted state names the
stub fields in ``unsensed_fields``), not silently presented as measured. The
``override`` path declares only the fields the operator did not supply.

Zero external dependencies — stdlib only.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

OUTPUT_DIR = Path("/dev/shm/hapax-perception")
OUTPUT_FILE = OUTPUT_DIR / "audience.json"
OVERRIDE_FILE = OUTPUT_DIR / "audience-override.json"
VIEWER_COUNT_FILE = Path("/dev/shm/hapax-compositor/youtube-viewer-count.txt")
CHAT_RECENT_FILE = Path("/dev/shm/hapax-chat/recent.jsonl")

POLL_INTERVAL_S = 2.0

#: ψ-value fields the audience producer cannot yet sense — the YouTube viewer-count
#: producer exposes only the concurrent viewer count. Named in each emitted state's
#: ``unsensed_fields`` so a consumer/auditor never reads them as real measurements
#: (invariant I2: the open value-leg is declared, not silently closed).
_UNSENSED_PSI_FIELDS: tuple[str, ...] = ("avg_watch_time_s", "subscriber_delta")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _read_viewer_count(path: Path | None = None) -> int | None:
    path = path or VIEWER_COUNT_FILE
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    try:
        return max(0, int(text))
    except ValueError:
        log.warning("invalid viewer-count payload at %s: %r", path, text)
        return None


def _read_chat_rate_per_min(path: Path | None = None, *, now: float | None = None) -> float:
    """Estimate recent chat rate from the chat reader ring buffer."""
    path = path or CHAT_RECENT_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return 0.0
    if not lines:
        return 0.0
    current = now if now is not None else time.time()
    recent = 0
    for line in lines[-200:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = item.get("timestamp", item.get("ts", item.get("received_at")))
        try:
            stamp = float(ts)
        except (TypeError, ValueError):
            continue
        if current - stamp <= 60.0:
            recent += 1
    return float(recent)


def _concept_mastery_payload() -> dict[str, Any]:
    try:
        from shared.concept_mastery import ConceptMastery, compute_zpd_affordance_pressure

        pressure = compute_zpd_affordance_pressure()
        mastery = ConceptMastery.read_shm()
        all_mastery = mastery.all_mastery() if mastery is not None else {}
        return {
            "tracked_count": len(all_mastery),
            "zpd_concepts": pressure.get("zpd_concepts", []),
            "unknown_concepts": pressure.get("unknown_concepts", []),
            "zpd_pressure": float(pressure.get("zpd_pressure") or 0.0),
            "unknown_pressure": float(pressure.get("unknown_pressure") or 0.0),
        }
    except Exception:
        log.debug("concept mastery enrichment failed", exc_info=True)
        return {
            "tracked_count": 0,
            "zpd_concepts": [],
            "unknown_concepts": [],
            "zpd_pressure": 0.0,
            "unknown_pressure": 0.0,
        }


def _enrich_with_concept_mastery(state: dict[str, Any]) -> dict[str, Any]:
    mastery = _concept_mastery_payload()
    state["concept_mastery"] = mastery
    state["zpd_pressure"] = mastery["zpd_pressure"]
    state["unknown_pressure"] = mastery["unknown_pressure"]
    return state


def _poll_youtube_api() -> dict[str, Any] | None:
    """Read live audience metrics derived from the YouTube API producer.

    Returns None until the viewer-count producer has published a sample.
    ``scripts/hapax-youtube-viewer-count-producer`` owns the direct
    ``videos.list`` call and writes the concurrent viewer count to SHM.
    """
    viewer_count = _read_viewer_count()
    if viewer_count is None:
        return None
    return {
        "viewer_count": viewer_count,
        "chat_rate_per_min": _read_chat_rate_per_min(),
        # avg_watch_time_s / subscriber_delta are UNSENSED stubs (declared in
        # unsensed_fields) — the viewer-count producer exposes neither retention
        # nor subscriber deltas. Kept as numeric 0 so the density consumer
        # (information_density_daemon._extract_float) does not break.
        "avg_watch_time_s": 0.0,
        "subscriber_delta": 0,
        "unsensed_fields": list(_UNSENSED_PSI_FIELDS),
    }


def _poll_audience() -> dict[str, Any]:
    """Read audience state from override file, YouTube API, or fall back to zeros."""
    # Manual override path — operator can drop a file to simulate audience
    override = _read_json(OVERRIDE_FILE)
    if override is not None:
        return _enrich_with_concept_mastery(
            {
                "viewer_count": override.get("viewer_count", 0),
                "chat_rate_per_min": override.get("chat_rate_per_min", 0.0),
                "avg_watch_time_s": override.get("avg_watch_time_s", 0.0),
                "subscriber_delta": override.get("subscriber_delta", 0),
                # Only the ψ-value fields the operator did NOT supply are unsensed;
                # a field present in the override is a real (operator-sensed) value.
                "unsensed_fields": [f for f in _UNSENSED_PSI_FIELDS if f not in override],
                "source": "override",
            }
        )

    # YouTube API path — via the dedicated producer's SHM output.
    yt = _poll_youtube_api()
    if yt is not None:
        yt["source"] = "youtube_api"
        return _enrich_with_concept_mastery(yt)

    # Fallback — no audience data available
    return _enrich_with_concept_mastery(
        {
            "viewer_count": 0,
            "chat_rate_per_min": 0.0,
            "avg_watch_time_s": 0.0,
            "subscriber_delta": 0,
            "unsensed_fields": list(_UNSENSED_PSI_FIELDS),
            "source": "fallback",
        }
    )


def _write_state(state: dict[str, Any]) -> None:
    """Write audience state to SHM."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(UTC).isoformat()
    tmp = OUTPUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(OUTPUT_FILE)


def run() -> None:
    """Main daemon loop — poll and write every POLL_INTERVAL_S."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log.info("audience_perception daemon starting (poll=%ss)", POLL_INTERVAL_S)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            state = _poll_audience()
            _write_state(state)
        except Exception:
            log.exception("audience poll tick failed")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    run()

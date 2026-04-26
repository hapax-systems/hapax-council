"""Studio source — wires L-12 scene state into awareness state.

Reads a scene-state flag file at ``~/.cache/hapax/l12-scene`` (path
overridable for tests) and returns a :class:`StudioBlock` for the
awareness aggregator to embed in the top-level :class:`AwarenessState`.

Per cc-task ``monitor-aggregate-awareness-signal``: the L-12 mixer's
scene state is operator-set via hardware (manual-recall on the
LiveTrak surface). There is no native auto-detect path. The flag file
is updated by the scene-recall helper script when the operator
switches scenes (council-side; eventually wireable to a hardware
detect path via PipeWire stream-state once Scene 8's AUX-C output
appears as an active node).

The source is intentionally lenient: missing flag file → block
defaults (``monitor_aux_c_active=False``). No exception escapes; a
broken flag file is treated as "scene unknown, assume non-monitor".
The block stays ``public=False`` per the spec — studio mixer state
stays off omg.lol fanout by default.
"""

from __future__ import annotations

import logging
from pathlib import Path

from prometheus_client import Counter

from agents.operator_awareness.state import StudioBlock

log = logging.getLogger(__name__)

DEFAULT_SCENE_FLAG_PATH = Path.home() / ".cache" / "hapax" / "l12-scene"
"""Operator-or-script-set scene state. Body is the active scene number
(``"1"``, ``"8"``, etc.); ``"8"`` means MONITOR-WORK is active and
``monitor_aux_c_active`` flips ``True``."""

# Scene 8 is the MONITOR-WORK scene per docs/audio/l12-scenes.md §8.
_MONITOR_WORK_SCENE_ID = "8"

studio_source_failures_total = Counter(
    "hapax_awareness_studio_source_failures_total",
    "Awareness aggregator studio-source failures (graceful degradation events).",
)


def _read_active_scene(scene_flag_path: Path) -> str | None:
    """Return the active scene id, or None on missing/unreadable file."""
    try:
        if not scene_flag_path.is_file():
            return None
        return scene_flag_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        log.debug("studio source: scene flag read failed: %s", exc)
        studio_source_failures_total.inc()
        return None


def collect_studio_block(
    scene_flag_path: Path = DEFAULT_SCENE_FLAG_PATH,
    *,
    public: bool = False,
) -> StudioBlock:
    """Compose a :class:`StudioBlock` for the awareness aggregator tick.

    ``public=False`` by default per the spec — studio mixer state is
    operator-private. Caller (the aggregator) decides when to flip;
    the source never overrides.
    """
    active_scene = _read_active_scene(scene_flag_path)
    monitor_active = active_scene == _MONITOR_WORK_SCENE_ID
    return StudioBlock(
        public=public,
        monitor_aux_c_active=monitor_active,
    )

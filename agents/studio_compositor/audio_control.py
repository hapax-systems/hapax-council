"""PipeWire per-stream volume control for YouTube audio slots.

Wraps wpctl for idempotent volume management. No toggle semantics —
set_volume(slot, 0.0) is always mute, set_volume(slot, 1.0) is always full.
Node IDs are discovered from pw-dump and cached, with automatic invalidation
on wpctl failure (handles ffmpeg restarts that change node IDs).
"""

from __future__ import annotations

import json
import logging
import subprocess

log = logging.getLogger(__name__)


class SlotAudioControl:
    """Per-slot YouTube audio volume control via PipeWire."""

    def __init__(self, slot_count: int = 3) -> None:
        self._slot_count = slot_count
        self._node_cache: dict[str, int] = {}  # stream_name -> node_id

    def _refresh_cache(self) -> None:
        """Parse pw-dump to discover youtube-audio node IDs."""
        self._node_cache.clear()
        try:
            result = subprocess.run(
                ["pw-dump"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            nodes = json.loads(result.stdout)
            for node in nodes:
                if node.get("type") != "PipeWire:Interface:Node":
                    continue
                props = node.get("info", {}).get("props", {})
                media_name = props.get("media.name", "")
                if media_name.startswith("youtube-audio-"):
                    self._node_cache[media_name] = node["id"]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
            log.warning("pw-dump failed: %s", exc)

    def discover_node(self, stream_name: str) -> int | None:
        """Find PipeWire node ID for a named stream.

        Returns cached result if available, otherwise runs pw-dump.
        """
        if stream_name in self._node_cache:
            return self._node_cache[stream_name]
        if not self._node_cache:
            self._refresh_cache()
        return self._node_cache.get(stream_name)

    def set_volume(self, slot_id: int, level: float) -> None:
        """Set volume for youtube-audio-{slot_id}. Idempotent.

        Args:
            slot_id: 0, 1, or 2
            level: 0.0 = silent, 1.0 = full volume
        """
        stream_name = f"youtube-audio-{slot_id}"
        node_id = self.discover_node(stream_name)
        if node_id is None:
            log.debug("No PipeWire node for %s", stream_name)
            return

        try:
            result = subprocess.run(
                ["wpctl", "set-volume", str(node_id), str(level)],
                timeout=2,
                capture_output=True,
            )
            if result.returncode != 0:
                # Node ID stale (ffmpeg restarted) — invalidate and retry once
                log.debug("wpctl failed for node %d, re-discovering", node_id)
                self._node_cache.clear()
                self._refresh_cache()
                node_id = self._node_cache.get(stream_name)
                if node_id is not None:
                    subprocess.run(
                        ["wpctl", "set-volume", str(node_id), str(level)],
                        timeout=2,
                        capture_output=True,
                    )
        except subprocess.TimeoutExpired:
            log.warning("wpctl timed out for %s", stream_name)

    def mute_all_except(self, active_slot: int) -> None:
        """Set active slot to 1.0, all others to 0.0."""
        for slot_id in range(self._slot_count):
            self.set_volume(slot_id, 1.0 if slot_id == active_slot else 0.0)

    def mute_all(self) -> None:
        """Mute all YouTube audio streams."""
        for slot_id in range(self._slot_count):
            self.set_volume(slot_id, 0.0)

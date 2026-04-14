"""PipeWire per-stream volume control for YouTube audio slots.

Wraps wpctl for idempotent volume management. No toggle semantics —
set_volume(slot, 0.0) is always mute, set_volume(slot, 1.0) is always full.
Node IDs are discovered from pw-dump and cached, with automatic invalidation
on wpctl failure (handles ffmpeg restarts that change node IDs).

Livestream-performance-map Sprint 4 F1+F2 / W3.1 + W3.2: the original
``mute_all`` / ``mute_all_except`` API is a binary cliff — instant 0 dB
to mute, instant restore on completion. That sounds like silence-then-
voice-then-silence punching through the music, exactly what the
operator does NOT want from a ducking system. The added ``duck()`` /
``restore()`` API provides smooth attack/release envelopes while
preserving the slot-rotation semantics of the binary methods.

Beta's Sprint 4 F1 recommended a PipeWire LSP sidechain compressor
(Option A) for sample-accurate ducking. That requires a 4-channel
filter-chain sink with explicit voice-bus loopback wiring and is a
larger architectural change. ``duck()`` / ``restore()`` is Option B
— Python wpctl envelopes — which is ~50 lines and ships tonight,
yielding ~30 ms attack / 350 ms release at the cost of slightly
chunkier ramps (8 steps per envelope, not sample-accurate).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time

from . import metrics

log = logging.getLogger(__name__)


# W3.1 default envelope shape — beta's Sprint 4 H3 recommendation.
# Tunable via the ``duck()`` / ``restore()`` keyword args.
_DEFAULT_DUCK_ATTENUATION = 0.4  # ~ -8 dB, beta's H3 starting point
_DEFAULT_ATTACK_MS = 30.0
_DEFAULT_RELEASE_MS = 350.0
# 8 steps per envelope — small enough that ``wpctl set-volume`` IPC at
# ~10 ms per call doesn't saturate the wire (8 calls × 3 slots = 24
# subprocess calls per envelope, ~240 ms of wpctl wall time during the
# ramp, then idle).
_RAMP_STEPS = 8


class SlotAudioControl:
    """Per-slot YouTube audio volume control via PipeWire."""

    def __init__(self, slot_count: int = 3) -> None:
        self._slot_count = slot_count
        self._node_cache: dict[str, int] = {}  # stream_name -> node_id
        # W3.1: per-slot last-set volume cache. Updated on every
        # ``set_volume`` call so ``duck()`` can snapshot the current state
        # without an extra ``wpctl get-volume`` round-trip per slot.
        # Defaults to 1.0 — slots are presumed full unless explicitly set.
        self._volume_cache: dict[int, float] = {i: 1.0 for i in range(slot_count)}
        # W3.1: ramp thread state. The lock guards _ramp_state +
        # _pre_duck_volumes + _ramp_thread + _cancel_event so duck()
        # and restore() can safely cancel-and-replace each other.
        self._ramp_lock = threading.Lock()
        self._ramp_state: str = "idle"  # "idle" | "ducking" | "ducked" | "restoring"
        self._pre_duck_volumes: dict[int, float] = {}
        self._ramp_thread: threading.Thread | None = None
        self._cancel_event: threading.Event = threading.Event()

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
        # W3.1: mirror the level into the cache regardless of wpctl
        # outcome. The cache is best-effort — a wpctl failure leaves
        # the cache slightly desynced but ``duck()`` / ``restore()``
        # still produce a sensible envelope (and a follow-up
        # ``set_volume`` corrects any drift on the next call).
        if 0 <= slot_id < self._slot_count:
            self._volume_cache[slot_id] = level

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

    # ── W3.1 envelope ducking ─────────────────────────────────────

    def duck(
        self,
        *,
        attenuation: float = _DEFAULT_DUCK_ATTENUATION,
        attack_ms: float = _DEFAULT_ATTACK_MS,
    ) -> None:
        """Smoothly attenuate all slots by ``attenuation`` over ``attack_ms``.

        Idempotent: calling ``duck()`` while already ducked is a no-op.
        Cancels any in-flight ``restore()`` and ducks from the current
        position. Spawns a daemon thread for the ramp; returns
        immediately so the caller (TTS playback) can proceed without
        blocking on the envelope.

        The pre-duck volumes are snapshotted from the cache and
        restored by ``restore()`` so the duck is non-destructive.
        """
        with self._ramp_lock:
            # Idempotency: already at the ducked state with no in-flight ramp
            if self._ramp_state == "ducked":
                return
            # Capture pre-duck state ONLY on the first duck (so a duck()
            # mid-restore doesn't clobber the original snapshot)
            if not self._pre_duck_volumes:
                self._pre_duck_volumes = dict(self._volume_cache)
            # Cancel any in-flight ramp
            self._cancel_event.set()

        if self._ramp_thread and self._ramp_thread.is_alive():
            self._ramp_thread.join(timeout=0.1)

        with self._ramp_lock:
            self._cancel_event = threading.Event()
            self._ramp_state = "ducking"
            cancel = self._cancel_event
            start_volumes = dict(self._volume_cache)
            target_volumes = {
                slot: max(0.0, vol * attenuation) for slot, vol in self._pre_duck_volumes.items()
            }
            duration_s = max(0.001, attack_ms / 1000.0)
        # W3.3: any non-idle envelope state is "music_ducked" for
        # observability purposes. The gauge stays high through the
        # attack ramp + sustain + release ramp, then drops on idle.
        metrics.set_music_ducked(True)

        self._ramp_thread = threading.Thread(
            target=self._run_ramp,
            args=(start_volumes, target_volumes, duration_s, cancel, "ducked"),
            daemon=True,
            name="duck-attack",
        )
        self._ramp_thread.start()

    def restore(self, *, release_ms: float = _DEFAULT_RELEASE_MS) -> None:
        """Smoothly restore all slots to their pre-duck volumes over ``release_ms``.

        Idempotent: calling ``restore()`` when not ducked is a no-op.
        Cancels any in-flight ``duck()`` and restores from the current
        position. Spawns a daemon thread for the ramp.

        After the ramp completes, ``_pre_duck_volumes`` is cleared so
        the next ``duck()`` snapshots fresh state. If the operator
        adjusted volumes between duck and restore via direct
        ``set_volume`` calls, the restore still goes back to the
        original pre-duck state — slot-rotation is a separate concern
        from envelope ducking.
        """
        with self._ramp_lock:
            if self._ramp_state == "idle":
                return
            if not self._pre_duck_volumes:
                # Defensive: nothing to restore to. Just snap idle.
                self._ramp_state = "idle"
                metrics.set_music_ducked(False)
                return
            self._cancel_event.set()

        if self._ramp_thread and self._ramp_thread.is_alive():
            self._ramp_thread.join(timeout=0.1)

        with self._ramp_lock:
            self._cancel_event = threading.Event()
            self._ramp_state = "restoring"
            cancel = self._cancel_event
            start_volumes = dict(self._volume_cache)
            target_volumes = dict(self._pre_duck_volumes)
            duration_s = max(0.001, release_ms / 1000.0)

        self._ramp_thread = threading.Thread(
            target=self._run_ramp,
            args=(start_volumes, target_volumes, duration_s, cancel, "idle"),
            daemon=True,
            name="duck-release",
        )
        self._ramp_thread.start()

    def _run_ramp(
        self,
        start_volumes: dict[int, float],
        target_volumes: dict[int, float],
        duration_s: float,
        cancel: threading.Event,
        terminal_state: str,
    ) -> None:
        """Linearly interpolate slot volumes from start → target.

        Runs ``_RAMP_STEPS`` evenly-spaced ``set_volume`` ticks.
        Aborts mid-ramp if ``cancel`` is set. On clean completion,
        sets the ramp state to ``terminal_state`` and (if terminal is
        ``idle``) clears ``_pre_duck_volumes``.
        """
        step_dt = duration_s / _RAMP_STEPS
        for step in range(1, _RAMP_STEPS + 1):
            if cancel.is_set():
                return
            progress = step / _RAMP_STEPS
            for slot in range(self._slot_count):
                start = start_volumes.get(slot, 1.0)
                end = target_volumes.get(slot, 1.0)
                volume = start + (end - start) * progress
                self.set_volume(slot, volume)
            if step < _RAMP_STEPS and not cancel.is_set():
                time.sleep(step_dt)

        with self._ramp_lock:
            # Only commit the terminal state if no one cancelled us
            # mid-finish. Otherwise let the new ramp own the state.
            if not cancel.is_set():
                self._ramp_state = terminal_state
                if terminal_state == "idle":
                    self._pre_duck_volumes = {}
                    metrics.set_music_ducked(False)

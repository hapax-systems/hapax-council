"""Couple audio policy to the operator's working mode.

Closes audit finding **E#7** — the 3-mode system (`research`/`rnd`/
`fortress`) was decoupled from the audio routing / loudness gates.
This module is the single seam where mode-specific audio invariants
land:

- **fortress** (livestream live): tighten broadcast invariants (true
  peak ceiling drops 0.5 dBTP below nominal), freeze the routing yaml,
  forbid default-sink switches, refuse cross-routes from
  `role.assistant` into the broadcast bus, kill OBS publish on any
  blocking reason.
- **research** (experiment-safe): relax non-essential checks (e.g.
  LUFS egress measurement is not performed when no broadcast intent
  is active) and widen the conf hot-swap window.
- **rnd** (default): permissive — empty constraints dict.

Consumers
---------

- ``shared.broadcast_audio_health.resolve_broadcast_audio_health``
  reads the constraint dict at compose-time so the
  ``audio-safe-for-broadcast.json`` envelope reflects the live mode.
- ``agents.audio_ducker`` consults the dict before applying any
  ``role.assistant → broadcast`` cross-route gain.
- ``agents.audio_router`` (and ``shared.audio_route_switcher``) gate
  ``pactl set-default-sink`` on
  ``current_audio_constraints().get("default_sink_change_allowed", True)``.

The mode file is at ``~/.cache/hapax/working-mode``; consumers that
need to react within one tick of a flip use
``working_mode_changed_since(...)``  with the mtime they last saw.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from shared.working_mode import WORKING_MODE_FILE, WorkingMode, get_working_mode


def fortress_audio_constraints() -> dict[str, object]:
    """Tighter audio invariants when livestream is live.

    The values here are the single source of truth for fortress-mode
    audio gating. Consumers must call ``current_audio_constraints()``
    rather than hard-coding behavior.
    """
    return {
        # True-peak ceiling drops below the nominal -1.0 dBTP YouTube
        # ceiling so we keep headroom on the limiter even when the
        # platform tightens its enforcement.
        "broadcast_true_peak_dbtp": -1.5,
        # No default-sink swaps while the stream is live — a single
        # `pactl set-default-sink` can break the OBS broadcast feed.
        "default_sink_change_allowed": False,
        # Routing yaml is the contract; freeze it during fortress so
        # nothing rewrites broadcast eligibility under us.
        "audio_routing_policy_yaml_frozen": True,
        # Explicit no-cross: `role.assistant` (TTS / agent voice) must
        # not be sidechain-ducked INTO the broadcast bus during
        # fortress; that path is reserved for live-program content.
        "duck_role_assistant_into_broadcast": False,
        # Kill switch: any blocking reason on the audio-safe envelope
        # triggers an OBS publish kill so we cannot accidentally air
        # an unsafe state.
        "obs_publish_kill_on_any_blocking_reason": True,
    }


def research_audio_constraints() -> dict[str, object]:
    """Relax non-essential checks when no broadcast intent is active.

    Research mode is for offline experimentation; the LUFS egress
    measurement is the slowest single check in the audio-safe
    envelope (5 s integration window) and offers no signal when no
    one is publishing.
    """
    return {
        "lufs_egress_check_skipped": True,
        # PipeWire conf hot-swap window: research can wait longer for
        # a graph to converge before tripping the staleness gate.
        "conf_hot_swap_window_seconds": 60,
    }


def rnd_audio_constraints() -> dict[str, object]:
    """Permissive default — no extra gates."""
    return {}


_MODE_TO_CONSTRAINTS: Final[dict[WorkingMode, object]] = {
    WorkingMode.FORTRESS: fortress_audio_constraints,
    WorkingMode.RESEARCH: research_audio_constraints,
    WorkingMode.RND: rnd_audio_constraints,
}


def current_audio_constraints() -> dict[str, object]:
    """Return the constraint dict for the live working mode.

    Defaults to the empty (RND) dict on any read error so a missing
    mode file never accidentally tightens broadcast invariants.
    """
    mode = get_working_mode()
    builder = _MODE_TO_CONSTRAINTS.get(mode, rnd_audio_constraints)
    return builder()  # type: ignore[operator]


def working_mode_mtime(path: Path | None = None) -> float | None:
    """Return the mtime of the working-mode file, or ``None`` if missing.

    Used by consumers to detect mode flips between ticks.
    """
    target = path or WORKING_MODE_FILE
    try:
        return target.stat().st_mtime
    except OSError:
        return None


def working_mode_changed_since(
    last_mtime: float | None,
    *,
    path: Path | None = None,
) -> tuple[bool, float | None]:
    """Return ``(changed, current_mtime)`` so callers can store-and-check.

    Pattern::

        last = None
        while running:
            changed, last = working_mode_changed_since(last)
            if changed:
                refresh_constraints()

    A first-time call (``last_mtime is None``) returns ``True`` so
    consumers always pick up the initial constraints.
    """
    current = working_mode_mtime(path)
    if last_mtime is None:
        return True, current
    if current is None:
        # File disappeared — treat as a change so the consumer falls
        # back to the (RND) default explicitly.
        return True, None
    return current != last_mtime, current


__all__ = [
    "current_audio_constraints",
    "fortress_audio_constraints",
    "research_audio_constraints",
    "rnd_audio_constraints",
    "working_mode_changed_since",
    "working_mode_mtime",
]

"""IngestMode — toggle between GStreamer compose mode and wgpu compose mode.

Phase 5b4 of the compositor unification epic. Lands the **capability**
that lets the operator switch between the two compositor topologies:

- **COMPOSE** (default): the existing GStreamer pipeline composes
  cameras, overlays, fx, and outputs to v4l2sink. The wgpu side
  runs the visual surface (Hapax Reverie) independently.
- **INGEST_ONLY**: the GStreamer pipeline ingests cameras only —
  v4l2src + decode + tee — and writes camera frames to shared memory
  for the wgpu side to sample. The wgpu compositor produces the
  final composited frame for both v4l2sink output AND the winit
  window via Phase 5b3's :class:`OutputRouter`.

This module ships only the **mode flag and helper**. It does NOT
modify ``pipeline.py`` to honor the flag — that's the final
operator-supervised flip step. After this PR, the operator can
toggle the flag and the next compositor restart will pick it up
(once pipeline.py is wired in a follow-up one-liner). Default is
COMPOSE so the live system sees no change.

Storage:
    ``~/.cache/hapax/compositor-mode`` — single-line text file.
    Missing file or unrecognized contents → COMPOSE.

See: docs/superpowers/specs/2026-04-12-phase-5b-unification-epic.md
"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path

log = logging.getLogger(__name__)

MODE_FILE: Path = Path.home() / ".cache" / "hapax" / "compositor-mode"


class IngestMode(StrEnum):
    """Compositor topology selector."""

    COMPOSE = "compose"
    """GStreamer composes cameras + overlays + fx (current default).

    The Hapax Reverie wgpu surface runs as an independent visual
    surface daemon and writes to /dev/shm/hapax-imagination/frame.jpg.
    The two pipelines are unrelated apart from sharing camera devices.
    """

    INGEST_ONLY = "ingest_only"
    """GStreamer ingests cameras only; wgpu composes everything.

    Phase 5b4: GStreamer's job collapses to v4l2src + decode + a
    shared-memory writer per camera. The wgpu compositor reads the
    cameras as Sources, runs the full Phase 5a/5b1 multi-target
    render plan, and produces the final composited frames. The
    Phase 5b3 OutputRouter wires render targets to v4l2sink (for
    /dev/video42) and the winit window.
    """


def current_mode() -> IngestMode:
    """Return the operator's currently selected compositor mode.

    Reads ``~/.cache/hapax/compositor-mode``. Falls back to
    :attr:`IngestMode.COMPOSE` when:

    - The file doesn't exist (fresh install)
    - The file is empty
    - The file contains a value that doesn't match a known IngestMode

    The fallback is deliberately silent — the live system must keep
    working in COMPOSE mode at all times unless the operator
    explicitly opts in.
    """
    try:
        raw = MODE_FILE.read_text().strip()
    except FileNotFoundError:
        return IngestMode.COMPOSE
    except OSError as exc:
        log.debug("compositor-mode read failed: %s", exc)
        return IngestMode.COMPOSE
    try:
        return IngestMode(raw)
    except ValueError:
        log.warning(
            "compositor-mode file %s contains unrecognized value %r; defaulting to COMPOSE",
            MODE_FILE,
            raw,
        )
        return IngestMode.COMPOSE


def set_mode(mode: IngestMode) -> None:
    """Persist the operator's compositor mode selection.

    Creates the parent directory if missing. Atomically replaces
    the existing file via write-then-rename so a concurrent
    :func:`current_mode` reader never sees a partial file.
    """
    MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODE_FILE.with_suffix(MODE_FILE.suffix + ".tmp")
    tmp.write_text(mode.value + "\n")
    import os

    os.replace(tmp, MODE_FILE)
    log.info("compositor mode set to %s", mode.value)


def is_ingest_only() -> bool:
    """Convenience: return ``True`` iff the current mode is INGEST_ONLY.

    Use this as the branch test in pipeline construction code:

        if is_ingest_only():
            build_ingest_only_pipeline(...)
        else:
            build_compose_pipeline(...)
    """
    return current_mode() is IngestMode.INGEST_ONLY


def reset_mode() -> None:
    """Delete the mode file, returning the system to its default.

    The next :func:`current_mode` call returns
    :attr:`IngestMode.COMPOSE`. Used by tests and by the operator
    after a failed INGEST_ONLY experiment.
    """
    try:
        MODE_FILE.unlink()
    except FileNotFoundError:
        pass

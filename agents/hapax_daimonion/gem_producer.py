"""GEM frame producer — turns ``gem.*`` impingements into mural keyframes.

Hapax authors the GEM ward (``agents/studio_compositor/gem_source.py``)
by writing ``/dev/shm/hapax-compositor/gem-frames.json``. This module
owns that write path. It tails the impingement bus with its own cursor,
filters for ``intent_family in {"gem.emphasis.*", "gem.composition.*"}``,
and renders impingement narrative into 1-3 BitchX-grammar keyframes.

Phase 3 of the GEM activation plan
(``docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md``).

Initial slice ships template-driven authoring (no LLM call). The
template extracts the impingement's emphasis text and frames it with
BitchX banner punctuation:

  ┌──[ EMPHASIS ]──┐
  │ <text>         │
  └────────────────┘

LLM-driven multi-keyframe authoring is a follow-on once the template
path is proven safe under the AntiPatternKind enforcement gate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agents.studio_compositor.gem_source import GemFrame, contains_emoji
from shared.impingement import Impingement
from shared.impingement_consumer import ImpingementConsumer

if TYPE_CHECKING:
    from agents.hapax_daimonion.__main__ import VoiceDaemon

log = logging.getLogger(__name__)

DEFAULT_FRAMES_PATH = Path("/dev/shm/hapax-compositor/gem-frames.json")
DEFAULT_BUS_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
DEFAULT_CURSOR_PATH = Path.home() / ".cache" / "hapax" / "impingement-cursor-daimonion-gem.txt"

# How many frames a single impingement may emit. Cap protects the surface
# from a runaway producer flooding the renderer.
MAX_FRAMES_PER_IMPINGEMENT = 3
# Maximum length of any single frame's text. Px437 raster has fixed cells;
# truncation keeps the lower-band geometry from overflowing.
MAX_FRAME_TEXT_CHARS = 80

GEM_INTENT_PREFIXES: tuple[str, ...] = ("gem.emphasis", "gem.composition")


def _intent_matches(imp: Impingement) -> bool:
    """True if the impingement should drive a GEM authoring pass."""
    if imp.intent_family is None:
        return False
    return any(imp.intent_family.startswith(p) for p in GEM_INTENT_PREFIXES)


def _extract_emphasis_text(imp: Impingement) -> str:
    """Pull a renderable text fragment from an impingement.

    Preference order:
    1. ``content.emphasis_text`` — explicit author choice
    2. ``content.narrative`` — DMN's own framing
    3. ``content.summary`` — generic detector output
    4. Empty string (caller will fall back to a stock frame)
    """
    for key in ("emphasis_text", "narrative", "summary"):
        value = imp.content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _frame_text_safe(text: str) -> str:
    """Sanitize and truncate a candidate frame text.

    Strips emoji codepoints (anti-pattern) and clips to MAX_FRAME_TEXT_CHARS.
    Returns empty string if nothing renderable remains.
    """
    if contains_emoji(text):
        return ""
    cleaned = text.strip()
    if not cleaned:
        return ""
    if len(cleaned) > MAX_FRAME_TEXT_CHARS:
        cleaned = cleaned[: MAX_FRAME_TEXT_CHARS - 1].rstrip() + "…"
    return cleaned


def render_emphasis_template(text: str) -> list[GemFrame]:
    """Template-driven 3-frame sequence around a single emphasis fragment.

    Frame 1: empty banner (sets up the cell), 400ms.
    Frame 2: text inside the banner, 1800ms (the emphasis hold).
    Frame 3: text with revision underline marks, 600ms (the "trace" leave).
    """
    safe = _frame_text_safe(text)
    if not safe:
        return []
    border = "─" * (len(safe) + 4)
    return [
        GemFrame(text=f"┌{border}┐\n│  {' ' * len(safe)}  │\n└{border}┘", hold_ms=400),
        GemFrame(text=f"┌{border}┐\n│  {safe}  │\n└{border}┘", hold_ms=1800),
        GemFrame(text=f"» {safe} «", hold_ms=600),
    ]


def render_composition_template(text: str) -> list[GemFrame]:
    """Template-driven sequence for a composition impingement.

    Currently a single-frame fragment with BitchX `>>>` prefix; richer
    multi-keyframe sequences (ASCII tree growing, glyph rotation) land
    in the LLM-driven follow-on.
    """
    safe = _frame_text_safe(text)
    if not safe:
        return []
    return [
        GemFrame(text=f">>> {safe}", hold_ms=2000),
    ]


def frames_for_impingement(imp: Impingement) -> list[GemFrame]:
    """Convert an impingement into ≤MAX_FRAMES_PER_IMPINGEMENT frames."""
    if not _intent_matches(imp):
        return []
    text = _extract_emphasis_text(imp)
    if not text:
        return []
    if imp.intent_family is not None and imp.intent_family.startswith("gem.composition"):
        frames = render_composition_template(text)
    else:
        frames = render_emphasis_template(text)
    return frames[:MAX_FRAMES_PER_IMPINGEMENT]


def write_frames_atomic(frames: list[GemFrame], path: Path) -> None:
    """Atomically replace ``path`` with the JSON serialization of ``frames``.

    Same tmp-rename pattern as the rest of the SHM publishers: write to a
    sibling temp file then rename so the renderer never sees a half-
    written payload. Parent directory created on demand.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "frames": [{"text": f.text, "hold_ms": f.hold_ms} for f in frames],
        "written_ts": time.time(),
    }
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


async def gem_producer_loop(
    daemon: VoiceDaemon,
    *,
    bus_path: Path = DEFAULT_BUS_PATH,
    cursor_path: Path = DEFAULT_CURSOR_PATH,
    frames_path: Path = DEFAULT_FRAMES_PATH,
    poll_interval_s: float = 0.5,
) -> None:
    """Tail the impingement bus and write GEM frames as authored intent arrives.

    Spawned as a daimonion background task; runs while ``daemon._running``.
    Errors are logged and the loop continues — the GEM ward must never
    take the daemon down.
    """
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    consumer = ImpingementConsumer(bus_path, cursor_path=cursor_path)

    log.info("gem-producer started; cursor=%s frames=%s", cursor_path, frames_path)

    while daemon._running:
        try:
            for imp in consumer.read_new():
                frames = frames_for_impingement(imp)
                if not frames:
                    continue
                try:
                    write_frames_atomic(frames, frames_path)
                    log.debug("gem-producer: wrote %d frames for %s", len(frames), imp.id)
                except Exception:
                    log.warning(
                        "gem-producer: write_frames_atomic failed for %s",
                        imp.id,
                        exc_info=True,
                    )
        except Exception:
            log.debug("gem-producer loop error", exc_info=True)
        await asyncio.sleep(poll_interval_s)


__all__ = [
    "DEFAULT_BUS_PATH",
    "DEFAULT_CURSOR_PATH",
    "DEFAULT_FRAMES_PATH",
    "GEM_INTENT_PREFIXES",
    "MAX_FRAMES_PER_IMPINGEMENT",
    "MAX_FRAME_TEXT_CHARS",
    "frames_for_impingement",
    "gem_producer_loop",
    "render_composition_template",
    "render_emphasis_template",
    "write_frames_atomic",
]

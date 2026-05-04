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


# Meta-narration pattern: phrases that describe what the SYSTEM is about
# to DO rather than CONTENT to render. The audit screenshot 2026-04-22
# showed "Compose a minimal CP437 glyph sequence to mark the current
# system status" rendered as GEM mural content — that's the LLM telling
# itself what to compose, not the composition itself. Per
# ``feedback_show_dont_tell_director`` the GEM ward must AUTHOR content,
# not transcribe directives. The patterns below reject the visible
# failure modes; new ones should be added when they appear in
# director-intent.jsonl.
_META_NARRATION_PREFIXES: tuple[str, ...] = (
    "compose ",
    "cut to ",
    "cuts to ",
    "cutting to ",
    "show ",
    "shows ",
    "showing ",
    "display ",
    "displays ",
    "displaying ",
    "render ",
    "renders ",
    "rendering ",
    "mark ",
    "marks ",
    "marking ",
    "highlight ",
    "highlights ",
    "highlighting ",
    "foreground ",
    "foregrounds ",
    "foregrounding ",
    "background ",
    "backgrounds ",
    "backgrounding ",
    "dim ",
    "dims ",
    "dimming ",
    "pulse ",
    "pulses ",
    "pulsing ",
    "drop ",
    "drops ",
    "dropping ",
    "switch ",
    "switches ",
    "switching ",
    "trigger ",
    "triggers ",
    "triggering ",
    "author ",
    "authors ",
    "authoring ",
    "let ",  # "let me show you", "let's bring up..."
)
_META_NARRATION_KEYWORDS: tuple[str, ...] = (
    " ward",
    " stance",
    " preset",
    " shader",
    " scrim",
    " homage",
    " ticker",
    " overlay",
    " compositor",
    " keyframe",
    " glyph sequence",
    " mural",
    " surface",
    " viewer",
    "system status",
    "current state",
)


def _is_meta_narration(text: str) -> bool:
    """True if ``text`` is the LLM telling the system what to render
    rather than CONTENT to render.

    Two-stage check: imperative-verb prefix OR any system-vocabulary
    keyword. Both stages are conservative — a real lyric like
    "cut me loose" would match the prefix check but the keyword stage
    would still pass it through; the GEM producer's caller falls back
    to a stock frame on rejection so a false positive degrades
    gracefully.
    """
    if not text:
        return True
    lower = text.lower().lstrip()
    if any(lower.startswith(p) for p in _META_NARRATION_PREFIXES):
        return True
    return any(kw in lower for kw in _META_NARRATION_KEYWORDS)


def _extract_emphasis_text(imp: Impingement) -> str:
    """Pull a renderable text fragment from an impingement.

    Preference order:
    1. ``content.emphasis_text`` — explicit author choice. Returned
       even if it looks meta — the explicit author field is the
       contract, the producer trusts it.
    2. ``content.summary`` — detector output. Trusted similarly.
    3. ``content.narrative`` — LLM's own framing. **Rejected if it
       reads as meta-narration** (per audit 2026-04-22, narratives
       like "Compose a CP437 glyph sequence to mark…" leaked into
       the mural as content rather than driving an actual compose).
       lssh-002 (P0 GEM rendering redesign) will replace this whole
       text-passthrough path with content authoring; until then the
       meta-filter prevents the worst leak.
    4. Empty string — caller skips the write so the renderer keeps the
       last valid sequence or uses its own visible fallback.
    """
    for key in ("emphasis_text", "summary"):
        value = imp.content.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return "" if _looks_like_corrupt_fragment(text) else text

    narrative = imp.content.get("narrative")
    if isinstance(narrative, str) and narrative.strip():
        text = narrative.strip()
        if _is_meta_narration(text) or _looks_like_corrupt_fragment(text):
            return ""
        return text
    return ""


def _looks_like_corrupt_fragment(text: str) -> bool:
    """Reject punctuation-only fragments seen in malformed GEM payloads."""

    return text.startswith(".") or " , ." in text


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
    return [
        GemFrame(text="┌──[ GEM ]──┐", hold_ms=400),
        GemFrame(text=f"│ {safe} │", hold_ms=1800),
        GemFrame(text=f"└─ {safe} ─┘", hold_ms=600),
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
    """Convert an impingement into ≤MAX_FRAMES_PER_IMPINGEMENT frames.

    Synchronous template path. The async variant
    ``async_frames_for_impingement`` tries LLM authoring first when the
    ``HAPAX_GEM_LLM_AUTHORING`` flag is set, and falls back here on any
    failure or when the flag is off.
    """
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


async def async_frames_for_impingement(imp: Impingement) -> list[GemFrame]:
    """Async authoring — LLM first when opted in, template fallback always.

    LLM authoring opt-in: ``HAPAX_GEM_LLM_AUTHORING=1`` env flag (read
    fresh each call so flips take effect without a restart). When the
    flag is off, behavior matches ``frames_for_impingement`` exactly.
    When on but the LLM call fails (network / timeout / Pydantic
    validation / model unavailable), the template path is used.
    """
    if not _intent_matches(imp):
        return []
    text = _extract_emphasis_text(imp)
    if not text:
        return []

    from agents.hapax_daimonion.gem_authoring_agent import (
        author_sequence,
        is_llm_authoring_enabled,
    )

    if is_llm_authoring_enabled():
        sequence = await author_sequence(imp, text)
        if sequence is not None and sequence.frames:
            return [GemFrame(text=f.text, hold_ms=f.hold_ms) for f in sequence.frames]

    return frames_for_impingement(imp)


def write_frames_atomic(frames: list[GemFrame], path: Path) -> None:
    """Atomically replace ``path`` with the JSON serialization of ``frames``.

    Same tmp-rename pattern as the rest of the SHM publishers: write to a
    sibling temp file then rename so the renderer never sees a half-
    written payload. Parent directory created on demand.
    """
    frame_payloads = [
        {"text": f.text.strip(), "hold_ms": f.hold_ms}
        for f in frames
        if f.text.strip() and not contains_emoji(f.text)
    ]
    if not frame_payloads:
        raise ValueError("gem frames payload must include at least one renderable frame")

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "frames": frame_payloads,
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
                frames = await async_frames_for_impingement(imp)
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
    "async_frames_for_impingement",
    "frames_for_impingement",
    "gem_producer_loop",
    "render_composition_template",
    "render_emphasis_template",
    "write_frames_atomic",
]

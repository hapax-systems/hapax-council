"""Witnessed readback for recruited segment media moves.

The layout-responsibility loop already proves a layout posture rendered via a
LayoutState-hash + ward-visibility receipt. This extends the same discipline to
media: a cued media move counts as success only when the readback proves the
visible effect — the OARB slot is actually showing the intended ref, or the
image object_ref appears in the layout readback's rendered object refs. A move
that merely wrote an intent cannot fake-succeed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from agents.studio_compositor.oarb_media_slot import SELECTOR_PATH, oarb_is_playing


@dataclass(frozen=True)
class MediaRenderVerdict:
    """Whether one media move's visible effect was witnessed in the readback."""

    object_ref: str
    media_kind: str
    rendered: bool


def media_render_verdicts(
    media_moves: Iterable,
    *,
    rendered_object_refs: Sequence[str] = (),
    oarb_selector_path: Path = SELECTOR_PATH,
) -> tuple[MediaRenderVerdict, ...]:
    """Assert each cued media move actually rendered.

    youtube → the live OARB selector shows the intended ref; image → the ref
    is present in the layout readback's ``rendered_object_refs``. Non-cued
    moves (gate-refused) are never rendered.
    """

    rendered_set = set(rendered_object_refs)
    verdicts: list[MediaRenderVerdict] = []
    for move in media_moves:
        object_ref = getattr(move, "object_ref", "")
        media_kind = getattr(move, "media_kind", "unknown")
        if not getattr(move, "cued", False):
            verdicts.append(MediaRenderVerdict(object_ref, media_kind, False))
            continue
        if media_kind == "youtube":
            rendered = oarb_is_playing(object_ref, selector_path=oarb_selector_path)
        else:
            rendered = object_ref in rendered_set
        verdicts.append(MediaRenderVerdict(object_ref, media_kind, rendered))
    return tuple(verdicts)


__all__ = ["MediaRenderVerdict", "media_render_verdicts"]

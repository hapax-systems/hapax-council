"""Single owner of the OARB (AoA media-sphere) media slot.

The OARB sphere's on-screen media is selected by one file —
``youtube-video-id.txt`` — which the live BGRA source
(``quake-live-media-source``) reads to feed the ``aoa-media-sphere`` texture.
The ``screwm-oarb-playlist-rotator`` writes that selector when its player slot
is idle.

To let the director cue a SPECIFIC ref WITHOUT bolting onto the rotator (which
would make the two fight over the slot), this module is the single in-process
owner of director cues: it writes the SAME selector file plus a director-cue
*lease* (``oarb-director-cue.json``) that marks the slot director-owned for a
bounded TTL. The rotator's idle-only policy already keeps it from interrupting
a playing cue; the lease is the cooperative contract for it to defer. No new
playback path is opened — the cue rides the existing YT media selector, so it
inherits the YouTube channel's level + cut-away-mute discipline.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SHM_DIR = Path("/dev/shm/hapax-compositor")
# Same selector the rotator writes (env-overridable to match it exactly).
SELECTOR_PATH = Path(
    os.environ.get("SCREWM_OARB_VIDEO_ID_PATH", str(SHM_DIR / "youtube-video-id.txt"))
)
DIRECTOR_CUE_PATH = SHM_DIR / "oarb-director-cue.json"
DEFAULT_CUE_TTL_S = 300.0
CUE_OWNER = "segment_director"

_OBJECT_YT_PREFIX = "object:yt:"
_URL_MARKERS = ("v=", "youtu.be/", "/embed/", "/shorts/")


@dataclass(frozen=True)
class OarbCueResult:
    """Outcome of cueing one media ref to the OARB slot."""

    cued: bool
    video_id: str | None
    reason: str


def video_id_from_ref(media_ref: str) -> str | None:
    """Resolve a stable youtube id from an object_ref or URL.

    Returns ``None`` for non-youtube refs (images) and unparseable inputs, so
    the caller cannot accidentally cue a non-video onto the sphere.
    """

    if not media_ref:
        return None
    ref = media_ref
    if ref.startswith(_OBJECT_YT_PREFIX):
        ref = ref[len(_OBJECT_YT_PREFIX) :]
    elif ref.startswith("object:"):
        return None
    for marker in _URL_MARKERS:
        if marker in ref:
            tail = ref.split(marker, 1)[1]
            for sep in ("&", "?", "/"):
                tail = tail.split(sep, 1)[0]
            return tail or None
    if ref and all(ch.isalnum() or ch in "-_" for ch in ref):
        return ref
    return None


def cue_media_to_oarb(
    media_ref: str,
    *,
    ttl_s: float = DEFAULT_CUE_TTL_S,
    now: float | None = None,
    selector_path: Path = SELECTOR_PATH,
    cue_path: Path = DIRECTOR_CUE_PATH,
) -> OarbCueResult:
    """Cue a specific media ref onto the OARB slot (the single owner path)."""

    import time

    video_id = video_id_from_ref(media_ref)
    if not video_id:
        return OarbCueResult(cued=False, video_id=None, reason="unresolvable_media_ref")
    ts = time.time() if now is None else now
    try:
        _atomic_write_text(selector_path, video_id + "\n")
        _atomic_write_json(
            cue_path,
            {
                "video_id": video_id,
                "media_ref": media_ref,
                "owner": CUE_OWNER,
                "ttl_s": ttl_s,
                "set_at": ts,
                "expires_at": ts + ttl_s,
            },
        )
    except OSError:
        log.warning("OARB cue write failed", exc_info=True)
        return OarbCueResult(cued=False, video_id=video_id, reason="write_failed")
    return OarbCueResult(cued=True, video_id=video_id, reason="cued")


def oarb_is_playing(media_ref: str, *, selector_path: Path = SELECTOR_PATH) -> bool:
    """Witnessed readback: is the OARB slot ACTUALLY showing ``media_ref``?

    Reads the live selector file (what the BGRA source consumes) and compares
    its video id to the intended one. A cued media move only counts as success
    when this returns True, so a move cannot fake-succeed by merely writing an
    intent — the rendered selector must match.
    """

    want = video_id_from_ref(media_ref)
    if not want:
        return False
    try:
        current = selector_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(current) and current == want


def cue_from_youtube_direction(
    data: Mapping[str, Any],
    *,
    now: float | None = None,
    selector_path: Path = SELECTOR_PATH,
    cue_path: Path = DIRECTOR_CUE_PATH,
) -> OarbCueResult | None:
    """Honor a ``cue-to-surface`` youtube-direction payload via the owner.

    Returns ``None`` for any other action or a missing media_ref, so the
    director loop's consumer can fall through to its legacy verbs.
    """

    if not isinstance(data, Mapping) or str(data.get("action") or "") != "cue-to-surface":
        return None
    media_ref = data.get("media_ref")
    if not isinstance(media_ref, str) or not media_ref:
        return None
    ttl_s = float(data.get("ttl_s") or 0.0) or DEFAULT_CUE_TTL_S
    return cue_media_to_oarb(
        media_ref,
        ttl_s=ttl_s,
        now=now,
        selector_path=selector_path,
        cue_path=cue_path,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


__all__ = [
    "CUE_OWNER",
    "DIRECTOR_CUE_PATH",
    "SELECTOR_PATH",
    "OarbCueResult",
    "cue_from_youtube_direction",
    "cue_media_to_oarb",
    "oarb_is_playing",
    "video_id_from_ref",
]

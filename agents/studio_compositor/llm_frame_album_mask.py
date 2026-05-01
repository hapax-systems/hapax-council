"""Album-cover redaction for the LLM-bound camera frame.

When ``album-state.playing=False`` the multimodal director LLM should
not receive a clean image of whatever cover is on the turntable —
otherwise it identifies the cover ("Special Herbs", etc.) and
hallucinates track-specific narrations from its training data even
though no text-side ``current_track`` is available. The other layers
of the false-grounding cascade (#1933 / #1936 consumer text guards,
#1945 producer silence gate) close text-side leaks; this module
closes the visual-side leak.

Approach
--------

Strict bbox masking would require either an extra vision-LLM call per
director tick (expensive — the director runs every 3-5 s) or a fixed
geometric region that breaks when ``camera.hero`` reshuffles the
compositor layout. The pragmatic alternative is whole-frame
**pixelation by downscale-then-upscale**: a coarse low-pass that
destroys high-frequency detail (album-cover graphics, label text,
chat overlay text) while preserving rough scene structure (operator
shape, motion, broad lighting). The LLM can still distinguish
"operator at desk" from "empty desk" for non-music activities; it
cannot read the album cover.

When ``album-state.playing=True`` the cover IS the legitimate
now-playing visual signal (per the cc-task spec: "when actually
playing, the cover IS legitimately the 'now playing' signal and
should reach the LLM"). The frame passes through unchanged.

Pure-logic — no I/O on the hot path beyond the album-state read.
The pixelation step is a single PIL resize round-trip; expected cost
is sub-millisecond at 1280×720.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

#: Default location of the album-state JSON written by
#: ``scripts/album-identifier.py::write_state``.
DEFAULT_ALBUM_STATE_PATH: Final[Path] = Path("/dev/shm/hapax-compositor/album-state.json")

#: Coarse low-pass target — the frame is downscaled to this resolution
#: then upscaled back to the original. 64×36 preserves the 16:9 aspect
#: of the 1280×720 LLM frame; high-frequency detail is destroyed but
#: silhouettes / motion / camera-tile layout remain readable.
PIXELATION_LOW_RES: Final[tuple[int, int]] = (64, 36)


@dataclass(frozen=True)
class MaskDecision:
    """Result of an album-state read.

    ``should_mask`` is ``True`` iff the frame should be redacted.
    ``reason`` carries a short tag for telemetry / log lines so the
    operator can audit why a tick was masked or not.
    """

    should_mask: bool
    reason: str


def read_mask_decision(state_path: Path = DEFAULT_ALBUM_STATE_PATH) -> MaskDecision:
    """Read ``album-state.json`` and decide whether to mask.

    Returns ``MaskDecision(should_mask=True, reason="...")`` when the
    file is missing, malformed, or carries ``playing=False``. Fail-closed
    by design: the conservative choice when state is unknown is to mask,
    since the leak we are preventing only fires when the LLM sees a
    clean cover the operator has NOT confirmed is playing.
    """
    try:
        if not state_path.exists():
            return MaskDecision(should_mask=True, reason="state-missing")
        raw = state_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("album-state read failed (%s); failing closed", exc)
        return MaskDecision(should_mask=True, reason="state-read-error")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("album-state JSON decode failed; failing closed")
        return MaskDecision(should_mask=True, reason="state-malformed")
    if not isinstance(data, dict):
        return MaskDecision(should_mask=True, reason="state-not-object")
    playing = data.get("playing", False)
    if playing is True:
        return MaskDecision(should_mask=False, reason="playing")
    return MaskDecision(should_mask=True, reason="not-playing")


def apply_pixelation(jpeg_bytes: bytes) -> bytes:
    """Downscale-then-upscale a JPEG to destroy high-frequency detail.

    Returns a JPEG of the same dimensions as the input. The operation
    is a coarse low-pass: the cover graphics, label text, and overlay
    text become unreadable; broad scene structure (silhouettes,
    layout) is preserved.

    Raises :class:`ValueError` if the input bytes do not decode as a
    valid image — callers should treat this as an upstream pipeline
    failure rather than masquerading the error as a successful mask.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover — PIL is a hard dep here
        raise RuntimeError("PIL is required for album-cover masking") from exc

    try:
        img = Image.open(io.BytesIO(jpeg_bytes))
        img.load()
    except Exception as exc:
        raise ValueError(f"could not decode input JPEG: {exc}") from exc

    original_size = img.size
    # Downscale with NEAREST so the result is hard pixelation (rather than
    # a blur that retains some readable contrast). Upscale with NEAREST
    # too so the output is visibly pixelated, not soft.
    low = img.resize(PIXELATION_LOW_RES, resample=Image.Resampling.NEAREST)
    redacted = low.resize(original_size, resample=Image.Resampling.NEAREST)

    buf = io.BytesIO()
    # Re-encode as JPEG with the original quality target; downstream
    # callers decode again so the JPEG-decode stability matters more
    # than file-size optimization.
    redacted.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def mask_if_not_playing(
    jpeg_bytes: bytes,
    state_path: Path = DEFAULT_ALBUM_STATE_PATH,
) -> tuple[bytes, MaskDecision]:
    """Redact the frame iff ``album-state.playing`` is not ``True``.

    Returns the (possibly redacted) JPEG bytes plus the decision that
    drove the choice — callers can attach the reason to log lines or
    a metric.

    On a decoder failure the raw input bytes are returned unmasked
    with a ``decode-failed`` reason. We deliberately do NOT fall back
    to a synthetic placeholder image: that would be silently
    discarding the operator's frame, and the director loop already
    handles missing-frame paths upstream.
    """
    decision = read_mask_decision(state_path)
    if not decision.should_mask:
        return jpeg_bytes, decision
    try:
        masked = apply_pixelation(jpeg_bytes)
    except ValueError:
        log.warning("album-mask: input JPEG would not decode; passing through unmasked")
        return jpeg_bytes, MaskDecision(should_mask=False, reason="decode-failed")
    return masked, decision

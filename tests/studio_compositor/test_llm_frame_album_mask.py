"""Tests for ``agents.studio_compositor.llm_frame_album_mask``.

Coverage:

- ``read_mask_decision``: missing file, malformed JSON, non-object root,
  ``playing=True`` → no mask, ``playing=False`` → mask, missing key
  defaults to mask (fail-closed).
- ``apply_pixelation``: input → output is a valid JPEG of the same
  dimensions; high-frequency content is destroyed (decoded back to
  numpy, the variance per pixelation block drops to ~0).
- ``mask_if_not_playing``: end-to-end wiring; bytes pass through
  unmodified when ``playing=True`` and are redacted when not;
  decoder failures pass through unmasked with a ``decode-failed``
  reason.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from agents.studio_compositor.llm_frame_album_mask import (
    PIXELATION_LOW_RES,
    MaskDecision,
    apply_pixelation,
    mask_if_not_playing,
    read_mask_decision,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _synth_jpeg(width: int = 128, height: int = 72, *, with_text: bool = True) -> bytes:
    """Generate a JPEG with high-frequency content (vertical stripes +
    optional text) for tests that verify pixelation destroys detail."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), (32, 32, 32))
    draw = ImageDraw.Draw(img)
    # 1px-wide stripes — pure high-frequency content. Pixelation should
    # collapse these to flat blocks.
    for x in range(0, width, 2):
        draw.line([(x, 0), (x, height)], fill=(255, 255, 255), width=1)
    if with_text:
        try:
            font = ImageFont.load_default()
        except OSError:
            font = None
        draw.text((4, 4), "ALBUM TEXT", fill=(255, 64, 64), font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _write_state(path: Path, payload: object | None) -> None:
    if payload is None:
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


# ── read_mask_decision ───────────────────────────────────────────────────


class TestReadMaskDecision:
    def test_missing_file_fails_closed(self, tmp_path: Path) -> None:
        decision = read_mask_decision(tmp_path / "absent.json")
        assert decision == MaskDecision(should_mask=True, reason="state-missing")

    def test_malformed_json_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        _write_state(path, "not json {{{")
        decision = read_mask_decision(path)
        assert decision == MaskDecision(should_mask=True, reason="state-malformed")

    def test_non_object_root_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        _write_state(path, ["a", "b"])
        decision = read_mask_decision(path)
        assert decision == MaskDecision(should_mask=True, reason="state-not-object")

    def test_playing_true_passes_through(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        _write_state(path, {"playing": True, "current_track": "x"})
        decision = read_mask_decision(path)
        assert decision == MaskDecision(should_mask=False, reason="playing")

    def test_playing_false_masks(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        _write_state(path, {"playing": False})
        decision = read_mask_decision(path)
        assert decision == MaskDecision(should_mask=True, reason="not-playing")

    def test_missing_playing_key_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        _write_state(path, {"current_track": ""})
        decision = read_mask_decision(path)
        assert decision == MaskDecision(should_mask=True, reason="not-playing")

    def test_playing_truthy_non_bool_fails_closed(self, tmp_path: Path) -> None:
        """``playing: 1`` is truthy in Python but not strictly ``True``;
        we require strict ``True`` because the consumer's safety contract
        depends on the producer's explicit confirmation."""
        path = tmp_path / "state.json"
        _write_state(path, {"playing": 1})
        decision = read_mask_decision(path)
        assert decision.should_mask is True


# ── apply_pixelation ─────────────────────────────────────────────────────


class TestApplyPixelation:
    def test_output_is_valid_jpeg_same_size(self) -> None:
        from PIL import Image

        src = _synth_jpeg(width=128, height=72)
        out = apply_pixelation(src)
        decoded = Image.open(io.BytesIO(out))
        decoded.load()
        assert decoded.size == (128, 72)

    def test_destroys_high_frequency_content(self) -> None:
        """Stripes of width 1 → pixelated blocks of size > stripe-width
        → adjacent original pixels collapse to the same block, so the
        per-block variance drops vs. the input."""
        from PIL import Image

        src = _synth_jpeg(width=128, height=72)
        out = apply_pixelation(src)

        src_img = Image.open(io.BytesIO(src)).convert("L")
        out_img = Image.open(io.BytesIO(out)).convert("L")

        src_pixels = list(src_img.getdata())
        out_pixels = list(out_img.getdata())

        def variance(values: list[int]) -> float:
            mean = sum(values) / len(values)
            return sum((v - mean) ** 2 for v in values) / len(values)

        # Per-pixel variance drops sharply because 1-pixel-wide stripes
        # collapse into wider pixelation blocks of one common value.
        # JPEG re-encoding adds some subtle artifacts so we don't expect
        # the variance to hit zero, but it should be a small fraction
        # of the source's variance.
        assert variance(out_pixels) < variance(src_pixels) / 5

    def test_invalid_input_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="could not decode"):
            apply_pixelation(b"this is not a jpeg")

    def test_low_res_constant_matches_aspect(self) -> None:
        """Confirm the documented aspect ratio sanity of the constant."""
        w, h = PIXELATION_LOW_RES
        # 16:9 aspect — both 1280×720 and 64×36 are 16:9.
        assert abs((w / h) - (16 / 9)) < 0.01


# ── mask_if_not_playing ──────────────────────────────────────────────────


class TestMaskIfNotPlaying:
    def test_pass_through_when_playing(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        _write_state(state, {"playing": True})
        src = _synth_jpeg()
        out, decision = mask_if_not_playing(src, state_path=state)
        assert out == src  # bytes unchanged
        assert decision.should_mask is False
        assert decision.reason == "playing"

    def test_redacts_when_not_playing(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        _write_state(state, {"playing": False})
        src = _synth_jpeg()
        out, decision = mask_if_not_playing(src, state_path=state)
        assert out != src
        assert decision.should_mask is True
        assert decision.reason == "not-playing"

    def test_redacts_when_state_missing(self, tmp_path: Path) -> None:
        state = tmp_path / "absent.json"
        src = _synth_jpeg()
        out, decision = mask_if_not_playing(src, state_path=state)
        assert out != src
        assert decision.reason == "state-missing"

    def test_decode_failure_passes_through_unmasked(self, tmp_path: Path) -> None:
        """Catastrophic decoder failure should NOT mask — that would
        silently swap the operator's input for a synthetic placeholder.
        Instead we surface the bytes unchanged with a ``decode-failed``
        reason so callers can observe the failure in a metric."""
        state = tmp_path / "state.json"
        _write_state(state, {"playing": False})
        bad = b"this is definitely not a jpeg"
        out, decision = mask_if_not_playing(bad, state_path=state)
        assert out == bad
        assert decision.should_mask is False
        assert decision.reason == "decode-failed"

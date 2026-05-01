"""Tests for ``agents.ir_vlm_runner``.

Coverage:

- Construction: rejects negative motion_threshold and non-positive
  cache_ttl_s.
- ``_perceptual_hash``: invalid bytes raise ValueError; identical
  inputs hash identically; visually-different inputs differ.
- ``_hamming_distance``: same length required; counts differing bits.
- ``MotionGatedVlmRunner.tick`` decision tree: first-call fires, cache
  blocks within TTL, motion gate blocks low-distance frames, high-
  distance frames refire after TTL, runner-None counts as failure
  but preserves cached, decode-failure counts as failure.
- ``fingerprint_image``: stable, short.
"""

from __future__ import annotations

import io

import pytest

from agents.ir_vlm_runner import (
    DEFAULT_CACHE_TTL_S,
    DEFAULT_MOTION_THRESHOLD,
    IrVlmRunnerState,
    MotionGatedVlmRunner,
    TickOutcome,
    _hamming_distance,
    _perceptual_hash,
    fingerprint_image,
)
from shared.ir_vlm_classifier import HandSemantics


def _solid_jpeg(brightness: int, *, size: int = 64) -> bytes:
    """Return a solid-grey JPEG of the requested brightness."""
    from PIL import Image

    img = Image.new("L", (size, size), brightness)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _checkerboard_jpeg(*, size: int = 64) -> bytes:
    from PIL import Image

    img = Image.new("L", (size, size), 0)
    pixels = img.load()
    for y in range(size):
        for x in range(size):
            pixels[x, y] = 255 if (x + y) % 2 == 0 else 0
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _semantics(intent: str = "typing on keyboard") -> HandSemantics:
    return HandSemantics(
        intent=intent,
        surface="laptop keyboard",
        hand_position="centered",
        confidence=0.9,
    )


# ── Helpers ──────────────────────────────────────────────────────────────


class TestPerceptualHash:
    def test_decoded_length_is_32_bytes(self) -> None:
        h = _perceptual_hash(_solid_jpeg(128))
        assert len(h) == 32  # 256 bits / 8

    def test_identical_inputs_hash_identically(self) -> None:
        a = _solid_jpeg(128)
        assert _perceptual_hash(a) == _perceptual_hash(a)

    def test_invalid_input_raises(self) -> None:
        with pytest.raises(ValueError, match="could not decode"):
            _perceptual_hash(b"definitely not a jpeg")

    def test_dramatically_different_inputs_differ(self) -> None:
        h1 = _perceptual_hash(_solid_jpeg(0))
        h2 = _perceptual_hash(_checkerboard_jpeg())
        assert _hamming_distance(h1, h2) > DEFAULT_MOTION_THRESHOLD


class TestHammingDistance:
    def test_zero_for_identical(self) -> None:
        b = b"\x00" * 32
        assert _hamming_distance(b, b) == 0

    def test_counts_differing_bits(self) -> None:
        a = b"\xff\x00"
        b = b"\x00\xff"
        # 8 bits differ in each byte, two bytes ⇒ 16.
        assert _hamming_distance(a, b) == 16

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="length mismatch"):
            _hamming_distance(b"\x00", b"\x00\x00")


# ── Construction ─────────────────────────────────────────────────────────


class TestConstruction:
    def _stub_runner(self, response):  # type: ignore[no-untyped-def]
        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            return response

        return runner

    def test_default_constants_match_documented_values(self) -> None:
        assert DEFAULT_MOTION_THRESHOLD == 12
        assert DEFAULT_CACHE_TTL_S == 15.0

    def test_rejects_negative_motion_threshold(self) -> None:
        with pytest.raises(ValueError, match="motion_threshold must be >= 0"):
            MotionGatedVlmRunner(runner=self._stub_runner(None), motion_threshold=-1)

    def test_rejects_nonpositive_cache_ttl(self) -> None:
        with pytest.raises(ValueError, match="cache_ttl_s must be > 0"):
            MotionGatedVlmRunner(runner=self._stub_runner(None), cache_ttl_s=0)
        with pytest.raises(ValueError, match="cache_ttl_s must be > 0"):
            MotionGatedVlmRunner(runner=self._stub_runner(None), cache_ttl_s=-1.0)


# ── Tick decision tree ──────────────────────────────────────────────────


class TestTickFirstCall:
    def test_first_call_fires_vlm_and_caches(self) -> None:
        called = {"n": 0}

        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            called["n"] += 1
            return _semantics().model_dump_json()

        run = MotionGatedVlmRunner(runner=runner)
        outcome = run.tick(_solid_jpeg(128), now=1000.0)

        assert called["n"] == 1
        assert outcome.reason == "call-made"
        assert outcome.semantics is not None
        assert run.cached == outcome.semantics
        assert run.stats.call_made == 1


class TestTickCache:
    def test_cache_hit_within_ttl(self) -> None:
        called = {"n": 0}

        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            called["n"] += 1
            return _semantics().model_dump_json()

        run = MotionGatedVlmRunner(runner=runner, cache_ttl_s=10.0)
        run.tick(_solid_jpeg(128), now=1000.0)
        # Second call inside the TTL window — even with a different
        # frame, the cache should block the VLM call.
        outcome = run.tick(_checkerboard_jpeg(), now=1005.0)

        assert called["n"] == 1
        assert outcome.reason == "cache-hit"
        assert outcome.semantics == run.cached
        assert run.stats.call_skipped_cache_hit == 1


class TestTickMotionGate:
    def test_low_motion_skips_vlm(self) -> None:
        called = {"n": 0}

        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            called["n"] += 1
            return _semantics().model_dump_json()

        run = MotionGatedVlmRunner(runner=runner, cache_ttl_s=0.001)
        # First call seeds the phash.
        run.tick(_solid_jpeg(128), now=1000.0)
        # TTL expires; second call uses an identical-ish frame.
        outcome = run.tick(_solid_jpeg(128), now=1100.0)

        assert called["n"] == 1
        assert outcome.reason == "no-motion"
        assert run.stats.call_skipped_no_motion == 1

    def test_high_motion_refires_after_ttl(self) -> None:
        responses = [_semantics("typing").model_dump_json(), _semantics("dj").model_dump_json()]

        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            return responses.pop(0)

        run = MotionGatedVlmRunner(runner=runner, cache_ttl_s=0.001)
        run.tick(_solid_jpeg(0), now=1000.0)
        outcome = run.tick(_checkerboard_jpeg(), now=1100.0)

        assert outcome.reason == "call-made"
        assert outcome.semantics is not None
        assert outcome.semantics.intent == "dj"
        assert run.stats.call_made == 2


class TestTickFailures:
    def test_runner_none_counts_failure_preserves_cache(self) -> None:
        responses: list[str | None] = [_semantics().model_dump_json(), None]

        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            return responses.pop(0)

        run = MotionGatedVlmRunner(runner=runner, cache_ttl_s=0.001)
        first = run.tick(_solid_jpeg(0), now=1000.0)
        second = run.tick(_checkerboard_jpeg(), now=1100.0)

        assert first.reason == "call-made"
        assert first.semantics is not None
        assert second.reason == "call-failed"
        assert second.semantics == first.semantics  # cache preserved
        assert run.stats.call_failed == 1

    def test_decode_failure_counts_failure(self) -> None:
        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            pytest.fail("runner should not be invoked when decode fails")

        run = MotionGatedVlmRunner(runner=runner)
        outcome = run.tick(b"this is not a jpeg", now=1000.0)
        assert outcome.reason == "decode-failed"
        assert outcome.semantics is None
        assert run.stats.call_failed == 1


class TestTickStateInjection:
    def test_state_is_observable_via_property(self) -> None:
        state = IrVlmRunnerState()

        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            return _semantics().model_dump_json()

        run = MotionGatedVlmRunner(runner=runner, state=state)
        assert run.state is state
        assert run.stats is state.stats

        run.tick(_solid_jpeg(128), now=1000.0)
        assert state.last_phash is not None
        assert state.last_call_ts == pytest.approx(1000.0)
        assert state.cached is not None


# ── fingerprint_image ────────────────────────────────────────────────────


class TestFingerprintImage:
    def test_stable_for_same_bytes(self) -> None:
        b = _solid_jpeg(128)
        assert fingerprint_image(b) == fingerprint_image(b)

    def test_short_hex(self) -> None:
        fp = fingerprint_image(_solid_jpeg(128))
        assert len(fp) == 8
        # md5 hex characters only.
        assert all(c in "0123456789abcdef" for c in fp)


# ── TickOutcome shape ────────────────────────────────────────────────────


class TestTickOutcome:
    def test_dataclass_carries_semantics_and_reason(self) -> None:
        out = TickOutcome(semantics=_semantics(), reason="call-made")
        assert out.semantics is not None
        assert out.reason == "call-made"

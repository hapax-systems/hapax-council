"""Tests for ``pi-edge/vlm_classifier.py``.

The module lives in pi-edge's flat namespace; tests load it via a
relative-path import so the council-side test runner can exercise it
without restructuring pi-edge.

Coverage:

- ``parse_vlm_response``: well-formed JSON / code-fenced JSON /
  malformed / schema-fail / out-of-range confidence / missing fields
  / empty / whitespace.
- ``call_litellm``: stubbed opener returning a well-formed response →
  raw text; HTTP error / unexpected JSON shape / empty bytes → None.
- ``MotionGatedVlmRunner.tick``: first-call fires + caches, cache hit
  inside TTL, motion gate skips low-distance frames, high-distance
  frames refire after TTL, runner returning None → call-failed
  preserves cache, decode-failure → decode-failed, parse-failure →
  parse-failed.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


def _load_pi_edge_module():
    """Import ``pi-edge/vlm_classifier.py`` by file path.

    Pi-edge's flat namespace is rooted under ``~/hapax-edge/`` on each
    Pi at deploy time. The council test suite imports the file
    directly so the production path stays untouched.
    """
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "pi-edge" / "vlm_classifier.py"
    spec = importlib.util.spec_from_file_location("pi_edge_vlm_classifier", module_path)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load module spec at {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pi_edge_vlm_classifier"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def vlm_classifier():
    return _load_pi_edge_module()


def _solid_jpeg(brightness: int = 128, *, size: int = 64) -> bytes:
    from PIL import Image

    img = Image.new("L", (size, size), brightness)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _checkerboard_jpeg(*, size: int = 64) -> bytes:
    from PIL import Image

    img = Image.new("L", (size, size), 0)
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = 255 if (x + y) % 2 == 0 else 0
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _good_response_text(intent: str = "typing on keyboard") -> str:
    return json.dumps(
        {
            "intent": intent,
            "surface": "laptop keyboard",
            "hand_position": "centered",
            "confidence": 0.85,
        }
    )


# ── parse_vlm_response ───────────────────────────────────────────────────


class TestParseVlmResponse:
    def test_well_formed_json(self, vlm_classifier) -> None:
        out = vlm_classifier.parse_vlm_response(_good_response_text())
        assert out is not None
        assert out["intent"] == "typing on keyboard"
        assert out["confidence"] == 0.85

    def test_code_fence_stripped(self, vlm_classifier) -> None:
        raw = "```json\n" + _good_response_text("dj") + "\n```"
        out = vlm_classifier.parse_vlm_response(raw)
        assert out is not None
        assert out["intent"] == "dj"

    def test_malformed_returns_none(self, vlm_classifier) -> None:
        assert vlm_classifier.parse_vlm_response("not json") is None

    def test_array_root_returns_none(self, vlm_classifier) -> None:
        assert vlm_classifier.parse_vlm_response('["intent"]') is None

    def test_missing_field_returns_none(self, vlm_classifier) -> None:
        raw = json.dumps({"intent": "x", "surface": "y"})
        assert vlm_classifier.parse_vlm_response(raw) is None

    def test_out_of_range_confidence_returns_none(self, vlm_classifier) -> None:
        raw = json.dumps(
            {
                "intent": "x",
                "surface": "y",
                "hand_position": "z",
                "confidence": 1.5,
            }
        )
        assert vlm_classifier.parse_vlm_response(raw) is None

    @pytest.mark.parametrize("raw", ["", "   ", "\n\n", "```\n```"])
    def test_empty_or_fence_only_returns_none(self, vlm_classifier, raw: str) -> None:
        assert vlm_classifier.parse_vlm_response(raw) is None

    def test_whitespace_in_strings_stripped(self, vlm_classifier) -> None:
        raw = json.dumps(
            {
                "intent": "  typing  ",
                "surface": "  keyboard ",
                "hand_position": " centered ",
                "confidence": 0.9,
            }
        )
        out = vlm_classifier.parse_vlm_response(raw)
        assert out is not None
        assert out["intent"] == "typing"
        assert out["surface"] == "keyboard"


# ── call_litellm ─────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _opener_returning(payload: dict | bytes):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def opener(req, timeout=None):  # type: ignore[no-untyped-def]
        del req, timeout
        return _FakeResponse(body)

    return opener


def _opener_raising(exc: Exception):
    def opener(req, timeout=None):  # type: ignore[no-untyped-def]
        del req, timeout
        raise exc

    return opener


class TestCallLitellm:
    def test_returns_raw_text_on_well_formed(self, vlm_classifier) -> None:
        opener = _opener_returning({"choices": [{"message": {"content": _good_response_text()}}]})
        out = vlm_classifier.call_litellm(_solid_jpeg(), opener=opener)
        assert out is not None
        assert "typing" in out

    def test_returns_none_on_http_error(self, vlm_classifier) -> None:
        opener = _opener_raising(OSError("network down"))
        out = vlm_classifier.call_litellm(_solid_jpeg(), opener=opener)
        assert out is None

    def test_returns_none_on_unexpected_shape(self, vlm_classifier) -> None:
        opener = _opener_returning({"choices": []})
        out = vlm_classifier.call_litellm(_solid_jpeg(), opener=opener)
        assert out is None

    def test_returns_none_on_empty_bytes(self, vlm_classifier) -> None:
        called = {"n": 0}

        def opener(req, timeout=None):  # type: ignore[no-untyped-def]
            del req, timeout
            called["n"] += 1
            return _FakeResponse(b"")

        out = vlm_classifier.call_litellm(b"", opener=opener)
        assert out is None
        assert called["n"] == 0  # short-circuited before HTTP call


# ── MotionGatedVlmRunner ─────────────────────────────────────────────────


class TestMotionGatedVlmRunner:
    def test_first_call_fires_and_caches(self, vlm_classifier) -> None:
        called = {"n": 0}

        def runner(jpeg, *, model):  # type: ignore[no-untyped-def]
            del jpeg, model
            called["n"] += 1
            return _good_response_text()

        run = vlm_classifier.MotionGatedVlmRunner(runner=runner)
        result = run.tick(_solid_jpeg(), now=1000.0)
        assert called["n"] == 1
        assert result.reason == "call-made"
        assert result.semantics is not None
        assert run.cached is not None
        assert run.calls_made == 1

    def test_cache_hit_within_ttl(self, vlm_classifier) -> None:
        called = {"n": 0}

        def runner(jpeg, *, model):  # type: ignore[no-untyped-def]
            del jpeg, model
            called["n"] += 1
            return _good_response_text()

        run = vlm_classifier.MotionGatedVlmRunner(runner=runner, cache_ttl_s=10.0)
        run.tick(_solid_jpeg(), now=1000.0)
        result = run.tick(_checkerboard_jpeg(), now=1005.0)
        assert called["n"] == 1
        assert result.reason == "cache-hit"
        assert run.calls_skipped_cache == 1

    def test_motion_gate_skips_low_distance(self, vlm_classifier) -> None:
        called = {"n": 0}

        def runner(jpeg, *, model):  # type: ignore[no-untyped-def]
            del jpeg, model
            called["n"] += 1
            return _good_response_text()

        run = vlm_classifier.MotionGatedVlmRunner(runner=runner, cache_ttl_s=0.001)
        run.tick(_solid_jpeg(), now=1000.0)
        result = run.tick(_solid_jpeg(), now=1100.0)
        assert called["n"] == 1
        assert result.reason == "no-motion"
        assert run.calls_skipped_motion == 1

    def test_high_motion_refires_after_ttl(self, vlm_classifier) -> None:
        responses = [_good_response_text("typing"), _good_response_text("dj")]

        def runner(jpeg, *, model):  # type: ignore[no-untyped-def]
            del jpeg, model
            return responses.pop(0)

        run = vlm_classifier.MotionGatedVlmRunner(runner=runner, cache_ttl_s=0.001)
        run.tick(_solid_jpeg(0), now=1000.0)
        result = run.tick(_checkerboard_jpeg(), now=1100.0)
        assert result.reason == "call-made"
        assert result.semantics is not None
        assert result.semantics["intent"] == "dj"
        assert run.calls_made == 2

    def test_runner_none_counts_failure_preserves_cache(self, vlm_classifier) -> None:
        responses: list[str | None] = [_good_response_text(), None]

        def runner(jpeg, *, model):  # type: ignore[no-untyped-def]
            del jpeg, model
            return responses.pop(0)

        run = vlm_classifier.MotionGatedVlmRunner(runner=runner, cache_ttl_s=0.001)
        first = run.tick(_solid_jpeg(0), now=1000.0)
        second = run.tick(_checkerboard_jpeg(), now=1100.0)
        assert first.reason == "call-made"
        assert second.reason == "call-failed"
        assert second.semantics == first.semantics
        assert run.calls_failed == 1

    def test_decode_failure_counts_failure(self, vlm_classifier) -> None:
        def runner(jpeg, *, model):  # type: ignore[no-untyped-def]
            pytest.fail("runner must not be invoked when decode fails")

        run = vlm_classifier.MotionGatedVlmRunner(runner=runner)
        out = run.tick(b"this is not a jpeg", now=1000.0)
        assert out.reason == "decode-failed"
        assert run.calls_failed == 1

    def test_parse_failure_counts_failure(self, vlm_classifier) -> None:
        def runner(jpeg, *, model):  # type: ignore[no-untyped-def]
            del jpeg, model
            return "not json"

        run = vlm_classifier.MotionGatedVlmRunner(runner=runner)
        out = run.tick(_solid_jpeg(), now=1000.0)
        assert out.reason == "parse-failed"
        assert run.calls_failed == 1

    def test_no_frame_counts_failure(self, vlm_classifier) -> None:
        def runner(jpeg, *, model):  # type: ignore[no-untyped-def]
            pytest.fail("runner must not be invoked on empty bytes")

        run = vlm_classifier.MotionGatedVlmRunner(runner=runner)
        out = run.tick(b"", now=1000.0)
        assert out.reason == "no-frame"
        assert run.calls_failed == 1

    def test_validation_guards(self, vlm_classifier) -> None:
        with pytest.raises(ValueError):
            vlm_classifier.MotionGatedVlmRunner(runner=lambda *a, **k: None, motion_threshold=-1)
        with pytest.raises(ValueError):
            vlm_classifier.MotionGatedVlmRunner(runner=lambda *a, **k: None, cache_ttl_s=0)

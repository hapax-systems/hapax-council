"""Tests for ``shared.ir_vlm_classifier``.

Coverage:

- ``HandSemantics`` validation: requires non-empty strings, clamps
  confidence, rejects extras.
- ``build_vlm_messages``: emits the OpenAI-compat shape with the
  base64 image_url and the system prompt.
- ``parse_vlm_response``: well-formed JSON → HandSemantics; code-fenced
  JSON stripped and parsed; JSON arrays / decode-fail / schema-fail
  / empty / whitespace → None.
- ``classify_hand_via_vlm``: stub runner returns expected
  HandSemantics; runner returning None → None; runner raising → None;
  empty bytes → None without invoking runner.
"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from shared.ir_vlm_classifier import (
    VLM_SYSTEM_PROMPT,
    HandSemantics,
    build_vlm_messages,
    classify_hand_via_vlm,
    parse_vlm_response,
)

# ── HandSemantics ────────────────────────────────────────────────────────


class TestHandSemantics:
    def test_minimal_valid(self) -> None:
        s = HandSemantics(
            intent="typing on keyboard",
            surface="laptop keyboard",
            hand_position="centered",
            confidence=0.9,
        )
        assert s.intent == "typing on keyboard"

    @pytest.mark.parametrize(
        "field,bad",
        [
            ("intent", ""),
            ("surface", ""),
            ("hand_position", ""),
        ],
    )
    def test_rejects_empty_strings(self, field: str, bad: str) -> None:
        kwargs = dict(
            intent="ok",
            surface="ok",
            hand_position="ok",
            confidence=0.5,
        )
        kwargs[field] = bad
        with pytest.raises(ValidationError):
            HandSemantics(**kwargs)

    @pytest.mark.parametrize("bad_conf", [-0.01, 1.01, 2.0])
    def test_rejects_out_of_range_confidence(self, bad_conf: float) -> None:
        with pytest.raises(ValidationError):
            HandSemantics(
                intent="ok",
                surface="ok",
                hand_position="ok",
                confidence=bad_conf,
            )

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            HandSemantics(
                intent="ok",
                surface="ok",
                hand_position="ok",
                confidence=0.5,
                bogus="extra",  # type: ignore[call-arg]
            )


# ── build_vlm_messages ───────────────────────────────────────────────────


class TestBuildVlmMessages:
    def test_shape_is_openai_compat(self) -> None:
        msgs = build_vlm_messages(b"\xff\xd8\xff\xe0pretend-jpeg")
        assert isinstance(msgs, list)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": VLM_SYSTEM_PROMPT}
        assert msgs[1]["role"] == "user"
        content = msgs[1]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image_url"
        url = content[0]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        encoded = url.split(",", 1)[1]
        assert base64.b64decode(encoded.encode("ascii")) == b"\xff\xd8\xff\xe0pretend-jpeg"
        assert content[1]["type"] == "text"


# ── parse_vlm_response ───────────────────────────────────────────────────


class TestParseVlmResponse:
    def test_well_formed_json(self) -> None:
        raw = (
            '{"intent": "cueing a record on the turntable", '
            '"surface": "turntable platter", '
            '"hand_position": "right edge", '
            '"confidence": 0.86}'
        )
        result = parse_vlm_response(raw)
        assert result is not None
        assert result.intent == "cueing a record on the turntable"
        assert result.confidence == pytest.approx(0.86)

    def test_code_fence_stripped(self) -> None:
        raw = (
            "```json\n"
            '{"intent": "typing on keyboard", '
            '"surface": "laptop keyboard", '
            '"hand_position": "centered", '
            '"confidence": 0.9}\n'
            "```"
        )
        result = parse_vlm_response(raw)
        assert result is not None
        assert result.surface == "laptop keyboard"

    def test_bare_code_fence_no_json(self) -> None:
        assert parse_vlm_response("```\n```") is None

    def test_array_at_root(self) -> None:
        assert parse_vlm_response('["intent"]') is None

    def test_decode_failure(self) -> None:
        assert parse_vlm_response("not json") is None

    def test_schema_failure_missing_fields(self) -> None:
        assert parse_vlm_response('{"intent": "x"}') is None

    def test_schema_failure_bad_confidence(self) -> None:
        raw = '{"intent": "x", "surface": "y", "hand_position": "z", "confidence": 5.0}'
        assert parse_vlm_response(raw) is None

    @pytest.mark.parametrize("raw", ["", "   ", "\n\n"])
    def test_empty_or_whitespace(self, raw: str) -> None:
        assert parse_vlm_response(raw) is None


# ── classify_hand_via_vlm ────────────────────────────────────────────────


class TestClassifyHandViaVlm:
    def _good_runner(self, response: str):
        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            return response

        return runner

    def test_returns_hand_semantics_on_well_formed_response(self) -> None:
        runner = self._good_runner(
            '{"intent": "adjusting a knob", "surface": "synth panel", '
            '"hand_position": "right half", "confidence": 0.7}'
        )
        result = classify_hand_via_vlm(b"\xff\xd8\xff\xe0jpeg", runner=runner)
        assert result is not None
        assert result.intent == "adjusting a knob"

    def test_returns_none_on_runner_returning_none(self) -> None:
        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            return None

        result = classify_hand_via_vlm(b"\xff\xd8\xff\xe0jpeg", runner=runner)
        assert result is None

    def test_returns_none_on_runner_exception(self) -> None:
        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            raise RuntimeError("network error")

        result = classify_hand_via_vlm(b"\xff\xd8\xff\xe0jpeg", runner=runner)
        assert result is None

    def test_empty_bytes_short_circuits(self) -> None:
        invoked = {"n": 0}

        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages, model
            invoked["n"] += 1
            return "ignored"

        result = classify_hand_via_vlm(b"", runner=runner)
        assert result is None
        assert invoked["n"] == 0

    def test_passes_model_to_runner(self) -> None:
        seen: list[str] = []

        def runner(messages, *, model):  # type: ignore[no-untyped-def]
            del messages
            seen.append(model)
            return None

        classify_hand_via_vlm(b"\xff\xd8\xff\xe0jpeg", runner=runner, model="balanced")
        assert seen == ["balanced"]

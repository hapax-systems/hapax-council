"""Unit tests for the S2 topic+type composability gate (deterministic verdict + fail-open)."""

import json
import os
from unittest import mock

import pytest

from agents.hapax_daimonion.segment_composability_gate import _gate_max_tokens, assess_composability


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *_a: object) -> bool:
        return False


def _urlopen_returning(signals: dict) -> mock.Mock:
    body = json.dumps({"choices": [{"message": {"content": json.dumps(signals)}}]}).encode()
    return mock.Mock(return_value=_Resp(body))


def _urlopen_full(*, content: str, model: str, finish_reason: str) -> mock.Mock:
    """Mock a full gateway response carrying model + finish_reason (truncation/served-model tests)."""
    body = json.dumps(
        {
            "model": model,
            "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
        }
    ).encode()
    return mock.Mock(return_value=_Resp(body))


def test_gate_max_tokens_default_and_env_override() -> None:
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HAPAX_COMPOSABILITY_GATE_MAX_TOKENS", None)
        assert _gate_max_tokens() == 2048
    with mock.patch.dict(os.environ, {"HAPAX_COMPOSABILITY_GATE_MAX_TOKENS": "4096"}):
        assert _gate_max_tokens() == 4096
    with mock.patch.dict(os.environ, {"HAPAX_COMPOSABILITY_GATE_MAX_TOKENS": "garbage"}):
        assert _gate_max_tokens() == 2048
    with mock.patch.dict(os.environ, {"HAPAX_COMPOSABILITY_GATE_MAX_TOKENS": "10"}):
        assert _gate_max_tokens() == 256  # floored


def test_truncation_is_loud_not_silent() -> None:
    # A reasoning-model fallback burns the token budget on hidden CoT -> finish_reason=length + truncated
    # JSON. The gate must FAIL LOUD (errored + served model surfaced), NOT silently fail-open as a verdict.
    urlopen = _urlopen_full(
        content='{"arc_or_list":"ar', model="gemini-3.1-pro-preview", finish_reason="length"
    )
    with mock.patch("urllib.request.urlopen", urlopen):
        r = assess_composability("rant", "t", ["b1", "b2", "b3"])
    assert r.errored is True
    assert "truncat" in r.reason.lower()
    assert "gemini-3.1-pro-preview" in r.reason  # served model surfaced, not hidden
    assert r.signals.get("served_model") == "gemini-3.1-pro-preview"


def test_served_model_captured_on_valid_verdict() -> None:
    signals = {
        "opening_hook": "h",
        "test1_resolves_specific_hook": True,
        "test2_reorder_breaks_it": True,
        "arc_or_list": "arc",
        "score": 5,
    }
    urlopen = _urlopen_full(
        content=json.dumps(signals), model="claude-sonnet-4-6", finish_reason="stop"
    )
    with mock.patch("urllib.request.urlopen", urlopen):
        r = assess_composability("rant", "t", ["b1", "b2", "b3"])
    assert r.accept is True
    assert r.signals.get("served_model") == "claude-sonnet-4-6"


def test_accepts_building_arc() -> None:
    signals = {
        "arc_or_list": "arc",
        "test1_resolves_specific_hook": True,
        "test2_reorder_breaks_it": True,
        "score": 5,
        "opening_hook": "the paradox",
    }
    with mock.patch("urllib.request.urlopen", _urlopen_returning(signals)):
        r = assess_composability("rant", "a paradox topic", ["b1", "b2", "b3"])
    assert r.accept is True
    assert r.errored is False


def test_rejects_parallel_list() -> None:
    signals = {
        "arc_or_list": "parallel_list",
        "test1_resolves_specific_hook": False,
        "test2_reorder_breaks_it": False,
        "score": 4,
    }
    with mock.patch("urllib.request.urlopen", _urlopen_returning(signals)):
        r = assess_composability("tier_list", "a tier list of items", ["b1", "b2", "b3"])
    assert r.accept is False


def test_rejects_arc_that_does_not_resolve_or_reorder_invariant() -> None:
    signals = {
        "arc_or_list": "arc",
        "test1_resolves_specific_hook": False,
        "test2_reorder_breaks_it": True,
        "score": 4,
    }
    with mock.patch("urllib.request.urlopen", _urlopen_returning(signals)):
        r = assess_composability("rant", "t", ["b1", "b2"])
    assert r.accept is False


def test_fail_open_on_error() -> None:
    with mock.patch("urllib.request.urlopen", side_effect=OSError("network down")):
        r = assess_composability("rant", "t", ["b1", "b2"])
    assert r.accept is True
    assert r.errored is True


def test_empty_beats_defers_to_upstream_skip() -> None:
    r = assess_composability("rant", "t", [])
    assert r.accept is True


def test_incomplete_response_fails_open() -> None:
    # A 200-OK from a misrouted/weak model that returns valid JSON but OMITS the structural decision
    # fields must FAIL OPEN (accept, errored) — never mass-reject a batch on a bad gateway route.
    signals = {"opening_hook": "something", "score": 5}  # no arc_or_list / test1 / test2
    with mock.patch("urllib.request.urlopen", _urlopen_returning(signals)):
        r = assess_composability("rant", "t", ["b1", "b2"])
    assert r.accept is True
    assert r.errored is True


def test_killswitch_disables_gate_without_network() -> None:
    # HAPAX_COMPOSABILITY_GATE=off hard-disables the gate (accept, errored) and makes NO gateway call.
    urlopen = mock.Mock(side_effect=AssertionError("gate must not call the gateway when disabled"))
    with mock.patch.dict(os.environ, {"HAPAX_COMPOSABILITY_GATE": "off"}):
        with mock.patch("urllib.request.urlopen", urlopen):
            r = assess_composability("tier_list", "a tier list", ["b1", "b2", "b3"])
    assert r.accept is True
    assert r.errored is True
    urlopen.assert_not_called()


def test_string_false_signals_are_rejected_not_coerced_true() -> None:
    # JSON-schema drift: a model that returns the STRING "false" for the structural tests must NOT be
    # read as pass (bool("false") is True). An arc whose tests are string-"false" must REJECT.
    signals = {
        "arc_or_list": "arc",
        "test1_resolves_specific_hook": "false",
        "test2_reorder_breaks_it": "false",
        "score": 5,
        "opening_hook": "x",
    }
    with mock.patch("urllib.request.urlopen", _urlopen_returning(signals)):
        r = assess_composability("rant", "t", ["b1", "b2"])
    assert r.accept is False


def test_string_score_below_floor_rejects() -> None:
    # A numeric-string score below REJECT_BELOW is coerced and still rejects.
    signals = {
        "arc_or_list": "arc",
        "test1_resolves_specific_hook": True,
        "test2_reorder_breaks_it": True,
        "score": "2",
    }
    with mock.patch("urllib.request.urlopen", _urlopen_returning(signals)):
        r = assess_composability("rant", "t", ["b1", "b2"])
    assert r.accept is False


def test_missing_or_nonnumeric_score_does_not_reject_an_arc() -> None:
    # The score floor only TIGHTENS: a valid structural arc with score omitted (or non-numeric) still
    # accepts — the three structural signals are load-bearing, not the optional score.
    for score in ({}, {"score": "not-a-number"}):
        signals = {
            "arc_or_list": "arc",
            "test1_resolves_specific_hook": True,
            "test2_reorder_breaks_it": True,
            **score,
        }
        with mock.patch("urllib.request.urlopen", _urlopen_returning(signals)):
            r = assess_composability("rant", "t", ["b1", "b2"])
        assert r.accept is True, f"arc with score={score} should accept"


@pytest.mark.llm
def test_anchor_classification_live() -> None:
    """Reproduce the 2x2 anchor classification against the REAL gateway model (excluded from CI by the
    ``llm`` marker; run with ``-m llm``). Pins the load-bearing claim that the live predictor separates a
    building arc from a tier-list — the deterministic reducer is covered by the mocked tests above."""
    arc = assess_composability(
        "rant",
        "A launch that looked like a triumph was actually the failure that doomed the product",
        [
            "open on the triumphant launch everyone remembers",
            "reveal the single decision made that day that planted the failure",
            "trace how that decision compounded until it killed the product",
            "land on why the 'triumph' was the failure all along",
        ],
    )
    tier = assess_composability(
        "tier_list",
        "Ranking governance enforcement failures from least to most severe",
        [
            "the least severe failure category",
            "a moderately severe failure category",
            "another moderately severe category",
            "the most severe failure category",
        ],
    )
    # Fail-open means a gateway outage yields accept+errored on both; only assert discrimination when the
    # live gate actually ran (not errored).
    if not arc.errored and not tier.errored:
        assert arc.accept is True
        assert tier.accept is False

"""Unit tests for the S2 topic+type composability gate (deterministic verdict + fail-open)."""

import json
import os
from unittest import mock

import pytest

from agents.hapax_daimonion.segment_composability_gate import assess_composability


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
    # When explicitly run live (-m llm), the gateway MUST be reachable — a fail-open (errored) result is a
    # genuine failure of the live-predictor check, NOT a silent pass. Assert the gate actually ran, then
    # assert it discriminates arc from tier-list. (Previously guarded by `if not errored`, which let a
    # gateway outage pass green and never proved the live predictor — claude-1, PR #4143.)
    assert not arc.errored, f"live gate errored (fail-open) — gateway unreachable: {arc.reason}"
    assert not tier.errored, f"live gate errored (fail-open) — gateway unreachable: {tier.reason}"
    assert arc.accept is True, f"live gate failed to ACCEPT a building arc: {arc.reason}"
    assert tier.accept is False, f"live gate failed to REJECT a tier-list: {tier.reason}"

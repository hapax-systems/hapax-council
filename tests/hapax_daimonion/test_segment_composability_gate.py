"""Unit tests for the S2 topic+type composability gate (deterministic verdict + fail-open)."""

import json
import os
from unittest import mock

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

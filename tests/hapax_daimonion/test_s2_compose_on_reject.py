"""RED-1: S2 compose-on-reject reframe.

The resident grounding model frames topics expository ("a rant on the importance of X")
which the S2 gate correctly rejects as parallel_list. On a real reject, the producer
rewrites (topic, beats) into an arc with the capable eval model, RE-VERIFIED by the same
gate — only a gate-passing reframe is propagated, so an un-composable segment never airs.

These pin the new units: reframe_to_arc (parse + fail-quiet), _attempt_s2_reframe
(reframe -> re-verify -> ledger), and the env killswitch.
"""

import json
import os
from unittest import mock

from agents.hapax_daimonion import daily_segment_prep as prep
from agents.hapax_daimonion import segment_composability_gate as gate
from agents.hapax_daimonion.segment_composability_gate import (
    CompositionGateResult,
    reframe_to_arc,
)


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *_a: object) -> bool:
        return False


def _urlopen(*, content: str, finish_reason: str = "stop") -> mock.Mock:
    body = json.dumps(
        {"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}
    ).encode()
    return mock.Mock(return_value=_Resp(body))


_BEATS = ["highlight the importance of X", "emphasize the risk", "make the case"]
_ARC = {
    "topic": "X was treated as optional until src:0 showed it silently breaks the system",
    "beats": [
        "open on the specific claim that X is optional (src:0)",
        "trace the concrete failure that followed",
        "resolve: the receipt flips the claim",
    ],
}


# ── reframe_to_arc ───────────────────────────────────────────────────────────


def test_reframe_parses_topic_and_beats() -> None:
    with mock.patch("urllib.request.urlopen", _urlopen(content=json.dumps(_ARC))):
        result = reframe_to_arc("rant", "the importance of X", _BEATS)
    assert result is not None
    new_topic, new_beats = result
    assert new_topic == _ARC["topic"]
    assert new_beats == _ARC["beats"]


def test_reframe_none_on_network_error() -> None:
    with mock.patch("urllib.request.urlopen", side_effect=OSError("network down")):
        assert reframe_to_arc("rant", "topic", _BEATS) is None


def test_reframe_none_on_truncation() -> None:
    # finish_reason=length => a reasoning-model fallback burned the budget; a truncated reframe is useless.
    with mock.patch(
        "urllib.request.urlopen", _urlopen(content='{"topic":"x","be', finish_reason="length")
    ):
        assert reframe_to_arc("rant", "topic", _BEATS) is None


def test_reframe_none_on_missing_topic() -> None:
    with mock.patch(
        "urllib.request.urlopen", _urlopen(content=json.dumps({"beats": _ARC["beats"]}))
    ):
        assert reframe_to_arc("rant", "topic", _BEATS) is None


def test_reframe_none_on_non_list_beats() -> None:
    with mock.patch(
        "urllib.request.urlopen", _urlopen(content=json.dumps({"topic": "x", "beats": "nope"}))
    ):
        assert reframe_to_arc("rant", "topic", _BEATS) is None


def test_reframe_none_on_too_few_beats() -> None:
    with mock.patch(
        "urllib.request.urlopen",
        _urlopen(content=json.dumps({"topic": "x", "beats": ["only one"]})),
    ):
        assert reframe_to_arc("rant", "topic", _BEATS) is None


def test_reframe_none_on_empty_input_beats() -> None:
    # No call should be made when there are no beats to reframe.
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("must not call gateway")):
        assert reframe_to_arc("rant", "topic", []) is None


# ── _attempt_s2_reframe (reframe -> re-verify -> ledger) ─────────────────────


def test_attempt_reframe_returns_plan_when_recheck_accepts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        gate, "reframe_to_arc", lambda *a, **k: (_ARC["topic"], list(_ARC["beats"]))
    )
    monkeypatch.setattr(
        gate,
        "assess_composability",
        lambda *a, **k: CompositionGateResult(True, "composable building arc"),
    )
    ledger_calls: list[dict] = []
    monkeypatch.setattr(
        prep, "_append_s2_composability_ledger", lambda *a, **k: ledger_calls.append(k)
    )

    result = prep._attempt_s2_reframe(
        tmp_path,
        prep_session={},
        programme_id="prog-x",
        role="rant",
        topic="the importance of X",
        beats=_BEATS,
        reason="parallel_list",
        timeout=5.0,
    )
    assert result == (_ARC["topic"], _ARC["beats"])
    # The reframe outcome is logged as a second, labeled producer-DV entry.
    assert len(ledger_calls) == 1
    assert ledger_calls[0]["accepted"] is True
    assert ledger_calls[0]["topic"] == _ARC["topic"]
    assert ledger_calls[0]["reason"].startswith("[reframed]")


def test_attempt_reframe_none_when_recheck_rejects(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        gate, "reframe_to_arc", lambda *a, **k: (_ARC["topic"], list(_ARC["beats"]))
    )
    monkeypatch.setattr(
        gate,
        "assess_composability",
        lambda *a, **k: CompositionGateResult(False, "still parallel_list"),
    )
    monkeypatch.setattr(prep, "_append_s2_composability_ledger", lambda *a, **k: None)
    result = prep._attempt_s2_reframe(
        tmp_path,
        prep_session={},
        programme_id="p",
        role="rant",
        topic="t",
        beats=_BEATS,
        reason="parallel_list",
        timeout=5.0,
    )
    assert result is None


def test_attempt_reframe_none_when_recheck_errored(tmp_path, monkeypatch) -> None:
    # A degraded/unverified re-check must NOT air the reframe (it is not a real ACCEPT).
    monkeypatch.setattr(
        gate, "reframe_to_arc", lambda *a, **k: (_ARC["topic"], list(_ARC["beats"]))
    )
    monkeypatch.setattr(
        gate,
        "assess_composability",
        lambda *a, **k: CompositionGateResult(True, "fail-open", errored=True),
    )
    monkeypatch.setattr(prep, "_append_s2_composability_ledger", lambda *a, **k: None)
    result = prep._attempt_s2_reframe(
        tmp_path,
        prep_session={},
        programme_id="p",
        role="rant",
        topic="t",
        beats=_BEATS,
        reason="parallel_list",
        timeout=5.0,
    )
    assert result is None


def test_attempt_reframe_none_when_reframe_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "reframe_to_arc", lambda *a, **k: None)
    called = {"assess": False}

    def _assess(*_a, **_k):
        called["assess"] = True
        return CompositionGateResult(True, "x")

    monkeypatch.setattr(gate, "assess_composability", _assess)
    monkeypatch.setattr(prep, "_append_s2_composability_ledger", lambda *a, **k: None)
    result = prep._attempt_s2_reframe(
        tmp_path,
        prep_session={},
        programme_id="p",
        role="rant",
        topic="t",
        beats=_BEATS,
        reason="parallel_list",
        timeout=5.0,
    )
    assert result is None
    assert called["assess"] is False  # no re-check when there is nothing to verify


# ── provenance + killswitch ──────────────────────────────────────────────────


def test_record_provenance_tracks_programme() -> None:
    session: dict = {}
    prep._record_s2_reframe_provenance(session, "prog-a")
    prep._record_s2_reframe_provenance(session, "prog-a")  # idempotent
    prep._record_s2_reframe_provenance(session, "prog-b")
    assert session["s2_reframed_programmes"] == ["prog-a", "prog-b"]


def test_reframe_enabled_default_and_off() -> None:
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HAPAX_SEGMENT_PREP_S2_REFRAME", None)
        assert prep._s2_reframe_enabled() is True
    for off in ("0", "false", "no", "off"):
        with mock.patch.dict(os.environ, {"HAPAX_SEGMENT_PREP_S2_REFRAME": off}):
            assert prep._s2_reframe_enabled() is False

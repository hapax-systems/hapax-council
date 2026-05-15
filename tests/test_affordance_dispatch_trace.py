"""Dispatch-trace instrumentation tests (PR-A1).

The trace JSONL is the only artifact PR-A2's observation report consumes,
so the gates below are pinned: each early-return path tags ``dropout_at``
with a stable string, the survivor path stays ``None``, and the writer
never raises on disk failure (fail-open is the contract).
"""

from __future__ import annotations

import json
import time
from unittest import mock

from shared.affordance import SelectionCandidate
from shared.affordance_pipeline import (
    DISPATCH_TRACE_ENV,
    AffordancePipeline,
)
from shared.impingement import Impingement, ImpingementType


def _make_imp(**overrides) -> Impingement:
    base: dict = dict(
        timestamp=time.time(),
        source="dmn",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.5,
        content={"metric": "x"},
    )
    base.update(overrides)
    return Impingement(**base)


def _read_trace(tmp_path) -> list[dict]:
    path = tmp_path / "dispatch-trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _patch_trace_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "shared.affordance_pipeline.DISPATCH_TRACE_FILE",
        tmp_path / "dispatch-trace.jsonl",
    )
    monkeypatch.setenv(DISPATCH_TRACE_ENV, "1")


def _fallback_candidate(**payload) -> SelectionCandidate:
    base_payload = {
        "consent_required": False,
        "public_capable": False,
        "monetization_risk": "none",
        "content_risk": "tier_0_owned",
    }
    base_payload.update(payload)
    return SelectionCandidate(
        capability_name="fallback.capability",
        similarity=0.9,
        payload=base_payload,
    )


def test_disabled_env_writes_nothing(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    monkeypatch.setenv(DISPATCH_TRACE_ENV, "0")
    p = AffordancePipeline()
    p.select(_make_imp())
    assert _read_trace(tmp_path) == []


def test_inhibited_drops_at_inhibited(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    imp = _make_imp(content={"metric": "flow_drop"})
    p.add_inhibition(imp, duration_s=60.0)
    p.select(imp)
    rows = _read_trace(tmp_path)
    assert rows and rows[-1]["dropout_at"] == "inhibited"


def test_interrupt_handler_records_winner(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    p.register_interrupt("population_critical", "fortress_governance", "fortress")
    imp = _make_imp(
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        interrupt_token="population_critical",
    )
    p.select(imp)
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] is None
    assert row["winner"] == "fortress_governance"
    assert row["stages"]["interrupt_handlers"] == 1


def test_interrupt_no_handler_drops(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    imp = _make_imp(
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
        interrupt_token="unknown",
    )
    p.select(imp)
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] == "interrupt_no_handler"
    assert row["interrupt_token"] == "unknown"


def test_no_embedding_records_fallback_count(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    with mock.patch.object(p, "_get_embedding", return_value=None):
        p.select(_make_imp())
    row = _read_trace(tmp_path)[-1]
    # The bundled catalog has keyword matches for the default impingement,
    # so dropout_at stays None — but the stages dict must report the count.
    assert "fallback_keyword_match" in row["stages"]


def test_no_embedding_empty_fallback_drops(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    with (
        mock.patch.object(p, "_get_embedding", return_value=None),
        mock.patch.object(p, "_fallback_keyword_match", return_value=[]),
    ):
        p.select(_make_imp())
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] == "no_embedding_fallback"
    assert row["stages"]["fallback_keyword_match"] == 0


def test_no_embedding_fallback_consent_drop_records_gate(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    candidate = _fallback_candidate(consent_required=True)
    empty_registry = mock.MagicMock()
    empty_registry.__iter__ = lambda self: iter([])
    with (
        mock.patch.object(p, "_get_embedding", return_value=None),
        mock.patch.object(p, "_fallback_keyword_match", return_value=[candidate]),
        mock.patch("shared.governance.consent.load_contracts", return_value=empty_registry),
    ):
        p.select(_make_imp())
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] == "consent_filter_empty"
    assert row["stages"]["fallback_keyword_match"] == 1
    assert row["stages"]["after_consent"] == 0


def test_no_embedding_fallback_monetization_drop_records_gate(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    candidate = _fallback_candidate(monetization_risk="high")
    with (
        mock.patch.object(p, "_get_embedding", return_value=None),
        mock.patch.object(p, "_fallback_keyword_match", return_value=[candidate]),
        mock.patch.object(p, "_active_programme_cached", return_value=None),
        mock.patch("shared.governance.monetization_safety._AUDIT_ENABLED", False),
    ):
        p.select(_make_imp())
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] == "monetization_filter_empty"
    assert row["stages"]["fallback_keyword_match"] == 1
    assert row["stages"]["after_consent"] == 1
    assert row["stages"]["after_monetization"] == 0


def test_no_embedding_fallback_content_risk_drop_records_gate(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    candidate = _fallback_candidate(content_risk="tier_4_risky")
    with (
        mock.patch.object(p, "_get_embedding", return_value=None),
        mock.patch.object(p, "_fallback_keyword_match", return_value=[candidate]),
        mock.patch.object(p, "_active_programme_cached", return_value=None),
    ):
        p.select(_make_imp())
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] == "content_risk_filter_empty"
    assert row["stages"]["fallback_keyword_match"] == 1
    assert row["stages"]["after_monetization"] == 1
    assert row["stages"]["after_content_risk"] == 0


def test_family_filter_empty_drops(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    imp = _make_imp(intent_family="camera.hero")
    with (
        mock.patch.object(p, "_get_embedding", return_value=[0.0] * 384),
        mock.patch.object(p, "_retrieve_family", return_value=[]),
    ):
        p.select(imp)
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] == "retrieve_family_empty"
    assert row["intent_family"] == "camera.hero"
    assert row["stages"]["retrieve_family"] == 0


def test_global_retrieve_empty_drops(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()
    with (
        mock.patch.object(p, "_get_embedding", return_value=[0.0] * 384),
        mock.patch.object(p, "_retrieve", return_value=[]),
    ):
        p.select(_make_imp())
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] == "retrieve_global_empty"
    assert row["stages"]["retrieve_global"] == 0


def test_threshold_miss_records_top_score(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    # Lift THRESHOLD high enough that a weak candidate cannot pass even
    # with the optimistic Thompson prior. THRESHOLD is module-global so
    # monkeypatch.setattr scopes it to this test only.
    monkeypatch.setattr("shared.affordance_pipeline.THRESHOLD", 10.0)
    p = AffordancePipeline()
    weak = SelectionCandidate(
        capability_name="weak.cap",
        similarity=0.1,
        combined=0.0,
        payload={},
    )
    with (
        mock.patch.object(p, "_get_embedding", return_value=[0.0] * 384),
        mock.patch.object(p, "_retrieve", return_value=[weak]),
        mock.patch.object(p, "_consent_allows", return_value=True),
    ):
        p.select(_make_imp())
    row = _read_trace(tmp_path)[-1]
    assert row["dropout_at"] == "threshold_miss"
    assert row["top_capability"] == "weak.cap"
    assert "top_score" in row and row["top_score"] is not None
    assert "effective_threshold" in row["stages"]


def test_writer_failure_is_fail_open(monkeypatch, tmp_path):
    _patch_trace_file(monkeypatch, tmp_path)
    p = AffordancePipeline()

    def _boom(*_a, **_kw):
        raise OSError("disk full")

    with mock.patch("builtins.open", side_effect=_boom):
        # Must not raise — recruitment hot path is sacred.
        p.select(_make_imp())

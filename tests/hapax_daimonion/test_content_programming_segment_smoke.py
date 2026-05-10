"""Tests for the content-programming segment smoke.

Pins outcome 2 of the segment-observability master task:
programme-authoring quality flows into ``segments.jsonl`` after a prep
run writes loadable artifacts, resolves role assets, and validates a
content-programme run envelope.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from agents.hapax_daimonion.content_programming_segment_smoke import (
    PROGRAMME_AUTHORING_SEGMENT_ROLE,
    assess_content_programming_quality,
    run_content_programming_smoke,
)
from shared.content_programme_run_store import build_fixture_envelope
from shared.segment_observability import QualityRating, SegmentLifecycle

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "smoke-content-programming-segment.py"


@dataclass(frozen=True)
class _Assets:
    is_empty: bool = False


def _artifact(
    *,
    programme_id: str = "prog-smoke",
    role: str = "rant",
    contract_ok: bool = True,
    live_event_ok: bool = True,
    actionability_ok: bool = True,
) -> dict[str, Any]:
    return {
        "programme_id": programme_id,
        "role": role,
        "topic": "source-backed segment smoke",
        "segment_beats": ["state the claim", "show the source consequence"],
        "prepared_script": [
            "Zuboff's measurement claim matters because the source changes the visible frame.",
            "The consequence is bounded to the receipt and stays inspectable in the segment.",
        ],
        "actionability_alignment": {"ok": actionability_ok},
        "segment_prep_contract_report": {"ok": contract_ok},
        "segment_live_event_report": {"ok": live_event_ok},
        "source_hashes": {"source:smoke": "abc123"},
    }


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _load_script() -> ModuleType:
    name = "smoke_content_programming_segment_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_quality_excellent_when_full_pipeline_readback_passes(tmp_path: Path) -> None:
    result = assess_content_programming_quality(
        expected_programmes=1,
        saved_paths=(tmp_path / "prog-smoke.json",),
        loaded_artifacts=(_artifact(),),
        assets_by_programme={"prog-smoke": _Assets()},
        run_envelopes=(build_fixture_envelope("dry_run"),),
    )

    assert result.rating is QualityRating.EXCELLENT
    assert "artifacts_ok=1/1" in result.notes
    assert "assets_resolved=1/1" in result.notes
    assert "envelopes_ok=1/1" in result.notes


def test_quality_good_when_artifacts_and_envelopes_pass_but_assets_are_sparse(
    tmp_path: Path,
) -> None:
    result = assess_content_programming_quality(
        expected_programmes=1,
        saved_paths=(tmp_path / "prog-smoke.json",),
        loaded_artifacts=(_artifact(),),
        assets_by_programme={"prog-smoke": _Assets(is_empty=True)},
        run_envelopes=(build_fixture_envelope("dry_run"),),
    )

    assert result.rating is QualityRating.GOOD
    assert "assets_resolved=0/1" in result.notes


def test_quality_acceptable_when_loaded_artifact_missing_contract(tmp_path: Path) -> None:
    result = assess_content_programming_quality(
        expected_programmes=1,
        saved_paths=(tmp_path / "prog-smoke.json",),
        loaded_artifacts=(_artifact(contract_ok=False),),
        assets_by_programme={"prog-smoke": _Assets()},
        run_envelopes=(build_fixture_envelope("dry_run"),),
    )

    assert result.rating is QualityRating.ACCEPTABLE
    assert "artifacts_ok=0/1" in result.notes


def test_quality_poor_when_prep_saved_nothing() -> None:
    result = assess_content_programming_quality(
        expected_programmes=1,
        saved_paths=(),
        loaded_artifacts=(),
        assets_by_programme={},
        run_envelopes=(),
    )

    assert result.rating is QualityRating.POOR


def test_run_smoke_writes_started_and_happened_with_programme_authoring_quality(
    tmp_path: Path,
) -> None:
    segment_log = tmp_path / "segments.jsonl"
    artifact_path = tmp_path / "prep" / "2026-05-10" / "prog-smoke.json"

    def fake_run_prep(prep_dir: Path) -> list[Path]:
        assert prep_dir == tmp_path / "prep"
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text("{}", encoding="utf-8")
        return [artifact_path]

    def fake_load_prepped(prep_dir: Path, **kwargs: Any) -> list[dict[str, Any]]:
        assert prep_dir == tmp_path / "prep"
        assert kwargs == {"require_selected": False, "strict_release_contract": False}
        return [_artifact()]

    result = run_content_programming_smoke(
        prep_dir=tmp_path / "prep",
        expected_programmes=1,
        topic_seed="smoke-topic",
        log_path=segment_log,
        run_prep_fn=fake_run_prep,
        load_prepped_fn=fake_load_prepped,
        asset_resolver=lambda *_args, **_kwargs: _Assets(),
        envelope_builder=lambda _artifact: build_fixture_envelope("dry_run"),
    )

    assert result.assessment.rating is QualityRating.EXCELLENT
    events = _events(segment_log)
    assert len(events) == 2
    started, happened = events
    assert started["lifecycle"] == SegmentLifecycle.STARTED.value
    assert happened["lifecycle"] == SegmentLifecycle.HAPPENED.value
    assert started["segment_id"] == happened["segment_id"]
    assert happened["programme_role"] == PROGRAMME_AUTHORING_SEGMENT_ROLE
    assert happened["topic_seed"] == "smoke-topic"
    assert happened["quality"]["programme_authoring"] == QualityRating.EXCELLENT.value
    assert happened["quality"]["vocal"] == QualityRating.UNMEASURED.value


def test_run_smoke_records_didnt_happen_and_poor_when_prep_raises(tmp_path: Path) -> None:
    segment_log = tmp_path / "segments.jsonl"

    def failing_run_prep(_prep_dir: Path) -> list[Path]:
        raise RuntimeError("planner unavailable")

    with pytest.raises(RuntimeError, match="planner unavailable"):
        run_content_programming_smoke(
            prep_dir=tmp_path / "prep",
            log_path=segment_log,
            run_prep_fn=failing_run_prep,
            load_prepped_fn=lambda *_args, **_kwargs: [],
        )

    started, terminal = _events(segment_log)
    assert started["lifecycle"] == SegmentLifecycle.STARTED.value
    assert terminal["lifecycle"] == SegmentLifecycle.DIDNT_HAPPEN.value
    assert terminal["quality"]["programme_authoring"] == QualityRating.POOR.value
    assert "planner unavailable" in terminal["quality"]["notes"]


def test_cli_entrypoint_returns_success_for_good_or_better(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _load_script()
    assessment = SimpleNamespace(rating=QualityRating.GOOD, notes="ok")
    monkeypatch.setattr(
        script,
        "run_content_programming_smoke",
        lambda **_kwargs: SimpleNamespace(assessment=assessment),
    )

    assert script._cli_entrypoint(["--expected-programmes", "1"]) == 0


def test_cli_entrypoint_returns_failure_when_smoke_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script()

    def boom(**_kwargs: Any) -> None:
        raise RuntimeError("prep failed")

    monkeypatch.setattr(script, "run_content_programming_smoke", boom)

    assert script._cli_entrypoint([]) == 13

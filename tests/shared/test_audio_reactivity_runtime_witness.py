"""Tests for the audio reactivity runtime witness fixture harness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from shared.audio_reactivity_runtime_witness import (
    FAIL_CLOSED_POLICY,
    REQUIRED_RUNTIME_WITNESS_FIXTURE_CASES,
    AudioReactivityFailureClass,
    AudioReactivityRuntimeWitnessError,
    AudioReactivityStimulusKind,
    AudioReactivityWitnessState,
    calibrate_runtime_anti_visualizer_threshold,
    evaluate_runtime_witness,
    evaluate_runtime_witness_fixture_set,
    load_audio_reactivity_runtime_witness_fixtures,
    read_runtime_shape_probe,
    result_to_variance_ledger_record,
    result_to_wcs_record,
    write_runtime_witness_trace,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_AT = "2026-05-20T19:00:00Z"


def test_fixture_loader_covers_required_cases_stimuli_and_fail_closed_policy() -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()

    assert set(fixtures.required_fixture_cases) == REQUIRED_RUNTIME_WITNESS_FIXTURE_CASES
    assert set(fixtures.fixtures_by_case()) >= REQUIRED_RUNTIME_WITNESS_FIXTURE_CASES
    assert fixtures.fail_closed_policy == FAIL_CLOSED_POLICY
    assert {fixture.stimulus_kind for fixture in fixtures.fixtures} >= set(
        AudioReactivityStimulusKind
    )


def test_fixture_expected_results_match_evaluator() -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()

    for fixture in fixtures.fixtures:
        result = evaluate_runtime_witness(fixture, checked_at=CHECKED_AT)
        assert result.state is fixture.expected_state, fixture.fixture_case
        assert result.failure_class is fixture.expected_failure_class, fixture.fixture_case
        assert result.certifies_fixture_or_dry_run_only is True


@pytest.mark.parametrize(
    ("fixture_case", "failure_class", "reason"),
    [
        (
            "false_activity_process_liveness",
            AudioReactivityFailureClass.FALSE_PROCESS_ACTIVITY,
            "process_liveness_not_audio_evidence",
        ),
        (
            "stale_activity_music_marker",
            AudioReactivityFailureClass.STALE_AUDIO_EVIDENCE,
            "source_evidence_stale",
        ),
        (
            "wrong_source_youtube_react_audio",
            AudioReactivityFailureClass.WRONG_SOURCE_ROLE,
            "active_audio_source_role_does_not_match_visual_source",
        ),
        (
            "audible_programme_visual_source_silent",
            AudioReactivityFailureClass.VISUAL_SOURCE_SILENT,
            "audible_programme_path_but_visual_source_silent",
        ),
        (
            "silent_broadcast_egress",
            AudioReactivityFailureClass.BROADCAST_EGRESS_SILENT,
            "broadcast_egress_not_public_audible",
        ),
    ],
)
def test_required_negative_cases_fail_with_specific_reasons(
    fixture_case: str,
    failure_class: AudioReactivityFailureClass,
    reason: str,
) -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()
    result = evaluate_runtime_witness(fixtures.require_case(fixture_case), checked_at=CHECKED_AT)

    assert result.state in {
        AudioReactivityWitnessState.FAILED,
        AudioReactivityWitnessState.BLOCKED,
    }
    assert result.failure_class is failure_class
    assert reason in result.blocked_reasons
    assert result.public_claim_allowed is False


def test_legitimate_high_reactivity_records_visual_response_and_anti_visualizer_score() -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()
    result = evaluate_runtime_witness(
        fixtures.require_case("legitimate_high_reactivity_music"),
        checked_at=CHECKED_AT,
    )

    assert result.state is AudioReactivityWitnessState.PASSED
    assert result.selected_source_ids == ["music-bed"]
    assert result.egress_audible is True
    assert result.visual_response_present is True
    assert result.anti_visualizer_score == 0.31
    assert result.anti_visualizer_passed is True
    assert result.public_claim_allowed is True
    assert result.witness_refs == [
        "frame:egress:music-high-reactivity:001",
        "lane:reverie:music-high-reactivity:001",
    ]

    wcs_record = result_to_wcs_record(result)
    variance_record = result_to_variance_ledger_record(result)
    assert wcs_record["status"] == "passed"
    assert wcs_record["public_claim_allowed"] is True
    assert variance_record["anti_visualizer_score"] == 0.31
    assert variance_record["variance_ledger_refs"] == ["variance-ledger:music-high-reactivity:001"]


def test_visualizer_register_scene_is_blocked_even_with_valid_audio_and_egress() -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()
    result = evaluate_runtime_witness(
        fixtures.require_case("visualizer_register_blocked"),
        checked_at=CHECKED_AT,
    )

    assert result.state is AudioReactivityWitnessState.FAILED
    assert result.source_role_verified is True
    assert result.egress_audible is True
    assert result.failure_class is AudioReactivityFailureClass.VISUALIZER_REGISTER_EXCEEDED
    assert result.anti_visualizer_passed is False
    assert "anti_visualizer_score_exceeds_threshold" in result.blocked_reasons


def test_mixed_source_fixture_keeps_music_selected_without_rejecting_tts_presence() -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()
    result = evaluate_runtime_witness(
        fixtures.require_case("mixed_source_music_over_tts"),
        checked_at=CHECKED_AT,
    )

    assert result.state is AudioReactivityWitnessState.PASSED
    assert result.selected_source_ids == ["music-bed"]
    assert set(result.active_source_ids) == {"music-bed", "broadcast-tts"}
    assert {role.value for role in result.active_roles} == {"music", "tts"}


def test_trace_export_is_durable_and_auditable(tmp_path: Path) -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()
    results = evaluate_runtime_witness_fixture_set(
        fixtures,
        cases=[
            "legitimate_high_reactivity_music",
            "audible_programme_visual_source_silent",
        ],
        checked_at=CHECKED_AT,
    )
    trace_path = tmp_path / "audio-reactivity-runtime-witness.jsonl"

    write_runtime_witness_trace(
        results,
        path=trace_path,
        generated_at="2026-05-20T19:01:00Z",
    )

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [record["fixture_case"] for record in records] == [
        "legitimate_high_reactivity_music",
        "audible_programme_visual_source_silent",
    ]
    assert records[0]["wcs_record"]["status"] == "passed"
    assert records[0]["variance_ledger_record"]["anti_visualizer_score"] == 0.31
    assert records[1]["failure_class"] == "visual_source_silent"
    assert records[1]["result"]["certifies_fixture_or_dry_run_only"] is True


def test_anti_visualizer_calibration_smoke_writes_trace(tmp_path: Path) -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()
    out_path = tmp_path / "anti-visualizer-calibration.json"

    threshold = calibrate_runtime_anti_visualizer_threshold(fixtures, out_path=out_path)

    trace = json.loads(out_path.read_text(encoding="utf-8"))
    assert 0.0 < threshold < 1.0
    assert trace["threshold"] == threshold
    assert trace["negative_n"] >= 1
    assert trace["positive_n"] >= 1
    assert max(trace["negative_scores"]) < min(trace["positive_scores"])


def test_runtime_shape_probe_is_shape_only(tmp_path: Path) -> None:
    unified = tmp_path / "unified-reactivity.json"
    ledger = tmp_path / "audio-source-ledger.json"
    broadcast = tmp_path / "audio-safe-for-broadcast.json"
    unified.write_text(
        json.dumps(
            {
                "per_source": {"music": {"rms": 0.5}, "tts": {"rms": 0.2}},
                "active_sources": ["music", "tts"],
            }
        ),
        encoding="utf-8",
    )
    ledger.write_text(
        json.dumps(
            {
                "source_rows": [
                    {"source_id": "music-bed", "role": "music"},
                    {"source_id": "broadcast-tts", "role": "tts"},
                ]
            }
        ),
        encoding="utf-8",
    )
    broadcast.write_text(json.dumps({"safe": True}), encoding="utf-8")

    probe = read_runtime_shape_probe(
        checked_at=CHECKED_AT,
        unified_reactivity_path=unified,
        audio_source_ledger_path=ledger,
        broadcast_health_path=broadcast,
    )

    assert probe.certifies_shape_only is True
    assert probe.unified_reactivity_present is True
    assert probe.unified_per_source_keys == ["music", "tts"]
    assert probe.unified_active_sources == ["music", "tts"]
    assert probe.ledger_source_ids == ["music-bed", "broadcast-tts"]
    assert probe.ledger_roles == ["music", "tts"]
    assert probe.broadcast_safe is True


def test_missing_required_fixture_case_fails_closed(tmp_path: Path) -> None:
    fixtures = load_audio_reactivity_runtime_witness_fixtures()
    payload: dict[str, Any] = fixtures.model_dump(mode="json")
    payload["fixtures"] = [
        fixture
        for fixture in payload["fixtures"]
        if fixture["fixture_case"] != "audible_programme_visual_source_silent"
    ]
    path = tmp_path / "missing-audio-reactivity-runtime-witness-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        AudioReactivityRuntimeWitnessError,
        match="audible_programme_visual_source_silent",
    ):
        load_audio_reactivity_runtime_witness_fixtures(path)


def test_cli_dry_run_smoke_outputs_fixture_results() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "hapax-audio-reactivity-runtime-witness"),
            "--dry-run",
            "--case",
            "legitimate_high_reactivity_music",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert payload[0]["fixture_case"] == "legitimate_high_reactivity_music"
    assert payload[0]["state"] == "passed"
    assert payload[0]["visual_response_present"] is True
    assert payload[0]["anti_visualizer_score"] == 0.31

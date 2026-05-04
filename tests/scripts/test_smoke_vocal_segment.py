"""Tests for scripts/smoke-vocal-segment.py.

Pins the quality-mapping boundaries between POOR / ACCEPTABLE / GOOD /
EXCELLENT, the gate-failure DIDNT_HAPPEN path, and the segments.jsonl
roundtrip via the canonical ``HAPAX_SEGMENTS_LOG`` env override.

The smoke script imports from :mod:`shared.segment_observability`
(the keystone shipped by alpha in PR #2472), so these tests pass only
when that module is present on PYTHONPATH.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "smoke-vocal-segment.py"


def _load_module() -> ModuleType:
    name = "smoke_vocal_segment_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def smoke():
    return _load_module()


def _emission(strength: float = 0.6):
    """Synthetic Emission-like object the cadence harness emits."""
    return SimpleNamespace(
        timestamp=0.0,
        strength=strength,
        programme_role="ambient",
        stimmung_stance="ambient",
    )


def _make_report(
    *,
    emissions: tuple = (),
    epm: float = 0.0,
    silence: float = 600.0,
    p50: float | None = None,
    gates: tuple = (),
):
    """SimpleNamespace shaped like the verify-vocal-cadence CadenceReport."""
    return SimpleNamespace(
        window_start=0.0,
        window_end=600.0,
        window_s=600.0,
        gates=gates,
        emissions=emissions,
        emissions_per_min=epm,
        longest_silence_s=silence,
        pressure_p10=None,
        pressure_p50=p50,
        pressure_p90=None,
        in_slo=False,
    )


# --- Quality mapping boundaries --------------------------------------------


class TestAssessVocalQualityBoundaries:
    def test_silent_run_is_poor(self, smoke):
        report = _make_report(emissions=())
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.POOR
        assert "0 emissions" in result.note

    def test_long_silence_is_poor_even_when_emissions_present(self, smoke):
        report = _make_report(
            emissions=(_emission(),) * 5,
            epm=1.0,
            silence=400.0,  # > 300s ceil
            p50=0.5,
        )
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.POOR
        assert "longest silence" in result.note

    def test_low_pressure_is_poor(self, smoke):
        report = _make_report(
            emissions=(_emission(0.1),) * 5,
            epm=1.0,
            silence=60.0,
            p50=0.1,
        )
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.POOR
        assert "pressure p50" in result.note

    def test_edge_band_is_acceptable(self, smoke):
        # 0.4/min sits between EDGE_MIN (0.3) and SLO_MIN (0.6).
        report = _make_report(
            emissions=(_emission(),) * 4,
            epm=0.4,
            silence=80.0,
            p50=0.5,
        )
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.ACCEPTABLE

    def test_in_band_with_long_silence_is_acceptable(self, smoke):
        # 1.0/min in band, silence 100s in (90, 300].
        report = _make_report(
            emissions=(_emission(),) * 10,
            epm=1.0,
            silence=100.0,
            p50=0.5,
        )
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.ACCEPTABLE
        assert "longest silence" in result.note

    def test_far_out_of_band_is_poor(self, smoke):
        # 5/min — way over EDGE_MAX (3.5).
        report = _make_report(
            emissions=(_emission(),) * 50,
            epm=5.0,
            silence=10.0,
            p50=0.7,
        )
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.POOR
        assert "far outside" in result.note

    def test_in_band_short_silences_healthy_pressure_is_excellent(self, smoke):
        report = _make_report(
            emissions=(_emission(0.7),) * 10,
            epm=1.0,
            silence=60.0,
            p50=0.7,  # >= PRESSURE_HEALTHY_FLOOR
        )
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.EXCELLENT

    def test_in_band_no_pressure_is_good(self, smoke):
        report = _make_report(
            emissions=(_emission(0.4),) * 10,
            epm=1.0,
            silence=60.0,
            p50=0.4,  # > poor ceiling but < healthy floor
        )
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.GOOD

    def test_in_band_p50_none_falls_to_good(self, smoke):
        report = _make_report(
            emissions=(_emission(),) * 10,
            epm=1.0,
            silence=60.0,
            p50=None,
        )
        result = smoke.assess_vocal_quality(report)
        assert result.rating == smoke.QualityRating.GOOD


# --- Gate-failure handling --------------------------------------------------


class TestGateFailureNote:
    def test_no_gates_returns_none(self, smoke):
        assert smoke._gate_failure_note(_make_report()) is None

    def test_first_failing_gate_wins(self, smoke):
        from shared.segment_observability import (  # type: ignore[import-not-found]
            QualityRating,  # noqa: F401 — import smoke-test
        )

        gates = (
            SimpleNamespace(name="g1", ok=True, detail="ok"),
            SimpleNamespace(name="g2", ok=False, detail="oh no"),
            SimpleNamespace(name="g3", ok=False, detail="also broken"),
        )
        result = smoke._gate_failure_note(_make_report(gates=gates))
        assert result is not None
        assert "g2" in result and "oh no" in result


class TestResolveProgrammeRole:
    def test_returns_role_when_gate_passed(self, smoke):
        gates = (
            SimpleNamespace(
                name="programme_active",
                ok=True,
                detail="programme=prog-x role=work_block",
            ),
        )
        assert smoke._resolve_programme_role(_make_report(gates=gates)) == "work_block"

    def test_falls_back_when_gate_failed(self, smoke):
        gates = (
            SimpleNamespace(
                name="programme_active",
                ok=False,
                detail="no programme has status=ACTIVE",
            ),
        )
        assert (
            smoke._resolve_programme_role(_make_report(gates=gates))
            == smoke.DEFAULT_PROGRAMME_ROLE_FALLBACK
        )

    def test_falls_back_when_gate_absent(self, smoke):
        assert (
            smoke._resolve_programme_role(_make_report()) == smoke.DEFAULT_PROGRAMME_ROLE_FALLBACK
        )


# --- segments.jsonl roundtrip (integration) ---------------------------------


class TestJsonlRoundtrip:
    def test_happy_path_writes_started_and_happened(self, smoke, monkeypatch, tmp_path: Path):
        log = tmp_path / "segments.jsonl"
        monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(log))

        # Pre-register a mock verifier the script will load.
        gates = (
            SimpleNamespace(
                name="programme_active",
                ok=True,
                detail="programme=prog-y role=tutorial",
            ),
            SimpleNamespace(name="audio_safe", ok=True, detail="safe=True"),
            SimpleNamespace(name="bias_enabled", ok=True, detail="active"),
            SimpleNamespace(name="daimonion_running", ok=True, detail="active"),
        )
        report = _make_report(
            emissions=(_emission(0.7),) * 12,
            epm=1.2,
            silence=45.0,
            p50=0.65,
            gates=gates,
        )
        fake_verifier = SimpleNamespace(
            build_report=lambda **kw: report,
            DEFAULT_IMPINGEMENTS_PATH=Path("/dev/null"),
            DEFAULT_AUDIO_SAFE_PATH=Path("/dev/null"),
        )
        monkeypatch.setattr(smoke, "_load_verifier", lambda: fake_verifier)

        rc = smoke.main(["--skip-pre-checks", "--topic-seed", "smoke-test"])
        assert rc == 0

        lines = [json.loads(line) for line in log.read_text().splitlines()]
        assert len(lines) == 2

        started, happened = lines
        assert started["lifecycle"] == "started"
        assert happened["lifecycle"] == "happened"
        assert started["segment_id"] == happened["segment_id"]
        assert happened["programme_role"] == "tutorial"
        assert happened["topic_seed"] == "smoke-test"
        assert happened["quality"]["vocal"] == "excellent"
        # Other dimensions stay UNMEASURED.
        assert happened["quality"]["programme_authoring"] == "unmeasured"
        assert happened["quality"]["chat_response"] == "unmeasured"

    def test_gate_failure_writes_started_and_didnt_happen(self, smoke, monkeypatch, tmp_path: Path):
        log = tmp_path / "segments.jsonl"
        monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(log))

        gates = (
            SimpleNamespace(
                name="audio_safe",
                ok=False,
                detail="audio_safe=False status=unsafe",
            ),
        )
        report = _make_report(
            emissions=(_emission(),) * 5, epm=1.0, silence=60.0, p50=0.5, gates=gates
        )
        fake_verifier = SimpleNamespace(
            build_report=lambda **kw: report,
            DEFAULT_IMPINGEMENTS_PATH=Path("/dev/null"),
            DEFAULT_AUDIO_SAFE_PATH=Path("/dev/null"),
        )
        monkeypatch.setattr(smoke, "_load_verifier", lambda: fake_verifier)

        rc = smoke._cli_entrypoint(["--skip-pre-checks"])
        assert rc == 13

        lines = [json.loads(line) for line in log.read_text().splitlines()]
        assert len(lines) == 2
        started, terminal = lines
        assert started["lifecycle"] == "started"
        assert terminal["lifecycle"] == "didnt_happen"
        assert terminal["quality"]["vocal"] == "poor"
        assert "audio_safe" in terminal["quality"]["notes"]

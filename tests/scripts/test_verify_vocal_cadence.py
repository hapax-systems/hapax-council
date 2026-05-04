"""Tests for scripts/verify-vocal-cadence.py.

The harness samples narrative_drive emissions from the impingement bus,
runs four pre-check gates, and emits a structured report. These tests
load the script as a module (filename has a hyphen, so importlib is
required) and exercise the pure helpers + ``build_report`` against
synthetic bus content. The systemctl + filesystem state checks are
exercised in isolation per gate, since each gate's failure path drives
a distinct exit code the operator reads to know which upstream
component is wrong.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "verify-vocal-cadence.py"


def _load_module() -> ModuleType:
    name = "verify_vocal_cadence_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def vc():
    """The script module under test."""
    return _load_module()


def _write_bus(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def _emission(ts: float, *, strength: float = 0.5, role: str = "work_block") -> dict:
    """Synthetic narrative_drive impingement on the bus."""
    return {
        "id": f"id-{ts:.3f}",
        "timestamp": ts,
        "source": "endogenous.narrative_drive",
        "type": "endogenous",
        "strength": strength,
        "content": {
            "narrative": "synthetic",
            "programme_role": role,
            "stimmung_stance": "ambient",
        },
    }


# --- collect_emissions ------------------------------------------------------


class TestCollectEmissions:
    def test_missing_file_returns_empty(self, vc, tmp_path: Path):
        emissions = vc.collect_emissions(
            tmp_path / "missing.jsonl",
            window_start=0.0,
            window_end=time.time(),
        )
        assert emissions == ()

    def test_filters_to_endogenous_narrative_drive_only(self, vc, tmp_path: Path):
        bus = tmp_path / "impingements.jsonl"
        now = time.time()
        _write_bus(
            bus,
            [
                _emission(now - 100),
                {
                    "id": "x",
                    "timestamp": now - 50,
                    "source": "operator.microphone",
                    "type": "operator",
                    "strength": 0.9,
                    "content": {},
                },
                _emission(now - 30),
            ],
        )
        emissions = vc.collect_emissions(bus, window_start=now - 200, window_end=now + 1)
        assert len(emissions) == 2
        assert all(e.timestamp <= now for e in emissions)

    def test_clips_to_window(self, vc, tmp_path: Path):
        bus = tmp_path / "impingements.jsonl"
        now = time.time()
        _write_bus(
            bus,
            [
                _emission(now - 1000),  # outside window
                _emission(now - 100),  # inside
                _emission(now - 10),  # inside
                _emission(now + 100),  # outside (future)
            ],
        )
        emissions = vc.collect_emissions(bus, window_start=now - 200, window_end=now)
        assert len(emissions) == 2

    def test_skips_malformed_lines(self, vc, tmp_path: Path):
        bus = tmp_path / "impingements.jsonl"
        bus.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        with bus.open("w", encoding="utf-8") as fh:
            fh.write("not json\n")
            fh.write(json.dumps(_emission(now - 10)) + "\n")
            fh.write("\n")  # blank line
            fh.write("{partial json")  # incomplete
        emissions = vc.collect_emissions(bus, window_start=now - 60, window_end=now)
        assert len(emissions) == 1


# --- longest_silence + percentile -------------------------------------------


class TestLongestSilence:
    def test_no_emissions_is_full_window(self, vc):
        gap = vc.longest_silence([], window_start=0, window_end=600)
        assert gap == 600

    def test_single_emission_centered_returns_larger_edge(self, vc):
        emissions = (
            vc.Emission(timestamp=300, strength=0.5, programme_role=None, stimmung_stance=None),
        )
        gap = vc.longest_silence(emissions, window_start=0, window_end=600)
        assert gap == 300

    def test_clusters_compute_intra_gap(self, vc):
        emissions = tuple(
            vc.Emission(timestamp=t, strength=0.5, programme_role=None, stimmung_stance=None)
            for t in (10, 20, 30, 250)
        )
        # 0→10 = 10, 10→20 = 10, 20→30 = 10, 30→250 = 220, 250→300 = 50
        assert vc.longest_silence(emissions, window_start=0, window_end=300) == 220


class TestPercentile:
    def test_empty_returns_none(self, vc):
        assert vc.percentile([], 50) is None

    def test_single_value_collapses(self, vc):
        assert vc.percentile([0.42], 10) == 0.42
        assert vc.percentile([0.42], 90) == 0.42

    def test_typical_distribution(self, vc):
        values = list(range(1, 101))  # 1..100
        # statistics.quantiles n=100 returns 99 cutpoints; index 49 is ~p50
        assert 45 < vc.percentile(values, 50) < 55


# --- in_slo / SLO band ------------------------------------------------------


class TestSloBand:
    def test_in_slo_inclusive_lower(self, vc):
        assert vc.in_slo(vc.SLO_MIN_PER_MIN) is True

    def test_in_slo_inclusive_upper(self, vc):
        assert vc.in_slo(vc.SLO_MAX_PER_MIN) is True

    def test_out_of_slo_below(self, vc):
        assert vc.in_slo(0.0) is False

    def test_out_of_slo_above(self, vc):
        assert vc.in_slo(10.0) is False


# --- Pre-check gates --------------------------------------------------------


class TestBiasFlag:
    def test_unset_is_active(self, vc, monkeypatch):
        monkeypatch.delenv(vc.BIAS_ENV, raising=False)
        gate = vc.check_bias_flag()
        assert gate.ok is True

    def test_one_is_active(self, vc, monkeypatch):
        monkeypatch.setenv(vc.BIAS_ENV, "1")
        assert vc.check_bias_flag().ok is True

    def test_zero_disables(self, vc, monkeypatch):
        monkeypatch.setenv(vc.BIAS_ENV, "0")
        gate = vc.check_bias_flag()
        assert gate.ok is False
        assert gate.exit_code == vc.EXIT_BIAS_DISABLED


class TestProgrammeGate:
    def test_no_active_programme_blocks(self, vc, monkeypatch):
        with mock.patch(
            "shared.programme_store.default_store",
            return_value=mock.Mock(active_programme=lambda: None),
        ):
            gate = vc.check_programme_active()
        assert gate.ok is False
        assert gate.exit_code == vc.EXIT_NO_PROGRAMME

    def test_listening_role_blocks(self, vc):
        # listening is excluded from _BROADCAST_ELIGIBLE_ROLES — the
        # operator chose a receptive programme; broadcast voice is wrong.
        prog = mock.Mock(programme_id="prog-x")
        prog.role = mock.Mock(value="listening")
        with mock.patch(
            "shared.programme_store.default_store",
            return_value=mock.Mock(active_programme=lambda: prog),
        ):
            gate = vc.check_programme_active()
        assert gate.ok is False
        assert gate.exit_code == vc.EXIT_PROGRAMME_INELIGIBLE

    def test_work_block_role_passes(self, vc):
        prog = mock.Mock(programme_id="prog-y")
        prog.role = mock.Mock(value="work_block")
        with mock.patch(
            "shared.programme_store.default_store",
            return_value=mock.Mock(active_programme=lambda: prog),
        ):
            gate = vc.check_programme_active()
        assert gate.ok is True


class TestDaimonionGate:
    def test_missing_systemctl_is_tooling_error(self, vc):
        with mock.patch("shutil.which", return_value=None):
            gate = vc.check_daimonion_running()
        assert gate.ok is False
        assert gate.exit_code == vc.EXIT_TOOLING_ERROR

    def test_inactive_unit_blocks(self, vc):
        with (
            mock.patch("shutil.which", return_value="/usr/bin/systemctl"),
            mock.patch(
                "subprocess.run",
                return_value=mock.Mock(returncode=3, stdout="inactive\n"),
            ),
        ):
            gate = vc.check_daimonion_running()
        assert gate.ok is False
        assert gate.exit_code == vc.EXIT_NO_DAIMONION


# --- build_report + select_exit_code ----------------------------------------


class TestBuildReport:
    def test_skip_pre_checks_yields_empty_gates(self, vc, tmp_path: Path):
        bus = tmp_path / "impingements.jsonl"
        bus.parent.mkdir(parents=True, exist_ok=True)
        bus.touch()
        report = vc.build_report(
            window_s=60,
            impingements_path=bus,
            audio_safe_path=tmp_path / "audio.json",
            skip_pre_checks=True,
        )
        assert report.gates == ()

    def test_report_counts_emissions_per_minute(self, vc, tmp_path: Path):
        bus = tmp_path / "impingements.jsonl"
        now = time.time()
        # 6 emissions over the past 120 s → 3/min
        _write_bus(bus, [_emission(now - 100 + 20 * i) for i in range(6)])
        report = vc.build_report(
            window_s=120,
            impingements_path=bus,
            audio_safe_path=tmp_path / "audio.json",
            skip_pre_checks=True,
        )
        assert len(report.emissions) == 6
        assert report.emissions_per_min == pytest.approx(3.0, rel=0.01)


class TestSelectExitCode:
    def _report(self, vc, *, gates=(), emissions=(), epm=0.0):
        return vc.CadenceReport(
            window_start=0,
            window_end=600,
            window_s=600,
            gates=gates,
            emissions=emissions,
            longest_silence_s=600,
            emissions_per_min=epm,
            pressure_p10=None,
            pressure_p50=None,
            pressure_p90=None,
            in_slo=vc.in_slo(epm),
        )

    def test_first_failing_gate_wins(self, vc):
        gates = (
            vc.GateStatus(name="g1", ok=True, detail=""),
            vc.GateStatus(name="g2", ok=False, detail="x", exit_code=vc.EXIT_AUDIO_UNSAFE),
            vc.GateStatus(name="g3", ok=False, detail="y", exit_code=vc.EXIT_BIAS_DISABLED),
        )
        report = self._report(vc, gates=gates)
        assert vc.select_exit_code(report) == vc.EXIT_AUDIO_UNSAFE

    def test_silent_when_no_emissions(self, vc):
        report = self._report(vc)
        assert vc.select_exit_code(report) == vc.EXIT_SILENT

    def test_out_of_band_when_emissions_below_slo(self, vc):
        e = vc.Emission(timestamp=10, strength=0.5, programme_role=None, stimmung_stance=None)
        report = self._report(vc, emissions=(e,), epm=0.1)
        assert vc.select_exit_code(report) == vc.EXIT_OUT_OF_BAND

    def test_ok_when_in_slo(self, vc):
        e = vc.Emission(timestamp=10, strength=0.5, programme_role=None, stimmung_stance=None)
        report = self._report(vc, emissions=(e,), epm=1.0)
        assert vc.select_exit_code(report) == vc.EXIT_OK


# --- Output rendering -------------------------------------------------------


class TestRendering:
    def test_to_json_round_trip(self, vc, tmp_path: Path):
        bus = tmp_path / "impingements.jsonl"
        bus.touch()
        report = vc.build_report(
            window_s=60,
            impingements_path=bus,
            audio_safe_path=tmp_path / "audio.json",
            skip_pre_checks=True,
        )
        payload = report.to_json()
        # Must be JSON-serializable end-to-end (no datetime, no Path)
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        assert decoded["emissions_count"] == 0
        assert decoded["in_slo"] is False

    def test_text_includes_slo_band(self, vc, tmp_path: Path):
        bus = tmp_path / "impingements.jsonl"
        bus.touch()
        report = vc.build_report(
            window_s=60,
            impingements_path=bus,
            audio_safe_path=tmp_path / "audio.json",
            skip_pre_checks=True,
        )
        text = vc.render_text(report)
        assert "SLO band" in text
        assert "longest silence" in text

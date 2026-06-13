"""DASEIN cognitive-core re-rooting regression pins.

These tests pin the severed-edge fixes from the 2026-06-13 cognitive-core
audit so they cannot silently regress:

1. ``_read_stimmung`` parses the LIVE top-level dim schema and does NOT capture
   bare top-level scalars (e.g. ``timestamp``) or ``overall_stance`` as fake
   dimensions (the spurious-key class).
2. The DMN/reverie perception reader points at the canonical
   ``~/.cache/hapax-daimonion/perception-state.json`` (not an absent /dev/shm).
3. The DMN aperture-snapshot loop path writes on the throttle, updates its
   clock, and swallows writer errors (write_aperture_snapshot had zero callers).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from agents.dmn.__main__ import APERTURE_SNAPSHOT_INTERVAL_S, DMNDaemon


class TestReadStimmung:
    """shared.perceptual_field._read_stimmung — live schema + spurious-key guard."""

    def _write_state(self, tmp_path: Path) -> Path:
        state = {
            "health": {"value": 0.16, "trend": "stable", "freshness_s": 5, "sigma": 0.1, "n": 3},
            "exploration_deficit": {"value": 0.54, "trend": "rising", "freshness_s": 5},
            "overall_stance": "seeking",  # str — must NOT become a dim
            "timestamp": 1765600000.123,  # bare scalar — must NOT become a dim
        }
        p = tmp_path / "state.json"
        p.write_text(json.dumps(state), encoding="utf-8")
        return p

    def test_parses_dict_dims_via_value_subkey(self, tmp_path, monkeypatch):
        import shared.perceptual_field as pf

        monkeypatch.setattr(pf, "_STIMMUNG_STATE", self._write_state(tmp_path))
        dims, stance = pf._read_stimmung()
        assert dims["health"] == 0.16
        assert dims["exploration_deficit"] == 0.54
        assert stance == "seeking"

    def test_bare_scalar_not_captured_as_dim(self, tmp_path, monkeypatch):
        """A top-level numeric scalar (timestamp) must not pollute the dims."""
        import shared.perceptual_field as pf

        monkeypatch.setattr(pf, "_STIMMUNG_STATE", self._write_state(tmp_path))
        dims, _ = pf._read_stimmung()
        assert "timestamp" not in dims

    def test_stance_str_not_captured_as_dim(self, tmp_path, monkeypatch):
        import shared.perceptual_field as pf

        monkeypatch.setattr(pf, "_STIMMUNG_STATE", self._write_state(tmp_path))
        dims, _ = pf._read_stimmung()
        assert "overall_stance" not in dims

    def test_missing_file_is_empty_not_crash(self, tmp_path, monkeypatch):
        import shared.perceptual_field as pf

        monkeypatch.setattr(pf, "_STIMMUNG_STATE", tmp_path / "absent.json")
        dims, stance = pf._read_stimmung()
        assert dims == {}
        assert stance is None

    def test_malformed_value_skipped(self, tmp_path, monkeypatch):
        import shared.perceptual_field as pf

        p = tmp_path / "state.json"
        p.write_text(
            json.dumps({"health": {"value": "not-a-number"}, "ok": {"value": 0.3}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(pf, "_STIMMUNG_STATE", p)
        dims, _ = pf._read_stimmung()
        assert "health" not in dims  # unparseable value dropped, no crash
        assert dims["ok"] == 0.3


class TestPerceptionPathReRoot:
    """Grounding re-root: perception reader must use the canonical ~/.cache path."""

    _CANONICAL = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"

    def test_dmn_sensor_uses_canonical_path(self):
        from agents.dmn.sensor import SensorConfig

        assert SensorConfig().voice_perception == self._CANONICAL

    @pytest.mark.parametrize("energy", [0.0, 0.25, 0.5, 0.75, 1.0, 1.5])
    def test_reverie_waveform_reads_canonical_path_without_indexerror(
        self, energy, tmp_path, monkeypatch
    ):
        """Exercise resolve_waveform_viz against the canonical ~/.cache perception
        file across the full live-energy range. Pins both the path re-root AND the
        viz off-by-one (energy>=1.0 previously indexed viz[8] -> IndexError -> the
        whole waveform silently failed even on valid live energy)."""
        import agents.reverie._content_resolvers as cr

        perc_dir = tmp_path / ".cache" / "hapax-daimonion"
        perc_dir.mkdir(parents=True)
        (perc_dir / "perception-state.json").write_text(json.dumps({"audio_energy_rms": energy}))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # don't touch the real sources protocol; assert the resolver got that far
        monkeypatch.setattr(cr, "_inject_recalled_text", lambda *a, **k: True)
        assert cr.resolve_waveform_viz("narrative", 0.8) is True


class TestApertureLoopPath:
    """DMN aperture-snapshot loop path — throttle, clock update, error swallow."""

    def _daemon(self, last: float) -> DMNDaemon:
        d = DMNDaemon.__new__(DMNDaemon)  # bypass heavy __init__
        d._last_aperture_s = last
        return d

    def test_skips_when_not_due(self):
        d = self._daemon(last=100.0)
        with mock.patch("shared.aperture_state.write_aperture_snapshot") as w:
            wrote = d._maybe_write_aperture(now_m=100.0 + APERTURE_SNAPSHOT_INTERVAL_S - 0.1)
        assert wrote is False
        w.assert_not_called()
        assert d._last_aperture_s == 100.0  # clock unchanged

    def test_writes_when_due_and_advances_clock(self):
        d = self._daemon(last=100.0)
        due = 100.0 + APERTURE_SNAPSHOT_INTERVAL_S
        with mock.patch("shared.aperture_state.write_aperture_snapshot") as w:
            wrote = d._maybe_write_aperture(now_m=due)
        assert wrote is True
        w.assert_called_once()
        assert d._last_aperture_s == due

    def test_writer_error_is_swallowed(self):
        d = self._daemon(last=0.0)
        with mock.patch(
            "shared.aperture_state.write_aperture_snapshot", side_effect=OSError("boom")
        ):
            wrote = d._maybe_write_aperture(now_m=1000.0)
        assert wrote is False  # error swallowed, loop continues

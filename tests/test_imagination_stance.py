"""Pin the imagination daemon's stimmung-stance reader (#4119 re-root).

`_read_stimmung_stance` was fixed to read the live ``overall_stance`` key (it
had read an absent ``stance`` key, so cadence modulation never saw the mood).
"""

from __future__ import annotations

import json

import agents.imagination_daemon.__main__ as imag


class TestReadStimmungStance:
    def test_reads_overall_stance(self, tmp_path, monkeypatch):
        p = tmp_path / "stimmung.json"
        p.write_text(json.dumps({"overall_stance": "seeking", "timestamp": 1.0}))
        monkeypatch.setattr(imag, "STIMMUNG_PATH", p)
        assert imag._read_stimmung_stance() == "seeking"

    def test_severity_stance_passes_through(self, tmp_path, monkeypatch):
        # imagination uses the raw stimmung vocabulary for cadence (no router map)
        p = tmp_path / "stimmung.json"
        p.write_text(json.dumps({"overall_stance": "critical"}))
        monkeypatch.setattr(imag, "STIMMUNG_PATH", p)
        assert imag._read_stimmung_stance() == "critical"

    def test_missing_key_defaults_nominal(self, tmp_path, monkeypatch):
        p = tmp_path / "stimmung.json"
        p.write_text(json.dumps({"timestamp": 1.0}))
        monkeypatch.setattr(imag, "STIMMUNG_PATH", p)
        assert imag._read_stimmung_stance() == "nominal"

    def test_missing_file_defaults_nominal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(imag, "STIMMUNG_PATH", tmp_path / "absent.json")
        assert imag._read_stimmung_stance() == "nominal"

    def test_malformed_json_defaults_nominal(self, tmp_path, monkeypatch):
        p = tmp_path / "stimmung.json"
        p.write_text("{ not valid json")
        monkeypatch.setattr(imag, "STIMMUNG_PATH", p)
        assert imag._read_stimmung_stance() == "nominal"

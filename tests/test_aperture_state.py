"""Tests for shared.aperture_state — unified aperture snapshot."""

from __future__ import annotations

import json
import time
from pathlib import Path

from shared.aperture_state import (
    read_aperture_state_block,
    write_aperture_snapshot,
)


def _write_health(tmp_path: Path, component: str, error: float = 0.1) -> Path:
    d = tmp_path / f"hapax-{component}"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "health.json"
    p.write_text(
        json.dumps(
            {
                "component": component,
                "reference": 0.5,
                "perception": 0.5 + error,
                "error": error,
                "timestamp": time.time(),
            }
        )
    )
    return p


def _make_sources(tmp_path: Path) -> dict[str, dict[str, Path]]:
    _write_health(tmp_path, "stimmung", 0.07)
    state_dir = tmp_path / "hapax-stimmung"
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps({"overall_stance": "nominal", "timestamp": time.time()}))

    _write_health(tmp_path, "compositor", 0.02)
    seg_dir = tmp_path / "hapax-compositor"
    seg_file = seg_dir / "active-segment.json"
    seg_file.write_text(
        json.dumps({"role": "rant", "topic": "Music production", "beat_progress": 0.5})
    )

    _write_health(tmp_path, "voice_daemon", 0.15)
    con_dir = tmp_path / "hapax-daimonion"
    con_dir.mkdir(parents=True, exist_ok=True)
    con_file = con_dir / "consent-state.json"
    con_file.write_text(json.dumps({"phase": "no_guest", "timestamp": time.time()}))

    _write_health(tmp_path, "imagination", 0.05)
    img_dir = tmp_path / "hapax-imagination"
    cur_file = img_dir / "current.json"
    cur_file.write_text(
        json.dumps({"narrative": "abstract flow", "salience": 0.8, "timestamp": time.time()})
    )

    return {
        "stimmung": {
            "health": tmp_path / "hapax-stimmung" / "health.json",
            "state": state_file,
        },
        "compositor": {
            "health": tmp_path / "hapax-compositor" / "health.json",
            "segment": seg_file,
        },
        "daimonion": {
            "health": tmp_path / "hapax-voice_daemon" / "health.json",
            "consent": con_file,
        },
        "imagination": {
            "health": tmp_path / "hapax-imagination" / "health.json",
            "current": cur_file,
        },
    }


class TestWriteApertureSnapshot:
    def test_writes_snapshot(self, tmp_path: Path) -> None:
        sources = _make_sources(tmp_path)
        out = tmp_path / "snapshot.json"
        result = write_aperture_snapshot(sources=sources, path=out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert "apertures" in data
        assert "stimmung" in data["apertures"]
        assert "compositor" in data["apertures"]
        assert "daimonion" in data["apertures"]
        assert "imagination" in data["apertures"]
        assert result == data

    def test_stimmung_stance(self, tmp_path: Path) -> None:
        sources = _make_sources(tmp_path)
        out = tmp_path / "snapshot.json"
        result = write_aperture_snapshot(sources=sources, path=out)
        assert result["apertures"]["stimmung"]["stance"] == "nominal"

    def test_compositor_segment(self, tmp_path: Path) -> None:
        sources = _make_sources(tmp_path)
        out = tmp_path / "snapshot.json"
        result = write_aperture_snapshot(sources=sources, path=out)
        assert result["apertures"]["compositor"]["role"] == "rant"
        assert result["apertures"]["compositor"]["topic"] == "Music production"

    def test_consent_phase(self, tmp_path: Path) -> None:
        sources = _make_sources(tmp_path)
        out = tmp_path / "snapshot.json"
        result = write_aperture_snapshot(sources=sources, path=out)
        assert result["apertures"]["daimonion"]["phase"] == "no_guest"

    def test_imagination_narrative(self, tmp_path: Path) -> None:
        sources = _make_sources(tmp_path)
        out = tmp_path / "snapshot.json"
        result = write_aperture_snapshot(sources=sources, path=out)
        assert result["apertures"]["imagination"]["narrative"] == "abstract flow"
        assert result["apertures"]["imagination"]["salience"] == 0.8

    def test_missing_files_handled(self, tmp_path: Path) -> None:
        sources = {
            "missing_component": {
                "health": tmp_path / "nonexistent" / "health.json",
            }
        }
        out = tmp_path / "snapshot.json"
        result = write_aperture_snapshot(sources=sources, path=out)
        entry = result["apertures"]["missing_component"]
        assert entry["error"] is None
        assert entry["stale"] is True

    def test_stale_health_marked(self, tmp_path: Path) -> None:
        d = tmp_path / "hapax-old"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "health.json"
        p.write_text(
            json.dumps(
                {
                    "component": "old",
                    "error": 0.1,
                    "timestamp": time.time() - 300,
                }
            )
        )
        sources = {"old": {"health": p}}
        out = tmp_path / "snapshot.json"
        result = write_aperture_snapshot(sources=sources, path=out)
        assert result["apertures"]["old"]["stale"] is True


class TestReadApertureStateBlock:
    def test_fresh_snapshot_returns_content(self, tmp_path: Path) -> None:
        sources = _make_sources(tmp_path)
        out = tmp_path / "snapshot.json"
        write_aperture_snapshot(sources=sources, path=out)
        block = read_aperture_state_block(path=out)
        assert "System apertures" in block
        assert "stimmung" in block
        assert "compositor" in block

    def test_stale_snapshot_returns_empty(self, tmp_path: Path) -> None:
        sources = _make_sources(tmp_path)
        out = tmp_path / "snapshot.json"
        write_aperture_snapshot(sources=sources, path=out)
        data = json.loads(out.read_text())
        data["timestamp"] = time.time() - 60
        out.write_text(json.dumps(data))
        block = read_aperture_state_block(path=out)
        assert block == ""

    def test_missing_snapshot_returns_empty(self, tmp_path: Path) -> None:
        block = read_aperture_state_block(path=tmp_path / "nope.json")
        assert block == ""

    def test_natural_language_output(self, tmp_path: Path) -> None:
        sources = _make_sources(tmp_path)
        out = tmp_path / "snapshot.json"
        write_aperture_snapshot(sources=sources, path=out)
        block = read_aperture_state_block(path=out)
        assert "nominal" in block or "stance" in block
        assert "rant" in block
        assert "no_guest" in block
        assert "abstract flow" in block

    def test_all_stale_apertures_returns_empty(self, tmp_path: Path) -> None:
        out = tmp_path / "snapshot.json"
        snapshot = {
            "timestamp": time.time(),
            "apertures": {"dead": {"component": "dead", "error": None, "stale": True}},
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snapshot))
        block = read_aperture_state_block(path=out)
        assert block == ""

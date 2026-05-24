from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "darkplaces-state-export.py"
BRIDGE = REPO_ROOT / "scripts" / "darkplaces-state-bridge.sh"


def _load_exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("darkplaces_state_export", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_darkplaces_state_export_writes_csqc_ward_text_files(tmp_path: Path) -> None:
    exporter = _load_exporter()
    game_dir = tmp_path / "game" / "data"
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()
    mode_file = tmp_path / "working-mode"
    uniforms_file = tmp_path / "uniforms.json"
    mode_file.write_text("rnd\n", encoding="utf-8")
    (shm_dir / "stimmung-energy.txt").write_text("0.62\n", encoding="utf-8")
    (shm_dir / "voice-active.txt").write_text("1\n", encoding="utf-8")
    _write_json(
        uniforms_file,
        {
            "content.salience": 0.31,
            "fb.trace_strength": 0.22,
            "content.intensity": 0.42,
            "signal.ward_fx_temporal_boost": 0.18,
            "signal.ward_fx_spectral_boost": 0.14,
            "post.vignette_strength": 0.19,
            "signal.color_warmth": 0.16,
            "slot1_3_emboss.strength": 0.12,
            "slot3_1_invert.strength": 0.21,
            "slot3_2_grain_bump.strength": 0.37,
            "slot4_1_colorgrade.sepia": 0.23,
        },
    )

    _write_json(
        shm_dir / "active-segment.json",
        {
            "role": "rant",
            "topic": "Rant on the importance of rigorous governance in AI agent development",
            "current_beat_index": 1,
            "total_beats": 4,
            "beat_progress": 0.5,
            "current_beat_text": "Escalate the argument with concrete evidence and explicit failure predicates.",
            "source_refs": [
                "rag:governance_importance",
                "profile-facts:evidence_based_decision_making",
                "profile-facts:vague_language_risks",
            ],
        },
    )
    _write_json(
        shm_dir / "active_wards.json",
        {"ward_ids": ["programme_banner", "segment_content", "pressure_gauge"]},
    )
    _write_json(shm_dir / "voice-state.json", {"operator_speech_active": True})
    _write_json(
        shm_dir / "album-state.json",
        {"artist": "Radiohead", "title": "Pablo Honey"},
    )
    _write_json(
        shm_dir / "token-ledger.json",
        {"total_tokens": 14056358, "active_viewers": 1},
    )
    _write_json(
        shm_dir / "unified-reactivity.json",
        {"blended": {"rms": 0.12, "onset": 0.34}},
    )

    exporter.export_state(game_dir, shm_dir, mode_file, uniforms_file)

    assert (game_dir / "working-mode.txt").read_text(encoding="utf-8").strip() == "rnd"
    assert (game_dir / "ward-01.txt").read_text(encoding="utf-8").strip() == "14056K TOK / 1 VIEW"
    assert (game_dir / "ward-02.txt").read_text(
        encoding="utf-8"
    ).strip() == "Radiohead / Pablo Honey"
    assert (game_dir / "ward-12.txt").read_text(encoding="utf-8").strip() == "VOICE ON / 36 WARDS"
    assert "BEAT 050%" in (game_dir / "ward-13.txt").read_text(encoding="utf-8")
    assert "RANT:" in (game_dir / "ward-21.txt").read_text(encoding="utf-8")
    assert (game_dir / "ward-28.txt").read_text(encoding="utf-8").strip() == "BEAT 2/4 050%"
    assert "Escalate the argument" in (game_dir / "ward-34.txt").read_text(encoding="utf-8")
    assert (game_dir / "ward-active-01.txt").read_text(encoding="utf-8").strip() == "0.0000"
    assert (game_dir / "ward-active-13.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "ward-active-21.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "ward-active-34.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "active-wards-line.txt").read_text(
        encoding="utf-8"
    ).strip() == "36 IN-SCROOM WARDS"
    assert (game_dir / "reverie-salience.txt").read_text(encoding="utf-8").strip() == "0.3100"
    assert (game_dir / "reverie-trace.txt").read_text(encoding="utf-8").strip() == "0.2200"
    assert (game_dir / "reverie-temporal.txt").read_text(encoding="utf-8").strip() == "0.1800"
    assert (game_dir / "reverie-spectral.txt").read_text(encoding="utf-8").strip() == "0.1400"
    assert (game_dir / "reverie-material.txt").read_text(encoding="utf-8").strip() == "0.3700"
    assert (game_dir / "reverie-inversion.txt").read_text(encoding="utf-8").strip() == "0.2100"
    assert (game_dir / "reverie-aperture.txt").read_text(encoding="utf-8").strip() == "0.1900"
    assert (game_dir / "reverie-thermal.txt").read_text(encoding="utf-8").strip() == "0.2300"
    assert (game_dir / "audio-rms.txt").read_text(encoding="utf-8").strip() == "0.1200"
    assert (game_dir / "audio-onset.txt").read_text(encoding="utf-8").strip() == "0.3400"


def test_darkplaces_state_export_writes_camera_source_scalars(tmp_path: Path) -> None:
    exporter = _load_exporter()
    shm_dir = tmp_path / "shm"
    sources_dir = tmp_path / "sources"
    shm_dir.mkdir()

    _write_json(
        shm_dir / "camera-classifications.json",
        {
            "brio-operator": {"ambient_priority": 7},
            "brio-room": {"ambient_priority": 3},
            "brio-synths": {"ambient_priority": 4},
            "c920-desk": {"ambient_priority": 5},
            "c920-room": {"ambient_priority": 8},
            "c920-overhead": {"ambient_priority": 6},
        },
    )
    fresh_dir = sources_dir / "camera-brio-operator"
    stale_dir = sources_dir / "camera-c920-room"
    fresh_dir.mkdir(parents=True)
    stale_dir.mkdir(parents=True)
    _write_json(fresh_dir / "manifest.json", {"ttl_ms": 3000})
    _write_json(stale_dir / "manifest.json", {"ttl_ms": 3000})
    (fresh_dir / "frame.rgba").write_bytes(b"rgba")
    (stale_dir / "frame.rgba").write_bytes(b"rgba")
    os.utime(fresh_dir / "frame.rgba", (99.0, 99.0))
    os.utime(stale_dir / "frame.rgba", (80.0, 80.0))

    lines = exporter.build_source_lines(shm_dir, sources_dir, now=100.0)

    assert lines["source-priority-01.txt"] == "0.7000"
    assert lines["source-priority-05.txt"] == "0.8000"
    assert lines["source-fresh-01.txt"] == "1.0000"
    assert lines["source-fresh-05.txt"] == "0.0000"
    assert lines["source-fresh-06.txt"] == "0.0000"


def test_darkplaces_state_bridge_delegates_to_exporter() -> None:
    body = BRIDGE.read_text(encoding="utf-8")

    assert "darkplaces-state-export.py" in body
    assert "--game-dir" in body
    assert "--uniforms-file" in body
    assert "Keep the original minimal bridge alive" in body


def test_darkplaces_state_export_rejects_bad_arguments_cleanly() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--not-a-real-option"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2

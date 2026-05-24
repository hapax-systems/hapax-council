from __future__ import annotations

import importlib.util
import json
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
    mode_file.write_text("rnd\n", encoding="utf-8")
    (shm_dir / "stimmung-energy.txt").write_text("0.62\n", encoding="utf-8")
    (shm_dir / "voice-active.txt").write_text("1\n", encoding="utf-8")

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

    exporter.export_state(game_dir, shm_dir, mode_file)

    assert (game_dir / "working-mode.txt").read_text(encoding="utf-8").strip() == "rnd"
    assert (game_dir / "ward-01.txt").read_text(encoding="utf-8").strip() == "14056K TOK / 1 VIEW"
    assert (game_dir / "ward-02.txt").read_text(
        encoding="utf-8"
    ).strip() == "Radiohead / Pablo Honey"
    assert (game_dir / "ward-12.txt").read_text(encoding="utf-8").strip() == "VOICE ON / 03 WARDS"
    assert "BEAT 050%" in (game_dir / "ward-13.txt").read_text(encoding="utf-8")
    assert "RANT:" in (game_dir / "ward-21.txt").read_text(encoding="utf-8")
    assert (game_dir / "ward-28.txt").read_text(encoding="utf-8").strip() == "BEAT 2/4 050%"
    assert "Escalate the argument" in (game_dir / "ward-34.txt").read_text(encoding="utf-8")


def test_darkplaces_state_bridge_delegates_to_exporter() -> None:
    body = BRIDGE.read_text(encoding="utf-8")

    assert "darkplaces-state-export.py" in body
    assert "--game-dir" in body
    assert "Keep the original minimal bridge alive" in body


def test_darkplaces_state_export_rejects_bad_arguments_cleanly() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--not-a-real-option"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2

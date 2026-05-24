#!/usr/bin/env python3
"""Export live Hapax state into DarkPlaces-readable text files.

DarkPlaces QuakeC can read files below the game directory, but cannot parse
JSON or upload live RGBA ward frames as textures. This exporter collapses the
current compositor/programme state into small ASCII lines that CSQC can render
inside the engine on top of the corresponding ward anchors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_GAME_DIR = Path.home() / ".darkplaces" / "screwm" / "data"
DEFAULT_SHM_DIR = Path("/dev/shm/hapax-compositor")
DEFAULT_MODE_FILE = Path.home() / ".cache" / "hapax" / "working-mode"

WARD_EXPORTS: dict[str, str] = {
    "01": "token_pole",
    "02": "album",
    "07": "stance_indicator",
    "09": "grounding_provenance_ticker",
    "12": "thinking_indicator",
    "13": "pressure_gauge",
    "21": "programme_banner",
    "28": "programme_state",
    "34": "segment_content",
}

IN_WORLD_WARD_COUNT = 35


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _one_line(value: object, *, limit: int = 54) -> str:
    text = "" if value is None else str(value)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + ">"
    return text


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text.rstrip("\n") + "\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _copy_text(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    try:
        text = src.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    _write_atomic(dst, _one_line(text, limit=80))


def _percent(value: object) -> str:
    try:
        return f"{float(value) * 100:03.0f}%"
    except (TypeError, ValueError):
        return "000%"


def _active_ward_count(active_wards: dict[str, Any]) -> int:
    ward_ids = active_wards.get("ward_ids")
    if isinstance(ward_ids, list):
        return len(ward_ids)
    return 0


def _screwm_ward_count(active_wards: dict[str, Any]) -> int:
    """DarkPlaces hosts all legacy Screwm wards even without Cairo assignments."""
    return max(IN_WORLD_WARD_COUNT, _active_ward_count(active_wards))


def build_ward_lines(shm_dir: Path) -> dict[str, str]:
    active_segment = _read_json(shm_dir / "active-segment.json")
    active_wards = _read_json(shm_dir / "active_wards.json")
    album = _read_json(shm_dir / "album-state.json")
    voice = _read_json(shm_dir / "voice-state.json")
    token = _read_json(shm_dir / "token-ledger.json")
    reactivity = _read_json(shm_dir / "unified-reactivity.json")

    role = _one_line(active_segment.get("role", "idle"), limit=12).upper()
    topic = _one_line(active_segment.get("topic", "waiting for programme"), limit=34)
    beat = _one_line(active_segment.get("current_beat_text", ""), limit=48)
    source_refs = active_segment.get("source_refs")
    source_line = ""
    if isinstance(source_refs, list):
        source_line = _one_line(" ".join(str(item) for item in source_refs[:3]), limit=48)

    beat_index = active_segment.get("current_beat_index", 0)
    total_beats = active_segment.get("total_beats", 0)
    progress = _percent(active_segment.get("beat_progress", 0))

    artist = _one_line(album.get("artist", ""), limit=18)
    title = _one_line(album.get("title", ""), limit=22)
    album_line = _one_line(f"{artist} / {title}", limit=44) if artist or title else "NO ALBUM"

    blended = reactivity.get("blended") if isinstance(reactivity.get("blended"), dict) else {}
    rms = _percent(blended.get("rms", 0))
    onset = _percent(blended.get("onset", 0))

    speech = "VOICE ON" if voice.get("operator_speech_active") else "VOICE QUIET"
    active_count = _screwm_ward_count(active_wards)
    token_line = _one_line(
        f"{int(token.get('total_tokens', 0)) // 1000}K TOK / {int(token.get('active_viewers', 0))} VIEW",
        limit=34,
    )

    return {
        "01": token_line,
        "02": album_line,
        "07": role or "NOMINAL",
        "09": source_line or "SOURCE WAIT",
        "12": f"{speech} / {active_count:02d} WARDS",
        "13": f"BEAT {progress} RMS {rms} ON {onset}",
        "21": _one_line(f"{role}: {topic}", limit=48),
        "28": _one_line(f"BEAT {int(beat_index) + 1}/{int(total_beats or 0)} {progress}", limit=32),
        "34": beat or "SEGMENT WAIT",
    }


def export_state(game_dir: Path, shm_dir: Path, mode_file: Path) -> None:
    game_dir.mkdir(parents=True, exist_ok=True)

    _copy_text(mode_file, game_dir / "working-mode.txt")
    _copy_text(shm_dir / "stimmung-energy.txt", game_dir / "stimmung-energy.txt")
    _copy_text(shm_dir / "voice-active.txt", game_dir / "voice-active.txt")

    ward_lines = build_ward_lines(shm_dir)
    for ordinal, ward_id in WARD_EXPORTS.items():
        line = ward_lines.get(ordinal, ward_id.upper())
        _write_atomic(game_dir / f"ward-{ordinal}.txt", line)

    active_segment = _read_json(shm_dir / "active-segment.json")
    active_wards = _read_json(shm_dir / "active_wards.json")
    _write_atomic(
        game_dir / "programme-line.txt",
        _one_line(active_segment.get("topic", "programme waiting"), limit=64),
    )
    _write_atomic(
        game_dir / "active-wards-line.txt",
        f"{_screwm_ward_count(active_wards):02d} IN-SCROOM WARDS",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--shm-dir", type=Path, default=DEFAULT_SHM_DIR)
    parser.add_argument("--mode-file", type=Path, default=DEFAULT_MODE_FILE)
    parser.add_argument("--copy-self-test", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.copy_self_test is not None:
        shutil.copy2(__file__, args.copy_self_test)
        return 0

    export_state(args.game_dir, args.shm_dir, args.mode_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

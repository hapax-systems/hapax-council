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
import time
from pathlib import Path
from typing import Any

DEFAULT_GAME_DIR = Path.home() / ".darkplaces" / "screwm" / "data"
DEFAULT_SHM_DIR = Path("/dev/shm/hapax-compositor")
DEFAULT_MODE_FILE = Path.home() / ".cache" / "hapax" / "working-mode"
DEFAULT_REVERIE_UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/uniforms.json")
DEFAULT_IMAGINATION_SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")

WARD_ACTIVITY_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "token_pole"),
    ("02", "album"),
    ("03", "stream_overlay"),
    ("04", "sierpinski"),
    ("05", "reverie"),
    ("06", "activity_header"),
    ("07", "stance_indicator"),
    ("08", "gem"),
    ("09", "grounding_provenance_ticker"),
    ("10", "impingement_cascade"),
    ("11", "recruitment_candidate_panel"),
    ("12", "thinking_indicator"),
    ("13", "pressure_gauge"),
    ("14", "activity_variety_log"),
    ("15", "whos_here"),
    ("16", "durf"),
    ("17", "coding_session_reveal"),
    ("18", "m8-display"),
    ("19", "steamdeck-display"),
    ("20", "egress_footer"),
    ("21", "programme_banner"),
    ("22", "precedent_ticker"),
    ("23", "programme_history"),
    ("24", "research_instrument_dashboard"),
    ("25", "cbip_signal_density"),
    ("26", "chat_ambient"),
    ("27", "chronicle_ticker"),
    ("28", "programme_state"),
    ("29", "polyend_instrument_reveal"),
    ("30", "interactive_lore_query"),
    ("31", "constructivist_research_poster"),
    ("32", "tufte_density"),
    ("33", "ascii_schematic"),
    ("34", "segment_content"),
    ("35", "m8_oscilloscope"),
    ("36", "cbip_dual_ir_displacement"),
)

WARD_EXPORTS: dict[str, str] = dict(WARD_ACTIVITY_EXPORTS)
IN_WORLD_WARD_COUNT = 36

SOURCE_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "brio-operator"),
    ("02", "brio-room"),
    ("03", "brio-synths"),
    ("04", "c920-desk"),
    ("05", "c920-room"),
    ("06", "c920-overhead"),
)


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


def _float01(payload: dict[str, Any], key: str) -> float:
    try:
        value = float(payload.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def _active_ward_count(active_wards: dict[str, Any]) -> int:
    ward_ids = active_wards.get("ward_ids")
    if isinstance(ward_ids, list):
        return len(ward_ids)
    return 0


def _ward_activity_aliases(ward_id: str) -> set[str]:
    normalized = ward_id.strip().lower().replace("-", "_")
    aliases = {normalized}
    if normalized.endswith("_overlay"):
        aliases.add(normalized[: -len("_overlay")])
    return aliases


def _screwm_ward_count(active_wards: dict[str, Any]) -> int:
    """DarkPlaces hosts all legacy Screwm wards even without Cairo assignments."""
    return max(IN_WORLD_WARD_COUNT, _active_ward_count(active_wards))


def build_ward_activity_lines(active_wards: dict[str, Any]) -> dict[str, str]:
    ward_ids = active_wards.get("ward_ids")
    active_set = (
        {
            alias
            for ward_id in ward_ids
            if isinstance(ward_id, str)
            for alias in _ward_activity_aliases(ward_id)
        }
        if isinstance(ward_ids, list)
        else set()
    )
    return {
        f"ward-active-{ordinal}.txt": (
            "1.0000" if _ward_activity_aliases(ward_id) & active_set else "0.0000"
        )
        for ordinal, ward_id in WARD_ACTIVITY_EXPORTS
    }


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
    ward_ids = active_wards.get("ward_ids")
    active_line = "ACTIVE WAIT"
    if isinstance(ward_ids, list) and ward_ids:
        active_line = _one_line(" ".join(str(item).upper() for item in ward_ids[:3]), limit=44)
    token_line = _one_line(
        f"{int(token.get('total_tokens', 0)) // 1000}K TOK / {int(token.get('active_viewers', 0))} VIEW",
        limit=34,
    )

    return {
        "01": token_line,
        "02": album_line,
        "03": _one_line(f"STREAM {active_count:02d} WARDS", limit=34),
        "04": f"AOA RMS {rms} ON {onset}",
        "05": _one_line(f"REVERIE {progress} {role}", limit=34),
        "06": _one_line(f"ACT {active_line}", limit=44),
        "07": role or "NOMINAL",
        "08": _one_line(f"GEM {rms} {onset}", limit=34),
        "09": source_line or "SOURCE WAIT",
        "10": _one_line(f"IMPINGE {progress} {active_count:02d}", limit=34),
        "11": _one_line(f"RECRUIT {role}", limit=34),
        "12": f"{speech} / {active_count:02d} WARDS",
        "13": f"BEAT {progress} RMS {rms} ON {onset}",
        "14": _one_line(f"VARIETY {active_count:02d} ACTIVE", limit=34),
        "15": _one_line(f"HERE {int(token.get('active_viewers', 0))} VIEW", limit=34),
        "16": _one_line(f"DURF {role}", limit=34),
        "17": _one_line(f"CODE {topic}", limit=44),
        "18": _one_line(f"M8 RMS {rms}", limit=34),
        "19": _one_line(f"DECK ONSET {onset}", limit=34),
        "20": _one_line(f"EGRESS {progress}", limit=34),
        "21": _one_line(f"{role}: {topic}", limit=48),
        "22": _one_line(f"PRECED {source_line or role}", limit=44),
        "23": _one_line(f"HIST {role} {progress}", limit=34),
        "24": _one_line(f"INSTR RMS {rms} ON {onset}", limit=34),
        "25": _one_line(f"CBIP {rms}/{onset}", limit=34),
        "26": _one_line(f"CHAT {speech}", limit=34),
        "27": _one_line(f"CHRON {int(beat_index) + 1}/{int(total_beats or 0)}", limit=34),
        "28": _one_line(f"BEAT {int(beat_index) + 1}/{int(total_beats or 0)} {progress}", limit=32),
        "29": _one_line(f"POLY {album_line}", limit=34),
        "30": _one_line(f"QUERY {topic}", limit=44),
        "31": _one_line(f"POSTER {source_line or topic}", limit=44),
        "32": _one_line(f"TUFTE {active_count:02d} WARDS", limit=34),
        "33": _one_line(f"ASCII {progress}", limit=34),
        "34": beat or "SEGMENT WAIT",
        "35": _one_line(f"SCOPE RMS {rms} ON {onset}", limit=34),
        "36": _one_line(f"IRDUAL {rms}/{onset}", limit=34),
    }


def build_reverie_lines(uniforms_file: Path) -> dict[str, str]:
    """Collapse Reverie uniforms into QuakeC-readable scalar fields."""
    uniforms = _read_json(uniforms_file)
    salience = _float01(uniforms, "content.salience")
    trace = _float01(uniforms, "fb.trace_strength")
    temporal = max(
        _float01(uniforms, "signal.ward_fx_temporal_boost"),
        _float01(uniforms, "slot2_2_stutter.freeze_chance"),
        _float01(uniforms, "slot2_3_glitch_block.intensity"),
    )
    spectral = max(
        _float01(uniforms, "signal.ward_fx_spectral_boost"),
        _float01(uniforms, "signal.ward_fx_chromatic_boost"),
        _float01(uniforms, "slot0_1_chromatic_aberration.intensity"),
    )
    material = max(
        _float01(uniforms, "slot1_3_emboss.strength"),
        _float01(uniforms, "slot3_2_grain_bump.strength"),
        _float01(uniforms, "post.sediment_strength"),
        salience * 0.25,
    )
    inversion = max(
        _float01(uniforms, "slot3_1_invert.strength"),
        _float01(uniforms, "slot2_3_glitch_block.intensity") * 0.5,
        _float01(uniforms, "slot3_0_strobe.active") * 0.35,
    )
    aperture = max(
        _float01(uniforms, "post.vignette_strength"),
        _float01(uniforms, "slot0_0_vignette.strength"),
    )
    thermal = max(
        _float01(uniforms, "signal.color_warmth"),
        _float01(uniforms, "slot4_1_colorgrade.sepia"),
        _float01(uniforms, "content.intensity") * 0.20,
        spectral * 0.40,
    )
    return {
        "reverie-salience.txt": f"{salience:.4f}",
        "reverie-trace.txt": f"{trace:.4f}",
        "reverie-temporal.txt": f"{temporal:.4f}",
        "reverie-spectral.txt": f"{spectral:.4f}",
        "reverie-material.txt": f"{material:.4f}",
        "reverie-inversion.txt": f"{inversion:.4f}",
        "reverie-aperture.txt": f"{aperture:.4f}",
        "reverie-thermal.txt": f"{thermal:.4f}",
    }


def build_audio_lines(shm_dir: Path) -> dict[str, str]:
    reactivity = _read_json(shm_dir / "unified-reactivity.json")
    blended = reactivity.get("blended") if isinstance(reactivity.get("blended"), dict) else {}
    return {
        "audio-rms.txt": f"{_float01(blended, 'rms'):.4f}",
        "audio-onset.txt": f"{_float01(blended, 'onset'):.4f}",
    }


def build_homage_lines(shm_dir: Path, uniforms_file: Path) -> dict[str, str]:
    """Collapse the active HOMAGE package into QuakeC-readable scalars."""
    active = _read_json(shm_dir / "homage-active.json")
    substrate = _read_json(shm_dir / "homage-substrate-package.json")
    uniforms = _read_json(uniforms_file)

    package = active.get("package") or substrate.get("package") or "none"
    package = _one_line(package, limit=32) or "none"
    substrate_package = _one_line(substrate.get("package", package), limit=32) or "none"
    quake_active = 1.0 if package == "quake" or substrate_package == "quake" else 0.0

    try:
        hue = float(substrate.get("palette_accent_hue_deg", 0.0))
    except (TypeError, ValueError):
        hue = 0.0
    hue_norm = max(0.0, min(1.0, hue / 360.0))

    return {
        "homage-package.txt": package,
        "homage-substrate-package.txt": substrate_package,
        "homage-quake-active.txt": f"{quake_active:.4f}",
        "homage-transition-energy.txt": f"{_float01(uniforms, 'signal.homage_custom_4_0'):.4f}",
        "homage-accent-hue.txt": f"{hue_norm:.4f}",
        "homage-signature-intensity.txt": f"{_float01(uniforms, 'signal.homage_custom_4_2'):.4f}",
        "homage-rotation-phase.txt": f"{_float01(uniforms, 'signal.homage_custom_4_3'):.4f}",
    }


def _source_frame_freshness(source_dir: Path, now: float | None = None) -> float:
    frame_path = source_dir / "frame.rgba"
    manifest = _read_json(source_dir / "manifest.json")
    if not frame_path.exists():
        return 0.0
    try:
        age = (time.time() if now is None else now) - frame_path.stat().st_mtime
    except OSError:
        return 0.0
    ttl_ms = manifest.get("ttl_ms", 3000)
    try:
        ttl_s = max(1.0, float(ttl_ms) / 1000.0)
    except (TypeError, ValueError):
        ttl_s = 3.0
    return 1.0 if age <= ttl_s * 3.0 else 0.0


def build_source_lines(
    shm_dir: Path,
    imagination_sources_dir: Path = DEFAULT_IMAGINATION_SOURCES_DIR,
    now: float | None = None,
) -> dict[str, str]:
    classifications = _read_json(shm_dir / "camera-classifications.json")
    lines: dict[str, str] = {}

    for ordinal, role in SOURCE_EXPORTS:
        details = classifications.get(role)
        details = details if isinstance(details, dict) else {}
        try:
            priority = float(details.get("ambient_priority", 0.0)) / 10.0
        except (TypeError, ValueError):
            priority = 0.0
        source_dir = imagination_sources_dir / f"camera-{role}"
        freshness = _source_frame_freshness(source_dir, now)
        lines[f"source-priority-{ordinal}.txt"] = f"{max(0.0, min(1.0, priority)):.4f}"
        lines[f"source-fresh-{ordinal}.txt"] = f"{freshness:.4f}"

    return lines


def export_state(
    game_dir: Path,
    shm_dir: Path,
    mode_file: Path,
    uniforms_file: Path = DEFAULT_REVERIE_UNIFORMS_FILE,
    imagination_sources_dir: Path = DEFAULT_IMAGINATION_SOURCES_DIR,
) -> None:
    game_dir.mkdir(parents=True, exist_ok=True)

    _copy_text(mode_file, game_dir / "working-mode.txt")
    _copy_text(shm_dir / "stimmung-energy.txt", game_dir / "stimmung-energy.txt")
    _copy_text(shm_dir / "voice-active.txt", game_dir / "voice-active.txt")

    ward_lines = build_ward_lines(shm_dir)
    for ordinal, ward_id in WARD_EXPORTS.items():
        line = ward_lines.get(ordinal, ward_id.upper())
        _write_atomic(game_dir / f"ward-{ordinal}.txt", line)
    active_wards = _read_json(shm_dir / "active_wards.json")
    for filename, line in build_ward_activity_lines(active_wards).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_reverie_lines(uniforms_file).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_audio_lines(shm_dir).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_homage_lines(shm_dir, uniforms_file).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_source_lines(shm_dir, imagination_sources_dir).items():
        _write_atomic(game_dir / filename, line)

    active_segment = _read_json(shm_dir / "active-segment.json")
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
    parser.add_argument("--uniforms-file", type=Path, default=DEFAULT_REVERIE_UNIFORMS_FILE)
    parser.add_argument(
        "--imagination-sources-dir", type=Path, default=DEFAULT_IMAGINATION_SOURCES_DIR
    )
    parser.add_argument("--copy-self-test", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.copy_self_test is not None:
        shutil.copy2(__file__, args.copy_self_test)
        return 0

    export_state(
        args.game_dir,
        args.shm_dir,
        args.mode_file,
        args.uniforms_file,
        args.imagination_sources_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

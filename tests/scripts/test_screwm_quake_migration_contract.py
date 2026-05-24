from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_screwm_quake_layout_routes_only_darkplaces_video() -> None:
    layout_path = REPO_ROOT / "config" / "compositor-layouts" / "screwm-quake.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))

    assert layout["name"] == "screwm-quake"
    assert layout["assignments"] == []
    assert [source["id"] for source in layout["sources"]] == ["darkplaces"]
    assert layout["sources"][0]["kind"] == "video"
    assert layout["sources"][0]["backend"] == "v4l2"
    assert layout["sources"][0]["params"]["device"] == "/dev/video52"
    assert layout["sources"][0]["params"]["role"] == "darkplaces_background"
    assert "Cairo" not in json.dumps(layout)


def test_screwm_shader_effects_are_unconditional_scroom_fields() -> None:
    shader_path = REPO_ROOT / "assets" / "quake" / "glsl" / "combined_crc59807.glsl"
    shader = shader_path.read_text(encoding="utf-8")
    start = shader.index("Screwm scroom post-processing")
    end = shader.index("#ifdef USEBLOOM", start)
    postprocess_block = shader[start:end]

    assert "#if defined(USERVEC" not in postprocess_block
    assert "Screwm scroom post-processing" in postprocess_block
    assert "Effects run unconditionally" in postprocess_block
    assert "All effects operate on the WORLD" in postprocess_block
    assert "spatial effects in one pass" in postprocess_block


def test_screwm_spec_marks_compositor_wards_as_temporary_gap() -> None:
    spec_path = (
        REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-05-23-screwm-quake-hybrid-isap.md"
    )
    spec = spec_path.read_text(encoding="utf-8")

    assert "DarkPlaces is the rendering" in spec
    assert "projected CSQC text/line overlays are diagnostic only" in spec
    assert (
        "temporary bridge only where DarkPlaces runtime texture limits block live content" in spec
    )
    assert "Wards stay in GStreamer compositor overlay" not in spec


def test_screwm_quake_reads_reverie_effect_signals_in_engine() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")

    assert "DEFAULT_REVERIE_UNIFORMS_FILE" in exporter
    assert "reverie-salience.txt" in exporter
    assert "reverie-temporal.txt" in exporter
    assert "coupling_read_reverie" in coupling
    assert "data/reverie-salience.txt" in coupling
    assert "coupling_reverie_temporal * 0.012" in coupling


def test_screwm_quake_embodies_live_ward_activity_in_engine_lights() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "build_ward_activity_lines" in exporter
    assert "ward-active-" in exporter
    assert 'screwm_read_norm("data/ward-active-01.txt")' in wards
    assert "screwm_active_36" in wards
    assert "screwm_add_ward_light('0 -118 28', 36, screwm_green, screwm_active_36)" in wards


def test_screwm_quake_carries_audio_reactivity_into_scroom_effects() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "audio-rms.txt" in exporter
    assert "audio-onset.txt" in exporter
    assert "coupling_read_audio" in coupling
    assert "coupling_audio_onset * 0.010" in coupling
    assert 'screwm_read_norm("data/audio-rms.txt")' in wards
    assert "screwm_audio_rms * 90" in wards


def test_screwm_quake_contract_matches_current_camera_aoa_and_sound_foundation() -> None:
    spec = (
        REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-05-23-screwm-quake-hybrid-isap.md"
    ).read_text(encoding="utf-8")
    defs = (REPO_ROOT / "assets" / "quake" / "qc" / "defs.qc").read_text(encoding="utf-8")
    world = (REPO_ROOT / "assets" / "quake" / "qc" / "world.qc").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")

    assert "stable noclip camera" in spec
    assert "MOVETYPE_NOCLIP" in defs
    assert "screwm_free_view_body(self);" in world
    assert "spawn_aoa();" in world
    assert "self.angles_y = self.angles_y + frametime * self.screwm_spin_y" in world
    for sound in (
        "ambient/perception.ogg",
        "ambient/cognition.ogg",
        "ambient/communication.ogg",
        "ambient/expression.ogg",
        "ambient/grounding.ogg",
    ):
        assert sound in world
    assert 'localcmd(strcat(strcat("map ", map_name), "\\n"));' in coupling
    assert "[x] Stable QuakeC review POV is noclip/free-camera" in spec
    assert "[x] AoA Sierpinski tetrahedron visible and rotating" in spec
    assert "[x] 5 ambient sound zones" in spec

from __future__ import annotations

import json
from pathlib import Path

from agents.studio_compositor.homage import QUAKE_PACKAGE, get_package, registered_package_names

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


def test_screwm_quake_homage_package_is_registered_and_exported_to_engine() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    spec = (
        REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-05-23-screwm-quake-hybrid-isap.md"
    ).read_text(encoding="utf-8")

    assert "quake" in registered_package_names()
    assert get_package("quake") is QUAKE_PACKAGE
    assert "homage-active.json" in exporter
    assert "homage-substrate-package.json" in exporter
    assert "homage-quake-active.txt" in exporter
    assert "screwm_add_homage_lights" in wards
    assert "ward/source lightfield" in spec
    assert "### D9: QuakeHomage Package [COMPLETE]" in spec


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
    assert "UserVec4.x > 0.001 && UserVec4.x < 1.0" not in postprocess_block
    assert "reserved for material emboss" in postprocess_block
    assert "color *= 1.0 - mask;" not in postprocess_block
    assert "smoothstep(0.35, 0.92, mask_dist)" in postprocess_block
    assert "mask_strength = min(mask_r, 0.25) * 0.35" in postprocess_block
    assert "vhs_strength = clamp(UserVec3.y * 8.0, 0.0, 1.0)" in postprocess_block
    assert "UserVec2: x=mortar_lines, y=edge_glow, z=posterize_levels, w=sharpen" in (
        postprocess_block
    )
    assert "vec3 sh_blur = (sh_l + sh_r + sh_u + sh_d) * 0.25" in postprocess_block
    assert "vhs_band) * 0.008" not in postprocess_block
    assert "float strobe_period" not in postprocess_block
    assert "color += vec3(strobe" not in postprocess_block
    assert "Breathing" not in postprocess_block


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
    assert "reverie-material.txt" in exporter
    assert "reverie-inversion.txt" in exporter
    assert "reverie-aperture.txt" in exporter
    assert "reverie-thermal.txt" in exporter
    assert "coupling_read_reverie" in coupling
    assert "data/reverie-salience.txt" in coupling
    assert "data/reverie-material.txt" in coupling
    assert "r_glsl_postprocess_uservec4" in coupling
    assert "coupling_reverie_temporal * 0.012" in coupling


def test_screwm_quake_embodies_live_ward_activity_in_engine_lights() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "build_ward_activity_lines" in exporter
    assert "WARD_ACTIVITY_EXPORTS" in exporter
    assert '"36", "cbip_dual_ir_displacement"' in exporter
    assert "ward-active-" in exporter
    assert 'endswith("_overlay")' in exporter
    assert 'screwm_read_norm("data/ward-active-01.txt")' in wards
    assert "screwm_active_36" in wards
    assert "screwm_add_ward_light('0 -160 28', 36, screwm_green, screwm_active_36)" in wards


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


def test_screwm_quake_review_baseline_has_no_clocked_light_pulses() -> None:
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "state lighting" in wards
    assert "pulse lighting" not in wards
    assert "radius = radius + 4 * sin(time" not in wards
    assert "radius = radius + 5 * sin(time" not in wards
    assert "radius = radius + 6 * sin(time" not in wards
    assert "pulse = pulse + 18 * sin(time" not in wards
    assert "adddynamiclight('0 40 176', pulse + voice_radius" in wards


def test_screwm_quake_contract_matches_current_camera_aoa_and_sound_foundation() -> None:
    spec = (
        REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-05-23-screwm-quake-hybrid-isap.md"
    ).read_text(encoding="utf-8")
    defs = (REPO_ROOT / "assets" / "quake" / "qc" / "defs.qc").read_text(encoding="utf-8")
    world = (REPO_ROOT / "assets" / "quake" / "qc" / "world.qc").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")

    assert "stable noclip camera" in spec
    assert "Camera speed (120-150s period)" not in spec
    assert "bounded postprocess pressure" in spec
    assert "The gamepad bridge fails" in spec
    assert "`--device`/`--allow-any-joystick`" in spec
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
    assert "material, inversion, aperture, and" in spec
    assert "Positive UserVec4.x is material emboss only" in spec
    assert "UserVec2.w now carries a bounded sharpen pass" in spec
    assert "Aperture pressure is non-destructive edge attenuation" in spec


def test_screwm_quake_asset_provenance_gate_is_documented() -> None:
    spec = (
        REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-05-23-screwm-quake-hybrid-isap.md"
    ).read_text(encoding="utf-8")
    licenses = (REPO_ROOT / "assets" / "quake" / "LICENSES.md").read_text(encoding="utf-8")

    assert "### D3: Texture/Asset Provenance [COMPLETE]" in spec
    assert "[x] Texture/asset provenance documented in `assets/quake/LICENSES.md`" in spec
    assert "Audit date: 2026-05-24" in licenses
    assert "LibreQuake v0.09-beta" in licenses
    assert "BSD for LibreQuake art/media assets" in licenses
    assert "not vendored under `assets/quake/`" in licenses
    assert "assets/quake/maps/screwm.wad" in licenses
    assert "scripts/generate-screwm-wad.py" in licenses
    assert "assets/quake/sound/ambient/*.ogg" in licenses
    assert "assets/quake/models/aoa.mdl" in licenses
    assert "assets/quake/qc/progs.dat" in licenses
    assert "assets/quake/csqc/csprogs.dat" in licenses
    assert "Original Quake/Bethesda/id Software" in licenses


def test_screwm_quake_systemd_watchdog_gate_is_documented() -> None:
    spec = (
        REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-05-23-screwm-quake-hybrid-isap.md"
    ).read_text(encoding="utf-8")
    unit = (REPO_ROOT / "systemd" / "units" / "hapax-darkplaces-v4l2.service").read_text(
        encoding="utf-8"
    )

    assert "### D8: hapax-darkplaces Systemd Unit [COMPLETE]" in spec
    assert "`hapax-darkplaces-v4l2.service` now uses the display-safe Xvfb feed route" in spec
    assert "`Type=notify`/`NotifyAccess=all` with `WatchdogSec=30s`" in spec
    assert "`NRestarts=0`" in spec
    assert "[x] Systemd unit starts/restarts cleanly with WatchdogSec" in spec
    assert "ExecStart=/usr/bin/bash -lc 'exec " in unit
    assert "scripts/darkplaces-v4l2-xvfb.sh" in unit
    assert "WatchdogSec=30s" in unit

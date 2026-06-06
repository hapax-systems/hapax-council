from __future__ import annotations

import json
import re
from pathlib import Path

from agents.studio_compositor.final_frame_classifier import classify_screwm_geometry_legibility
from agents.studio_compositor.homage import QUAKE_PACKAGE, get_package, registered_package_names

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_TEXTURE_CVAR_RE = re.compile(
    r"(?:^|[+\s])hapax_live_texture(?P<slot>\d*)_"
    r"(?P<key>name|path|width|height)\s+(?P<value>\S+)",
    re.MULTILINE,
)
PATCH_LIVE_TEXTURE_DIM_RE = re.compile(
    r'"hapax_live_texture(?P<slot>\d*)_(?P<key>width|height)",\s+"(?P<value>\d+)"'
)
UNIFIED_DIFF_HUNK_RE = re.compile(
    r"^@@ -\d+(?:,(?P<old_count>\d+))? \+\d+(?:,(?P<new_count>\d+))? @@"
)


def _assert_unified_patch_hunk_counts(patch_text: str) -> None:
    current_header = ""
    old_count = 0
    new_count = 0
    expected_old = 0
    expected_new = 0

    def assert_current_hunk() -> None:
        if current_header:
            assert old_count == expected_old, current_header
            assert new_count == expected_new, current_header

    for line in patch_text.splitlines():
        hunk = UNIFIED_DIFF_HUNK_RE.match(line)
        if hunk:
            assert_current_hunk()
            current_header = line
            expected_old = int(hunk.group("old_count") or "1")
            expected_new = int(hunk.group("new_count") or "1")
            old_count = 0
            new_count = 0
            continue
        if line.startswith("diff --git "):
            # File boundary in a multi-file patch: finalize the previous file's
            # last hunk and stop counting so the following index/---/+++ headers
            # are not mistaken for hunk body lines.
            assert_current_hunk()
            current_header = ""
            continue
        if not current_header:
            continue
        if line.startswith("\\"):
            continue
        prefix = line[:1]
        if prefix == "+":
            new_count += 1
        elif prefix == "-":
            old_count += 1
        else:
            old_count += 1
            new_count += 1
    assert_current_hunk()


def _live_texture_slots_from_text(text: str) -> dict[int, dict[str, str]]:
    slots: dict[int, dict[str, str]] = {}
    for match in LIVE_TEXTURE_CVAR_RE.finditer(text):
        slot = int(match.group("slot") or "1")
        slots.setdefault(slot, {})[match.group("key")] = match.group("value")
    return slots


def _live_texture_patch_dimensions(text: str) -> dict[int, dict[str, int]]:
    slots: dict[int, dict[str, int]] = {}
    for match in PATCH_LIVE_TEXTURE_DIM_RE.finditer(text):
        slot = int(match.group("slot") or "1")
        slots.setdefault(slot, {})[match.group("key")] = int(match.group("value"))
    return slots


def _slot_for_texture(slots: dict[int, dict[str, str]], texture: str) -> int:
    matching = [slot for slot, values in slots.items() if values.get("name") == texture]
    assert len(matching) == 1
    return matching[0]


def _env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


def test_screwm_quake_layout_routes_only_darkplaces_video() -> None:
    layout_path = REPO_ROOT / "config" / "compositor-layouts" / "screwm-quake.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))

    assert layout["name"] == "screwm-quake"
    assert layout["assignments"] == []
    assert [source["id"] for source in layout["sources"]] == ["darkplaces"]
    assert layout["sources"][0]["kind"] == "video"
    assert layout["sources"][0]["backend"] == "v4l2"
    assert layout["sources"][0]["params"]["device"] == "/dev/video52"
    assert layout["sources"][0]["params"]["natural_w"] == 1920
    assert layout["sources"][0]["params"]["natural_h"] == 1080
    assert layout["sources"][0]["params"]["fps"] == 60
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


def test_screwm_shader_effects_are_diagnostic_screen_space_only() -> None:
    shader_path = REPO_ROOT / "assets" / "quake" / "glsl" / "combined_crc59807.glsl"
    crc_shader_path = REPO_ROOT / "assets" / "quake" / "glsl" / "combined_crc27804.glsl"
    assert crc_shader_path.read_text(encoding="utf-8") == shader_path.read_text(encoding="utf-8")
    shader = shader_path.read_text(encoding="utf-8")
    start = shader.index("Screwm/Scroom diagnostic post-processing")
    end = shader.index("#ifdef USEBLOOM", start)
    postprocess_block = shader[start:end]

    assert "#if defined(USERVEC" not in postprocess_block
    assert "Screwm/Scroom diagnostic post-processing" in postprocess_block
    assert "screen-space shader canary" in postprocess_block
    assert "Release-grade expression is geometry-bound" in postprocess_block
    assert "Effects run when r_glsl_postprocess is explicitly enabled" in postprocess_block
    assert "All effects operate on the WORLD" not in postprocess_block
    assert "entity-local drift/compositing field" not in postprocess_block
    assert "Signal-bound aura" in postprocess_block
    assert "signal_presence" in postprocess_block
    assert "gl_FragCoord" not in postprocess_block
    assert "screen lattice" in postprocess_block
    assert "Block drift/smear" in postprocess_block
    assert "UserVec4.x > 0.001 && UserVec4.x < 1.0" not in postprocess_block
    assert "reserved for material emboss" in postprocess_block
    assert "color *= 1.0 - mask;" not in postprocess_block
    assert "smoothstep(0.35, 0.92, mask_dist)" in postprocess_block
    assert "mask_strength = min(mask_r, 0.25) * 0.35" in postprocess_block
    assert "vhs_strength = clamp(UserVec3.y * 8.0, 0.0, 1.0)" in postprocess_block
    assert "UserVec2: x=signal_aura, y=edge_glow, z=posterize_levels, w=sharpen" in (
        postprocess_block
    )
    assert "mortar_lines" not in postprocess_block
    assert "vec3 sh_blur = (sh_l + sh_r + sh_u + sh_d) * 0.25" in postprocess_block
    assert "Shader-load canary" in postprocess_block
    assert "UserVec4.y > 0.95" in postprocess_block
    assert "particle_system" in postprocess_block or "texture_mode > 0.94" in postprocess_block
    assert "particle_tint" in postprocess_block
    assert "color += vec3(dust * dust_density" not in postprocess_block
    assert "color += vec3(noise_val * noise_str" not in postprocess_block
    assert "color += vec3((pn1" not in postprocess_block
    assert "dust_tint" in postprocess_block
    assert "noise_tint" in postprocess_block
    assert "pn_tint" in postprocess_block
    assert "max(signal_presence" not in postprocess_block
    assert "thermal_mix * signal_presence" in postprocess_block
    assert "vhs_band) * 0.008" not in postprocess_block
    assert "float strobe_period" not in postprocess_block
    assert "color += vec3(strobe" not in postprocess_block
    assert "Breathing" not in postprocess_block


def test_screwm_effect_modes_are_family_gated_before_reaching_shader() -> None:
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")

    assert "if (coupling_apply_effect_review_preset())\n        return;" not in coupling
    assert "coupling_screen_postprocess_enabled" in coupling
    assert "coupling_clear_screen_postprocess" in coupling
    assert 'cvar_set("r_glsl_postprocess", "0")' in coupling
    assert "coupling_effect_review_preset >= 6.5" in coupling
    assert "release-grade Screwm expression" in coupling
    assert "coupling_effect_review_preset >= 3.5 && coupling_effect_review_preset < 4.5" in coupling
    assert "halftone_val = 7;" in coupling
    assert "emboss_val = 0.36;" in coupling
    assert "threshold_val = 0.13;" in coupling
    assert "float mode_temporal = coupling_effect_mode_temporal;" in coupling
    assert "float mode_compositing = coupling_effect_mode_compositing;" in coupling
    assert "if (temporal_signal <= 0.01)" in coupling
    assert "if (coupling_effect_drift_compositing <= 0.01)" in coupling
    assert "mode_temporal > 0.68" in coupling
    assert "mode_compositing > 0.38" in coupling


def test_screwm_density_grounding_feeds_spatial_drift_baseline() -> None:
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")

    assert "float coupling_effect_drift_density;" in coupling
    assert "float coupling_effect_drift_density_currency;" in coupling
    assert 'coupling_read_float("data/effect-drift-density.txt", 0)' in coupling
    assert 'coupling_read_float("data/effect-drift-density-currency.txt", 0)' in coupling
    assert "float density_grounding = coupling_clamp_range(" in coupling
    assert (
        "coupling_max2(coupling_effect_drift_density * 1.6, coupling_effect_drift_density_currency * 1.25)"
        in coupling
    )
    assert "+ density_grounding + coupling_visual_chain_param_pressure" in coupling
    assert "fog_density = 0.008 - coupling_energy" in coupling
    assert "coupling_effect_drift_density * fog_density" not in coupling


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


def test_darkplaces_fork_patch_uploads_live_media_into_world_textures() -> None:
    patch = (REPO_ROOT / "assets" / "quake" / "darkplaces" / "hapax-live-texture.patch").read_text(
        encoding="utf-8"
    )

    _assert_unified_patch_hunk_counts(patch)
    assert "HAPAX_LIVE_TEXTURE_SLOT_COUNT 17" in patch
    assert "hapax_live_texture_name" in patch
    assert "hapax_live_texture7_name" in patch
    assert '"progs/aoa_sphere.mdl_0"' in patch
    assert '"progs/aoa.mdl_0"' in patch
    assert '"2048"' in patch
    assert '"1024"' in patch
    assert '"1280"' in patch
    assert '"720"' in patch
    assert '"cam_bop"' in patch
    assert '"cam_brm"' in patch
    assert '"cam_bsy"' in patch
    assert '"cam_cdk"' in patch
    assert '"cam_crm"' in patch
    assert '"cam_cov"' in patch
    assert '"ward_atlas"' in patch
    assert '"w09"' in patch
    assert '"w22"' in patch
    assert '"w27"' in patch
    assert '"w05"' in patch
    assert '"w18"' in patch
    assert '"w19"' in patch
    assert '"w35"' in patch
    assert '"speech_wave"' in patch
    assert "quake-live-reverie.bgra" in patch
    assert "quake-live-speech-wave.bgra" in patch
    assert "quake-live-aoa-atlas.bgra" in patch
    assert "quake-live-ir-brio-operator.bgra" in patch
    assert "quake-live-ir-brio-room.bgra" in patch
    assert "quake-live-ir-brio-synths.bgra" in patch
    assert "quake-live-ticker-grounding.bgra" in patch
    assert "quake-live-ticker-precedent.bgra" in patch
    assert "quake-live-ticker-chronicle.bgra" in patch
    assert '"2304"' in patch
    assert '"340"' in patch
    assert '"512"' in patch
    assert '"128"' in patch
    assert "R_HapaxLiveTexture_UpdateSlot" in patch
    assert "R_HapaxLiveTexture_FindWorldSkinFrame" in patch
    assert "R_SkinFrame_FindNextByName(NULL, name)" in patch
    assert "R_LoadTexture2D" in patch
    assert "TEXTYPE_BGRA" in patch
    assert "TEXF_FORCELINEAR" in patch
    assert "TEXF_ALLOWUPDATES" in patch
    assert "#include <sys/stat.h>" in patch
    assert "hapax_live_texture_slot_state_t" in patch
    assert "stat(path, &st)" in patch
    assert "st.st_mtim.tv_nsec" in patch
    assert "state->uploaded && state->file_size == st.st_size" in patch
    assert 'R_HapaxLiveTexture_Debug("disabled"' in patch
    assert 'R_HapaxLiveTexture_Debug("slot-active"' in patch
    assert 'R_HapaxLiveTexture_Debug("alloc-failed"' in patch
    assert 'strcmp(name, "progs/aoa.mdl_0")' in patch
    assert "R_HapaxLiveTexture_ApplyGain" not in patch
    assert "0.36f" not in patch
    assert "R_UpdateTexture(texture, state->pixels" in patch
    assert "for (slot = 0; slot < HAPAX_LIVE_TEXTURE_SLOT_COUNT; ++slot)" in patch
    assert "R_HapaxLiveTexture_UpdateSlot(slot, &hapax_live_texture_enable[slot]" in patch
    assert "for (i = 0; i < HAPAX_LIVE_TEXTURE_SLOT_COUNT; ++i)" in patch
    assert "R_HapaxLiveTexture_Update();" in patch


def test_darkplaces_fork_patch_material_flags_world_drift_eligibility() -> None:
    patch = (REPO_ROOT / "assets" / "quake" / "darkplaces" / "hapax-live-texture.patch").read_text(
        encoding="utf-8"
    )

    assert "#define MATERIALFLAG_HAPAXDRIFT 0x00400000" in patch
    assert "qbool dphapaxdrift;" in patch
    assert '"hapax_drift"' in patch
    assert '"dphapaxdrift"' in patch
    assert "shader.dphapaxdrift = true;" in patch
    assert "texture->basematerialflags |= MATERIALFLAG_HAPAXDRIFT;" in patch
    assert "static qbool Mod_HapaxDriftEligibleTextureName" in patch
    for texture_prefix in ('"drift_"', '"hex_"', '"stipple_"', '"geometry"'):
        assert texture_prefix in patch

    setup_start = patch.index("void R_SetupShader_Surface")
    setup_end = patch.index("if (t->currentmaterialflags & MATERIALFLAG_ALPHATEST)", setup_start)
    setup_block = patch[setup_start:setup_end]
    assert "t->currentmaterialflags & MATERIALFLAG_HAPAXDRIFT" in setup_block
    assert 'strncmp(t->name, "drift_"' not in setup_block
    assert "rsurface.entity && rsurface.entity != r_refdef.scene.worldentity" in setup_block


def test_screwm_live_media_sources_apply_receiver_local_drift() -> None:
    media_source = (REPO_ROOT / "scripts" / "quake-live-media-source.py").read_text(
        encoding="utf-8"
    )
    ticker_source = (REPO_ROOT / "scripts" / "quake-live-ticker-source.py").read_text(
        encoding="utf-8"
    )
    atlas_source = (REPO_ROOT / "scripts" / "quake-live-ward-atlas-source.py").read_text(
        encoding="utf-8"
    )
    reverie_source = (REPO_ROOT / "scripts" / "quake-live-reverie-source.py").read_text(
        encoding="utf-8"
    )
    drift_source = (REPO_ROOT / "scripts" / "quake_media_drift.py").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")

    assert "MediaDriftRenderer" in media_source
    assert "MediaDriftRenderer" in ticker_source
    assert "MediaDriftRenderer" in atlas_source
    assert "MediaDriftRenderer" in reverie_source
    assert "drift_input_hash" in media_source
    assert "drift_input_hash" in ticker_source
    assert "drift_input_hash" in atlas_source
    assert "drift_input_hash" in reverie_source
    assert "--gpu-drift" in media_source
    assert "--gpu-drift" in ticker_source
    assert "--gpu-drift" in atlas_source
    assert "--gpu-drift" in reverie_source
    assert "_gpu_drift_paths" in media_source
    assert "_gpu_drift_paths" in ticker_source
    assert "_gpu_drift_paths" in atlas_source
    assert "_gpu_drift_paths" in reverie_source
    assert "gpu_drift_output_owner" in media_source
    assert "gpu_drift_output_owner" in ticker_source
    assert "gpu_drift_output_owner" in atlas_source
    assert "gpu_drift_output_owner" in reverie_source
    assert "receiver-local drift" in drift_source.lower()
    assert "effect-drift-active-ratio.txt" in drift_source
    assert "effect-drift-active-slot-ratio.txt" in drift_source
    assert "effect-drift-fast-ratio.txt" in drift_source
    assert "effect-drift-mode-texture.txt" in drift_source
    assert "visual-chain-drift.txt" in drift_source
    assert "previous_rgb" in drift_source
    assert 'cvar_set("r_glsl_postprocess_uservec1"' in coupling
    assert "localcmd(cmd);" not in coupling


def test_screwm_media_drift_batches_slot_readback() -> None:
    source = (
        REPO_ROOT
        / "hapax-logos"
        / "crates"
        / "hapax-visual"
        / "src"
        / "bin"
        / "screwm_media_drift.rs"
    ).read_text(encoding="utf-8")

    assert "fn encode(" in source
    assert "Option<wgpu::CommandBuffer>" in source
    assert "fn read_complete_frame(" in source
    assert "read_complete_frame(&self.cfg.raw_path, self.expected_bytes)?" in source
    assert "fn producer_sidecar_path_for(" in source
    assert "fn read_producer_raw_sidecar(" in source
    assert "read_producer_raw_sidecar(&self.last_producer_sidecar_path)" in source
    assert "fn finish_readback(" in source
    assert "queue.submit(commands)" in source
    assert "prev_tex: wgpu::Texture" in source
    assert 'label: Some("media-drift previous")' in source
    assert "binding: 3" in source
    assert 'label: Some("media-drift clear previous")' in source
    assert "enc.copy_texture_to_texture(" in source
    assert ".map_async(wgpu::MapMode::Read" in source
    assert "device.poll(wgpu::Maintain::Wait)" in source
    assert source.count("device.poll(wgpu::Maintain::Wait)") == 1
    assert "for (idx, rx) in waits" in source
    assert "struct SlotMetadata" in source
    assert 'let meta_path = self.cfg.out_path.with_extension("json");' in source
    assert "atomic_write(&meta_path" in source
    assert "output_hash" in source
    assert "drift_changed" in source
    assert "producer_sidecar_path" in source
    assert "producer_sidecar_present" in source
    assert "producer_raw_output_matches_raw_path" in source
    assert "producer_final_output_matches_output_path" in source
    assert "producer_input_hash_matches_raw" in source


def test_screwm_ward_atlas_reuses_media_drift_inline_without_runtime_flip() -> None:
    source = (
        REPO_ROOT
        / "hapax-logos"
        / "crates"
        / "hapax-visual"
        / "src"
        / "bin"
        / "screwm_ward_atlas.rs"
    ).read_text(encoding="utf-8")

    assert "MEDIA_DRIFT_SHADER_SRC" in source
    assert "media_drift.wgsl" in source
    assert "load_drift_state" in source
    assert "DriftUniforms::new(" in source
    assert "ReceiverClass::Atlas" in source
    assert "HAPAX_WARD_ATLAS_INLINE_DRIFT" in source
    assert "HAPAX_WARD_ATLAS_DRIFT_GAME_DATA" in source
    assert "HAPAX_SCREWM_DRIFT_GAME_DATA" in source
    assert "DEFAULT_ATLAS_DRIFT_INTENSITY" in source
    assert "inline_drift" in source
    assert "drift_state_intensity" in source
    assert "ward-atlas inline media-drift pass" in source
    assert "drift_prev_tex" in source
    assert "ward-atlas clear media-drift previous" in source
    assert "TextureView(&drift_prev_view)" in source
    assert "HAPAX_WARD_ATLAS_ACTIVE_SLOTS=ward-atlas" not in source
    assert "systemctl" not in source


def test_screwm_gpu_drift_cutover_preflight_is_source_only() -> None:
    source = (REPO_ROOT / "scripts" / "screwm-gpu-drift-cutover-preflight.py").read_text(
        encoding="utf-8"
    )

    assert "parse_live_texture_slots" in source
    assert "build_manifest" in source
    assert "drift_slots_env" in source
    assert "producer_env_flag" in source
    assert "runtime_actions_performed" in source
    assert "subprocess" not in source
    assert "systemctl" not in source


def test_screwm_media_mount_contracts_are_deterministic() -> None:
    contract = json.loads(
        (REPO_ROOT / "config" / "screwm-quake-media-mounts.json").read_text(encoding="utf-8")
    )
    mounts = {mount["id"]: mount for mount in contract["mounts"]}

    assert contract["version"] == "screwm-quake-media-mounts-v1"
    assert mounts["aoa-media-sphere"]["texture"] == "progs/aoa_sphere.mdl_0"
    assert mounts["aoa-media-sphere"]["name"] == "OARB"
    assert mounts["aoa-media-sphere"]["expanded_name"] == "Ocular Attention Representation Ball"
    assert mounts["aoa-media-sphere"]["projection"] == "sphere-front"
    assert mounts["aoa-media-sphere"]["gpu_drift_intensity"] == 1.6
    assert mounts["aoa-media-sphere"]["projection_contract"] == "oarb_sphere_front_aspect_v2"
    assert mounts["aoa-media-sphere"]["texture_size"] == [2048, 1024]
    assert mounts["aoa-media-sphere"]["native_resolution"] == [2048, 1024]
    assert mounts["aoa-media-sphere"]["liveness_class"] == "live-public-media"
    assert mounts["aoa-media-sphere"]["mount_kind"] == "live-object-of-attention-sphere"
    assert mounts["aoa-media-sphere"]["hybrid_contract"]["memory_format"] == "BGRA8888"
    assert mounts["aoa-media-sphere"]["target_visual_angle_deg"] == 50.5
    assert mounts["aoa-media-sphere"]["target_visual_angle_deg_max"] == 52.0
    assert mounts["aoa-media-sphere"]["legibility_px_per_degree_floor"] == 40.0
    assert mounts["aoa-media-sphere"]["intended_view_distance"] == 730
    assert mounts["aoa-media-sphere"]["computed_mount_width"] == 689
    assert mounts["aoa-media-sphere"]["runtime_scale"] == 1.0
    assert mounts["aoa-media-sphere"]["physical_radius"] == 344.42
    assert mounts["aoa-media-sphere"]["enclosure"] == "aoa-tetrix-inner-volume"
    assert (
        mounts["aoa-media-sphere"]["fit_contract"] == "regular-tetrix-central-void-perfect-insphere"
    )
    assert mounts["aoa-media-sphere"]["fit_basis"] == (
        "regular-level4-sierpinski-pyramid-central-octahedral-void-insphere"
    )
    assert mounts["aoa-media-sphere"]["enclosure_clearance_ratio"] == 1.0
    assert mounts["aoa-media-sphere"]["inner_void_radius_fill_ratio"] == 1.0
    assert mounts["aoa-media-sphere"]["origin"] == [0, -555, 224]
    assert mounts["aoa-media-sphere"]["fractal_depth"] == 4
    assert mounts["aoa-media-sphere"]["leaf_face_edge_units"] == 105.46
    assert mounts["aoa-media-sphere"]["aoa_parent_edge_units"] == 1687
    assert mounts["aoa-media-sphere"]["fractal_face_count"] == 1024
    assert (
        "one triangular fractal face per atlas cell"
        in mounts["aoa-media-sphere"]["per_face_surface_atlas"]
    )
    assert "depth-veil" in mounts["aoa-media-sphere"]["occlusion_policy"]
    assert mounts["aoa-media-sphere"]["freshness"] == "live-producer-heartbeat"
    assert mounts["aoa-media-sphere"]["consent_or_license"]
    assert "object-of-attention" in mounts["aoa-media-sphere"]["purpose"]
    assert mounts["aoa-media-sphere"]["material_profile"] == "spherical-attention-live-media"

    aoa_atlas = mounts["aoa-fractal-face-atlas"]
    assert aoa_atlas["role"] == "aoa-face-atlas"
    assert aoa_atlas["texture"] == "progs/aoa.mdl_0"
    assert aoa_atlas["producer_kind"] == "live-aoa-face-atlas"
    assert aoa_atlas["producer_output"] == "/dev/shm/hapax-compositor/quake-live-aoa-atlas.bgra"
    assert aoa_atlas["control_input"] == "/dev/shm/hapax-compositor/aoa-face-controls.json"
    assert aoa_atlas["native_resolution"] == [2048, 2048]
    assert aoa_atlas["texture_size"] == [2048, 2048]
    assert aoa_atlas["liveness_class"] == "live-compositor-fractal-face-control"
    assert aoa_atlas["projection"] == "regular-tetrix-skinframe"
    assert aoa_atlas["source_aspect"] == [1, 1]
    assert aoa_atlas["gpu_drift_intensity"] == 2.25
    assert aoa_atlas["target_visual_angle_deg"] == 98.1
    assert aoa_atlas["target_visual_angle_deg_max"] == 100.0
    assert aoa_atlas["intended_view_distance"] == 732
    assert aoa_atlas["computed_mount_width"] == 1687
    assert aoa_atlas["legibility_px_per_degree_floor"] == 20.0
    assert aoa_atlas["runtime_scale"] == 1.0
    assert aoa_atlas["geometry_revision"] == ("aoa-regular-tetrix-v7-30pct-larger-perfect-fit-oarb")
    assert aoa_atlas["fit_contract"] == "regular-tetrix-central-void-perfect-insphere"
    assert aoa_atlas["fractal_depth"] == 4
    assert aoa_atlas["leaf_face_edge_units"] == 105.46
    assert aoa_atlas["aoa_parent_edge_units"] == 1687
    assert aoa_atlas["fractal_face_count"] == 1024
    assert aoa_atlas["atlas_contract"] == "one-live-control-cell-per-rendered-fractal-face"
    assert aoa_atlas["face_operability_contract"] == (
        "stable-independent-control-per-rendered-fractal-face"
    )
    assert "face_index-addressed JSON controls" in aoa_atlas["face_control_schema"]
    assert "non-aggregate" in aoa_atlas["face_control_scope"]
    assert aoa_atlas["atlas_columns"] == 32
    assert aoa_atlas["atlas_cell_size"] == 64
    assert aoa_atlas["hybrid_contract"]["memory_format"] == "BGRA8888"
    assert "slot 14" in aoa_atlas["hybrid_contract"]["update_semantics"]
    assert "not as a fourth-wall overlay" in aoa_atlas["drift_interaction"]["principle"]

    reverie = mounts["reverie-field"]
    assert reverie["texture"] == "w05"
    assert reverie["producer_kind"] == "live-reverie-substrate"
    assert reverie["mount_kind"] == "live-reverie-substrate"
    assert reverie["native_resolution"] == [960, 540]
    assert reverie["texture_size"] == [960, 540]
    assert reverie["source_aspect"] == [16, 9]
    assert reverie["target_visual_angle_deg"] == 18.0
    assert reverie["physical_width"] == 222
    assert reverie["origin"] == [-1620, 900, 330]
    assert reverie["facing"] == "x"
    assert reverie["receiver_light_multiplier"] == 3.4
    assert reverie["receiver_light_distance"] == 18
    assert reverie["texture_upload_gain"] == 1.0
    assert reverie["visible_border"] is False
    assert reverie["visible_grid_background"] is False
    assert reverie["hybrid_contract"]["quake_binding"] == "BSP brush texture w05"
    assert reverie["hybrid_contract"]["memory_format"] == "BGRA8888"

    camera_mounts = [mount for mount in contract["mounts"] if mount["role"] == "camera-source"]
    assert len(camera_mounts) == 6
    for mount in camera_mounts:
        assert mount["source_id"] == mount["id"]
        assert mount["liveness_class"] == "live-local-camera"
        assert mount["native_resolution"] == [1280, 720]
        assert mount["capture_format"] == "mjpeg"
        assert mount["capture_resolution"] == [1280, 720]
        assert mount["capture_fps"] == 10
        assert mount["texture_fps"] == 5
        assert mount["mount_kind"] == "live-camera-instrument"
        assert mount["hybrid_contract"]["memory_format"] == "BGRA8888"
        assert mount["resolution_basis"] == "runtime-contained-mjpeg-720p10-live-texture-5fps"
        assert mount["producer_kind"] == "live-camera"
        assert mount["freshness"] == "live-camera-frame"
        assert mount["consent_or_license"] == "operator-owned-local-camera"
        assert mount["purpose"]
        assert mount["projection"] == "flat"
        assert mount["source_aspect"] == [16, 9]
        assert mount["texture_size"] == [1280, 720]
        assert mount["target_visual_angle_deg"] == 24.0
        assert mount["intended_view_distance"] == 4818
        assert mount["anti_parasocial_posture"] == "instrument-not-intimacy-billboard"
        assert mount["material_profile"] == "flat-live-camera-instrument"
        assert mount["physical_width"] == 2048
        assert mount["computed_mount_width"] == 2048
        assert mount["texture"].startswith("cam_")
        assert mount["producer_output"].endswith(".bgra")
    ir_wards = {
        "brio-operator-ir-ward": (
            "brio-operator-ir",
            "w18",
            "/dev/shm/hapax-compositor/quake-live-ir-brio-operator.bgra",
            "slot 15",
            [-1180, -1320, 650],
        ),
        "brio-room-ir-ward": (
            "brio-room-ir",
            "w19",
            "/dev/shm/hapax-compositor/quake-live-ir-brio-room.bgra",
            "slot 16",
            [-1180, 400, 650],
        ),
        "brio-synths-ir-ward": (
            "brio-synths-ir",
            "w35",
            "/dev/shm/hapax-compositor/quake-live-ir-brio-synths.bgra",
            "slot 17",
            [-1180, -2240, 1180],
        ),
    }
    for mount_id, (
        source_id,
        texture,
        output,
        slot_label,
        origin,
    ) in ir_wards.items():
        mount = mounts[mount_id]
        assert mount["role"] == "state-ward"
        assert mount["source_id"] == source_id
        assert mount["texture"] == texture
        assert mount["producer_output"] == output
        assert mount["producer_kind"] == "live-camera-ir"
        assert mount["liveness_class"] == "live-local-ir-camera"
        assert mount["mount_kind"] == "live-camera-instrument"
        assert mount["native_resolution"] == [340, 340]
        assert mount["capture_format"] == "gray"
        assert mount["capture_resolution"] == [340, 340]
        assert mount["capture_fps"] == 10
        assert mount["texture_fps"] == 6
        assert mount["source_aspect"] == [1, 1]
        assert mount["texture_size"] == [340, 340]
        assert mount["physical_width"] == 1024
        assert mount["computed_mount_width"] == 1024
        assert mount["receiver_light_multiplier"] == 2.6
        assert mount["receiver_light_distance"] == 18
        assert mount["origin"] == origin
        assert mount["facing"] == "x"
        assert mount["hybrid_contract"]["quake_binding"] == f"BSP brush texture {texture}"
        assert slot_label in mount["hybrid_contract"]["update_semantics"]
        assert "hidden atlas proxies" in mount["drift_interaction"]["principle"]
    for mount_id, texture in (
        ("grounding-provenance-ticker", "w09"),
        ("precedent-ticker", "w22"),
        ("chronicle-ticker", "w27"),
    ):
        ticker = mounts[mount_id]
        assert ticker["texture"] == texture
        assert ticker["producer_kind"] == "live-ticker"
        assert ticker["mount_kind"] == "live-text-instrument"
        assert ticker["native_resolution"] == [1344, 176]
        assert ticker["source_aspect"] == [84, 11]
        assert ticker["physical_width"] == 768
        assert ticker["hybrid_contract"]["producer_binding"].startswith("Hapax Cairo/Pango")

    ward_atlas = mounts["ward-atlas"]
    assert ward_atlas["role"] == "ward-atlas-source"
    assert ward_atlas["texture"] == "ward_atlas"
    assert ward_atlas["producer_kind"] == "live-compositor-ward-atlas"
    assert ward_atlas["native_resolution"] == [2048, 2304]
    assert ward_atlas["texture_size"] == [2048, 2304]
    assert ward_atlas["cell_size"] == [512, 256]
    assert ward_atlas["atlas_columns"] == 4
    assert ward_atlas["atlas_rows"] == 9
    assert ward_atlas["active_visible_indices"] == list(range(1, 37))
    assert ward_atlas["activation_policy"] == "all-wards-spatialized-36-of-36"
    assert ward_atlas["hybrid_contract"]["update_semantics"].startswith(
        "DarkPlaces live-texture slot updates one atlas"
    )

    speech = mounts["speech-waveform"]
    assert speech["role"] == "speech-wave-source"
    assert speech["texture"] == "speech_wave"
    assert speech["producer_kind"] == "live-speech-waveform"
    assert speech["producer_output"] == "/dev/shm/hapax-compositor/quake-live-speech-wave.bgra"
    assert speech["native_resolution"] == [512, 128]
    assert speech["texture_size"] == [512, 128]
    assert speech["source_aspect"] == [4, 1]
    assert speech["target_visual_angle_deg"] == 18.0
    assert speech["physical_width"] == 384
    assert speech["signal_legibility_px_per_degree_floor"] == 24.0
    assert "512x128 low-latency slot" in speech["legibility_basis"]
    assert speech["origin"] == [-80, -555, 104]
    assert speech["facing"] == "y"
    assert speech["liveness_class"] == "live-voice-representation"
    assert speech["material_profile"] == "live-speech-waveform-field"
    assert speech["hybrid_contract"]["memory_format"] == "BGRA8888"
    assert "slot 13" in speech["hybrid_contract"]["update_semantics"]
    assert "never a global scene pulse" in speech["drift_interaction"]["principle"]


def test_screwm_live_camera_texture_dimensions_match_all_runtime_declarations() -> None:
    contract = json.loads(
        (REPO_ROOT / "config" / "screwm-quake-media-mounts.json").read_text(encoding="utf-8")
    )
    autoexec_slots = _live_texture_slots_from_text(
        (REPO_ROOT / "assets" / "quake" / "config" / "autoexec.cfg").read_text(encoding="utf-8")
    )
    launcher_slots = _live_texture_slots_from_text(
        (REPO_ROOT / "scripts" / "darkplaces-v4l2-xvfb.sh").read_text(encoding="utf-8")
    )
    patch_dims = _live_texture_patch_dimensions(
        (REPO_ROOT / "assets" / "quake" / "darkplaces" / "hapax-live-texture.patch").read_text(
            encoding="utf-8"
        )
    )
    camera_mounts = [mount for mount in contract["mounts"] if mount["role"] == "camera-source"]

    assert len(camera_mounts) == 6
    for mount in camera_mounts:
        width, height = mount["texture_size"]
        assert mount["native_resolution"] == [width, height]
        assert mount["capture_resolution"] == [width, height]

        env = _env_file(REPO_ROOT / "config" / "quake-live-cameras" / f"{mount['id']}.env")
        assert env["HAPAX_QUAKE_CAMERA_SIZE"] == f"{width}x{height}"
        assert int(env["HAPAX_QUAKE_LIVE_TEXTURE_WIDTH"]) == width
        assert int(env["HAPAX_QUAKE_LIVE_TEXTURE_HEIGHT"]) == height
        assert int(env["HAPAX_QUAKE_CAMERA_FPS"]) == mount["capture_fps"]
        assert int(env["HAPAX_QUAKE_LIVE_TEXTURE_FPS"]) == mount["texture_fps"]
        assert env["HAPAX_QUAKE_LIVE_TEXTURE_NAME"] == mount["texture"]
        assert env["HAPAX_QUAKE_LIVE_TEXTURE_OUTPUT"] == mount["producer_output"]

        for slots in (autoexec_slots, launcher_slots):
            slot = _slot_for_texture(slots, mount["texture"])
            assert int(slots[slot]["width"]) == width
            assert int(slots[slot]["height"]) == height
            assert slots[slot]["path"] == mount["producer_output"]
            assert patch_dims[slot] == {"width": width, "height": height}

    ir_ward_mounts = {
        "brio-operator-ir-ward": "brio-operator-ir",
        "brio-room-ir-ward": "brio-room-ir",
        "brio-synths-ir-ward": "brio-synths-ir",
    }
    for mount in (mount for mount in contract["mounts"] if mount["id"] in ir_ward_mounts):
        width, height = mount["texture_size"]
        assert mount["native_resolution"] == [width, height]
        assert mount["capture_resolution"] == [width, height]

        env = _env_file(
            REPO_ROOT / "config" / "quake-live-cameras" / f"{ir_ward_mounts[mount['id']]}.env"
        )
        assert env["HAPAX_QUAKE_CAMERA_SIZE"] == f"{width}x{height}"
        assert int(env["HAPAX_QUAKE_LIVE_TEXTURE_WIDTH"]) == width
        assert int(env["HAPAX_QUAKE_LIVE_TEXTURE_HEIGHT"]) == height
        assert int(env["HAPAX_QUAKE_CAMERA_FPS"]) == mount["capture_fps"]
        assert int(env["HAPAX_QUAKE_LIVE_TEXTURE_FPS"]) == mount["texture_fps"]
        assert env["HAPAX_QUAKE_LIVE_TEXTURE_NAME"] == mount["texture"]
        assert env["HAPAX_QUAKE_LIVE_TEXTURE_OUTPUT"] == mount["producer_output"]

        for slots in (autoexec_slots, launcher_slots):
            slot = _slot_for_texture(slots, mount["texture"])
            assert slot in {15, 16, 17}
            assert int(slots[slot]["width"]) == width
            assert int(slots[slot]["height"]) == height
            assert slots[slot]["path"] == mount["producer_output"]
            assert patch_dims[slot] == {"width": width, "height": height}

    speech = next(mount for mount in contract["mounts"] if mount["id"] == "speech-waveform")
    width, height = speech["texture_size"]
    assert speech["native_resolution"] == [width, height]
    for slots in (autoexec_slots, launcher_slots):
        slot = _slot_for_texture(slots, speech["texture"])
        assert slot == 13
        assert int(slots[slot]["width"]) == width
        assert int(slots[slot]["height"]) == height
        assert slots[slot]["path"] == speech["producer_output"]
        assert patch_dims[slot] == {"width": width, "height": height}

    aoa_atlas = next(
        mount for mount in contract["mounts"] if mount["id"] == "aoa-fractal-face-atlas"
    )
    width, height = aoa_atlas["texture_size"]
    assert aoa_atlas["native_resolution"] == [width, height]
    for slots in (autoexec_slots, launcher_slots):
        slot = _slot_for_texture(slots, aoa_atlas["texture"])
        assert slot == 14
        assert int(slots[slot]["width"]) == width
        assert int(slots[slot]["height"]) == height
        assert slots[slot]["path"] == aoa_atlas["producer_output"]
        assert patch_dims[slot] == {"width": width, "height": height}


def test_screwm_media_mount_contract_keeps_homage_out_of_portable_surface() -> None:
    contract = json.loads(
        (REPO_ROOT / "config" / "screwm-quake-media-mounts.json").read_text(encoding="utf-8")
    )
    framework = json.loads(
        (REPO_ROOT / "config" / "screwm-spatiotemporal-framework.json").read_text(encoding="utf-8")
    )
    pack = json.loads(
        (REPO_ROOT / "config" / "homage-packs" / "bitchx-acid-enlightenment.json").read_text(
            encoding="utf-8"
        )
    )

    forbidden = framework["media_theory_constraints"]["portable_mount_forbidden_homage_tokens"]
    core_material_profiles = [
        str(mount["material_profile"]).lower() for mount in contract["mounts"]
    ]
    for profile in core_material_profiles:
        assert not any(token in profile for token in forbidden)

    assert pack["id"] == framework["media_theory_constraints"]["reference_homage_pack"]
    assert set(pack["technology_lineage"]) >= {"BitchX", "ACiD ASCII", "Enlightenment GTK"}
    assert set(pack["material_profile_bindings"]) >= set(core_material_profiles)
    assert "portable framework" in pack["portable_boundary"].lower()
    assert "homage-specific" in pack["portable_boundary"].lower()


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
    assert "data/effect-review-preset.txt" in coupling
    assert "coupling_apply_effect_review_preset" in coupling
    assert "coupling_screen_postprocess_enabled" in coupling
    assert "coupling_clear_screen_postprocess" in coupling
    assert "reference/readability baseline" in coupling
    assert "threshold/inversion stress" in coupling
    assert "coupling_read_effect_drift" in coupling
    assert "data/effect-drift-compositing.txt" in coupling
    assert "data/visual-chain-param-pressure.txt" in coupling
    assert "r_glsl_postprocess_uservec4" in coupling
    assert "coupling_reverie_temporal * 0.008" in coupling
    assert "effect-drift-kind-variance.txt" in exporter
    assert "coupling_effect_drift_kind_variance" in coupling
    assert "family_mutation" in coupling


def test_screwm_quake_embodies_live_ward_activity_in_engine_lights() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "build_ward_activity_lines" in exporter
    assert "WARD_ACTIVITY_EXPORTS" in exporter
    assert '"36", "cbip_dual_ir_displacement"' in exporter
    assert "ward-active-" in exporter
    assert "build_ward_property_lines" in exporter
    assert "WARD_PROPERTY_Z_BASE" in exporter
    assert '"presence": presence' in exporter
    assert 'f"ward-{name}-{ordinal}.txt"' in exporter
    assert "ward-property-fishbowl-pressure.txt" in exporter
    assert "IN_SCROOM_FISHBOWL_WARD_PROPERTIES" in exporter
    assert 'endswith("_overlay")' in exporter
    assert 'screwm_read_norm("data/ward-active-01.txt")' in wards
    assert 'screwm_read_norm("data/ward-presence-01.txt")' in wards
    assert 'screwm_read_norm("data/ward-property-depth-pressure.txt")' in wards
    assert "screwm_active_36" in wards
    assert "screwm_presence_36" in wards
    assert "screwm_add_ward_property_field_lights" in wards
    assert "presence * 96" in wards
    assert "activity = screwm_clamp(active + presence * 0.70" in wards
    assert "screwm_ward_property_fishbowl_pressure * 34" in wards
    assert (
        "screwm_add_ward_light('-1180 -600 330', 36, screwm_green, screwm_active_36, screwm_presence_36)"
    ) in wards


def test_screwm_quake_carries_audio_reactivity_into_scroom_effects() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "audio-rms.txt" in exporter
    assert "audio-onset.txt" in exporter
    assert "coupling_read_audio" in coupling
    assert "coupling_audio_onset *" in coupling
    assert "float warp_val" in coupling
    assert 'screwm_read_norm("data/audio-rms.txt")' in wards
    assert "screwm_audio_rms * 24" in wards
    assert "screwm_add_theatre_spot" in wards
    assert "screwm_synthwave_color" in wards


def test_screwm_quake_embodies_no_front_garden_material_language() -> None:
    mapgen = (REPO_ROOT / "scripts" / "generate-screwm-map.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "WARD_GARDEN_LAYOUT" in mapgen
    assert "SCROOM_LIGHT_MARKER" in mapgen
    assert "SCROOM_PATH_STONES" in mapgen
    assert "Do not instantiate diagnostic path stones" in mapgen
    assert "No physical drift graph stones" in mapgen
    assert "scroom-garden-path-stone" not in mapgen
    assert 'screwm_read_norm("data/reverie-material.txt")' in wards
    assert "screwm_add_material_field_lights" in wards
    assert "adddynamiclight('0 -620 326'" in wards


def test_screwm_quake_embodies_entity_local_spatial_effects() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    mapgen = (REPO_ROOT / "scripts" / "generate-screwm-map.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    scene_quad = (
        REPO_ROOT
        / "hapax-logos"
        / "crates"
        / "hapax-visual"
        / "src"
        / "shaders"
        / "scene_quad.wgsl"
    ).read_text(encoding="utf-8")

    assert "entity_local_mirror" in scene_quad
    assert "entity_local_breathing" in scene_quad
    assert "DEFAULT_ENTITY_LOCAL_EFFECT_STATE_FILE" in exporter
    assert "DEFAULT_SHADER_PLAN_FILE" in exporter
    assert "LOCAL_EFFECT_EXPORTS" in exporter
    assert "build_entity_local_effect_lines" in exporter
    assert "build_shader_plan_lines" in exporter
    assert "local-effect-{ordinal}.txt" in exporter
    assert "IN_SCROOM_SHADER_PASS_PLAN" in exporter
    assert "ENTITY_LOCAL_SOURCE_PLANE" in exporter
    assert "SCROOM_LOCAL_EFFECTS" in mapgen
    assert "scene_quad.wgsl" in mapgen
    assert "scroom-local-effect-lens" in mapgen
    assert 'screwm_read_norm("data/local-effect-01.txt")' in wards
    assert 'screwm_read_norm("data/shader-plan-pass-count.txt")' in wards
    assert "screwm_add_local_effect_lights" in wards
    assert "screwm_add_shader_plan_lights" in wards
    assert "screwm_add_local_effect_light('-980 -1780 214'" in wards
    assert "screwm_add_local_effect_light('0 -1320 512'" in wards
    assert "screwm_add_local_effect_light('760 720 148'" in wards


def test_screwm_quake_embodies_visual_layer_stimmung_state() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    visual_state = (
        REPO_ROOT / "hapax-logos" / "crates" / "hapax-visual" / "src" / "state.rs"
    ).read_text(encoding="utf-8")

    assert "VISUAL_STATE_PATH" in visual_state
    assert "STIMMUNG_PATH" in visual_state
    assert "ambient_params" in visual_state
    assert "zone_opacities" in visual_state
    assert "build_visual_layer_lines" in exporter
    assert "VISUAL_ZONE_EXPORTS" in exporter
    assert "DEFAULT_STIMMUNG_STATE_FILE" in exporter
    assert "IN_SCROOM_VISUAL_LAYER_STATE" in exporter
    assert 'screwm_read_norm("data/visual-zone-01.txt")' in wards
    assert 'screwm_read_norm("data/visual-stance.txt")' in wards
    assert 'screwm_read_norm("data/stimmung-error.txt")' in wards
    assert "screwm_add_visual_layer_lights" in wards
    assert "screwm_add_visual_zone_light('-300 -548 340'" in wards
    assert "screwm_visual_stance * 90" in wards


def test_screwm_quake_embodies_visual_chain_effect_drift_state() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    visual_chain = (REPO_ROOT / "agents" / "visual_chain.py").read_text(encoding="utf-8")
    effect_drift = (
        REPO_ROOT / "hapax-logos" / "crates" / "hapax-visual" / "src" / "effect_drift.rs"
    ).read_text(encoding="utf-8")

    assert 'SHM_PATH = Path("/dev/shm/hapax-visual/visual-chain-state.json")' in visual_chain
    assert "effect-drift-state.json" in exporter
    assert "VISUAL_CHAIN_EXPORTS" in exporter
    assert "DEFAULT_VISUAL_CHAIN_STATE_FILE" in exporter
    assert "DEFAULT_VISUAL_CHAIN_FALLBACK_STATE_FILE" in exporter
    assert "DEFAULT_EFFECT_DRIFT_STATE_FILE" in exporter
    assert "DEFAULT_EFFECT_DRIFT_FALLBACK_STATE_FILE" in exporter
    assert "screwm-effect-drift-fallback-state.json" in exporter
    assert "_is_real_slotdrift_state" in exporter
    assert "build_visual_chain_lines" in exporter
    assert "IN_SCROOM_EFFECT_DRIFT_STATE" in exporter
    assert "PARAM_DRIFT_RATE" in effect_drift
    assert "CHAIN_SEEDS" in effect_drift
    assert "parameter_regions" in effect_drift
    assert 'screwm_read_norm("data/visual-chain-01.txt")' in wards
    assert 'screwm_read_norm("data/effect-drift-tonal.txt")' in wards
    assert 'screwm_read_norm("data/effect-drift-compositing.txt")' in wards
    assert "screwm_add_visual_chain_lights" in wards
    assert "screwm_effect_drift_region_count * 34" in wards
    assert "screwm_effect_drift_compositing * 104" in wards


def test_screwm_quake_embodies_imagination_fragment_intent_state() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    imagination = (REPO_ROOT / "agents" / "imagination.py").read_text(encoding="utf-8")
    uniforms = (REPO_ROOT / "agents" / "reverie" / "_uniforms.py").read_text(encoding="utf-8")

    assert 'CURRENT_PATH = SHM_DIR / "current.json"' in imagination
    assert "CANONICAL_DIMENSIONS" in imagination
    assert "MATERIAL_MAP" in uniforms
    assert "DEFAULT_IMAGINATION_CURRENT_FILE" in exporter
    assert "IMAGINATION_DIMENSION_EXPORTS" in exporter
    assert "IMAGINATION_MATERIAL_VALUES" in exporter
    assert "build_imagination_fragment_lines" in exporter
    assert "IN_SCROOM_IMAGINATION_FRAGMENT" in exporter
    assert 'screwm_read_norm("data/imagination-salience.txt")' in wards
    assert 'screwm_read_norm("data/imagination-dim-01.txt")' in wards
    assert "screwm_imagination_material_weight" in wards
    assert "screwm_add_imagination_intent_lights" in wards
    assert "screwm_imagination_salience * 118" in wards


def test_screwm_quake_embodies_content_source_manifests() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    content_sources = (
        REPO_ROOT / "hapax-logos" / "crates" / "hapax-visual" / "src" / "content_sources.rs"
    ).read_text(encoding="utf-8")

    assert 'const SOURCES_DIR: &str = "/dev/shm/hapax-imagination/sources";' in content_sources
    assert "CONTENT_SOURCE_EXPORTS" in exporter
    assert "build_content_source_lines" in exporter
    assert "IN_SCROOM_CONTENT_SOURCE_MANIFESTS" in exporter
    assert 'screwm_read_norm("data/content-source-count.txt")' in wards
    assert 'screwm_read_norm("data/content-source-fresh-01.txt")' in wards
    assert "screwm_add_content_source_light" in wards
    assert "fresh * 78 + opacity * 46 + area * 42" in wards


def test_screwm_quake_embodies_gem_recruitment_mural_state() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    gem_source = (REPO_ROOT / "agents" / "studio_compositor" / "gem_source.py").read_text(
        encoding="utf-8"
    )
    gem_canvas = (REPO_ROOT / "agents" / "studio_compositor" / "gem_canvas.py").read_text(
        encoding="utf-8"
    )

    assert 'DEFAULT_FRAMES_PATH = Path("/dev/shm/hapax-gem/gem-frames.json")' in gem_source
    assert "build_graffiti_layers" in gem_source
    assert 'COMPOSITION_PATH = Path("/dev/shm/hapax-compositor/gem-composition.json")' in gem_canvas
    assert "GRID_COLS = 115" in gem_canvas
    assert "DEFAULT_GEM_RECRUITMENT_FILE" in exporter
    assert "DEFAULT_GEM_FRAMES_FILE" in exporter
    assert "build_gem_mural_lines" in exporter
    assert "IN_SCROOM_GEM_RECRUITMENT_MURAL" in exporter
    assert 'screwm_read_norm("data/gem-recruitment-score.txt")' in wards
    assert 'screwm_read_norm("data/gem-layer-density.txt")' in wards
    assert "screwm_add_gem_mural_lights" in wards
    assert "screwm_gem_recruitment_score * 92" in wards
    assert "screwm_gem_layer_density * 96" in wards


def test_screwm_quake_embodies_impingement_recruitment_field_state() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    recent_producer = (REPO_ROOT / "scripts" / "hapax-recent-impingements-producer").read_text(
        encoding="utf-8"
    )

    assert "/dev/shm/hapax-compositor/recent-impingements.json" in recent_producer
    assert "DEFAULT_RECENT_IMPINGEMENTS_FILE" in exporter
    assert "DEFAULT_RECENT_RECRUITMENT_FILE" in exporter
    assert "build_impingement_recruitment_lines" in exporter
    assert "IN_SCROOM_IMPINGEMENT_RECRUITMENT_FIELD" in exporter
    assert 'screwm_read_norm("data/impingement-count.txt")' in wards
    assert 'screwm_read_norm("data/recruitment-family-count.txt")' in wards
    assert "screwm_add_impingement_recruitment_lights" in wards
    assert "screwm_impingement_strength * 82" in wards
    assert "screwm_recruitment_transition_pressure * 98" in wards


def test_screwm_quake_embodies_programme_segment_field_state() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    programme_state = (REPO_ROOT / "agents" / "operator_awareness" / "state.py").read_text(
        encoding="utf-8"
    )

    assert "class ProgrammeBlock" in programme_state
    assert "active_programme" in programme_state
    assert "PROGRAMME_ROLE_VALUES" in exporter
    assert "build_programme_segment_lines" in exporter
    assert "IN_SCROOM_PROGRAMME_SEGMENT_FIELD" in exporter
    assert 'screwm_read_norm("data/programme-role.txt")' in wards
    assert 'screwm_read_norm("data/programme-beat-progress.txt")' in wards
    assert "screwm_add_programme_segment_lights" in wards
    assert "screwm_programme_role * 72" in wards
    assert "screwm_programme_source_pressure * 78" in wards


def test_screwm_quake_embodies_live_context_field_state() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "ALBUM_RISK_VALUES" in exporter
    assert "build_live_context_lines" in exporter
    assert "IN_SCROOM_LIVE_CONTEXT_FIELD" in exporter
    assert 'screwm_read_norm("data/live-token-pressure.txt")' in wards
    assert 'screwm_read_norm("data/live-album-confidence.txt")' in wards
    assert 'screwm_read_norm("data/live-voice-active.txt")' in wards
    assert "screwm_add_live_context_lights" in wards
    assert "screwm_live_token_pressure * 88" in wards
    assert "screwm_live_album_confidence * 82" in wards


def test_screwm_quake_embodies_governance_health_field_state() -> None:
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "DEFAULT_DAIMONION_CONSENT_FILE" in exporter
    assert "build_governance_health_lines" in exporter
    assert "IN_SCROOM_GOVERNANCE_HEALTH_FIELD" in exporter
    assert 'screwm_read_norm("data/governance-consent-allowed.txt")' in wards
    assert 'screwm_read_norm("data/governance-health-error.txt")' in wards
    assert 'screwm_read_norm("data/governance-follow-confidence.txt")' in wards
    assert "screwm_add_governance_health_lights" in wards
    assert "screwm_governance_consent_allowed * 82" in wards
    assert "screwm_governance_follow_confidence * 64" in wards


def test_screwm_quake_spec_contains_migrated_intention_routes() -> None:
    spec = (
        REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-05-23-screwm-quake-hybrid-isap.md"
    ).read_text(encoding="utf-8")

    assert "IN_SCROOM_VISUAL_LAYER_STATE" in spec
    assert "IN_SCROOM_EFFECT_DRIFT_STATE" in spec
    assert "IN_SCROOM_IMAGINATION_FRAGMENT" in spec
    assert "IN_SCROOM_CONTENT_SOURCE_MANIFESTS" in spec
    assert "IN_SCROOM_GEM_RECRUITMENT_MURAL" in spec
    assert "IN_SCROOM_IMPINGEMENT_RECRUITMENT_FIELD" in spec
    assert "IN_SCROOM_PROGRAMME_SEGMENT_FIELD" in spec
    assert "IN_SCROOM_LIVE_CONTEXT_FIELD" in spec
    assert "IN_SCROOM_GOVERNANCE_HEALTH_FIELD" in spec
    assert "visual-chain/effect-drift exporter is the intentional containment layer" in spec
    assert "does not satisfy the Phase 4 parity gate by" in spec
    assert "itself, but it prevents the legacy Scroom systems" in spec
    assert (
        "Visual-layer, visual-chain/effect-drift, imagination-fragment, "
        "content-source manifest, GEM recruitment/mural, "
        "impingement/recruitment, programme/segment, live-context, and "
        "governance/health intent is exported into DarkPlaces" in spec
    )


def test_screwm_quake_review_baseline_has_no_clocked_light_pulses() -> None:
    wards = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")

    assert "state lighting" in wards
    assert "pulse lighting" not in wards
    assert "radius = radius + 4 * sin(time" not in wards
    assert "radius = radius + 5 * sin(time" not in wards
    assert "radius = radius + 6 * sin(time" not in wards
    assert "pulse = pulse + 18 * sin(time" not in wards
    assert "adddynamiclight('0 -555 224', pulse + voice_radius" in wards


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
    assert "float AOA_MODEL_SCALE = 1.0;" in defs
    assert "vector AOA_SPHERE_CENTER = '0 -555 224';" in defs
    assert "float AOA_SPHERE_MODEL_SCALE = 1.0;" in defs
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
    assert "[x] AoA/tetrix anchor with attendant sphere visible and rotating" in spec
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


def test_screwm_geo_drift_defaults_stay_within_legibility_floor() -> None:
    """Geo drift amplitudes ship at conservative defaults until the legibility floor
    (spec 2026-06-03 STEP 5 — 5f cull-bbox<->ampmax `AMPMAX_SAFE=min(bbox)*(1-CULL_MARGIN)`,
    5g rest-pose metric `0.4*IoU + 0.3*(1-max_disp/AMPMAX_SAFE) + 0.3*edge_corr >= 0.70`) is
    implemented and measured. Pinning the defaults makes any increase a conscious decision that
    must first land the floor — closing the gap that let prior shader changes drift unreviewed."""
    patch = (REPO_ROOT / "assets" / "quake" / "darkplaces" / "hapax-live-texture.patch").read_text(
        encoding="utf-8"
    )
    exporter = (REPO_ROOT / "scripts" / "darkplaces-state-export.py").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")
    autoexec = (REPO_ROOT / "assets" / "quake" / "config" / "autoexec.cfg").read_text(
        encoding="utf-8"
    )
    expected = {
        "hapax_drift_geo_amp": 24,
        "hapax_drift_geo_ampmax": 36,
        "hapax_drift_geo_content": 5,
    }
    for name, want in expected.items():
        match = re.search(rf'"{name}",\s*"(\d+)"', patch)
        assert match is not None, f"geo cvar {name} default missing from patch"
        assert int(match.group(1)) == want, (
            f"{name} default changed from {want}; STEP 5 legibility floor (5f/5g) must land first"
        )
    # Container amplitude must never exceed the hard displacement clamp.
    assert expected["hapax_drift_geo_amp"] <= expected["hapax_drift_geo_ampmax"]
    conservative_floor = classify_screwm_geometry_legibility(
        bbox_extents=(64, 64, 64),
        max_displacement=expected["hapax_drift_geo_ampmax"],
        rest_pose_iou=1.0,
        edge_correlation=1.0,
    )
    assert conservative_floor.passed, conservative_floor
    unsafe_increase = classify_screwm_geometry_legibility(
        bbox_extents=(64, 64, 64),
        max_displacement=64,
        rest_pose_iou=1.0,
        edge_correlation=1.0,
    )
    assert not unsafe_increase.passed
    assert "screwm_geo_legibility:max_displacement_exceeds_ampmax_safe" in unsafe_increase.reasons

    assert "DRIFT_GEO_BASELINES" in exporter
    assert '"amp": 0.5' in exporter
    assert '"freq": 0.3' in exporter
    assert '"speed": 0.25' in exporter
    assert '"content": 0.2' in exporter
    assert "drift-geo-amp.txt" in exporter
    assert "drift-geo-content.txt" in exporter
    assert "spatial_pressure = 0.0" in exporter

    assert "void() coupling_apply_drift_geo" in coupling
    assert 'coupling_read_float("data/drift-geo-amp.txt", coupling_drift_geo_amp)' in coupling
    assert 'cvar_set("hapax_drift_geo_amp"' in coupling
    assert 'cvar_set("hapax_drift_geo_ampmax", ftos(ampmax_val))' in coupling
    assert "amp_val = 18 + coupling_drift_geo_amp * 12;" in coupling
    assert "ampmax_val = 36;" in coupling
    assert "content_val = 4 + coupling_drift_geo_content * 5;" in coupling
    assert coupling.index("coupling_apply_drift_geo();") < coupling.index(
        "coupling_apply_stimmung();"
    )

    assert "set hapax_drift_geo_amp 24" in autoexec
    assert "set hapax_drift_geo_ampmax 36" in autoexec
    assert "set hapax_drift_geo_speed 0.25" in autoexec
    assert "set hapax_drift_geo_swirl 1.0" in autoexec

    assert "r_glsl_postprocess_ruttetra_enable" in coupling
    assert "warp_val = 9.0;" in coupling
    assert "noise_val = 7.0;" in coupling
    assert "halftone_val = 1.5;" in coupling

#!/usr/bin/env python3
"""Generate Quake .map files for the Screwm migration scene.

Sealed BSP substrate with Screwm/AoA composition anchors. Uses only
axis-aligned box brushes to guarantee qbsp seals the map (no vis leaks).

Supports two working modes per hapax design language §2:
  --mode rnd       Gruvbox Hard Dark (warm brown, amber lights)
  --mode research  Solarized Dark (cool blue-grey, white lights)

Default generates both BSPs: screwm-rnd.bsp and screwm-research.bsp.
"""

import argparse
import json
import math
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MEDIA_MOUNT_CONTRACTS_PATH = REPO_ROOT / "config" / "screwm-quake-media-mounts.json"
SURFACE_CONTRACTS_PATH = REPO_ROOT / "config" / "screwm-quake-surface-contracts.json"
SPATIOTEMPORAL_FRAMEWORK_PATH = REPO_ROOT / "config" / "screwm-spatiotemporal-framework.json"
HOMAGE_PACK_PATH = REPO_ROOT / "config" / "homage-packs" / "bitchx-acid-enlightenment.json"
DEFAULT_COMPOSITOR_LAYOUT_PATH = REPO_ROOT / "config" / "compositor-layouts" / "default.json"
UNITS_PER_METER = 32
TOWER_RADIUS_M = 16.5
TOWER_FLOOR_M = -2.0
TOWER_CEIL_M = 26.5
WALL_THICK = 16
AOA_HEIGHT_M = 5.5
WARD_PANEL_COUNT = 36

TR = int(TOWER_RADIUS_M * UNITS_PER_METER)
FLOOR_Z = int(TOWER_FLOOR_M * UNITS_PER_METER)
CEIL_Z = int(TOWER_CEIL_M * UNITS_PER_METER)
AOA_X = 0
AOA_Y = -555
AOA_Z = int(AOA_HEIGHT_M * UNITS_PER_METER)
ROOM_X_EXT = 2080
ROOM_Y_MIN = -2550
ROOM_Y_MAX = 1440
EXT = ROOM_X_EXT
REVIEW_ALCOVE_Y_MIN = ROOM_Y_MIN
REVIEW_WARD_Y = AOA_Y
REVIEW_DRIFT_Y = AOA_Y - 45
ROOM_LEFT_X = -ROOM_X_EXT + WALL_THICK + 18
ROOM_RIGHT_X = ROOM_X_EXT - WALL_THICK - 18
ROOM_ENTRY_Y = ROOM_Y_MIN + WALL_THICK + 28
ROOM_FAR_Y = ROOM_Y_MAX - WALL_THICK - 24
LEVEL_BANDS = [
    ("perception", FLOOR_Z, FLOOR_Z + 96),
    ("cognition", FLOOR_Z + 96, FLOOR_Z + 192),
    ("communication", FLOOR_Z + 192, FLOOR_Z + 288),
    ("expression", FLOOR_Z + 288, FLOOR_Z + 384),
    ("grounding", FLOOR_Z + 384, CEIL_Z),
]

WARD_ANCHORS = [
    "token_pole",
    "album",
    "stream_overlay",
    "aoa_oarb_state",
    "reverie",
    "activity_header",
    "stance_indicator",
    "gem",
    "grounding_provenance_ticker",
    "impingement_cascade",
    "recruitment_candidate_panel",
    "thinking_indicator",
    "pressure_gauge",
    "activity_variety_log",
    "whos_here",
    "durf",
    "coding_session_reveal",
    "m8-display",
    "steamdeck-display",
    "egress_footer",
    "programme_banner",
    "precedent_ticker",
    "programme_history",
    "research_instrument_dashboard",
    "cbip_signal_density",
    "chat_ambient",
    "chronicle_ticker",
    "programme_state",
    "polyend_instrument_reveal",
    "interactive_lore_query",
    "constructivist_research_poster",
    "tufte_density",
    "ascii_schematic",
    "segment_content",
    "m8_oscilloscope",
    "cbip_dual_ir_displacement",
]

WARD_DOMAINS = {
    "token_pole": "token",
    "album": "music",
    "stream_overlay": "communication",
    "aoa_oarb_state": "perception",
    "reverie": "perception",
    "activity_header": "cognition",
    "stance_indicator": "presence",
    "gem": "perception",
    "grounding_provenance_ticker": "director",
    "impingement_cascade": "communication",
    "recruitment_candidate_panel": "cognition",
    "thinking_indicator": "presence",
    "pressure_gauge": "presence",
    "activity_variety_log": "cognition",
    "whos_here": "presence",
    "durf": "perception",
    "coding_session_reveal": "cognition",
    "m8-display": "music",
    "steamdeck-display": "music",
    "egress_footer": "director",
    "programme_banner": "director",
    "precedent_ticker": "director",
    "programme_history": "cognition",
    "research_instrument_dashboard": "cognition",
    "cbip_signal_density": "perception",
    "chat_ambient": "communication",
    "chronicle_ticker": "director",
    "programme_state": "director",
    "polyend_instrument_reveal": "music",
    "interactive_lore_query": "cognition",
    "constructivist_research_poster": "cognition",
    "tufte_density": "cognition",
    "ascii_schematic": "cognition",
    "segment_content": "communication",
    "m8_oscilloscope": "music",
    "cbip_dual_ir_displacement": "perception",
}

WARD_DEPTH_PLANES = {
    "token_pole": "hero-presence",
    "album": "beyond-scrim",
    "stream_overlay": "surface-scrim",
    "aoa_oarb_state": "beyond-scrim",
    "reverie": "beyond-scrim",
    "activity_header": "surface-scrim",
    "stance_indicator": "surface-scrim",
    "gem": "beyond-scrim",
    "thinking_indicator": "surface-scrim",
    "whos_here": "surface-scrim",
    "durf": "beyond-scrim",
    "egress_footer": "surface-scrim",
    "programme_banner": "surface-scrim",
    "precedent_ticker": "surface-scrim",
    "chronicle_ticker": "surface-scrim",
    "programme_state": "surface-scrim",
    "segment_content": "surface-scrim",
}

WARD_DEPTH_STYLES = {
    "surface-scrim": {"layers": 0, "pad": 0, "y_step": 0, "x_shift": 0, "z_shift": 0},
    "near-surface": {"layers": 1, "pad": 7, "y_step": 12, "x_shift": 2, "z_shift": -2},
    "hero-presence": {"layers": 2, "pad": 9, "y_step": 14, "x_shift": -3, "z_shift": 3},
    "beyond-scrim": {"layers": 3, "pad": 11, "y_step": 16, "x_shift": 4, "z_shift": -4},
}

DOMAIN_GLOW_TEX = {
    "communication": "drift_g",
    "presence": "drift_a",
    "token": "drift_c",
    "music": "drift_r",
    "cognition": "drift_c",
    "director": "drift_a",
    "perception": "drift_g",
}

DOMAIN_LIGHT_COLOR = {
    "communication": (0.55, 0.95, 0.42),
    "presence": (1.00, 0.70, 0.28),
    "token": (0.45, 0.95, 0.88),
    "music": (1.00, 0.35, 0.65),
    "cognition": (0.40, 0.88, 1.00),
    "director": (1.00, 0.62, 0.23),
    "perception": (0.58, 0.88, 0.34),
}

WARD_COLUMNS = 7
WARD_PANE_W = 86
WARD_PANE_H = 54
WARD_FRAME_PAD = 6
WARD_FRAME_T = 4
WARD_X_SPACING = 74
WARD_Z_SPACING = 54
WARD_Y_TOP = 62
WARD_Y_STEP = -36
WARD_TOP_Z = FLOOR_Z + 344
WARD_GLOW_TEX = ["drift_c", "drift_a", "drift_r", "drift_g"]
MEDIA_RECEIVER_EDGE_TEX = "scroom"
SYNTHWAVE_TICKER_WARDS = {9, 22, 27}
SPECIAL_WARD_POSITIONS = {
    36: (0, WARD_Y_TOP + 5 * WARD_Y_STEP, FLOOR_Z + 92),
}

GARDEN_CAMERA_STATIONS = [
    ("entry-stone", (0, -2380, 164), (0, AOA_Y, AOA_Z)),
    ("threshold-stone", (-320, -2200, 168), (AOA_X, AOA_Y, AOA_Z)),
    ("left-borrowed-view", (-860, -1880, 184), (-1180, -1600, 240)),
    ("left-media-window", (-1040, -1480, 196), (-1580, -1320, 230)),
    ("aoa-pause", (-320, -900, 182), (AOA_X, AOA_Y, AOA_Z)),
    ("right-borrowed-view", (860, -1000, 184), (1180, -1120, 240)),
    ("right-media-window", (1040, -1480, 196), (1580, -1320, 230)),
    ("far-garden-view", (420, -430, 220), (AOA_X, AOA_Y, AOA_Z + 18)),
]

WARD_GARDEN_LAYOUT = {
    # No-front Scroom garden: ward identity mounts form side groves, an entry
    # threshold, and a far borrowed-view band around the walking loop. The
    # doubled room remains open enough that AoA/sphere/media can be read from
    # multiple positions instead of becoming a fourth-wall theatre.
    1: (-900, -2360, 130, "y"),
    2: (-1180, -1780, 150, "x"),
    3: (-1040, 980, 300, "y"),
    4: (-1180, -1540, 245, "x"),
    5: (-700, -1120, 260, "y"),
    6: (1180, -1780, 315, "x"),
    7: (-640, 980, 190, "y"),
    8: (-1180, -760, 260, "x"),
    9: (-1580, -1860, 220, "x"),
    10: (-260, 980, 330, "y"),
    11: (1180, -1540, 230, "x"),
    12: (80, 980, 215, "y"),
    13: (420, 980, 140, "y"),
    14: (1180, -980, 165, "x"),
    15: (800, 980, 285, "y"),
    16: (-1180, -420, 150, "x"),
    17: (1180, -760, 290, "x"),
    18: (-1180, -150, 250, "x"),
    19: (-1180, -2020, 310, "x"),
    20: (520, -2360, 105, "y"),
    21: (1160, 980, 340, "y"),
    22: (1580, -1860, 220, "x"),
    23: (1180, -420, 160, "x"),
    24: (1180, -150, 300, "x"),
    25: (-1180, -1180, 350, "x"),
    26: (-1040, 980, 140, "y"),
    27: (-1580, -980, 360, "x"),
    28: (-80, 980, 120, "y"),
    29: (-1180, 120, 345, "x"),
    30: (1180, -2020, 115, "x"),
    31: (1180, -1240, 300, "x"),
    32: (1180, -580, 110, "x"),
    33: (1180, -280, 330, "x"),
    34: (1160, 980, 210, "y"),
    35: (-1180, -1320, 330, "x"),
    36: (-1180, -600, 330, "x"),
}

SOURCE_PANE_W = 62
SOURCE_PANE_H = 38
AOA_PAYLOAD_PANE_W = 28
AOA_PAYLOAD_PANE_H = 20
AOA_SPHERE_FACE_SIZE = 128
AOA_SPHERE_STRIP_COUNT = 0
AOA_PAYLOAD_PANES = [
    ("root-pane", "aoa_root", "drift_c", -4, 108, 1.00),
    ("tri-texture", "aoa_tri", "drift_g", -72, 62, 0.92),
    ("data-glyph", "aoa_data", "drift_a", 72, 62, 0.92),
    ("signal-glyph", "aoa_glyph", "drift_r", -118, -6, 0.78),
    ("edge-accent", "aoa_edge", "drift_c", 118, -6, 0.78),
    ("lod-gate", "aoa_lod", "drift_g", -76, -74, 0.70),
    ("privacy-gate", "aoa_priv", "drift_a", 76, -74, 0.70),
    ("source-posture", "aoa_src", "drift_r", -176, 40, 0.58),
    ("composition", "aoa_comp", "drift_c", 176, 40, 0.58),
    ("payload-gate", "aoa_gate", "drift_g", 0, -112, 0.64),
]

SCROOM_SCENE_GRAPH_PANES = [
    # Larger media/source surfaces echo the 3D Scroom references. They are
    # room-mounted anchors, not a flat fourth-wall scene.
    ("camera-source", "brio-operator", "cam_bop", "drift_a", -1580, -2140, 290, 128, 72),
    ("camera-source", "brio-room", "cam_brm", "drift_g", -1580, -1320, 190, 120, 68),
    ("camera-source", "brio-synths", "cam_bsy", "drift_r", -1580, -500, 300, 120, 68),
    ("camera-source", "c920-desk", "cam_cdk", "drift_c", 1580, -2140, 290, 120, 68),
    ("camera-source", "c920-room", "cam_crm", "drift_g", 1580, -1320, 190, 120, 68),
    ("camera-source", "c920-overhead", "cam_cov", "drift_c", 1580, -500, 300, 120, 68),
    ("ir", "cbip-ir", "w36", "drift_g", -1180, -600, 330, 64, 40),
    ("ward-shelf", "programme-history", "w23", "drift_a", 1180, -420, 160, 64, 40),
    ("ward-shelf", "instrument-dashboard", "w24", "drift_c", 1180, -150, 300, 64, 40),
    ("ward-shelf", "interactive-query", "w30", "drift_a", 1180, -2020, 115, 64, 40),
    ("mid-band", "chat-ambient", "w26", "drift_g", -1040, 1010, 140, 60, 38),
    ("mid-band", "impingement", "w10", "drift_a", -260, 1010, 330, 60, 38),
    ("far-band", "variety-log", "w14", "drift_c", 1180, -980, 165, 56, 34),
    ("far-band", "scope-wave", "w35", "drift_r", -1180, -1320, 330, 56, 34),
]
SCROOM_LIGHT_MARKER = (AOA_X, AOA_Y, FLOOR_Z + 390)
SCROOM_MATERIAL_BEAMS = []
SCROOM_GRID_X_LINES = []
SCROOM_GRID_Y_LINES = []
SCROOM_PATH_STONES = [
    ("roji-entry", "drift_c", 0, -2405, FLOOR_Z + 7, 210, 32),
    ("threshold", "drift_g", -320, -2200, FLOOR_Z + 7, 148, 30),
    ("left-borrowed-view", "drift_g", -860, -1880, FLOOR_Z + 7, 190, 32),
    ("left-media-pause", "drift_c", -1040, -1480, FLOOR_Z + 7, 196, 32),
    ("aoa-pause", "drift_a", -320, -900, FLOOR_Z + 7, 208, 34),
    ("right-borrowed-view", "drift_g", 860, -1000, FLOOR_Z + 7, 190, 32),
    ("right-media-pause", "drift_r", 1040, -1480, FLOOR_Z + 7, 196, 32),
    ("far-garden-view", "drift_g", 420, -430, FLOOR_Z + 7, 188, 32),
    ("return-ridge", "drift_r", 0, -2380, FLOOR_Z + 7, 156, 30),
]
SCROOM_GARDEN_ISLANDS = [
    ("entry-raked-bed", "scroom", 0, -2340, FLOOR_Z + 2, 720, 150),
    ("left-raked-bed", "scroom", -900, -1680, FLOOR_Z + 2, 620, 150),
    ("aoa-raked-bed", "scroom", -250, -980, FLOOR_Z + 2, 620, 160),
    ("right-raked-bed", "scroom", 900, -1080, FLOOR_Z + 2, 620, 150),
    ("far-raked-bed", "scroom", 300, -360, FLOOR_Z + 2, 640, 136),
    ("return-raked-bed", "scroom", 820, -1880, FLOOR_Z + 2, 500, 132),
]
SCROOM_GARDEN_LANTERNS = [
    ("entry-lantern", "drift_c", -560, -2220, FLOOR_Z + 18),
    ("left-lantern", "drift_g", -1120, -1425, FLOOR_Z + 18),
    ("aoa-lantern", "drift_a", -560, -790, FLOOR_Z + 18),
    ("right-lantern", "drift_r", 1120, -1030, FLOOR_Z + 18),
    ("far-lantern", "drift_g", 720, -200, FLOOR_Z + 18),
]
SCROOM_LOCAL_EFFECTS = [
    # Mirrors scene_quad.wgsl entity-local source-plane spatial effects.
    ("mirror", "fx_mirr", "drift_c", -250, -522, FLOOR_Z + 92),
    ("kaleidoscope", "fx_kale", "drift_r", -200, -522, FLOOR_Z + 92),
    ("warp", "fx_warp", "drift_g", -150, -522, FLOOR_Z + 92),
    ("fisheye", "fx_fish", "drift_c", -100, -522, FLOOR_Z + 92),
    ("transform", "fx_xfrm", "drift_a", -50, -522, FLOOR_Z + 92),
    ("displacement_map", "fx_disp", "drift_r", 0, -522, FLOOR_Z + 92),
    ("droste", "fx_dros", "drift_c", 50, -522, FLOOR_Z + 92),
    ("tunnel", "fx_tunn", "drift_g", 100, -522, FLOOR_Z + 92),
    ("tile", "fx_tile", "drift_a", 150, -522, FLOOR_Z + 92),
    ("drift", "fx_drif", "drift_g", 200, -522, FLOOR_Z + 92),
    ("breathing", "fx_brea", "drift_a", 250, -522, FLOOR_Z + 92),
]


def load_media_mount_contracts(path=MEDIA_MOUNT_CONTRACTS_PATH):
    """Load deterministic media mount contracts used by map/runtime producers."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_surface_contracts(path=SURFACE_CONTRACTS_PATH):
    """Load deterministic room-surface contracts used by BSP substrate generation."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_spatiotemporal_framework(path=SPATIOTEMPORAL_FRAMEWORK_PATH):
    """Load operative spatial/temporal/media constraints for Screwm generation."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_homage_pack(path=HOMAGE_PACK_PATH):
    """Load the active reference Homage pack used to express mount profiles."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_default_source_dimensions(path=DEFAULT_COMPOSITOR_LAYOUT_PATH):
    """Return natural source dimensions for ward-aspect contracts."""
    data = json.loads(path.read_text(encoding="utf-8"))
    dimensions = {}
    for source in data.get("sources", []):
        params = source.get("params") or {}
        width = int(params.get("natural_w") or 0)
        height = int(params.get("natural_h") or 0)
        if width > 0 and height > 0:
            dimensions[source["id"]] = (width, height)
    return dimensions


MEDIA_MOUNT_CONTRACTS = load_media_mount_contracts()
SURFACE_CONTRACTS = load_surface_contracts()
MEDIA_MOUNTS_BY_ID = {mount["id"]: mount for mount in MEDIA_MOUNT_CONTRACTS["mounts"]}
MEDIA_MOUNTS_BY_TEXTURE = {
    mount["texture"]: mount for mount in MEDIA_MOUNT_CONTRACTS["mounts"] if "texture" in mount
}
SURFACE_CONTRACTS_BY_ROLE = {surface["role"]: surface for surface in SURFACE_CONTRACTS["surfaces"]}
SPATIOTEMPORAL_FRAMEWORK = load_spatiotemporal_framework()
HOMAGE_PACK = load_homage_pack()
HOMAGE_PROFILE_BINDINGS = HOMAGE_PACK.get("material_profile_bindings", {})
DEFAULT_SOURCE_DIMENSIONS = load_default_source_dimensions()
STATIC_WARD_MOUNT_PROFILE = "state-ward-instrument"


def aspect_height(width, source_aspect):
    aspect_w, aspect_h = source_aspect
    return int(round(width * aspect_h / aspect_w))


def source_anchor_from_mount(mount):
    width = int(mount["physical_width"])
    return {
        "role": mount["id"],
        "texture": mount["texture"],
        "camera_class": mount["id"].split("-", 1)[0],
        "domain": mount["domain"],
        "pos": tuple(int(v) for v in mount["origin"]),
        "facing": mount.get("facing", "y"),
        "w": width,
        "h": aspect_height(width, mount["source_aspect"]),
        "texture_size": tuple(int(v) for v in mount["texture_size"]),
        "texture_transform": mount.get("texture_transform"),
        "producer_output": mount["producer_output"],
        "projection": mount["projection"],
        "mount": mount,
    }


SOURCE_ANCHORS = [
    source_anchor_from_mount(mount)
    for mount in MEDIA_MOUNT_CONTRACTS["mounts"]
    if mount.get("role") == "camera-source"
]

ACTIVE_WARD_MOUNTS_BY_INDEX = {
    int(mount["texture"][1:]): mount
    for mount in MEDIA_MOUNT_CONTRACTS["mounts"]
    if isinstance(mount.get("texture"), str)
    and mount["texture"].startswith("w")
    and mount["texture"][1:].isdigit()
}
WARD_ATLAS_MOUNT = MEDIA_MOUNTS_BY_ID.get("ward-atlas")
WARD_ATLAS_CELL_W, WARD_ATLAS_CELL_H = (
    tuple(int(v) for v in WARD_ATLAS_MOUNT.get("cell_size", [512, 256]))
    if WARD_ATLAS_MOUNT
    else (512, 256)
)
WARD_ATLAS_COLUMNS = int(WARD_ATLAS_MOUNT.get("atlas_columns", 4)) if WARD_ATLAS_MOUNT else 4
WARD_ATLAS_VISIBLE_INDICES = (
    frozenset(int(value) for value in WARD_ATLAS_MOUNT.get("active_visible_indices", []))
    if WARD_ATLAS_MOUNT
    else frozenset()
)
ACTIVE_WARD_INDICES = frozenset(ACTIVE_WARD_MOUNTS_BY_INDEX) | WARD_ATLAS_VISIBLE_INDICES

# Current visual baseline: the compositor owns the ward pixels through the
# live atlas; DarkPlaces owns the spatial mount, occlusion, lighting, and camera.
BASELINE_SOURCE_ROLES = {source["role"] for source in SOURCE_ANCHORS}


def validate_spatiotemporal_framework():
    """Fail generation when the current scene violates non-optional framework gates."""
    framework = SPATIOTEMPORAL_FRAMEWORK
    spatial = framework["spatial_constraints"]
    media = framework["media_constraints"]
    media_theory = framework.get("media_theory_constraints", {})
    camera = framework["camera_temporal_constraints"]
    anti_parasocial = framework["anti_parasocial_constraints"]

    failures = []
    if framework.get("status") != "operative_required":
        failures.append("framework status is not operative_required")
    if len(framework.get("research_lanes", [])) != 8:
        failures.append("framework must preserve eight research lanes")
    if spatial.get("units_per_meter") != UNITS_PER_METER:
        failures.append("framework units_per_meter does not match generator")

    room_width_m = (ROOM_X_EXT * 2) / UNITS_PER_METER
    room_depth_m = (ROOM_Y_MAX - ROOM_Y_MIN) / UNITS_PER_METER
    room_height_m = (CEIL_Z - FLOOR_Z) / UNITS_PER_METER
    if room_width_m < spatial["minimum_room_width_m"]:
        failures.append(f"room width {room_width_m:.2f}m below framework minimum")
    if room_depth_m < spatial["minimum_room_depth_m"]:
        failures.append(f"room depth {room_depth_m:.2f}m below framework minimum")
    if room_height_m < spatial["minimum_room_height_m"]:
        failures.append(f"room height {room_height_m:.2f}m below framework minimum")
    if len(GARDEN_CAMERA_STATIONS) < spatial["target_primary_loop_station_count"]:
        failures.append("garden path does not expose enough pause stations")
    if not spatial.get("no_front_required"):
        failures.append("framework must require no-front spatial organization")
    for key in (
        "screens_are_spatial_objects_not_windows",
        "remediation_contract_required",
        "medium_specificity_required",
        "homage_technology_must_remain_swappable",
        "portable_framework_must_not_embed_homage_specific_assets",
        "deep_homage_pack_must_remain_data_profile",
        "material_profile_binding_required",
        "mount_projection_must_be_declared_before_runtime",
        "fourth_wall_surface_is_not_entity",
        "screen_space_overlays_forbidden_for_final_wards",
        "physical_bsp_mount_chrome_disabled_by_default",
        "mount_expression_must_be_coordinate_bound_to_receiver",
        "true_temporal_history_belongs_to_compositor",
    ):
        if not media_theory.get(key):
            failures.append(f"media-theory constraint {key} is not enabled")
    for key in (
        "camera_wards_are_instruments_not_intimacy_billboards",
        "forbid_extractive_face_hero_default",
        "operator_presence_must_be_mediated_by_system_role",
        "audience_address_must_be_operational_not_simulated_rapport",
        "spatialized_presence_required",
        "camera_wards_must_not_own_the_centerline_by_default",
        "object_of_attention_discipline_required",
        "viewer_agency_targets_space_or_object_not_personality",
        "ticker_text_must_be_operational_not_intimate_address",
        "reveal_hide_cycle_required_for_presence_media",
    ):
        if not anti_parasocial.get(key):
            failures.append(f"anti-parasocial constraint {key} is not enabled")
    if anti_parasocial.get("max_face_dominant_camera_wards_per_pause_view") != 1:
        failures.append("anti-parasocial face-dominance budget must stay at one")

    forbidden_homage_tokens = tuple(
        str(token).lower()
        for token in media_theory.get("portable_mount_forbidden_homage_tokens", [])
    )
    required_mount_expression_fields = set(
        media_theory.get("required_homage_mount_expression_fields", [])
    )
    required_fields = set(media["required_mount_fields"])
    required_flat_fields = set(media.get("required_flat_mount_fields", []))
    required_sphere_fields = set(media.get("required_sphere_mount_fields", []))
    required_camera_fields = set(media.get("required_camera_mount_fields", []))
    required_hybrid_fields = set(media.get("required_hybrid_contract_fields", []))
    required_source_context = set(anti_parasocial.get("required_source_context", []))
    for mount in MEDIA_MOUNT_CONTRACTS["mounts"]:
        missing = sorted(required_fields - mount.keys())
        if missing:
            failures.append(f"media mount {mount.get('id', '<unknown>')} missing {missing}")
        material_profile = str(mount.get("material_profile", "")).lower()
        for token in forbidden_homage_tokens:
            if token and token in material_profile:
                failures.append(
                    f"media mount {mount.get('id', '<unknown>')} embeds Homage token "
                    f"{token!r} in portable material_profile"
                )
        profile = mount.get("material_profile")
        binding = HOMAGE_PROFILE_BINDINGS.get(profile)
        if media_theory.get("material_profile_binding_required") and binding is None:
            failures.append(
                f"media mount {mount.get('id', '<unknown>')} material_profile "
                f"{profile!r} is not bound by active Homage pack"
            )
        expression = (binding or {}).get("mount_expression")
        if media_theory.get("material_profile_binding_required") and not isinstance(
            expression, dict
        ):
            failures.append(
                f"media mount {mount.get('id', '<unknown>')} material_profile "
                f"{profile!r} lacks mount_expression"
            )
        elif expression:
            missing_expression = sorted(required_mount_expression_fields - expression.keys())
            if missing_expression:
                failures.append(
                    f"media mount {mount.get('id', '<unknown>')} mount_expression missing "
                    f"{missing_expression}"
                )
        hybrid_contract = mount.get("hybrid_contract")
        if not isinstance(hybrid_contract, dict):
            failures.append(f"media mount {mount.get('id', '<unknown>')} missing hybrid_contract")
        else:
            missing_hybrid = sorted(required_hybrid_fields - hybrid_contract.keys())
            if missing_hybrid:
                failures.append(
                    f"media mount {mount.get('id', '<unknown>')} hybrid_contract missing "
                    f"{missing_hybrid}"
                )
        missing_context = sorted(required_source_context - mount.keys())
        if missing_context:
            failures.append(
                f"media mount {mount.get('id', '<unknown>')} missing source context "
                f"{missing_context}"
            )
        native = mount.get("native_resolution")
        if not isinstance(native, list) or len(native) != 2 or min(native) <= 0:
            failures.append(
                f"media mount {mount.get('id', '<unknown>')} has invalid native_resolution"
            )
        view_distance = float(mount.get("intended_view_distance", 0))
        target_angle = float(mount.get("target_visual_angle_deg", 0))
        computed_width = float(mount.get("computed_mount_width", 0))
        if view_distance <= 0 or target_angle <= 0 or computed_width <= 0:
            failures.append(
                f"media mount {mount.get('id', '<unknown>')} lacks positive view/angle/width contract"
            )
        else:
            expected_width = 2 * view_distance * math.tan(math.radians(target_angle) / 2)
            if abs(expected_width - computed_width) > max(4.0, expected_width * 0.025):
                failures.append(
                    f"media mount {mount.get('id', '<unknown>')} computed width "
                    f"{computed_width:.1f} does not match {target_angle:.1f}deg at "
                    f"{view_distance:.1f}u"
                )
            if target_angle < media["minimum_inspection_visual_angle_deg"]:
                failures.append(
                    f"media mount {mount.get('id', '<unknown>')} target visual angle below inspection minimum"
                )
            if target_angle > media["target_hero_media_visual_angle_deg_max"]:
                failures.append(
                    f"media mount {mount.get('id', '<unknown>')} target visual angle exceeds hero maximum"
                )
            if isinstance(native, list) and len(native) == 2:
                px_per_degree = native[0] / target_angle
                if px_per_degree < media["minimum_media_px_per_degree"]:
                    failures.append(
                        f"media mount {mount.get('id', '<unknown>')} below px/degree legibility floor"
                    )
        if str(mount.get("projection", "")).startswith("flat"):
            missing_flat = sorted(required_flat_fields - mount.keys())
            if missing_flat:
                failures.append(
                    f"flat media mount {mount.get('id', '<unknown>')} missing {missing_flat}"
                )
            if mount.get("visible_border") is not False:
                failures.append(
                    f"flat media mount {mount.get('id', '<unknown>')} allows a visible border"
                )
            if mount.get("visible_backing_panel") is not False:
                failures.append(
                    f"flat media mount {mount.get('id', '<unknown>')} allows a backing panel"
                )
            if mount.get("visible_grid_background") is not False:
                failures.append(
                    f"flat media mount {mount.get('id', '<unknown>')} allows a grid background"
                )
            if mount.get("physical_chrome") != "forbidden":
                failures.append(
                    f"flat media mount {mount.get('id', '<unknown>')} allows physical chrome"
                )
            if mount.get("edge_faces") != "hidden_or_zero_contrast":
                failures.append(
                    f"flat media mount {mount.get('id', '<unknown>')} exposes non-receiver edge faces"
                )
            if "legibility" not in str(mount.get("size_policy", "")):
                failures.append(
                    f"flat media mount {mount.get('id', '<unknown>')} lacks legibility size policy"
                )
            physical_width = float(mount.get("physical_width", 0))
            if computed_width > 0 and abs(physical_width - computed_width) > max(
                4.0, computed_width * 0.025
            ):
                failures.append(
                    f"flat media mount {mount.get('id', '<unknown>')} physical width "
                    "does not match computed visual-angle width"
                )
        if mount.get("surface") == "sphere":
            missing_sphere = sorted(required_sphere_fields - mount.keys())
            if missing_sphere:
                failures.append(
                    f"sphere media mount {mount.get('id', '<unknown>')} missing {missing_sphere}"
                )
            clearance_ratio = float(mount.get("enclosure_clearance_ratio", 0))
            fill_ratio = float(mount.get("inner_void_radius_fill_ratio", 0))
            if clearance_ratio < media.get("minimum_aoa_inner_void_clearance_ratio", 0):
                failures.append(
                    f"sphere media mount {mount.get('id', '<unknown>')} below inner-void clearance"
                )
            if fill_ratio <= 0 or fill_ratio > media.get(
                "maximum_aoa_oarb_inner_void_radius_fill_ratio", 1.0
            ):
                failures.append(
                    f"sphere media mount {mount.get('id', '<unknown>')} has invalid inner-void fill"
                )
            if clearance_ratio > 0 and abs(fill_ratio - (1.0 / clearance_ratio)) > 0.0001:
                failures.append(
                    f"sphere media mount {mount.get('id', '<unknown>')} fill does not invert clearance"
                )
            physical_width = float(mount.get("physical_radius", 0)) * 2
            if computed_width > 0 and abs(physical_width - computed_width) > max(
                4.0, computed_width * 0.025
            ):
                failures.append(
                    f"sphere media mount {mount.get('id', '<unknown>')} diameter "
                    "does not match computed visual-angle width"
                )
        if mount.get("role") == "camera-source":
            missing_camera = sorted(required_camera_fields - mount.keys())
            if missing_camera:
                failures.append(f"camera mount {mount['id']} missing {missing_camera}")
            tex_w, tex_h = mount["texture_size"]
            if tex_w < media["minimum_camera_texture_width_px"]:
                failures.append(f"camera mount {mount['id']} texture width below minimum")
            if tex_h < media["minimum_camera_texture_height_px"]:
                failures.append(f"camera mount {mount['id']} texture height below minimum")
            # Preferred 1080p camera mounts remain an upgrade target; the hard
            # gate follows the currently deployed 720p live-texture boundary.
            if native != mount["texture_size"]:
                failures.append(
                    f"camera mount {mount['id']} native_resolution must match texture_size"
                )
            if mount.get("capture_resolution") != mount["texture_size"]:
                failures.append(
                    f"camera mount {mount['id']} capture_resolution must match texture_size"
                )
            if mount.get("capture_fps", 0) < media.get("camera_capture_fps_min", 0):
                failures.append(f"camera mount {mount['id']} capture_fps below minimum")
            aspect_w, aspect_h = mount["source_aspect"]
            if tex_w * aspect_h != tex_h * aspect_w:
                failures.append(f"camera mount {mount['id']} texture aspect does not match source")
            expected_h = aspect_height(int(mount["physical_width"]), (aspect_w, aspect_h))
            if expected_h <= 0:
                failures.append(f"camera mount {mount['id']} has invalid aspect height")
        if mount.get("id") == "aoa-media-sphere":
            tex_w, tex_h = mount["texture_size"]
            if tex_w < media["minimum_aoa_sphere_texture_width_px"]:
                failures.append("AoA sphere texture width below framework minimum")
            if tex_h < media["minimum_aoa_sphere_texture_height_px"]:
                failures.append("AoA sphere texture height below framework minimum")

        drift_interaction = mount.get("drift_interaction")
        if not isinstance(drift_interaction, dict) or not drift_interaction.get("owner"):
            failures.append(
                f"media mount {mount.get('id', '<unknown>')} lacks drift interaction owner"
            )
        elif not drift_interaction.get("families"):
            failures.append(
                f"media mount {mount.get('id', '<unknown>')} lacks drift interaction families"
            )
        if expression:
            layers = expression.get("layers") or []
            forbidden_layers = {
                "shadow_backing",
                "beveled_outer_frame",
                "corner_ticks",
                "standoff_posts",
                "status_spine",
                "terminal_header_rail",
            }
            leaked_layers = sorted(set(layers) & forbidden_layers)
            if leaked_layers:
                failures.append(
                    f"media mount {mount.get('id', '<unknown>')} Homage expression emits "
                    f"forbidden mount layers {leaked_layers}"
                )

    if camera["target_fps"] != 60:
        failures.append("framework target fps must remain 60 for the OBS route")
    if not camera.get("manual_control_noclip_required"):
        failures.append("manual control must remain noclip-capable")
    if camera.get("review_path_period_s_min", 0) < 300:
        failures.append("framework review path minimum period must be at least 300s")
    if camera.get("review_path_period_s_target", 0) < camera.get("review_path_period_s_min", 0):
        failures.append("framework review path target is below minimum period")

    if failures:
        raise ValueError("Screwm spatiotemporal framework violation: " + "; ".join(failures))


def validate_surface_contracts():
    """Fail generation if room-scale surfaces fall back to arbitrary Quake materials."""
    required_roles = {"floor", "ceiling", "wall"}
    required_fields = {
        "id",
        "role",
        "surface_kind",
        "substrate",
        "texture",
        "producer_kind",
        "source_id",
        "freshness",
        "consent_or_license",
        "purpose",
        "material_profile",
        "projection",
        "texture_scale",
        "texture_optional",
        "live_texture_slot_required",
        "hybrid_contract",
    }
    required_hybrid_fields = set(
        SPATIOTEMPORAL_FRAMEWORK["media_constraints"]["required_hybrid_contract_fields"]
    )
    forbidden_textures = {"city4_2", "ground1_6", "sky4"}
    failures = []

    if SURFACE_CONTRACTS.get("version") != "screwm-quake-surface-contracts-v1":
        failures.append("surface contract version is not screwm-quake-surface-contracts-v1")
    info_contract = SURFACE_CONTRACTS.get("information_surface_contract", {})
    required_info_fields = {
        "principle",
        "admissible_texture_types",
        "required_semantic_channels",
        "forbidden_material_semantics",
        "failure_predicates",
    }
    missing_info_fields = required_info_fields - set(info_contract)
    if missing_info_fields:
        failures.append(
            f"information surface contract missing fields: {sorted(missing_info_fields)}"
        )
    if "quake_scenic_material" not in set(info_contract.get("forbidden_material_semantics", [])):
        failures.append("information surface contract must forbid Quake scenic material identity")
    if "clean_room_homage_chrome" not in set(info_contract.get("admissible_texture_types", [])):
        failures.append(
            "information surface contract must preserve clean-room Homage texture grammar"
        )
    if set(SURFACE_CONTRACTS_BY_ROLE) != required_roles:
        failures.append("surface contracts must define floor, ceiling, and wall roles exactly")

    for surface in SURFACE_CONTRACTS["surfaces"]:
        missing = required_fields - set(surface)
        if missing:
            failures.append(f"{surface.get('id', '<unknown>')} missing fields: {sorted(missing)}")
        hybrid = surface.get("hybrid_contract", {})
        missing_hybrid = required_hybrid_fields - set(hybrid)
        if missing_hybrid:
            failures.append(
                f"{surface.get('id', '<unknown>')} missing hybrid fields: {sorted(missing_hybrid)}"
            )
        texture = surface.get("texture")
        if texture in forbidden_textures:
            failures.append(
                f"{surface.get('id', '<unknown>')} uses forbidden scenic texture {texture}"
            )
        if surface.get("producer_kind") != "hapax-compositor-drift-material":
            failures.append(f"{surface.get('id', '<unknown>')} is not compositor/drift-derived")
        if not str(surface.get("material_profile", "")).startswith("room-"):
            failures.append(f"{surface.get('id', '<unknown>')} lacks room material profile")
        texture_scale = surface.get("texture_scale", [])
        if (
            not isinstance(texture_scale, list)
            or len(texture_scale) != 2
            or any(float(value) < 3.0 for value in texture_scale)
        ):
            failures.append(
                f"{surface.get('id', '<unknown>')} texture_scale must be a 2-axis non-material repeat scale"
            )

    if failures:
        raise ValueError("Screwm surface contract violation: " + "; ".join(failures))


validate_spatiotemporal_framework()
validate_surface_contracts()

MODE_PRESETS = {
    "rnd": {
        "wall_tex": "cmp_wall",
        "floor_tex": "cmp_floor",
        "ceil_tex": "cmp_ceil",
        "ramp_tex": "metal5_2",
        "level_wall_tex": ["cmp_wall", "cmp_wall", "cmp_wall", "cmp_wall", "cmp_wall"],
        "level_ledge_tex": ["cmp_wall", "cmp_wall", "cmp_wall", "cmp_wall", "cmp_wall"],
        "pedestal_tex": "drift_a",
        "fog": "0.015 0.10 0.075 0.055",
        "level_light": 285,
        "wall_light": 105,
        "aoa_light_value": 290,
        "lights": [
            (1.0, 0.71, 0.39),
            (0.90, 0.65, 0.30),
            (0.78, 0.39, 0.60),
            (0.70, 0.85, 0.35),
            (1.0, 0.50, 0.25),
        ],
        "aoa_light": (1.0, 0.78, 0.50),
        "message": "The Screwm [R&D]",
    },
    "research": {
        "wall_tex": "cmp_wall",
        "floor_tex": "cmp_floor",
        "ceil_tex": "cmp_ceil",
        "ramp_tex": "metal5_2",
        "level_wall_tex": ["cmp_wall", "cmp_wall", "cmp_wall", "cmp_wall", "cmp_wall"],
        "level_ledge_tex": ["cmp_wall", "cmp_wall", "cmp_wall", "cmp_wall", "cmp_wall"],
        "pedestal_tex": "drift_c",
        "fog": "0.014 0.035 0.07 0.10",
        "level_light": 255,
        "wall_light": 90,
        "aoa_light_value": 250,
        "lights": [
            (0.40, 0.65, 0.80),
            (0.30, 0.55, 0.75),
            (0.50, 0.40, 0.70),
            (0.35, 0.70, 0.55),
            (0.60, 0.45, 0.45),
        ],
        "aoa_light": (0.50, 0.65, 0.80),
        "message": "The Screwm [Research]",
    },
}


def level_texture_bands(preset, key="level_wall_tex"):
    textures = preset.get(key) or [preset["wall_tex"]] * len(LEVEL_BANDS)
    return [
        (name, z1, z2, textures[min(idx, len(textures) - 1)])
        for idx, (name, z1, z2) in enumerate(LEVEL_BANDS)
    ]


def fmt_plane(
    p1,
    p2,
    p3,
    tex,
    texture_scale=(1, 1),
    texture_rotation=0,
    texture_shift=(0, 0),
):
    scale_x, scale_y = texture_scale
    shift_x, shift_y = texture_shift
    return (
        f"( {p1[0]} {p1[1]} {p1[2]} ) "
        f"( {p2[0]} {p2[1]} {p2[2]} ) "
        f"( {p3[0]} {p3[1]} {p3[2]} ) "
        f"{tex} {shift_x:.6g} {shift_y:.6g} {texture_rotation:.6g} "
        f"{scale_x:.6g} {scale_y:.6g}"
    )


def box_brush(
    x1,
    y1,
    z1,
    x2,
    y2,
    z2,
    tex,
    texture_scale=(1, 1),
    texture_rotation=0,
    texture_shift=(0, 0),
):
    mn = [min(x1, x2), min(y1, y2), min(z1, z2)]
    mx = [max(x1, x2), max(y1, y2), max(z1, z2)]
    if mx[0] - mn[0] < 1 or mx[1] - mn[1] < 1 or mx[2] - mn[2] < 1:
        return None
    planes = [
        fmt_plane(
            (mn[0], mn[1], mn[2]),
            (mn[0], mx[1], mn[2]),
            (mn[0], mn[1], mx[2]),
            tex,
            texture_scale,
            texture_rotation,
            texture_shift,
        ),
        fmt_plane(
            (mx[0], mn[1], mn[2]),
            (mx[0], mn[1], mx[2]),
            (mx[0], mx[1], mn[2]),
            tex,
            texture_scale,
            texture_rotation,
            texture_shift,
        ),
        fmt_plane(
            (mn[0], mn[1], mn[2]),
            (mn[0], mn[1], mx[2]),
            (mx[0], mn[1], mn[2]),
            tex,
            texture_scale,
            texture_rotation,
            texture_shift,
        ),
        fmt_plane(
            (mn[0], mx[1], mn[2]),
            (mx[0], mx[1], mn[2]),
            (mn[0], mx[1], mx[2]),
            tex,
            texture_scale,
            texture_rotation,
            texture_shift,
        ),
        fmt_plane(
            (mn[0], mn[1], mn[2]),
            (mx[0], mn[1], mn[2]),
            (mn[0], mx[1], mn[2]),
            tex,
            texture_scale,
            texture_rotation,
            texture_shift,
        ),
        fmt_plane(
            (mn[0], mn[1], mx[2]),
            (mn[0], mx[1], mx[2]),
            (mx[0], mn[1], mx[2]),
            tex,
            texture_scale,
            texture_rotation,
            texture_shift,
        ),
    ]
    return "{\n" + "\n".join(planes) + "\n}"


def media_pane_brush(
    x1,
    y1,
    z1,
    x2,
    y2,
    z2,
    live_tex,
    edge_tex,
    front_face,
    texture_scale=(1, 1),
    texture_rotation=0,
    texture_shift=(0, 0),
):
    """Return a pane whose live media exists on exactly one truth-bearing face."""
    mn = [min(x1, x2), min(y1, y2), min(z1, z2)]
    mx = [max(x1, x2), max(y1, y2), max(z1, z2)]
    if mx[0] - mn[0] < 1 or mx[1] - mn[1] < 1 or mx[2] - mn[2] < 1:
        return None

    plane_defs = [
        (
            "x_min",
            (mn[0], mn[1], mn[2]),
            (mn[0], mx[1], mn[2]),
            (mn[0], mn[1], mx[2]),
        ),
        (
            "x_max",
            (mx[0], mn[1], mn[2]),
            (mx[0], mn[1], mx[2]),
            (mx[0], mx[1], mn[2]),
        ),
        (
            "y_min",
            (mn[0], mn[1], mn[2]),
            (mn[0], mn[1], mx[2]),
            (mx[0], mn[1], mn[2]),
        ),
        (
            "y_max",
            (mn[0], mx[1], mn[2]),
            (mx[0], mx[1], mn[2]),
            (mn[0], mx[1], mx[2]),
        ),
        (
            "z_min",
            (mn[0], mn[1], mn[2]),
            (mx[0], mn[1], mn[2]),
            (mn[0], mx[1], mn[2]),
        ),
        (
            "z_max",
            (mn[0], mn[1], mx[2]),
            (mn[0], mx[1], mx[2]),
            (mx[0], mn[1], mx[2]),
        ),
    ]

    opposite_face = {
        "x_min": "x_max",
        "x_max": "x_min",
        "y_min": "y_max",
        "y_max": "y_min",
        "z_min": "z_max",
        "z_max": "z_min",
    }[front_face]

    planes = []
    for face, p1, p2, p3 in plane_defs:
        if face in (front_face, opposite_face):
            planes.append(
                fmt_plane(
                    p1,
                    p2,
                    p3,
                    live_tex,
                    texture_scale,
                    texture_rotation,
                    texture_shift,
                )
            )
        else:
            # Side faces are only Quake's finite brush thickness. Mapping the
            # same live receiver texture prevents them reading as a separate
            # physical frame around the ward.
            planes.append(
                fmt_plane(p1, p2, p3, live_tex, texture_scale, texture_rotation, texture_shift)
            )
    return "{\n" + "\n".join(planes) + "\n}"


def inward_x_normal(x):
    return 1 if x < 0 else -1


def inward_y_normal(y):
    return 1 if y < (ROOM_Y_MIN + ROOM_Y_MAX) // 2 else -1


def offset_span(center, direction, near, far):
    return tuple(sorted((center + direction * near, center + direction * far)))


def pane_light_origin(x, y, z, facing, distance):
    if facing == "x":
        return x + inward_x_normal(x) * distance, y, z
    return x, y + inward_y_normal(y) * distance, z


def pane_texture_scale(w, h, texture_size=None, texture_transform=None):
    if not texture_size:
        return (1, 1)
    tex_w, tex_h = texture_size
    scale_x = max(0.03125, w / tex_w)
    scale_y = max(0.03125, h / tex_h)
    if texture_transform:
        scale_x *= int(texture_transform.get("u_sign", 1))
        scale_y *= int(texture_transform.get("v_sign", 1))
    return (scale_x, scale_y)


def pane_texture_rotation(texture_transform=None):
    if not texture_transform:
        return 0
    return int(texture_transform.get("rotation", 0))


def pane_texture_shift(x, y, z, w, h, facing, texture_scale, texture_transform=None):
    if not texture_transform or not texture_transform.get("surface_local"):
        return (0, 0)
    scale_x, scale_y = texture_scale
    u_offset = int(texture_transform.get("u_offset_px", 0))
    v_offset = int(texture_transform.get("v_offset_px", 0))
    if facing == "x":
        return (u_offset - (y - w / 2) / scale_x, v_offset + (z + h / 2) / scale_y)
    return (u_offset - (x - w / 2) / scale_x, v_offset + (z + h / 2) / scale_y)


def centered_span(center, size):
    """Integer brush span whose length is exactly the declared media size."""
    start = int(center) - int(size) // 2
    return start, start + int(size)


def framed_y_pane(
    comment_prefix,
    idx,
    name,
    tex,
    frame_tex,
    x,
    y,
    z,
    w,
    h,
    texture_size=None,
    texture_transform=None,
):
    """Return a y-facing truth-bearing media pane.

    Mount expression is compositor/CSQC-owned. BSP brush chrome made the
    wards read as Quake objects and produced visible non-media clutter, so the
    map generator only emits the declared receiver surface.
    """
    brushes = []
    texture_scale = pane_texture_scale(w, h, texture_size, texture_transform)
    x0, x1 = centered_span(x, w)
    z0, z1 = centered_span(z, h)
    pane = media_pane_brush(
        x0,
        y - 1,
        z0,
        x1,
        y + 1,
        z1,
        tex,
        MEDIA_RECEIVER_EDGE_TEX,
        "y_max" if inward_y_normal(y) > 0 else "y_min",
        texture_scale=texture_scale,
        texture_rotation=pane_texture_rotation(texture_transform),
        texture_shift=pane_texture_shift(x, y, z, w, h, "y", texture_scale, texture_transform),
    )
    if pane:
        brushes.append(f"// {comment_prefix} {idx:02d}: {name} {tex}\n{pane}")

    return brushes


def framed_x_pane(
    comment_prefix,
    idx,
    name,
    tex,
    frame_tex,
    x,
    y,
    z,
    w,
    h,
    texture_size=None,
    texture_transform=None,
):
    """Return an x-facing truth-bearing media pane.

    Mount expression is compositor/CSQC-owned. BSP brush chrome made the
    wards read as Quake objects and produced visible non-media clutter, so the
    map generator only emits the declared receiver surface.
    """
    brushes = []
    texture_scale = pane_texture_scale(w, h, texture_size, texture_transform)
    y0, y1 = centered_span(y, w)
    z0, z1 = centered_span(z, h)
    pane = media_pane_brush(
        x - 1,
        y0,
        z0,
        x + 1,
        y1,
        z1,
        tex,
        MEDIA_RECEIVER_EDGE_TEX,
        "x_max" if inward_x_normal(x) > 0 else "x_min",
        texture_scale=texture_scale,
        texture_rotation=pane_texture_rotation(texture_transform),
        texture_shift=pane_texture_shift(x, y, z, w, h, "x", texture_scale, texture_transform),
    )
    if pane:
        brushes.append(f"// {comment_prefix} {idx:02d}: {name} {tex}\n{pane}")

    return brushes


def framed_garden_pane(
    comment_prefix,
    idx,
    name,
    tex,
    frame_tex,
    x,
    y,
    z,
    w,
    h,
    facing,
    texture_size=None,
    texture_transform=None,
    mount=None,
):
    if facing == "x":
        brushes = framed_x_pane(
            comment_prefix,
            idx,
            name,
            tex,
            frame_tex,
            x,
            y,
            z,
            w,
            h,
            texture_size,
            texture_transform,
        )
    else:
        brushes = framed_y_pane(
            comment_prefix,
            idx,
            name,
            tex,
            frame_tex,
            x,
            y,
            z,
            w,
            h,
            texture_size,
            texture_transform,
        )
    brushes.extend(
        homage_mount_chrome(comment_prefix, idx, name, mount, frame_tex, x, y, z, w, h, facing)
    )
    return brushes


def mount_expression_for_mount(mount):
    if not mount:
        return {}
    profile = mount.get("material_profile")
    binding = HOMAGE_PROFILE_BINDINGS.get(profile, {})
    return binding.get("mount_expression", {}) or {}


def mount_chrome_textures(expression, frame_tex):
    textures = expression.get("chrome_textures", {}) if expression else {}
    return {
        "backing": textures.get("backing", "scroom"),
        "accent": textures.get("accent", frame_tex),
        "shadow": textures.get("shadow", "metal5_2"),
        "primary": frame_tex,
    }


def add_mount_brush(brushes, comment_prefix, idx, name, part, brush):
    if brush:
        brushes.append(f"// {comment_prefix}-mount-{part} {idx:02d}: {name}\n{brush}")


def homage_mount_chrome(comment_prefix, idx, name, mount, frame_tex, x, y, z, w, h, facing):
    """Return physical Homage-pack mount chrome around a declared ward surface.

    Disabled for the clean Scroom baseline. Mounts are still declared by the
    media contract, but visible mount expression must be supplied by
    compositor/CSQC effects bound to the media surface, not by extra BSP chrome.
    """
    return []


def ward_state_lamp(idx, anchor, glow_tex, x, y, z, w, h, facing):
    """Physical live-state receiver beside a ward pane.

    CSQC cannot rewrite BSP textures every frame, so each ward gets a small
    in-world lamp/spine next to its baked identity texture. Dynamic ward lights
    illuminate these receivers from live activity/presence scalars.
    """
    # Suppressed in the clean Scroom baseline. State belongs in the live atlas,
    # dynamic lights, and compositor-bound mount field, not as duplicate BSP
    # geometry beside the media.
    return []


def axis_beam_segments(comment_prefix, idx, name, tex, start, end, thickness=3):
    """Return orthogonal thin beam segments approximating a volumetric ray."""
    sx, sy, sz = start
    ex, ey, ez = end
    joints = ((sx, sy, sz), (ex, sy, sz), (ex, ey, sz), (ex, ey, ez))
    brushes = []

    for part_idx, (a, b) in enumerate(zip(joints[:-1], joints[1:], strict=True), start=1):
        ax, ay, az = a
        bx, by, bz = b
        if a == b:
            continue
        segment = box_brush(
            min(ax, bx) - thickness,
            min(ay, by) - thickness,
            min(az, bz) - thickness,
            max(ax, bx) + thickness,
            max(ay, by) + thickness,
            max(az, bz) + thickness,
            tex,
        )
        if segment:
            brushes.append(f"// {comment_prefix} {idx:02d}.{part_idx}: {name} {tex}\n{segment}")

    return brushes


def ward_anchor_position(idx):
    if idx in WARD_GARDEN_LAYOUT:
        x, y, z, _facing = WARD_GARDEN_LAYOUT[idx]
        return x, y, z
    if idx in SPECIAL_WARD_POSITIONS:
        return SPECIAL_WARD_POSITIONS[idx]
    col = (idx - 1) % WARD_COLUMNS
    row = (idx - 1) // WARD_COLUMNS
    x = int((col - (WARD_COLUMNS - 1) * 0.5) * WARD_X_SPACING)
    y = WARD_Y_TOP + row * WARD_Y_STEP
    z = int(WARD_TOP_Z - row * WARD_Z_SPACING)
    return x, y, z


def ward_review_position(idx):
    return ward_anchor_position(idx)


def ward_garden_facing(idx):
    if idx in WARD_GARDEN_LAYOUT:
        return WARD_GARDEN_LAYOUT[idx][3]
    return "y"


def ward_review_drift_midpoint(src, dst):
    x1, y1, z1 = ward_review_position(src)
    x2, y2, z2 = ward_review_position(dst)
    return (x1 + x2) // 2, (y1 + y2) // 2, (z1 + z2) // 2


def ward_domain(idx):
    return WARD_DOMAINS[WARD_ANCHORS[idx - 1]]


def ward_depth_plane(idx):
    return WARD_DEPTH_PLANES.get(WARD_ANCHORS[idx - 1], "near-surface")


def ward_atlas_cell(idx):
    col = (idx - 1) % WARD_ATLAS_COLUMNS
    row = (idx - 1) // WARD_ATLAS_COLUMNS
    return col, row


def ward_atlas_texture_transform(idx):
    col, row = ward_atlas_cell(idx)
    return {
        "u_sign": 1,
        "v_sign": 1,
        "rotation": 0,
        "surface_local": True,
        "u_offset_px": col * WARD_ATLAS_CELL_W,
        "v_offset_px": row * WARD_ATLAS_CELL_H,
        "reason": "Ward atlas cells are selected by deterministic surface-local UV offsets",
    }


def reduced_aspect(width, height):
    divisor = math.gcd(max(1, int(width)), max(1, int(height)))
    return [max(1, int(width) // divisor), max(1, int(height) // divisor)]


def ward_source_aspect(idx, anchor):
    direct_mount = ACTIVE_WARD_MOUNTS_BY_INDEX.get(idx)
    if direct_mount and direct_mount.get("source_aspect"):
        return list(direct_mount["source_aspect"])
    width, height = DEFAULT_SOURCE_DIMENSIONS.get(anchor, (WARD_ATLAS_CELL_W, WARD_ATLAS_CELL_H))
    return reduced_aspect(width, height)


def ward_source_mount_width(idx, anchor):
    direct_mount = ACTIVE_WARD_MOUNTS_BY_INDEX.get(idx)
    if direct_mount and direct_mount.get("physical_width"):
        return int(direct_mount["physical_width"])
    aspect_w, aspect_h = ward_source_aspect(idx, anchor)
    aspect = aspect_w / max(1, aspect_h)
    width = int(round(math.sqrt((320 * 160) * aspect)))
    return max(180, min(620, width))


def ward_live_mount_contract(idx, anchor):
    direct_mount = ACTIVE_WARD_MOUNTS_BY_INDEX.get(idx)
    if direct_mount:
        return direct_mount
    if not WARD_ATLAS_MOUNT or idx not in WARD_ATLAS_VISIBLE_INDICES:
        return None
    col, row = ward_atlas_cell(idx)
    mount = dict(WARD_ATLAS_MOUNT)
    source_aspect = ward_source_aspect(idx, anchor)
    physical_width = ward_source_mount_width(idx, anchor)
    mount.update(
        {
            "id": f"{anchor}-atlas-cell",
            "role": "state-ward",
            "source_id": anchor,
            "texture": WARD_ATLAS_MOUNT["texture"],
            "texture_size": [WARD_ATLAS_CELL_W, WARD_ATLAS_CELL_H],
            "source_aspect": source_aspect,
            "texture_transform": ward_atlas_texture_transform(idx),
            "atlas_cell": [col, row],
            "purpose": f"{anchor} compositor-authored live ward surface",
            "physical_width": physical_width,
            "domain": ward_domain(idx),
        }
    )
    return mount


def ward_pane_dimensions(idx):
    """Scale ward identity mounts by role depth without destroying density."""
    mount = ward_live_mount_contract(idx, WARD_ANCHORS[idx - 1])
    if mount:
        width = int(mount["physical_width"])
        return width, aspect_height(width, mount["source_aspect"])
    if idx in SYNTHWAVE_TICKER_WARDS:
        return 320, 42
    plane = ward_depth_plane(idx)
    if plane == "hero-presence":
        return WARD_PANE_W + 28, WARD_PANE_H + 16
    if plane == "surface-scrim":
        return WARD_PANE_W + 16, WARD_PANE_H + 8
    if plane == "beyond-scrim":
        return WARD_PANE_W + 8, WARD_PANE_H + 6
    return WARD_PANE_W, WARD_PANE_H


def static_ward_mount_contract(idx, anchor, texture):
    """Return a deterministic non-live mount contract for a ward identity pane."""
    return {
        "id": anchor,
        "role": "state-ward",
        "mount_kind": "state-ward-instrument",
        "substrate": "darkplaces_bsp_texture",
        "surface": "plane",
        "texture": texture,
        "producer_kind": "darkplaces-state-export",
        "source_id": anchor,
        "freshness": "darkplaces-state-export-text-and-light",
        "consent_or_license": "system-owned-operational-state",
        "purpose": f"{anchor} ward identity and live state receiver",
        "material_profile": STATIC_WARD_MOUNT_PROFILE,
        "projection": "flat",
        "hybrid_contract": {
            "quake_binding": f"BSP brush texture {texture}",
            "producer_binding": "Hapax state exporter writes ward text/activity scalars read by CSQC",
            "memory_format": "Quake WAD indexed texture plus CSQC scalar/text files",
            "update_semantics": "Baked in-world ward surface, live state carried by dynamic lights and projected label",
            "aspect_policy": "ward icon texture is mapped once across the declared mount face",
            "compositor_role": "Hapax owns state semantics; DarkPlaces owns spatialized ward placement and lighting",
        },
    }


def static_ward_surface_texture(domain):
    """Return a neutral geometric surface material for non-media wards."""
    return DOMAIN_GLOW_TEX.get(domain, "scroom")


def sealed_room(preset):
    brushes = []
    floor_contract = SURFACE_CONTRACTS_BY_ROLE["floor"]
    ceiling_contract = SURFACE_CONTRACTS_BY_ROLE["ceiling"]
    wall_contract = SURFACE_CONTRACTS_BY_ROLE["wall"]
    ft = floor_contract["texture"]
    ct = ceiling_contract["texture"]
    wt = wall_contract["texture"]
    floor_scale = tuple(floor_contract.get("texture_scale", [4, 4]))
    ceiling_scale = tuple(ceiling_contract.get("texture_scale", [4, 4]))
    wall_scale = tuple(wall_contract.get("texture_scale", [4, 4]))
    brushes.append(
        box_brush(
            -EXT,
            ROOM_Y_MIN,
            FLOOR_Z - WALL_THICK,
            EXT,
            ROOM_Y_MAX,
            FLOOR_Z,
            ft,
            texture_scale=floor_scale,
        )
    )
    brushes.append(
        box_brush(
            -EXT,
            ROOM_Y_MIN,
            CEIL_Z,
            EXT,
            ROOM_Y_MAX,
            CEIL_Z + WALL_THICK,
            ct,
            texture_scale=ceiling_scale,
        )
    )
    brushes.append(
        box_brush(
            -EXT,
            ROOM_Y_MIN,
            FLOOR_Z,
            -EXT + WALL_THICK,
            ROOM_Y_MAX,
            CEIL_Z,
            wt,
            texture_scale=wall_scale,
        )
    )
    brushes.append(
        box_brush(
            EXT - WALL_THICK,
            ROOM_Y_MIN,
            FLOOR_Z,
            EXT,
            ROOM_Y_MAX,
            CEIL_Z,
            wt,
            texture_scale=wall_scale,
        )
    )
    brushes.append(
        box_brush(
            -EXT,
            ROOM_Y_MIN,
            FLOOR_Z,
            EXT,
            ROOM_Y_MIN + WALL_THICK,
            CEIL_Z,
            wt,
            texture_scale=wall_scale,
        )
    )
    brushes.append(
        box_brush(
            -EXT,
            ROOM_Y_MAX - WALL_THICK,
            FLOOR_Z,
            EXT,
            ROOM_Y_MAX,
            CEIL_Z,
            wt,
            texture_scale=wall_scale,
        )
    )
    return [b for b in brushes if b]


def pillar_columns(preset):
    """No free-standing columns in the reviewable scroom baseline."""
    return []


def level_ledges(preset):
    """Wall bands are deferred; the baseline must read as open space first."""
    return []


def central_lattice(preset):
    """No diagnostic floor crosshair under AoA; the object must stand itself."""
    return []


def ward_review_panes(_preset):
    """Spatialize every ward as an in-world instrument.

    Live media wards use their declared producer contracts. The remaining
    wards are deterministic state instruments: one baked icon face, one
    in-world mount, one activity lamp, and CSQC-projected live data.
    """
    brushes = []

    for idx in sorted(ACTIVE_WARD_INDICES):
        anchor = WARD_ANCHORS[idx - 1]
        mount = ward_live_mount_contract(idx, anchor)
        x, y, z = ward_review_position(idx)
        w, h = ward_pane_dimensions(idx)
        facing = ward_garden_facing(idx)
        domain = ward_domain(idx)
        glow_tex = DOMAIN_GLOW_TEX[domain]
        tex = mount["texture"] if mount else static_ward_surface_texture(domain)
        texture_size = tuple(int(v) for v in mount["texture_size"]) if mount else (64, 64)
        texture_transform = mount.get("texture_transform") if mount else None
        mount_contract = mount or static_ward_mount_contract(idx, anchor, tex)
        brushes.extend(
            framed_garden_pane(
                "ward-garden-pane",
                idx,
                anchor,
                tex,
                glow_tex,
                x,
                y,
                z,
                w,
                h,
                facing,
                texture_size,
                texture_transform,
                mount_contract,
            )
        )
        brushes.extend(ward_state_lamp(idx, anchor, glow_tex, x, y, z, w, h, facing))

    return brushes


def aoa_payload_panes(_preset):
    """Deferred so the AoA reads as one coherent object first."""
    return []


def aoa_attendant_sphere_face(_preset):
    """The media sphere is now a live-textured MDL entity, not BSP strips."""
    return []


def scroom_scene_graph_bands(_preset):
    """Deferred while establishing the clean live-media Scroom baseline."""
    return []


def scroom_material_field(_preset):
    """Do not instantiate diagnostic path stones, markers, or lantern posts."""
    return []


def scroom_room_grid(_preset):
    """No room-grid backing behind wards in the clean receiver baseline."""
    return []


def scroom_local_effect_lenses(_preset):
    """Deferred until the clean live-media baseline is readable."""
    return []


def ward_review_drift_paths(_preset):
    """No physical drift graph stones. Drift must be visible as behavior."""
    return []


def ward_depth_echo_panes(_preset):
    """Depth is carried by paths/lightfields in the garden baseline."""
    return []


def ward_scrim_panes(_preset):
    """The duplicate deep ward lattice is disabled in the open scroom baseline."""
    return []


def source_constellation_panes(_preset):
    """Physical source/camera anchors inside the scroom."""
    brushes = []

    for idx, source in enumerate(SOURCE_ANCHORS, start=1):
        role = source["role"]
        if role not in BASELINE_SOURCE_ROLES:
            continue
        tex = source["texture"]
        domain = source["domain"]
        glow_tex = DOMAIN_GLOW_TEX[domain]
        x, y, z = source["pos"]
        w = int(source.get("w", SOURCE_PANE_W))
        h = int(source.get("h", SOURCE_PANE_H))
        brushes.extend(
            framed_garden_pane(
                "source-garden-anchor",
                idx,
                role,
                tex,
                glow_tex,
                x,
                y,
                z,
                w,
                h,
                source.get("facing", "y"),
                source.get("texture_size"),
                source.get("texture_transform"),
                mount=source.get("mount"),
            )
        )

    return brushes


DRIFT_LINKS = [
    (1, 9, "drift_c"),
    (2, 10, "drift_a"),
    (3, 11, "drift_r"),
    (4, 12, "drift_g"),
    (5, 13, "drift_c"),
    (6, 14, "drift_a"),
    (7, 15, "drift_a"),
    (8, 16, "drift_g"),
    (15, 23, "drift_g"),
    (16, 24, "drift_c"),
    (17, 25, "drift_c"),
    (18, 26, "drift_r"),
    (19, 27, "drift_r"),
    (20, 28, "drift_a"),
    (21, 28, "drift_a"),
    (22, 30, "drift_a"),
    (24, 31, "drift_c"),
    (27, 34, "drift_a"),
    (4, 18, "drift_c"),
    (18, 32, "drift_g"),
    (29, 35, "drift_r"),
    (30, 33, "drift_c"),
    (31, 34, "drift_c"),
    (33, 36, "drift_c"),
    (34, 36, "drift_g"),
    (25, 36, "drift_r"),
    (32, 36, "drift_c"),
]


def ward_drift_paths(_preset):
    """The duplicate deep drift lattice is disabled in the open scroom baseline."""
    return []


def central_pedestal(preset):
    """No pedestal under AoA; the object must stand as its own receiver."""
    return []


def ramp_shelves(preset):
    return []


def lights(preset):
    entities = []
    level_light = int(preset.get("level_light", 300))
    wall_light = int(preset.get("wall_light", 150))
    aoa_light_value = int(preset.get("aoa_light_value", 350))
    # Central lights at each level (near AoA axis)
    for i in range(5):
        frac = i / 4
        z = min(FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac) + 32, CEIL_Z - 16)
        angle = i * (2 * math.pi / 5)
        x = int(TR * 0.3 * math.cos(angle))
        y = AOA_Y + int(TR * 0.3 * math.sin(angle))
        r, g, b = preset["lights"][i]
        entities.append(
            "{\n"
            f'"classname" "light"\n'
            f'"origin" "{x} {y} {z}"\n'
            f'"light" "{level_light}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )

    # Wall-mounted lights at each pillar (8 pillars × 3 vertical positions)
    for pillar in range(8):
        angle = pillar * (math.pi / 4) + math.pi / 8
        px = int((TR - 48) * math.cos(angle))
        py = AOA_Y + int((TR - 48) * math.sin(angle))
        for level in range(3):
            frac = (level + 1) / 4
            z = FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac)
            light_idx = min(level + 1, 4)
            r, g, b = preset["lights"][light_idx]
            entities.append(
                "{\n"
                f'"classname" "light"\n'
                f'"origin" "{px} {py} {z}"\n'
                f'"light" "{wall_light}"\n'
                f'"_color" "{r} {g} {b}"\n'
                "}"
            )

    # AoA center light (brighter, warm)
    ar, ag, ab = preset["aoa_light"]
    entities.append(
        "{\n"
        '"classname" "light"\n'
        f'"origin" "{AOA_X} {AOA_Y} {AOA_Z}"\n'
        f'"light" "{aoa_light_value}"\n'
        f'"_color" "{ar} {ag} {ab}"\n'
        "}"
    )

    # Review fill lights live inside the scroom corridor. They keep the fixed
    # POV critiqueable without turning the scene into a flat/fullbright level.
    review_fill = int(level_light * 0.92)
    for idx, (_name, (x, y, z), _target) in enumerate(GARDEN_CAMERA_STATIONS, start=1):
        scale = (0.64, 0.72, 0.82, 0.90, 0.94, 0.86, 0.76, 0.66)[idx - 1]
        entities.append(
            f"// review-fill-light {idx}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{x} {y} {z}"\n'
            f'"light" "{int(review_fill * scale)}"\n'
            f'"_color" "{ar} {ag} {ab}"\n'
            "}"
        )
    return entities


def ward_lights(preset):
    """Deferred with the full ward pane inventory."""
    return []


def ward_review_lights(preset):
    """Baked lights for all in-world garden ward mounts."""
    entities = []
    base = int(preset.get("wall_light", 100) * 0.78)

    for idx in sorted(ACTIVE_WARD_INDICES):
        anchor = WARD_ANCHORS[idx - 1]
        mount = ward_live_mount_contract(idx, anchor)
        x, y, z = ward_review_position(idx)
        facing = ward_garden_facing(idx)
        domain = ward_domain(idx)
        light_distance = int((mount or {}).get("receiver_light_distance", 28))
        light_multiplier = float((mount or {}).get("receiver_light_multiplier", 1.0))
        lx, ly, lz = pane_light_origin(x, y, z, facing, light_distance)
        r, g, b = DOMAIN_LIGHT_COLOR[domain]
        entities.append(
            f"// ward-garden-light {idx:02d}: {anchor}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{lx} {ly} {lz}"\n'
            f'"light" "{int(base * light_multiplier)}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )
    return entities


def source_lights(preset):
    """Baked source constellation lights; live camera state can modulate later."""
    entities = []
    base = int(preset.get("wall_light", 100) * 1.25)

    for idx, source in enumerate(SOURCE_ANCHORS, start=1):
        if source["role"] not in BASELINE_SOURCE_ROLES:
            continue
        x, y, z = source["pos"]
        lx, ly, lz = pane_light_origin(x, y, z, source.get("facing", "y"), 18)
        r, g, b = DOMAIN_LIGHT_COLOR[source["domain"]]
        entities.append(
            f"// source-light {idx:02d}: {source['role']}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{lx} {ly} {lz}"\n'
            f'"light" "{base}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )
    return entities


def aoa_payload_lights(preset):
    """Deferred so the AoA reads as one coherent object first."""
    return []


def aoa_attendant_sphere_lights(preset):
    """Baked light support for the visible AoA sphere/media face."""
    base = int(preset.get("aoa_light_value", 260) * 0.68)
    ar, ag, ab = preset["aoa_light"]
    x = AOA_X
    y = AOA_Y + 42
    z = AOA_Z
    lx, ly, lz = pane_light_origin(x, y, z, "y", 36)
    return [
        "// aoa-attendant-sphere-light 01: yt-media-face\n"
        "{\n"
        '"classname" "light"\n'
        f'"origin" "{lx} {ly} {lz}"\n'
        f'"light" "{base}"\n'
        f'"_color" "{ar} {ag} {ab}"\n'
        "}"
    ]


def scroom_scene_graph_lights(preset):
    """Deferred while the live-media ward surfaces are being stabilized."""
    return []


def scroom_local_effect_lights(preset):
    """Deferred until the clean live-media baseline is readable."""
    return []


def sectioned_brushes(section, brushes):
    return [f"// section: {section}", *brushes]


def generate_map(preset):
    lines = []
    lines.append(f"// Screwm Tower — {preset['message']}")
    lines.append("")

    worldspawn_brushes = (
        sectioned_brushes("sealed-scroom-shell", sealed_room(preset))
        + sectioned_brushes("tower-pillar-columns", pillar_columns(preset))
        + sectioned_brushes("tower-level-ledges", level_ledges(preset))
        + sectioned_brushes("central-aoa-lattice", central_lattice(preset))
        + sectioned_brushes("tower-ramp-shelves", ramp_shelves(preset))
        + sectioned_brushes("central-aoa-pedestal", central_pedestal(preset))
        + sectioned_brushes("aoa-attendant-sphere", aoa_attendant_sphere_face(preset))
        + sectioned_brushes("aoa-payload-panes", aoa_payload_panes(preset))
        + sectioned_brushes("scroom-scene-graph-bands", scroom_scene_graph_bands(preset))
        + sectioned_brushes("scroom-material-field", scroom_material_field(preset))
        + sectioned_brushes("scroom-room-grid", scroom_room_grid(preset))
        + sectioned_brushes("scroom-local-effect-lenses", scroom_local_effect_lenses(preset))
        + sectioned_brushes("ward-depth-echo-planes", ward_depth_echo_panes(preset))
        + sectioned_brushes("ward-garden-clumps", ward_review_panes(preset))
        + sectioned_brushes("ward-garden-drift-stones", ward_review_drift_paths(preset))
        + sectioned_brushes("source-camera-constellation", source_constellation_panes(preset))
        + sectioned_brushes("ward-scrim-panes", ward_scrim_panes(preset))
        + sectioned_brushes("ward-drift-paths", ward_drift_paths(preset))
    )

    lines.append("{")
    lines.append('"classname" "worldspawn"')
    lines.append(f'"message" "{preset["message"]}"')
    lines.append('"wad" "screwm.wad"')
    lines.append(f'"fog" "{preset["fog"]}"')
    lines.append('"_minlight" "16"')
    lines.append('"_minlight_color" "0.12 0.14 0.18"')
    for brush in worldspawn_brushes:
        lines.append(brush)
    lines.append("}")
    lines.append("")

    lines.append(
        f'{{\n"classname" "info_player_start"\n"origin" "0 0 {FLOOR_Z + 48}"\n"angle" "90"\n}}'
    )
    lines.append("")

    for light in (
        lights(preset)
        + aoa_attendant_sphere_lights(preset)
        + aoa_payload_lights(preset)
        + scroom_scene_graph_lights(preset)
        + scroom_local_effect_lights(preset)
        + ward_review_lights(preset)
        + ward_lights(preset)
        + source_lights(preset)
    ):
        lines.append(light)
        lines.append("")

    return "\n".join(lines)


def compile_map(map_path: Path, output_dir: Path, *, full_vis: bool = False):
    bsp_name = map_path.stem
    vis_cmd = ["vis", str(output_dir / f"{bsp_name}.bsp")]
    if not full_vis:
        vis_cmd.insert(1, "-fast")
    cmds = [
        ["qbsp", str(map_path)],
        ["light", "-extra", "-lit", str(output_dir / f"{bsp_name}.bsp")],
        vis_cmd,
    ]
    for cmd in cmds:
        print(f"  {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(output_dir))
        if result.returncode != 0:
            print(f"    WARNING: {cmd[0]} returned {result.returncode}")
        else:
            print("    OK")


def main():
    parser = argparse.ArgumentParser(description="Generate Screwm tower BSP maps")
    parser.add_argument("--mode", choices=["rnd", "research", "both"], default="both")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument(
        "--full-vis",
        action="store_true",
        help="Run full vis instead of fast vis; useful for final BSP optimization, not visual iteration.",
    )
    args = parser.parse_args()

    if len(WARD_ANCHORS) != WARD_PANEL_COUNT:
        raise SystemExit(
            f"WARD_ANCHORS has {len(WARD_ANCHORS)} entries; expected {WARD_PANEL_COUNT}"
        )

    output_dir = Path(__file__).parent.parent / "assets" / "quake" / "maps"
    output_dir.mkdir(parents=True, exist_ok=True)

    modes = ["rnd", "research"] if args.mode == "both" else [args.mode]

    for mode in modes:
        preset = MODE_PRESETS[mode]
        map_content = generate_map(preset)
        map_name = f"screwm-{mode}"
        map_path = output_dir / f"{map_name}.map"
        map_path.write_text(map_content)
        print(f"Generated {map_path} ({len(map_content)} bytes)")

        if args.compile:
            compile_map(map_path, output_dir, full_vis=args.full_vis)
            bsp_path = output_dir / f"{map_name}.bsp"
            if bsp_path.exists():
                print(f"  BSP: {bsp_path} ({bsp_path.stat().st_size} bytes)")

    # Also generate the default screwm.map (rnd mode) for backward compat
    if args.mode == "both":
        default_content = generate_map(MODE_PRESETS["rnd"])
        default_path = output_dir / "screwm.map"
        default_path.write_text(default_content)
        if args.compile:
            compile_map(default_path, output_dir, full_vis=args.full_vis)


if __name__ == "__main__":
    main()

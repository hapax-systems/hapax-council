"""Main StudioCompositor class -- thin orchestration shell."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)

from .audio_capture import CompositorAudioCapture
from .config import CACHE_DIR, SNAPSHOT_DIR, STATUS_FILE
from .effects import init_graph_runtime
from .layout_loader import LayoutStore
from .layout_state import LayoutState
from .models import CompositorConfig, OverlayState, TileRect
from .output_router import OutputRouter
from .overlay_zones import OverlayZoneManager
from .profiles import load_camera_profiles
from .source_registry import SourceRegistry

log = logging.getLogger(__name__)

BROADCAST_MODE_PATH = Path("/dev/shm/hapax-compositor/broadcast-mode.json")
_VALID_BROADCAST_MODES = frozenset({"desktop", "mobile", "dual"})


def _ingest_camera_salience_livestream_status(status: dict[str, Any]) -> bool:
    """Push one compositor status snapshot into the salience broker."""
    try:
        from shared.camera_salience_producer_adapters import livestream_to_envelope
        from shared.camera_salience_singleton import broker as _camera_broker

        cameras = status.get("cameras")
        active_camera = str(status.get("camera_profile") or "unknown")
        if isinstance(cameras, dict):
            for role, state in cameras.items():
                if state == "active":
                    active_camera = str(role)
                    break
        active_count = int(status.get("active_cameras", 0) or 0)
        total_cameras = int(status.get("total_cameras", 0) or 0)
        confidence = 0.45
        if total_cameras > 0:
            confidence = max(0.45, min(0.95, active_count / total_cameras))
        envelope = livestream_to_envelope(
            {
                "active_camera": active_camera,
                "scene_name": str(status.get("broadcast_mode") or status.get("state") or "unknown"),
                "frame_ts": status.get("timestamp") or time.time(),
                "confidence": confidence,
            }
        )
        if envelope is None:
            return False
        _camera_broker().ingest(envelope)
        return True
    except Exception:
        log.debug("camera salience livestream ingest failed", exc_info=True)
        return False


def _env_enabled(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _layout_source_ids_for_enabled_stages(layout: Layout) -> list[str]:
    """Return assigned source IDs whose render stage is enabled this boot."""
    from agents.studio_compositor.layout_source_gates import layout_source_enabled

    enabled_stages: set[str] = set()
    if _env_enabled("HAPAX_PRE_FX_LAYOUT_DRAW_ENABLED", default=True):
        enabled_stages.add("pre_fx")
    if not _env_enabled("HAPAX_COMPOSITOR_DISABLE_POST_FX_OVERLAY", default=False):
        enabled_stages.add("post_fx")

    active: list[str] = []
    seen: set[str] = set()
    for assignment in layout.assignments:
        stage = getattr(assignment, "render_stage", "pre_fx")
        if (
            stage not in enabled_stages
            or assignment.source in seen
            or not layout_source_enabled(assignment.source)
        ):
            continue
        active.append(assignment.source)
        seen.add(assignment.source)
    return active


# ---------------------------------------------------------------------------
# Source-registry epic Phase D task 13 — Layout loader + hardcoded rescue
#
# ``load_layout_or_fallback`` reads the canonical baseline JSON from disk
# and returns the parsed ``Layout``; any failure (missing file, malformed
# JSON, schema violation) logs a WARNING and resolves to
# ``_FALLBACK_LAYOUT`` — a hardcoded mirror of ``config/compositor-layouts/
# default.json`` so the compositor always boots with a working source
# registry even if the on-disk config is absent or corrupted.
#
# Dormant in main: the function is a standalone helper with no caller
# yet. Task 14 will call it from ``StudioCompositor.start()`` and feed
# the result into ``LayoutState`` + ``SourceRegistry``.
# ---------------------------------------------------------------------------


_FALLBACK_LAYOUT = Layout(
    name="default",
    description=(
        "Hardcoded fallback layout — rescue path when default.json is missing "
        "or cannot be parsed. Structurally identical to "
        "config/compositor-layouts/default.json (garage-door merge)."
    ),
    sources=[
        SourceSchema(
            id="token_pole",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "TokenPoleCairoSource",
                "natural_w": 300,
                "natural_h": 300,
            },
            update_cadence="rate",
            rate_hz=2.0,
        ),
        SourceSchema(
            id="album",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "AlbumOverlayCairoSource",
                "natural_w": 400,
                "natural_h": 520,
            },
            update_cadence="rate",
            rate_hz=2.0,
        ),
        SourceSchema(
            id="stream_overlay",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "StreamOverlayCairoSource",
                "natural_w": 400,
                "natural_h": 200,
            },
            update_cadence="rate",
            rate_hz=2.0,
        ),
        SourceSchema(
            id="sierpinski",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "SierpinskiCairoSource",
                "natural_w": 840,
                "natural_h": 840,
            },
            update_cadence="rate",
            rate_hz=2.0,
        ),
        SourceSchema(
            id="reverie",
            kind="external_rgba",
            backend="shm_rgba",
            params={
                "natural_w": 640,
                "natural_h": 360,
                "shm_path": "/dev/shm/hapax-sources/reverie.rgba",
            },
        ),
        SourceSchema(
            id="activity_header",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ActivityHeaderCairoSource",
                "natural_w": 540,
                "natural_h": 200,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["legibility", "authorship"],
        ),
        SourceSchema(
            id="stance_indicator",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "StanceIndicatorCairoSource",
                "natural_w": 100,
                "natural_h": 40,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["legibility", "authorship"],
        ),
        SourceSchema(
            id="gem",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "GemCairoSource",
                "natural_w": 1840,
                "natural_h": 240,
            },
            update_cadence="rate",
            rate_hz=24.0,
            tags=["homage", "expression", "graffiti-emphasis-mural"],
        ),
        SourceSchema(
            id="grounding_provenance_ticker",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "GroundingProvenanceTickerCairoSource",
                "natural_w": 480,
                "natural_h": 40,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["legibility", "grounding"],
        ),
        SourceSchema(
            id="impingement_cascade",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ImpingementCascadeCairoSource",
                "natural_w": 480,
                "natural_h": 360,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["hothouse", "pressure"],
        ),
        SourceSchema(
            id="recruitment_candidate_panel",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "RecruitmentCandidatePanelCairoSource",
                "natural_w": 800,
                "natural_h": 60,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["hothouse", "authorship"],
        ),
        SourceSchema(
            id="thinking_indicator",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ThinkingIndicatorCairoSource",
                "natural_w": 170,
                "natural_h": 44,
            },
            update_cadence="rate",
            rate_hz=6.0,
            tags=["hothouse", "authorship"],
        ),
        SourceSchema(
            id="pressure_gauge",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "PressureGaugeCairoSource",
                "natural_w": 300,
                "natural_h": 52,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["hothouse", "pressure"],
        ),
        SourceSchema(
            id="activity_variety_log",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ActivityVarietyLogCairoSource",
                "natural_w": 400,
                "natural_h": 140,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["hothouse", "authorship"],
        ),
        SourceSchema(
            id="whos_here",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "WhosHereCairoSource",
                "natural_w": 230,
                "natural_h": 46,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["hothouse", "audience"],
        ),
        SourceSchema(
            id="durf",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "DURFCairoSource",
                "natural_w": 530,
                "natural_h": 180,
            },
            update_cadence="rate",
            rate_hz=6.0,
            tags=["homage", "durf", "full-frame"],
            ward_id="durf",
        ),
        SourceSchema(
            id="coding_session_reveal",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "CodingSessionReveal",
                "natural_w": 960,
                "natural_h": 720,
            },
            update_cadence="rate",
            rate_hz=6.0,
            tags=["homage", "durf", "coding-session", "operator-foot-terminal"],
            ward_id="coding-session-reveal",
        ),
        SourceSchema(
            id="m8-display",
            kind="external_rgba",
            backend="shm_rgba",
            params={
                "natural_w": 320,
                "natural_h": 240,
                "shm_path": "/dev/shm/hapax-sources/m8-display.rgba",
            },
            tags=["instrument", "m8"],
            ward_id="m8-display",
        ),
        SourceSchema(
            id="steamdeck-display",
            kind="external_rgba",
            backend="shm_rgba",
            params={
                "natural_w": 1920,
                "natural_h": 1080,
                "shm_path": "/dev/shm/hapax-sources/steamdeck-display.rgba",
            },
            tags=["homage", "re-splay", "steamdeck"],
        ),
        SourceSchema(
            id="egress_footer",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "EgressFooterCairoSource",
                "natural_w": 1920,
                "natural_h": 30,
            },
            update_cadence="rate",
            rate_hz=1.0,
            tags=["governance", "anti-personification", "egress"],
        ),
        SourceSchema(
            id="programme_banner",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ProgrammeBannerWard",
                "natural_w": 540,
                "natural_h": 280,
            },
            update_cadence="rate",
            rate_hz=1.0,
            tags=["programme", "ward", "lower-third"],
            ward_id="programme-banner",
        ),
        SourceSchema(
            id="precedent_ticker",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "PrecedentTickerCairoSource",
                "natural_w": 460,
                "natural_h": 140,
            },
            update_cadence="rate",
            rate_hz=0.5,
            tags=["homage", "ward", "lore-ext", "bitchx"],
            ward_id="precedent-ticker",
        ),
        SourceSchema(
            id="programme_history",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ProgrammeHistoryCairoSource",
                "natural_w": 460,
                "natural_h": 110,
            },
            update_cadence="rate",
            rate_hz=0.5,
            tags=["homage", "ward", "lore-ext", "moksha"],
            ward_id="programme-history",
        ),
        SourceSchema(
            id="research_instrument_dashboard",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ResearchInstrumentDashboardCairoSource",
                "natural_w": 540,
                "natural_h": 220,
            },
            update_cadence="rate",
            rate_hz=0.5,
            tags=["homage", "ward", "lore-ext", "hybrid", "keystone"],
            ward_id="research-instrument-dashboard",
        ),
        SourceSchema(
            id="cbip_signal_density",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "CBIPSignalDensityCairoSource",
                "natural_w": 400,
                "natural_h": 400,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["homage", "cbip", "music"],
            ward_id="cbip-signal-density",
        ),
        SourceSchema(
            id="chat_ambient",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ChatAmbientWard",
                "natural_w": 400,
                "natural_h": 200,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["homage", "chat", "audience"],
            ward_id="chat-ambient",
        ),
        SourceSchema(
            id="chronicle_ticker",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ChronicleTickerCairoSource",
                "natural_w": 420,
                "natural_h": 140,
            },
            update_cadence="rate",
            rate_hz=0.5,
            tags=["homage", "ward", "lore-ext", "chronicle"],
            ward_id="chronicle-ticker",
        ),
        SourceSchema(
            id="programme_state",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ProgrammeStateCairoSource",
                "natural_w": 360,
                "natural_h": 120,
            },
            update_cadence="rate",
            rate_hz=0.5,
            tags=["homage", "ward", "lore-ext", "programme"],
            ward_id="programme-state",
        ),
        SourceSchema(
            id="polyend_instrument_reveal",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "PolyendInstrumentReveal",
                "natural_w": 640,
                "natural_h": 360,
            },
            update_cadence="rate",
            rate_hz=6.0,
            tags=["instrument", "polyend", "reveal"],
            ward_id="polyend-instrument-reveal",
        ),
        SourceSchema(
            id="interactive_lore_query",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "InteractiveLoreQueryWard",
                "natural_w": 460,
                "natural_h": 200,
            },
            update_cadence="rate",
            rate_hz=2.0,
            tags=["homage", "ward", "lore-ext", "chat", "bitchx"],
            ward_id="interactive-lore-query",
        ),
        SourceSchema(
            id="constructivist_research_poster",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ConstructivistResearchPosterWard",
                "natural_w": 520,
                "natural_h": 180,
            },
            update_cadence="rate",
            rate_hz=0.5,
            tags=["homage", "ward", "research-poster"],
            ward_id="constructivist-research-poster",
        ),
        SourceSchema(
            id="tufte_density",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "TufteDensityWard",
                "natural_w": 520,
                "natural_h": 180,
            },
            update_cadence="rate",
            rate_hz=0.5,
            tags=["homage", "ward", "research-poster"],
            ward_id="tufte-density",
        ),
        SourceSchema(
            id="ascii_schematic",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ASCIISchematicWard",
                "natural_w": 520,
                "natural_h": 180,
            },
            update_cadence="rate",
            rate_hz=0.5,
            tags=["homage", "ward", "research-poster"],
            ward_id="ascii-schematic",
        ),
        SourceSchema(
            id="segment_content",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "SegmentContentWard",
                "natural_w": 540,
                "natural_h": 200,
            },
            update_cadence="rate",
            rate_hz=1.0,
            tags=["segment", "ward", "content"],
            ward_id="segment-content",
        ),
        SourceSchema(
            id="m8_oscilloscope",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "M8OscilloscopeCairoSource",
                "natural_w": 1280,
                "natural_h": 128,
            },
            update_cadence="rate",
            rate_hz=15.0,
            tags=["instrument", "m8", "oscilloscope"],
            ward_id="m8-oscilloscope",
        ),
        SourceSchema(
            id="cbip_dual_ir_displacement",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "CBIPDualIrDisplacementCairoSource",
                "natural_w": 640,
                "natural_h": 480,
            },
            update_cadence="rate",
            rate_hz=6.0,
            tags=["cbip", "ir", "displacement"],
            ward_id="cbip-dual-ir-displacement",
        ),
    ],
    surfaces=[
        SurfaceSchema(
            id="sierpinski-overlay",
            geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=1920, h=1080),
            z_order=2,
        ),
        SurfaceSchema(
            id="lower-left-album",
            geometry=SurfaceGeometry(kind="rect", x=10, y=554, w=200, h=200),
            z_order=3,
        ),
        SurfaceSchema(
            id="upper-left-vitruvian",
            geometry=SurfaceGeometry(kind="rect", x=10, y=344, w=200, h=200),
            z_order=3,
        ),
        SurfaceSchema(
            id="obsidian-overlay-region",
            geometry=SurfaceGeometry(kind="rect", x=300, y=840, w=900, h=80),
            z_order=2,
        ),
        SurfaceSchema(
            id="lyrics-region",
            geometry=SurfaceGeometry(kind="rect", x=1350, y=0, w=500, h=1080),
            z_order=2,
        ),
        SurfaceSchema(
            id="impingement-cascade-midleft",
            geometry=SurfaceGeometry(kind="rect", x=1550, y=200, w=340, h=250),
            z_order=50,
        ),
        SurfaceSchema(
            id="recruitment-candidate-top",
            geometry=SurfaceGeometry(kind="rect", x=340, y=16, w=660, h=60),
            z_order=52,
        ),
        SurfaceSchema(
            id="thinking-indicator-tr",
            geometry=SurfaceGeometry(kind="rect", x=1200, y=16, w=150, h=44),
            z_order=54,
        ),
        SurfaceSchema(
            id="pressure-gauge-ul",
            geometry=SurfaceGeometry(kind="rect", x=10, y=764, w=300, h=52),
            z_order=50,
        ),
        SurfaceSchema(
            id="activity-variety-log-midbottom",
            geometry=SurfaceGeometry(kind="rect", x=1550, y=460, w=340, h=150),
            z_order=50,
        ),
        SurfaceSchema(
            id="whos-here-tc",
            geometry=SurfaceGeometry(kind="rect", x=1050, y=16, w=140, h=44),
            z_order=54,
        ),
        SurfaceSchema(
            id="reverie-upper-right",
            geometry=SurfaceGeometry(kind="rect", x=1400, y=20, w=480, h=170),
            z_order=15,
        ),
        SurfaceSchema(
            id="stance-indicator-right-column",
            geometry=SurfaceGeometry(kind="rect", x=1800, y=420, w=100, h=40),
            z_order=54,
        ),
        SurfaceSchema(
            id="grounding-ticker-right-column",
            geometry=SurfaceGeometry(kind="rect", x=1370, y=480, w=480, h=40),
            z_order=52,
        ),
        SurfaceSchema(
            id="activity-header-top-mid",
            geometry=SurfaceGeometry(kind="rect", x=400, y=86, w=800, h=56),
            z_order=52,
        ),
        SurfaceSchema(
            id="m8-oscilloscope-rightcol",
            geometry=SurfaceGeometry(kind="rect", x=1350, y=396, w=500, h=128),
            z_order=3,
        ),
        SurfaceSchema(
            id="chronicle-ticker-right-column",
            geometry=SurfaceGeometry(kind="rect", x=1380, y=560, w=420, h=140),
            z_order=52,
        ),
        SurfaceSchema(
            id="precedent-ticker-right-column",
            geometry=SurfaceGeometry(kind="rect", x=1380, y=720, w=460, h=140),
            z_order=52,
        ),
        SurfaceSchema(
            id="video_out_v4l2_loopback",
            geometry=SurfaceGeometry(kind="video_out", target="/dev/video42", render_target="main"),
            z_order=100,
        ),
        SurfaceSchema(
            id="video_out_rtmp_mediamtx",
            geometry=SurfaceGeometry(
                kind="video_out",
                target="rtmp://127.0.0.1:1935/studio",
                render_target="main",
            ),
            z_order=101,
        ),
        SurfaceSchema(
            id="video_out_hls_playlist",
            geometry=SurfaceGeometry(kind="video_out", target="hls://local", render_target="main"),
            z_order=102,
        ),
        SurfaceSchema(
            id="gem-mural-bottom",
            geometry=SurfaceGeometry(kind="rect", x=0, y=920, w=1920, h=160),
            z_order=5,
        ),
        SurfaceSchema(
            id="egress-footer-bottom",
            geometry=SurfaceGeometry(kind="rect", x=0, y=1050, w=1920, h=30),
            z_order=60,
        ),
        SurfaceSchema(
            id="programme-banner-bottom",
            geometry=SurfaceGeometry(kind="rect", x=300, y=780, w=500, h=50),
            z_order=28,
        ),
        SurfaceSchema(
            id="durf-fullframe",
            geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=1920, h=1080),
            z_order=1,
        ),
        SurfaceSchema(
            id="coding-session-fullframe",
            geometry=SurfaceGeometry(kind="rect", x=480, y=80, w=960, h=720),
            z_order=10,
            update_cadence="rate",
        ),
        SurfaceSchema(
            id="coding-session-peek",
            geometry=SurfaceGeometry(kind="rect", x=1448, y=280, w=448, h=320),
            z_order=10,
            update_cadence="rate",
        ),
        SurfaceSchema(
            id="research-dashboard-right",
            geometry=SurfaceGeometry(kind="rect", x=1380, y=860, w=500, h=180),
            z_order=22,
        ),
        SurfaceSchema(
            id="steamdeck-display-pip",
            geometry=SurfaceGeometry(kind="rect", x=960, y=60, w=920, h=580),
            z_order=42,
        ),
        SurfaceSchema(
            id="steamdeck-display-fullscreen",
            geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=1920, h=1080),
            z_order=42,
        ),
        SurfaceSchema(
            id="cbip-signal-density-surface",
            geometry=SurfaceGeometry(kind="rect", x=16, y=200, w=340, h=340),
            z_order=35,
        ),
        SurfaceSchema(
            id="chat-ambient-surface",
            geometry=SurfaceGeometry(kind="rect", x=1400, y=860, w=500, h=180),
            z_order=35,
        ),
        SurfaceSchema(
            id="chronicle-ticker-surface",
            geometry=SurfaceGeometry(kind="rect", x=370, y=612, w=420, h=140),
            z_order=35,
        ),
        SurfaceSchema(
            id="programme-state-surface",
            geometry=SurfaceGeometry(kind="rect", x=370, y=760, w=360, h=120),
            z_order=35,
        ),
        SurfaceSchema(
            id="polyend-instrument-reveal-surface",
            geometry=SurfaceGeometry(kind="rect", x=640, y=360, w=640, h=360),
            z_order=35,
        ),
        SurfaceSchema(
            id="interactive-lore-query-surface",
            geometry=SurfaceGeometry(kind="rect", x=1400, y=460, w=460, h=200),
            z_order=35,
        ),
        SurfaceSchema(
            id="constructivist-research-poster-surface",
            geometry=SurfaceGeometry(kind="rect", x=700, y=820, w=520, h=180),
            z_order=35,
        ),
        SurfaceSchema(
            id="tufte-density-surface",
            geometry=SurfaceGeometry(kind="rect", x=360, y=890, w=520, h=180),
            z_order=35,
        ),
        SurfaceSchema(
            id="ascii-schematic-surface",
            geometry=SurfaceGeometry(kind="rect", x=16, y=100, w=520, h=180),
            z_order=35,
        ),
        SurfaceSchema(
            id="segment-content-surface",
            geometry=SurfaceGeometry(kind="rect", x=690, y=200, w=540, h=200),
            z_order=35,
        ),
        SurfaceSchema(
            id="m8-oscilloscope-surface",
            geometry=SurfaceGeometry(kind="rect", x=320, y=680, w=1280, h=128),
            z_order=35,
        ),
        SurfaceSchema(
            id="cbip-dual-ir-displacement-surface",
            geometry=SurfaceGeometry(kind="rect", x=16, y=440, w=320, h=240),
            z_order=35,
        ),
    ],
    assignments=[
        Assignment(source="stream_overlay", surface="obsidian-overlay-region"),
        Assignment(source="album", surface="lower-left-album"),
        Assignment(source="token_pole", surface="upper-left-vitruvian"),
        Assignment(source="impingement_cascade", surface="impingement-cascade-midleft"),
        Assignment(source="recruitment_candidate_panel", surface="recruitment-candidate-top"),
        Assignment(source="thinking_indicator", surface="thinking-indicator-tr"),
        Assignment(source="pressure_gauge", surface="pressure-gauge-ul"),
        Assignment(source="activity_variety_log", surface="activity-variety-log-midbottom"),
        Assignment(source="whos_here", surface="whos-here-tc"),
        Assignment(source="reverie", surface="reverie-upper-right"),
        Assignment(source="stance_indicator", surface="stance-indicator-right-column"),
        Assignment(source="grounding_provenance_ticker", surface="grounding-ticker-right-column"),
        Assignment(source="activity_header", surface="activity-header-top-mid"),
        Assignment(source="m8-display", surface="m8-oscilloscope-rightcol"),
        Assignment(source="programme_history", surface="chronicle-ticker-right-column"),
        Assignment(source="precedent_ticker", surface="precedent-ticker-right-column"),
        Assignment(source="sierpinski", surface="sierpinski-overlay", render_stage="pre_fx"),
        Assignment(source="gem", surface="gem-mural-bottom"),
        Assignment(source="egress_footer", surface="egress-footer-bottom"),
        Assignment(source="programme_banner", surface="programme-banner-bottom"),
        Assignment(source="durf", surface="durf-fullframe", render_stage="pre_fx"),
        Assignment(
            source="coding_session_reveal",
            surface="coding-session-fullframe",
            opacity=0.0,
            render_stage="pre_fx",
        ),
        Assignment(
            source="coding_session_reveal",
            surface="coding-session-peek",
            opacity=0.0,
            render_stage="pre_fx",
        ),
        Assignment(source="research_instrument_dashboard", surface="research-dashboard-right"),
        Assignment(source="steamdeck-display", surface="steamdeck-display-pip", opacity=1.0),
        Assignment(source="steamdeck-display", surface="steamdeck-display-fullscreen", opacity=0.0),
        Assignment(
            source="cbip_signal_density",
            surface="cbip-signal-density-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="chat_ambient",
            surface="chat-ambient-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="chronicle_ticker",
            surface="chronicle-ticker-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="programme_state",
            surface="programme-state-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="polyend_instrument_reveal",
            surface="polyend-instrument-reveal-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="interactive_lore_query",
            surface="interactive-lore-query-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="constructivist_research_poster",
            surface="constructivist-research-poster-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="tufte_density",
            surface="tufte-density-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="ascii_schematic",
            surface="ascii-schematic-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="segment_content",
            surface="segment-content-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="m8_oscilloscope",
            surface="m8-oscilloscope-surface",
            opacity=1.0,
            non_destructive=True,
        ),
        Assignment(
            source="cbip_dual_ir_displacement",
            surface="cbip-dual-ir-displacement-surface",
            opacity=1.0,
            non_destructive=True,
        ),
    ],
)


def _notify_fallback(target: Path, reason: str) -> None:
    """Send a throttled ntfy when the compositor falls back to _FALLBACK_LAYOUT.

    Post-epic audit Phase 1 finding #6: AC-8 ("deleting default.json →
    fallback layout + ntfy") only had the fallback half wired.
    Non-fatal — notification failures must never mask the fallback
    itself. The notification path mirrors the camera-transition
    pattern in ``_notify_camera_transition`` but without the
    per-role throttle (layout fallback is rare enough that one
    notification per event is the right cadence).
    """
    try:
        from shared.notify import send_notification

        send_notification(
            title="Compositor layout fallback",
            body=(
                f"{target}: {reason}. Booting with hardcoded _FALLBACK_LAYOUT. "
                "Check the file or restore from git."
            ),
            tag="compositor-layout-fallback",
            priority="default",
        )
    except Exception:
        log.debug("fallback layout ntfy failed", exc_info=True)


def load_layout_or_fallback(path: Path) -> Layout:
    """Load a compositor Layout from JSON, falling back to the hardcoded rescue.

    Any failure mode — file missing, malformed JSON, pydantic validation
    error — logs a WARNING with the offending path, fires a one-shot
    ntfy via :func:`_notify_fallback`, and returns ``_FALLBACK_LAYOUT``.
    The compositor boots with a working source registry unconditionally.
    """
    target = Path(path)
    try:
        raw = json.loads(target.read_text())
    except FileNotFoundError:
        log.warning("compositor layout %s missing — using fallback", target)
        _notify_fallback(target, "file missing")
        return _FALLBACK_LAYOUT
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "compositor layout %s could not be read (%s) — using fallback",
            target,
            exc,
        )
        _notify_fallback(target, f"read error: {exc}")
        return _FALLBACK_LAYOUT

    try:
        layout = Layout.model_validate(raw)
    except ValueError as exc:
        log.warning(
            "compositor layout %s failed schema validation (%s) — using fallback",
            target,
            exc,
        )
        _notify_fallback(target, f"schema validation failed: {exc}")
        return _FALLBACK_LAYOUT
    expected_name = target.stem
    if expected_name and layout.name != expected_name and target.name == "default.json":
        if target.resolve() != _DEFAULT_LAYOUT_PATH.resolve():
            log.warning(
                "compositor layout %s internal name %r does not match file stem %r — "
                "using repo default layout instead",
                target,
                layout.name,
                expected_name,
            )
            _notify_fallback(target, "layout name/path mismatch")
            return load_layout_or_fallback(_DEFAULT_LAYOUT_PATH)
        log.warning(
            "repo default layout %s internal name %r does not match file stem %r — using fallback",
            target,
            layout.name,
            expected_name,
        )
        _notify_fallback(target, "repo default layout name/path mismatch")
        return _FALLBACK_LAYOUT
    # A+ Stage 2: layouts are authored in 1920×1080 absolute coords. The
    # canvas is currently 1280×720 (or whatever HAPAX_COMPOSITOR_OUTPUT_*
    # overrides set). The rescale function in layout_loader.py was added
    # alongside the canvas resize but only wired into LayoutStore (which
    # is advisory). The active render path (this function → LayoutState
    # → fx_chain.pip_draw_from_layout → blit_scaled) was missed, so
    # surface coordinates have been used unscaled — pushing wards 33%
    # right (and right-edge wards completely off-canvas) ever since
    # commit c2ee21e86. Apply the same rescaling here so layout JSON
    # geometry is normalized before the renderer reads it.
    from .layout_loader import _rescale_layout

    return _rescale_layout(layout)


# Repo-root-anchored default layout path. Resolved from this file's
# location at import time rather than from the process CWD so the
# compositor can be invoked from any working directory without silently
# falling through to ``_FALLBACK_LAYOUT``. File layout: this file lives at
# ``agents/studio_compositor/compositor.py`` → ``parents[2]`` is the repo
# root → append ``config/compositor-layouts/default.json``.
_DEFAULT_LAYOUT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "default.json"
)


class StudioCompositor:
    """Manages the GStreamer compositing pipeline."""

    def __init__(
        self,
        config: CompositorConfig,
        *,
        layout_path: Path | None = None,
    ) -> None:
        self.config = config
        # Source-registry epic Phase D task 14 — Layout loader + registry.
        # ``_DEFAULT_LAYOUT_PATH`` is computed from ``__file__`` at import
        # time, so the default resolves to the repo's baseline layout JSON
        # regardless of the process CWD. ``load_layout_or_fallback`` still
        # handles the missing-file path itself for the rescue case.
        self._layout_path: Path = (
            Path(layout_path) if layout_path is not None else _DEFAULT_LAYOUT_PATH
        )
        self.layout_state: LayoutState | None = None
        self.source_registry: SourceRegistry | None = None
        self.output_router: OutputRouter | None = None
        self._layout_autosaver: Any = None
        self._layout_file_watcher: Any = None
        self._command_server: Any = None
        self._director_segment_runner: Any = None
        self.pipeline: Any = None
        self.loop: Any = None
        self._running = False
        self._camera_status: dict[str, str] = {}
        self._camera_status_lock = threading.Lock()
        # v4l2sink heartbeat (Phase 1 stall detection). Updated by
        # pipeline.py's BUFFER probe on the v4l2sink's static sink pad
        # — fires on every frame pushed. Read by lifecycle.py's
        # watchdog tick to gate the systemd WATCHDOG=1 ping.
        # Ref: docs/research/2026-04-20-v4l2sink-stall-prevention.md §7.
        self._v4l2_frame_count: int = 0
        self._v4l2_last_frame_monotonic: float = 0.0
        self._v4l2_lock = threading.Lock()
        self._shmsink_frame_count: int = 0
        self._shmsink_last_frame_monotonic: float = 0.0
        self._shmsink_lock = threading.Lock()
        # GL chain output probe — direct detection of GL chain death.
        self._gl_last_frame_monotonic: float = 0.0
        # Cc-task ``compositor-v4l2sink-graph-mutation-stall`` (2026-05-04):
        # auto-recovery bookkeeping. Tracks consecutive failed sink-
        # reattach attempts so the watchdog tick can decide whether to
        # try recovery again or escalate to "withhold the ping" and
        # let systemd SIGABRT the unit. Late import keeps the recovery
        # module out of the cold-start critical path.
        from agents.studio_compositor.v4l2_stall_recovery import StallRecoveryState

        self._v4l2_recovery_state = StallRecoveryState()
        self._recording_status: dict[str, str] = {}
        self._recording_status_lock = threading.Lock()
        self._element_to_role: dict[str, str] = {}
        self._status_timer_id: int | None = None
        self._broadcast_mode_timer_id: int | None = None
        self._activity_router_timer_id: int | None = None
        self._activity_router: Any | None = None
        self._broadcast_mode: str = self._resolve_broadcast_mode()
        self._egress_manifest_gate: Any | None = None
        self._egress_compose_safe_active = False
        self._mobile_salience_router: Any | None = None
        self._mobile_cairo_runner: Any | None = None
        self._overlay_state = OverlayState()
        self._overlay_canvas_size: tuple[int, int] = (config.output_width, config.output_height)
        self._tile_layout: dict[str, TileRect] = {}
        self._state_reader_thread: threading.Thread | None = None
        # Task #150 Phase 1 — scene classifier background thread. Created
        # lazily in ``start_layout_only`` when the feature flag is on.
        self._scene_classifier_thread: Any = None
        self._GLib: Any = None
        self._Gst: Any = None
        self._active_profile_name: str = ""
        self._camera_profiles = load_camera_profiles(config.camera_profiles)
        self._status_dir_exists = False
        self._recording_valves: dict[str, Any] = {}
        self._recording_muxes: dict[str, Any] = {}
        self._hls_valve: Any = None
        self._consent_recording_allowed: bool = True
        self._overlay_cache_surface: Any = None
        self._overlay_cache_timestamp: float = 0.0
        self._overlay_cache_cam_hash: str = ""
        self._camera_salience_broker: Any | None = None
        try:
            from shared.camera_salience_singleton import broker as _camera_broker

            self._camera_salience_broker = _camera_broker()
        except Exception:
            log.debug("camera salience broker startup init failed", exc_info=True)
        # Phase 10 observability polish — wire the Phase 7 BudgetTracker
        # that has sat dead since PR #752. One tracker shared across every
        # CairoSourceRunner in the process; lifecycle.start_compositor
        # schedules the GLib timer that publishes snapshots to
        # /dev/shm/hapax-compositor/costs.json and degraded.json.
        from agents.studio_compositor.budget import BudgetTracker

        self._budget_tracker = BudgetTracker()
        self._overlay_zone_manager = OverlayZoneManager(budget_tracker=self._budget_tracker)
        self._audio_capture = CompositorAudioCapture()

        # CVS #145 — bidirectional audio ducking controller. Runs on
        # its own background thread polling VAD + YT-audio state files at
        # 30 ms cadence. Feature-flag-gated at dispatch level (no
        # PipeWire changes unless ``HAPAX_AUDIO_DUCKING_ACTIVE=1``), but
        # the state-machine ticks regardless so
        # ``hapax_audio_ducking_state{state=...}`` tracks reality
        # continuously for Grafana. Instantiated lazily at start_compositor
        # time — see ``lifecycle.py``.
        self._audio_ducking: Any | None = None

        # Ward stimmung modulator (z-axis spec Phase 2). Constructed
        # unconditionally; the ``maybe_tick`` early-returns when
        # ``HAPAX_WARD_MODULATOR_ACTIVE`` is unset so existing deploys
        # see no behavior change. Wired into ``fx_tick_callback``.
        from agents.studio_compositor.ward_stimmung_modulator import (
            UNIFORMS_PATH,
            WardStimmungModulator,
        )

        self._ward_stimmung_modulator = WardStimmungModulator(uniforms_path=UNIFORMS_PATH)

        self._graph_runtime = init_graph_runtime(self)

        # Phase 2c: LayoutStore — loads Source/Surface/Assignment layouts.
        # Currently advisory only — no rendering code consumes this yet.
        # Phase 3 will wire the active Layout into the executor.
        self._layout_store = LayoutStore()
        if "default" in self._layout_store.list_available():
            self._layout_store.set_active("default")

        from agents.effect_graph.visual_governance import AtmosphericSelector

        self._atmospheric_selector = AtmosphericSelector()
        self._idle_start: float | None = None
        self._current_preset_name: str | None = None

        # Task #135 — publish camera classification metadata so Hapax
        # (director, reverie, daimonion) can reason semantically about
        # each camera (operator-face / turntables / outboard-gear / etc.)
        # Written once at construction; reload paths should call
        # publish_camera_classifications() again.
        try:
            self.publish_camera_classifications()
        except Exception:
            log.exception("publish_camera_classifications failed (non-fatal)")

    def publish_camera_classifications(self) -> dict[str, dict[str, Any]]:
        """Write camera classification metadata to ``/dev/shm``.

        Task #135. Exposes each configured camera's semantic classification
        (``semantic_role``, ``subject_ontology``, ``angle``,
        ``operator_visible``, ``ambient_priority``) as a dict keyed by role
        so downstream perception (director loop, reverie mixer) can reason
        about what each camera points at.

        Atomic tmp+rename so readers never see a partial file. Safe to call
        at startup and on config reload. Returns the published dict for
        caller inspection (tests use it directly).
        """
        classifications: dict[str, dict[str, Any]] = {
            cam.role: {
                "semantic_role": cam.semantic_role,
                "subject_ontology": list(cam.subject_ontology),
                "angle": cam.angle,
                "operator_visible": cam.operator_visible,
                "ambient_priority": cam.ambient_priority,
            }
            for cam in self.config.cameras
        }
        try:
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            target = SNAPSHOT_DIR / "camera-classifications.json"
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(classifications, indent=2))
            tmp.rename(target)
        except OSError:
            log.debug("camera-classifications.json write failed", exc_info=True)
        return classifications

    def _build_activity_router(self, layout: Any, registry: Any) -> Any | None:
        """Build the activity-reveal router from registered family wards."""
        try:
            from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin
            from agents.studio_compositor.activity_router import ActivityRouter, RouterConfig
            from agents.studio_compositor.m8_instrument_reveal import M8InstrumentReveal
        except Exception:
            log.debug("activity router imports failed", exc_info=True)
            return None

        wards: list[ActivityRevealMixin] = []
        seen: set[str] = set()
        for source_id in registry.ids():
            backend = getattr(registry, "_backends", {}).get(source_id)
            source = getattr(backend, "_source", None)
            if isinstance(source, ActivityRevealMixin):
                ward_id = type(source).WARD_ID
                if ward_id not in seen:
                    wards.append(source)
                    seen.add(ward_id)

        for source in getattr(layout, "sources", ()):
            if getattr(source, "ward_id", None) != M8InstrumentReveal.WARD_ID:
                continue
            if M8InstrumentReveal.WARD_ID in seen:
                continue
            shm_path = source.params.get("shm_path") if hasattr(source, "params") else None
            wards.append(
                M8InstrumentReveal(
                    shm_path=Path(shm_path) if shm_path else None,
                    start_poll_thread=False,
                )
            )
            seen.add(M8InstrumentReveal.WARD_ID)

        if not wards:
            log.info("activity router not started: no activity-reveal wards registered")
            return None
        router = ActivityRouter(wards=wards, config=RouterConfig())
        log.info(
            "activity router ready: policy=%s wards=%s",
            router.policy.value,
            ",".join(type(ward).WARD_ID for ward in wards),
        )
        return router

    def _activity_router_tick(self) -> bool:
        if not self._running:
            return False
        router = self._activity_router
        if router is None:
            return True
        try:
            router.tick()
        except Exception:
            log.exception("activity router tick failed")
        return self._running

    def _resolve_control_plane_layout(self, layout_name: str) -> Layout | None:
        """Resolve a named compositor layout for runtime control-plane activation."""

        store = getattr(self, "_layout_store", None)
        if store is None:
            return None
        try:
            store.reload_changed()
            layout = store.get(layout_name)
            if layout is None:
                return None
            try:
                from agents.studio_compositor.layout_fragment_guard import (
                    compose_segment_fragment_over_layout,
                )

                if self.layout_state is not None:
                    composed = compose_segment_fragment_over_layout(
                        layout_name=layout_name,
                        fragment_layout=layout,
                        base_layout=self.layout_state.get(),
                    )
                    if composed is not None:
                        return composed
            except Exception:
                log.debug(
                    "layout control-plane segment composition failed for %s",
                    layout_name,
                    exc_info=True,
                )
            return layout
        except Exception:
            log.debug("layout control-plane resolver failed for %s", layout_name, exc_info=True)
            return None

    def _prepare_control_plane_layout_activation(self, layout_name: str, layout: Layout) -> None:
        """Prepare registries before a named runtime layout becomes active."""

        self._ensure_layout_sources_registered(layout)
        try:
            from agents.studio_compositor.ward_registry import populate_from_layout

            populate_from_layout(layout)
        except Exception:
            log.debug("ward registry update failed for layout %s", layout_name, exc_info=True)
        store = getattr(self, "_layout_store", None)
        if store is not None:
            try:
                store.set_active(layout_name)
            except Exception:
                log.debug("layout store activation failed for %s", layout_name, exc_info=True)

    def _ensure_layout_sources_registered(self, layout: Layout) -> None:
        """Construct and start any source backends introduced by a runtime layout."""

        registry = self.source_registry
        if registry is None:
            return
        startable_source_ids = set(_layout_source_ids_for_enabled_stages(layout))
        existing = set(registry.ids())
        for source in layout.sources:
            if source.id in existing:
                continue
            try:
                backend = registry.construct_backend(source, budget_tracker=self._budget_tracker)
                registry.register(source.id, backend)
                start = getattr(backend, "start", None)
                if start is not None and source.id in startable_source_ids:
                    start()
                existing.add(source.id)
                log.info("runtime layout source registered: %s", source.id)
            except Exception as exc:
                log.exception(
                    "failed to construct runtime layout source %s (backend=%s)",
                    source.id,
                    source.backend,
                )
                StudioCompositor._record_source_backend_error("runtime-layout", source, exc)

    def _publish_broadcast_manifest_and_gate(self) -> None:
        """Publish the provenance manifest and apply the egress gate."""

        from shared.content_source_provenance_egress import (
            EgressManifestGate,
            build_broadcast_manifest,
            read_music_provenance_asset,
            visual_asset_from_camera_role,
            visual_asset_from_source_schema,
            write_broadcast_manifest,
        )

        visual_assets = []
        if self.layout_state is not None:
            visual_assets.extend(
                visual_asset_from_source_schema(source)
                for source in self.layout_state.get().sources
            )
        visual_assets.extend(visual_asset_from_camera_role(cam.role) for cam in self.config.cameras)

        loader = getattr(self, "_sierpinski_loader", None)
        for slot in getattr(loader, "video_slots", ()):
            try:
                asset = slot.current_asset()
            except Exception:
                log.debug("sierpinski slot asset read failed", exc_info=True)
                continue
            if asset is None:
                continue
            visual_assets.append(
                asset.to_broadcast_manifest_asset(source_id=f"visual-pool-slot-{slot.slot_id}")
            )

        audio_asset = read_music_provenance_asset()
        manifest = build_broadcast_manifest(
            audio_assets=(audio_asset,) if audio_asset is not None else (),
            visual_assets=visual_assets,
        )

        if self._egress_manifest_gate is None:
            self._egress_manifest_gate = EgressManifestGate(
                producer_id="studio_compositor.compositor"
            )
        write_broadcast_manifest(manifest, self._egress_manifest_gate.manifest_path)
        decision = self._egress_manifest_gate.tick(manifest)
        if decision is None:
            return
        pm = getattr(self, "_pipeline_manager", None)
        if decision.kill_switch_fired:
            self._egress_compose_safe_active = True
            if pm is not None:
                try:
                    pm.set_compose_safe(True)
                except Exception:
                    log.debug("egress gate compose-safe apply failed", exc_info=True)
        elif self._egress_compose_safe_active:
            self._egress_compose_safe_active = False
            if pm is not None and not getattr(self, "_compose_safe_active", False):
                try:
                    pm.set_compose_safe(False)
                except Exception:
                    log.debug("egress gate compose-safe clear failed", exc_info=True)

    def _on_graph_params_changed(self, node_id: str, params: dict) -> None:
        if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
            self._slot_pipeline.update_node_uniforms(node_id, params)

    def _on_graph_plan_changed(self, old_plan: Any, new_plan: Any) -> None:
        # MUST run on the GLib main loop — set_property("fragment") on
        # PLAYING glfeedback elements requires the GL thread. Calling
        # from the state-reader daemon thread deadlocks: the state-reader
        # holds the Python GIL waiting for GL context, the GL streaming
        # thread holds the GL context waiting for the GIL. This was the
        # root cause of the persistent GL chain stall (2026-05-07).
        if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
            GLib = self._GLib
            if GLib is not None:
                GLib.idle_add(
                    lambda p=new_plan: (
                        self._slot_pipeline.activate_plan(p),
                        log.info("Slot pipeline activated: %s", p.name if p else "none"),
                        False,
                    )[2]
                )
            else:
                self._slot_pipeline.activate_plan(new_plan)
                log.info("Slot pipeline activated: %s", new_plan.name if new_plan else "none")

    def _resolve_camera_role(self, element: Any) -> str | None:
        if element is None:
            return None
        name = element.get_name()
        if name in self._element_to_role:
            return self._element_to_role[name]
        for _elem_prefix, role in self._element_to_role.items():
            role_suffix = role.replace("-", "_")
            if role_suffix in name:
                return role
        return None

    def _mark_camera_offline(self, role: str) -> None:
        with self._camera_status_lock:
            prev = self._camera_status.get(role)
            if prev == "offline":
                return
            self._camera_status[role] = "offline"
        log.warning("Camera %s marked offline", role)
        self._write_status("running")
        self._notify_camera_transition(role, prev or "unknown", "offline")

    def _mark_camera_online(self, role: str) -> None:
        with self._camera_status_lock:
            prev = self._camera_status.get(role)
            if prev == "active":
                return
            self._camera_status[role] = "active"
        log.info("Camera %s marked active", role)
        self._write_status("running")
        self._notify_camera_transition(role, prev or "unknown", "active")

    def _notify_camera_transition(self, role: str, prev: str, curr: str) -> None:
        """Throttled ntfy on camera state transition. Uses /dev/shm tracker file
        to coalesce duplicate transitions within a 60s window."""
        try:
            from shared.notify import send_notification

            tracker = Path("/dev/shm/hapax-compositor") / f"last-ntfy-{role}.txt"
            tracker.parent.mkdir(parents=True, exist_ok=True)
            now = time.monotonic()
            last_payload = ""
            last_ts = 0.0
            if tracker.exists():
                try:
                    raw = tracker.read_text().strip().split("\n", 1)
                    last_ts = float(raw[0]) if raw else 0.0
                    last_payload = raw[1] if len(raw) > 1 else ""
                except (ValueError, IndexError, OSError):
                    pass
            if last_payload == curr and (now - last_ts) < 60.0:
                return
            tracker.write_text(f"{now}\n{curr}")
            priority = "high" if curr == "offline" else "default"
            tag = "rotating_light" if curr == "offline" else "white_check_mark"
            send_notification(
                title=f"Camera {role} → {curr}",
                message=f"Transitioned from {prev}",
                priority=priority,
                tags=[tag],
            )
        except Exception:
            log.exception("ntfy on camera transition failed (role=%s)", role)

    def _on_bus_message(self, bus: Any, message: Any) -> bool:
        Gst = self._Gst
        t = message.type
        if t == Gst.MessageType.EOS:
            log.info("Pipeline EOS")
            self.stop()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            src_name = message.src.get_name() if message.src else "unknown"
            # Scope RTMP bin errors to their bin and rebuild in place.
            # Prefix filtering is reliable because every element in each
            # detachable egress bin is named with its endpoint prefix.
            if src_name.startswith("rtmp_") or src_name.startswith("mobile_rtmp_"):
                is_mobile = src_name.startswith("mobile_rtmp_")
                endpoint = "mobile" if is_mobile else "youtube"
                log.error(
                    "RTMP bin error endpoint=%s (element %s): %s (debug=%s)",
                    endpoint,
                    src_name,
                    err.message,
                    debug,
                )
                rtmp_bin = (
                    getattr(self, "_mobile_rtmp_bin", None)
                    if is_mobile
                    else getattr(self, "_rtmp_bin", None)
                )
                pipeline = self.pipeline
                if rtmp_bin is not None and pipeline is not None and self._GLib is not None:
                    self._GLib.idle_add(lambda: (rtmp_bin.rebuild_in_place(pipeline), False)[1])
                try:
                    from . import metrics

                    metrics.RTMP_ENCODER_ERRORS_TOTAL.labels(endpoint=endpoint).inc()
                    metrics.RTMP_BIN_REBUILDS_TOTAL.labels(endpoint=endpoint).inc()
                except Exception:
                    pass
                return True
            role = self._resolve_camera_role(message.src)
            if role is not None:
                log.error("Camera %s error (element %s): %s", role, src_name, err.message)
                self._mark_camera_offline(role)
            elif src_name.startswith("fx-v4l2"):
                log.warning("FX v4l2sink error (non-fatal): %s", err.message)
            elif src_name == "output" and "busy" in err.message:
                log.warning("v4l2sink format renegotiation failed (non-fatal): %s", err.message)
            elif src_name.startswith("fxsrc-"):
                # FX source branch error — non-fatal
                log.warning("FX source branch error (non-fatal): %s", err.message)
                try:
                    from .fx_chain import switch_fx_source

                    switch_fx_source(self, "live")
                except Exception:
                    log.exception("FX source fallback switch failed after error")
            elif (
                src_name == "hls-sink"
                or src_name.startswith("splitmuxsink")
                or src_name.startswith("giostreamsink")
                or src_name.startswith("mpegtsmux")
                or "hls" in src_name.lower()
            ):
                # hls-sink and its internal children (splitmuxsink,
                # giostreamsink, mpegtsmux) all emit ERROR messages that
                # must be scoped non-fatal. The hlssink2 element wraps a
                # splitmuxsink which wraps a giostreamsink, and each
                # child posts errors under its own src_name — the
                # original scope check (drop #33) only caught
                # src_name == "hls-sink" and missed the children.
                # EMFILE errors from hls-sink write paths surface on
                # giostreamsink0 and must not escalate to self.stop().
                # Archive now copies live-cache segments instead of moving
                # them, so ENOENT fragment deletion is no longer a benign
                # rotator race and should remain visible.
                msg = err.message or ""
                log.warning("HLS sink error (non-fatal): %s", msg)
            else:
                log.error("Pipeline error from %s: %s (debug: %s)", src_name, err.message, debug)
                self.stop()
        elif t == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            log.warning("Pipeline warning: %s (debug: %s)", err.message, debug)
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old, new, _ = message.parse_state_changed()
                log.debug("Pipeline state: %s -> %s", old.value_nick, new.value_nick)
        return True

    def _on_v4l2_frame_pushed(self) -> None:
        """Called from the v4l2sink BUFFER probe (streaming-thread hot path)."""
        now = time.monotonic()
        with self._v4l2_lock:
            self._v4l2_frame_count += 1
            self._v4l2_last_frame_monotonic = now
        try:
            from . import metrics

            if metrics.V4L2SINK_FRAMES_TOTAL is not None:
                metrics.V4L2SINK_FRAMES_TOTAL.inc()
        except Exception:
            pass

    def _on_shmsink_frame_pushed(self) -> None:
        """Called from the compositor-side shmsink BUFFER probe.

        This proves only that the compositor wrote a frame to the SHM bridge
        socket. It deliberately does not update v4l2 counters: the bridge
        sidecar and OBS-visible device need their own truth predicates.
        """
        now = time.monotonic()
        with self._shmsink_lock:
            self._shmsink_frame_count += 1
            self._shmsink_last_frame_monotonic = now
        try:
            from . import metrics

            if metrics.SHMSINK_FRAMES_TOTAL is not None:
                metrics.SHMSINK_FRAMES_TOTAL.inc()
        except Exception:
            pass

    def v4l2_frame_seen_within(self, seconds: float) -> bool:
        """True iff v4l2sink pushed a frame within the last ``seconds``."""
        with self._v4l2_lock:
            if self._v4l2_last_frame_monotonic == 0.0:
                return False
            return (time.monotonic() - self._v4l2_last_frame_monotonic) < seconds

    def shmsink_frame_seen_within(self, seconds: float) -> bool:
        """True iff compositor-side shmsink pushed a frame recently."""
        with self._shmsink_lock:
            if self._shmsink_last_frame_monotonic == 0.0:
                return False
            return (time.monotonic() - self._shmsink_last_frame_monotonic) < seconds

    def _write_status(self, state: str) -> None:
        if not self._status_dir_exists:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._status_dir_exists = True
        with self._camera_status_lock:
            cameras = dict(self._camera_status)
        with self._recording_status_lock:
            recording_cameras = dict(self._recording_status)
        with self._overlay_state._lock:
            guest_present = self._overlay_state._data.guest_present
            consent_phase = self._overlay_state._data.consent_phase
        active_count = sum(1 for s in cameras.values() if s == "active")
        hls_url = (
            str(Path(self.config.hls.output_dir) / "stream.m3u8") if self.config.hls.enabled else ""
        )
        rtmp_bin = getattr(self, "_rtmp_bin", None)
        rtmp_attached = bool(rtmp_bin.is_attached()) if rtmp_bin is not None else False
        rtmp_rebuild_count = (
            int(getattr(rtmp_bin, "rebuild_count", 0)) if rtmp_bin is not None else 0
        )
        mobile_rtmp_bin = getattr(self, "_mobile_rtmp_bin", None)
        mobile_rtmp_attached = (
            bool(mobile_rtmp_bin.is_attached()) if mobile_rtmp_bin is not None else False
        )
        mobile_rtmp_rebuild_count = (
            int(getattr(mobile_rtmp_bin, "rebuild_count", 0)) if mobile_rtmp_bin is not None else 0
        )
        status = {
            "state": state,
            "pid": os.getpid(),
            "cameras": cameras,
            "active_cameras": active_count,
            "total_cameras": len(cameras),
            "output_device": self.config.output_device,
            "resolution": f"{self.config.output_width}x{self.config.output_height}",
            "recording_enabled": self.config.recording.enabled,
            "recording_cameras": recording_cameras,
            "hls_enabled": self.config.hls.enabled,
            "hls_url": hls_url,
            "rtmp_attached": rtmp_attached,
            "rtmp_rebuild_count": rtmp_rebuild_count,
            "mobile_rtmp_attached": mobile_rtmp_attached,
            "mobile_rtmp_rebuild_count": mobile_rtmp_rebuild_count,
            "broadcast_mode": self._broadcast_mode,
            "camera_profile": self._active_profile_name,
            "consent_recording_allowed": self._consent_recording_allowed,
            "guest_present": guest_present,
            "consent_phase": consent_phase,
            "timestamp": time.time(),
        }
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2))
        tmp.rename(STATUS_FILE)
        try:
            consent_file = SNAPSHOT_DIR / "consent-state.txt"
            consent_file.write_text("allowed" if self._consent_recording_allowed else "blocked")
        except OSError:
            pass
        _ingest_camera_salience_livestream_status(status)

    def _status_tick(self) -> bool:
        if self._running:
            self._write_status("running")
            try:
                self._publish_broadcast_manifest_and_gate()
            except Exception:
                log.debug("broadcast provenance manifest tick failed", exc_info=True)
            # Drop #41 BT-5 / drop #52 FDL-2: publish process fd count so
            # future regressions in the camera-rebuild-thrash path become
            # scrape-visible before they hit the LimitNOFILE=65536
            # ceiling. os.listdir on /proc/self/fd is a cheap file count;
            # use a broad try/except because the directory can momentarily
            # vanish during heavy fd churn.
            try:
                from . import metrics as _metrics

                if _metrics.COMP_PROCESS_FD_COUNT is not None:
                    import os as _os

                    _metrics.COMP_PROCESS_FD_COUNT.set(len(_os.listdir("/proc/self/fd")))
            except Exception:
                log.debug("fd count gauge update failed", exc_info=True)
        return self._running

    @staticmethod
    def _record_counter(counter_name: str, labels: dict[str, str]) -> None:
        try:
            from . import metrics

            counter = getattr(metrics, counter_name, None)
            if counter is not None:
                counter.labels(**labels).inc()
        except Exception:
            log.debug("compositor observability counter %s failed", counter_name, exc_info=True)

    @staticmethod
    def _record_source_backend_error(phase: str, source: SourceSchema, exc: BaseException) -> None:
        StudioCompositor._record_counter(
            "COMP_SOURCE_BACKEND_ERRORS_TOTAL",
            {
                "phase": phase,
                "source_id": source.id,
                "backend": source.backend,
                "exception_class": type(exc).__name__,
            },
        )

    @staticmethod
    def _record_stop_error(component: str, exc: BaseException) -> None:
        StudioCompositor._record_counter(
            "COMP_STOP_ERRORS_TOTAL",
            {
                "component": component,
                "exception_class": type(exc).__name__,
            },
        )

    @staticmethod
    def _record_rtmp_side_effect_error(phase: str, exc: BaseException) -> None:
        StudioCompositor._record_counter(
            "RTMP_SIDE_EFFECT_ERRORS_TOTAL",
            {
                "phase": phase,
                "exception_class": type(exc).__name__,
            },
        )

    def _resolve_broadcast_mode(self) -> str:
        mode = (os.environ.get("HAPAX_BROADCAST_MODE") or "dual").strip().lower()
        try:
            if BROADCAST_MODE_PATH.exists():
                data = json.loads(BROADCAST_MODE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    mode = str(data.get("mode") or mode).strip().lower()
        except (OSError, json.JSONDecodeError):
            log.debug("broadcast-mode read failed", exc_info=True)
        if mode not in _VALID_BROADCAST_MODES:
            log.warning("invalid broadcast mode %r; falling back to dual", mode)
            mode = "dual"
        return mode

    def _set_broadcast_mode(self, mode: str) -> None:
        self._broadcast_mode = mode if mode in _VALID_BROADCAST_MODES else "dual"
        try:
            from . import metrics

            metrics.set_broadcast_mode(self._broadcast_mode)
        except Exception:
            log.debug("broadcast mode metric update failed", exc_info=True)

    def _broadcast_mode_tick(self) -> bool:
        if not self._running:
            return False
        mode = StudioCompositor._resolve_broadcast_mode(self)
        if mode == self._broadcast_mode:
            return True
        previous = self._broadcast_mode
        StudioCompositor._set_broadcast_mode(self, mode)
        if self.pipeline is not None and StudioCompositor._any_livestream_attached(self):
            ok, detail = StudioCompositor._apply_livestream_mode(self, activate=True, mode=mode)
            if not ok:
                log.error("broadcast mode apply failed (%s -> %s): %s", previous, mode, detail)
        StudioCompositor._sync_mobile_support_threads(self)
        self._write_status("running")
        return True

    def _any_livestream_attached(self) -> bool:
        rtmp_bin = self.__dict__.get("_rtmp_bin")
        mobile_bin = self.__dict__.get("_mobile_rtmp_bin")
        return bool(
            (rtmp_bin is not None and rtmp_bin.is_attached())
            or (mobile_bin is not None and mobile_bin.is_attached())
        )

    def _sync_mobile_support_threads(self) -> None:
        mobile_bin = self.__dict__.get("_mobile_rtmp_bin")
        mobile_attached = bool(mobile_bin.is_attached()) if mobile_bin is not None else False
        if mobile_attached and self.__dict__.get("_broadcast_mode") in ("mobile", "dual"):
            StudioCompositor._ensure_mobile_support_threads(self)
        else:
            StudioCompositor._stop_mobile_support_threads(self)

    def _ensure_mobile_support_threads(self) -> None:
        try:
            if self.__dict__.get("_mobile_salience_router") is None:
                from agents.studio_compositor.mobile_salience_router import MobileSalienceRouter

                self._mobile_salience_router = MobileSalienceRouter()
                self._mobile_salience_router.start()
            if self.__dict__.get("_mobile_cairo_runner") is None:
                from agents.studio_compositor.mobile_cairo_sources import MobileCairoRunner

                self._mobile_cairo_runner = MobileCairoRunner()
                self._mobile_cairo_runner.start()
        except Exception:
            log.exception("mobile support thread start failed")

    def _stop_mobile_support_threads(self) -> None:
        for attr in ("_mobile_cairo_runner", "_mobile_salience_router"):
            worker = self.__dict__.get(attr)
            if worker is None:
                continue
            try:
                worker.stop()
            except Exception:
                log.exception("%s stop failed", attr)
            setattr(self, attr, None)

    def start_layout_only(self) -> None:
        """Phase D task 14 — load the Layout and populate SourceRegistry.

        This is the first phase of :meth:`start` and a standalone entry
        point for tests that want to exercise Layout wiring without
        touching GStreamer. Idempotent: calling twice is a no-op.

        On success, ``self.layout_state`` holds an in-memory authority
        over the current Layout and ``self.source_registry`` maps every
        Source from that Layout to a live backend. Per-source backend
        construction failures are logged and skipped — a broken cairo
        class or a missing shm path must never take down the compositor.
        """
        if self.layout_state is not None and self.source_registry is not None:
            return

        layout = load_layout_or_fallback(self._layout_path)
        state = LayoutState(layout)
        registry = SourceRegistry()

        # Populate the ward registry from this layout so per-ward property
        # dispatchers (`ward.size.<id>.*`, etc.) can validate against the
        # canonical catalog and operator tooling can list every addressable
        # ward. Atomic dict swap inside `populate_from_layout` keeps any
        # concurrent reader on a stable snapshot during the layout swap.
        try:
            from agents.studio_compositor.ward_registry import (
                clear_registry,
                populate_camera_pips,
                populate_from_layout,
                populate_overlay_zones,
                populate_youtube_slots,
            )

            # Clear first so a future layout swap can't leave stale ward
            # IDs from a prior layout sitting alongside the current ones.
            # Today there's no swap path (the if-guard above short-circuits
            # if layout_state already exists), but the explicit reset
            # documents the assumption.
            clear_registry()
            populate_from_layout(layout)
            populate_overlay_zones(["main", "research", "lyrics"])
            populate_youtube_slots(slot_count=3)
            populate_camera_pips(
                [
                    "c920-overhead",
                    "c920-desk",
                    "c920-room",
                    "brio-operator",
                    "brio-synths",
                    "brio-room",
                ]
            )
        except Exception:
            log.exception("ward_registry bootstrap failed; continuing without registry")

        for source in layout.sources:
            try:
                backend = registry.construct_backend(source, budget_tracker=self._budget_tracker)
            except Exception as exc:
                log.exception(
                    "failed to construct backend for source %s (backend=%s)",
                    source.id,
                    source.backend,
                )
                StudioCompositor._record_source_backend_error("construct", source, exc)
                continue
            try:
                registry.register(source.id, backend)
            except ValueError as exc:
                log.exception(
                    "duplicate source_id %s in layout — dropping later registration",
                    source.id,
                )
                StudioCompositor._record_source_backend_error("register", source, exc)
        self.layout_state = state
        self.source_registry = registry

        # Drop #41 BT-1 fix: start registered backends that expose
        # a start() method. Previously this was missing, leaving
        # layout-declared Cairo sources (token_pole, album,
        # stream_overlay, reverie) constructed-but-dormant — their
        # background render threads never ran and pip_draw_from_layout
        # silently skipped them. See SourceRegistry.start_all docstring
        # for the full analysis. The start set is bounded to render
        # stages active for this boot so incident containment does not
        # keep hidden Cairo runners burning CPU behind a disabled stage.
        registered_source_ids = set(registry.ids())
        registry.start_all(
            [
                source_id
                for source_id in _layout_source_ids_for_enabled_stages(layout)
                if source_id in registered_source_ids
            ]
        )
        self._activity_router = self._build_activity_router(layout, registry)

        # LRR Phase 2 item 10b: populate CairoSourceRegistry from the
        # zone catalog at `config/compositor-zones.yaml`. This is the
        # NEW zone-binding registry (distinct from SourceRegistry which
        # handles surface backend binding). Failures are logged but
        # never raised — a missing or malformed zone catalog must not
        # take down the compositor. HSEA Phase 1 will consume the
        # populated registry via `CairoSourceRegistry.get_for_zone()`.
        try:
            from agents.studio_compositor.cairo_source_registry import load_zone_defaults

            zones_path = Path(__file__).resolve().parents[2] / "config" / "compositor-zones.yaml"
            registered, skipped = load_zone_defaults(zones_path)
            log.info(
                "cairo_source_registry populated: registered=%d skipped=%d",
                registered,
                skipped,
            )
        except Exception:
            log.exception(
                "cairo_source_registry population failed — "
                "HSEA Phase 1 zone lookups will return empty results"
            )

        # Phase 10 carry-over from Phase 2 item 10: attach the router
        # that enumerates video_out surfaces. Pure data plumbing —
        # the legacy hardcoded sink construction in ``pipeline.py`` is
        # still authoritative at runtime. Downstream consumers (e.g.
        # future router-driven sink building, or diagnostics) read from
        # ``self.output_router.bindings()``. Log the discovered
        # bindings so the operator can confirm each video_out surface
        # is visible to the new router plumbing.
        self.output_router = OutputRouter.from_layout(layout)
        for binding in self.output_router:
            log.info(
                "output router binding: surface=%s render_target=%s sink_kind=%s sink_path=%s",
                binding.surface_id,
                binding.render_target,
                binding.sink_kind,
                binding.sink_path,
            )

        log.info(
            "layout loaded: name=%s sources=%d registered=%d bindings=%d",
            layout.name,
            len(layout.sources),
            len(registry.ids()),
            len(self.output_router),
        )

        # Post-epic audit finding #1: LayoutAutoSaver + LayoutFileWatcher
        # exist in layout_persistence.py but were never instantiated by
        # StudioCompositor, leaving AC-5 ("file-watch reload within ≤2s")
        # unwired. Start both here so runtime layout edits round-trip
        # through the in-memory state.
        try:
            from agents.studio_compositor.layout_persistence import (
                LayoutAutoSaver,
                LayoutFileWatcher,
            )

            self._layout_autosaver = LayoutAutoSaver(state, self._layout_path)
            self._layout_autosaver.start()
            self._layout_file_watcher = LayoutFileWatcher(state, self._layout_path)
            self._layout_file_watcher.start()
            log.info(
                "layout persistence threads started: autosave + file-watch on %s",
                self._layout_path,
            )
        except Exception:
            log.exception(
                "failed to start layout persistence threads — "
                "compositor continues without auto-save or hot-reload"
            )

        # Delta post-epic retirement handoff item #5: start the compositor
        # command server so runtime layout mutations from window.__logos /
        # MCP / voice can round-trip through the in-memory LayoutState.
        # The ``flush_callback`` hooks ``compositor.layout.save`` to the
        # autosaver's immediate-flush path. ``reload_callback`` stays None —
        # the ``LayoutFileWatcher`` polling loop already picks up external
        # edits within ≤2 s, so a manual reload nudge isn't needed yet.
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        command_sock = Path(runtime_dir) / "hapax-compositor-commands.sock"
        try:
            from agents.studio_compositor.command_server import CommandServer

            flush_cb: Callable[[], None] | None = None
            if self._layout_autosaver is not None:
                flush_cb = self._layout_autosaver.flush_now
            self._command_server = CommandServer(
                state,
                command_sock,
                flush_callback=flush_cb,
                reload_callback=None,
                layout_resolver=self._resolve_control_plane_layout,
                layout_names_provider=self._layout_store.list_available,
                layout_activation_callback=self._prepare_control_plane_layout_activation,
            )
            self._command_server.start()
        except Exception:
            log.exception(
                "failed to start compositor command server — "
                "runtime layout mutation via window.__logos / MCP is unavailable"
            )

        try:
            from agents.studio_compositor.director_segment_runner import (
                maybe_start_director_segment_runner,
            )

            self._director_segment_runner = maybe_start_director_segment_runner(
                self,
                command_socket_path=command_sock,
            )
        except Exception:
            log.exception("failed to start director segment runner")

        # 2026-04-23 Gemini-audit Phase 3 — the compositor-embedded
        # recent-impingements publisher (added in #1209) read ``salience``
        # from /dev/shm/hapax-dmn/impingements.jsonl, but the correct key
        # is ``strength``, leaving empty-string ward entries on the
        # broadcast. It also raced the dedicated systemd unit
        # ``hapax-recent-impingements.service`` (active since 2026-04-20,
        # backed by ``scripts/hapax-recent-impingements-producer``), which
        # already owns this SHM path and uses the correct schema. The
        # systemd producer is the single writer for
        # ``/dev/shm/hapax-compositor/recent-impingements.json``; the
        # compositor-embedded variant has been removed.
        self._recent_pub = None

        # Task #150 Phase 1 — start the scene classifier thread by default
        # per directive feedback_features_on_by_default 2026-04-25T20:55Z.
        # Operator opts out via HAPAX_SCENE_CLASSIFIER_ACTIVE=0. Flag-gated;
        # returns None (and logs) when inactive.
        try:
            from agents.studio_compositor.scene_classifier import (
                maybe_start_scene_classifier,
            )

            self._scene_classifier_thread = maybe_start_scene_classifier()
        except Exception:
            log.exception("failed to start scene_classifier thread")
            self._scene_classifier_thread = None

        # cc-task scene-classifier-publish-restore (audit R3 / Auditor E
        # finding #10a, 2026-05-02): re-publish camera-classifications.json
        # every ~30s so any change to the camera registry (config reload,
        # PR #2246 loader fill, future dynamic per-camera ML classifier)
        # reaches FollowModeController without a compositor restart.
        try:
            from agents.studio_compositor.camera_classifier_publisher import (
                maybe_start_camera_classifier_publisher,
            )

            self._camera_classifier_publisher = maybe_start_camera_classifier_publisher(self)
        except Exception:
            log.exception("failed to start camera_classifier_publisher")
            self._camera_classifier_publisher = None

    def start(self) -> None:
        """Build and start the pipeline."""
        self.start_layout_only()

        from .lifecycle import start_compositor

        start_compositor(self)

    def stop(self) -> None:
        """Stop the pipeline cleanly."""
        thread = getattr(self, "_scene_classifier_thread", None)
        if thread is not None:
            try:
                thread.stop()
            except Exception as exc:
                log.exception("scene_classifier thread stop failed")
                StudioCompositor._record_stop_error("scene_classifier_thread", exc)
            self._scene_classifier_thread = None
        publisher = getattr(self, "_camera_classifier_publisher", None)
        if publisher is not None:
            try:
                publisher.stop()
            except Exception as exc:
                log.exception("camera_classifier_publisher stop failed")
                StudioCompositor._record_stop_error("camera_classifier_publisher", exc)
            self._camera_classifier_publisher = None
        runner = getattr(self, "_director_segment_runner", None)
        if runner is not None:
            try:
                runner.stop()
            except Exception as exc:
                log.exception("director_segment_runner stop failed")
                StudioCompositor._record_stop_error("director_segment_runner", exc)
            self._director_segment_runner = None
        if self._command_server is not None:
            try:
                self._command_server.stop()
            except Exception as exc:
                log.exception("CommandServer.stop failed")
                StudioCompositor._record_stop_error("command_server", exc)
            self._command_server = None
        if getattr(self, "_recent_pub", None) is not None:
            try:
                self._recent_pub.stop()
            except Exception as exc:
                log.exception("recent_pub.stop failed")
                StudioCompositor._record_stop_error("recent_pub", exc)
            self._recent_pub = None
        if self._layout_file_watcher is not None:
            try:
                self._layout_file_watcher.stop()
            except Exception as exc:
                log.exception("LayoutFileWatcher.stop failed")
                StudioCompositor._record_stop_error("layout_file_watcher", exc)
            self._layout_file_watcher = None
        if self._layout_autosaver is not None:
            try:
                self._layout_autosaver.stop()
            except Exception as exc:
                log.exception("LayoutAutoSaver.stop failed")
                StudioCompositor._record_stop_error("layout_autosaver", exc)
            self._layout_autosaver = None

        from .lifecycle import stop_compositor

        stop_compositor(self)

    def toggle_livestream(self, activate: bool, reason: str = "") -> tuple[bool, str]:
        """Attach or detach the configured RTMP output bins. Consent-gated by the
        unified semantic recruitment pipeline — this method should only be
        called from the affordance handler which runs after the consent
        check.

        Phase 5 of the camera 24/7 resilience epic (closes A7).
        """
        rtmp_bin = self.__dict__.get("_rtmp_bin")
        mobile_bin = self.__dict__.get("_mobile_rtmp_bin")
        if rtmp_bin is None and mobile_bin is None:
            return False, "rtmp bin not constructed"
        if self.__dict__.get("pipeline") is None:
            return False, "composite pipeline not built"

        mode = StudioCompositor._resolve_broadcast_mode(self)
        StudioCompositor._set_broadcast_mode(self, mode)

        if activate:
            if StudioCompositor._livestream_matches_mode(self, mode):
                StudioCompositor._sync_mobile_support_threads(self)
                return True, "already live"
            ok, detail = StudioCompositor._apply_livestream_mode(
                self,
                activate=True,
                mode=mode,
            )
            if not ok:
                StudioCompositor._sync_mobile_support_threads(self)
                return False, detail
            StudioCompositor._sync_mobile_support_threads(self)
            try:
                from shared.notify import send_notification

                from . import metrics

                metrics.set_broadcast_mode(mode)
                send_notification(
                    title="Livestream started",
                    message=f"Mode: {mode}. Reason: {reason}",
                    priority="default",
                    tags=["rocket"],
                )
            except Exception as exc:
                log.exception("rtmp attach side-effects raised (non-fatal)")
                StudioCompositor._record_rtmp_side_effect_error("attach", exc)
            return True, f"livestream egress attached ({mode})"
        else:
            if not StudioCompositor._any_livestream_attached(self):
                StudioCompositor._sync_mobile_support_threads(self)
                return True, "already off"
            ok, detail = StudioCompositor._apply_livestream_mode(
                self,
                activate=False,
                mode=mode,
            )
            StudioCompositor._sync_mobile_support_threads(self)
            try:
                from shared.notify import send_notification

                from . import metrics

                metrics.RTMP_CONNECTED.labels(endpoint="youtube").set(0)
                metrics.RTMP_CONNECTED.labels(endpoint="mobile").set(0)
                send_notification(
                    title="Livestream stopped",
                    message=f"Reason: {reason}",
                    priority="default",
                    tags=["stop_sign"],
                )
            except Exception as exc:
                log.exception("rtmp detach side-effects raised (non-fatal)")
                StudioCompositor._record_rtmp_side_effect_error("detach", exc)
            return ok, detail

    def _livestream_matches_mode(self, mode: str) -> bool:
        rtmp_bin = self.__dict__.get("_rtmp_bin")
        mobile_bin = self.__dict__.get("_mobile_rtmp_bin")
        desktop_attached = bool(rtmp_bin.is_attached()) if rtmp_bin is not None else False
        mobile_attached = bool(mobile_bin.is_attached()) if mobile_bin is not None else False
        desktop_desired = rtmp_bin is not None and mode in ("desktop", "dual")
        mobile_desired = mobile_bin is not None and mode in ("mobile", "dual")
        return desktop_attached == desktop_desired and mobile_attached == mobile_desired

    def _apply_livestream_mode(self, *, activate: bool, mode: str) -> tuple[bool, str]:
        pipeline = self.__dict__.get("pipeline")
        if pipeline is None:
            return False, "composite pipeline not built"
        rtmp_bin = self.__dict__.get("_rtmp_bin")
        mobile_bin = self.__dict__.get("_mobile_rtmp_bin")
        if rtmp_bin is None and mode in ("desktop", "dual"):
            return False, "desktop rtmp bin not constructed"
        if mobile_bin is None and mode in ("mobile", "dual"):
            return False, "mobile rtmp bin not constructed"

        if not activate:
            if rtmp_bin is not None and rtmp_bin.is_attached():
                rtmp_bin.detach_and_teardown(pipeline)
            if mobile_bin is not None and mobile_bin.is_attached():
                mobile_bin.detach_and_teardown(pipeline)
            StudioCompositor._publish_livestream_metrics(self, mode)
            return True, "livestream egress detached"

        errors: list[str] = []
        if rtmp_bin is not None:
            should_attach_desktop = mode in ("desktop", "dual")
            if should_attach_desktop and not rtmp_bin.is_attached():
                if not rtmp_bin.build_and_attach(pipeline):
                    errors.append("desktop rtmp attach failed")
            elif not should_attach_desktop and rtmp_bin.is_attached():
                rtmp_bin.detach_and_teardown(pipeline)

        if mobile_bin is not None:
            should_attach_mobile = mode in ("mobile", "dual")
            if should_attach_mobile and not mobile_bin.is_attached():
                if not mobile_bin.build_and_attach(pipeline):
                    errors.append("mobile rtmp attach failed")
            elif not should_attach_mobile and mobile_bin.is_attached():
                mobile_bin.detach_and_teardown(pipeline)

        if errors:
            return False, "; ".join(errors)
        StudioCompositor._publish_livestream_metrics(self, mode)
        return True, f"livestream egress mode applied: {mode}"

    def _publish_livestream_metrics(self, mode: str) -> None:
        try:
            from . import metrics

            rtmp_bin = self.__dict__.get("_rtmp_bin")
            mobile_bin = self.__dict__.get("_mobile_rtmp_bin")
            if metrics.RTMP_CONNECTED is not None:
                metrics.RTMP_CONNECTED.labels(endpoint="youtube").set(
                    1 if rtmp_bin is not None and rtmp_bin.is_attached() else 0
                )
                metrics.RTMP_CONNECTED.labels(endpoint="mobile").set(
                    1 if mobile_bin is not None and mobile_bin.is_attached() else 0
                )
            metrics.set_broadcast_mode(mode)
        except Exception:
            log.debug("livestream metric publish failed", exc_info=True)

"""Execute segment_cues by writing directly to compositor SHM control files.

When a beat advances, the corresponding segment_cue is parsed and executed
as direct SHM writes — no LLM intermediary. This gives Hapax tight control
over the visual surface during segments: fronting cameras, displaying
homages/images/YouTube videos, controlling depth (scrim push/pull),
managing mood, and triggering transitions.

Cue vocabulary (comma-separated within one cue string):
    camera.hero tight|wide|standard|<camera-role>
    front.youtube <url>
    front.homage <name>
    front.image <url>
    front.glyph <text>
    front.cam
    scrim.push
    scrim.pull
    composition.reframe wide|tight|standard
    mood.tone_pivot warm|cool|neutral|intense
    transition.cut
    transition.dissolve
    media.play
    media.pause
    media.resume
    gem.emphasis stamp <text>
    gem.spawn
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from pathlib import Path

from agents.studio_compositor.action_receipts import emit_action_receipt
from shared.action_receipt import ActionReceiptStatus

log = logging.getLogger(__name__)

_SHM_DIR = Path("/dev/shm/hapax-compositor")
_ACTION_RECEIPTS_JSONL = _SHM_DIR / "action-receipts.jsonl"


def _atomic_write_json(path: Path, payload: dict) -> bool:
    """Atomic tmp+rename write to SHM."""
    try:
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(path.parent),
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        json.dump(payload, fd, separators=(",", ":"))
        fd.flush()
        fd.close()
        Path(fd.name).rename(path)
        return True
    except Exception:
        log.debug("atomic write failed for %s", path, exc_info=True)
        return False


def _atomic_write_text(path: Path, text: str) -> bool:
    """Atomic tmp+rename write of plain text."""
    try:
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(path.parent),
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        fd.write(text)
        fd.flush()
        fd.close()
        Path(fd.name).rename(path)
        return True
    except Exception:
        log.debug("atomic write failed for %s", path, exc_info=True)
        return False


# ── Camera control ───────────────────────────────────────────────────────

_HERO_CAMERA_OVERRIDE = _SHM_DIR / "hero-camera-override.json"

# Map from short names to camera roles
_CAMERA_ROLES: dict[str, str] = {
    "tight": "brio-operator",
    "wide": "c920-room",
    "standard": "c920-desk",
    "overhead": "c920-overhead",
    "room": "brio-room",
    "synths": "brio-synths",
    "operator": "brio-operator",
}


def _exec_camera_hero(args: str) -> None:
    """camera.hero <variant> — switch the hero camera."""
    variant = args.strip().lower()
    role = _CAMERA_ROLES.get(variant, variant)
    _atomic_write_json(
        _HERO_CAMERA_OVERRIDE,
        {
            "camera_role": role,
            "ttl_s": 60.0,
            "set_at": time.time(),
            "source_capability": f"segment_cue.camera.hero.{variant}",
        },
    )
    log.info("cue_executor: camera.hero → %s", role)


# ── Front an asset ───────────────────────────────────────────────────────

_YOUTUBE_VIDEO_ID = _SHM_DIR / "youtube-video-id.txt"
_HOMAGE_ACTIVE_ARTEFACT = _SHM_DIR / "homage-active-artefact.json"
_NARRATIVE_STRUCTURAL_INTENT = _SHM_DIR / "narrative-structural-intent.json"

# YouTube URL → video ID extraction
_YT_URL_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)"
    r"([A-Za-z0-9_-]{11})"
)


def _exec_front_youtube(args: str) -> None:
    """front.youtube <url> — display a YouTube video on the surface."""
    url = args.strip()
    m = _YT_URL_RE.search(url)
    video_id = m.group(1) if m else url.strip()
    _atomic_write_text(_YOUTUBE_VIDEO_ID, video_id)
    log.info("cue_executor: front.youtube → %s", video_id)


def _exec_front_homage(args: str, *, request_id: str | None = None) -> None:
    """front.homage <name> — bring a named homage to foreground."""
    name = args.strip()
    active_written = _atomic_write_json(
        _HOMAGE_ACTIVE_ARTEFACT,
        {
            "package": name,
            "content": "",
            "form": "segment-front",
            "author_tag": "segment_cue",
            "weight": 1.0,
        },
    )
    # Also write structural intent to bring homage to foreground
    structural_written = _atomic_write_json(
        _NARRATIVE_STRUCTURAL_INTENT,
        {
            "homage_rotation_mode": "paused",
            "updated_at": time.time(),
        },
    )
    applied = active_written and structural_written
    emit_action_receipt(
        request_id=request_id,
        capability_name="segment_cue.front.homage",
        requested_action=f"front.homage {name}",
        status=ActionReceiptStatus.APPLIED if applied else ActionReceiptStatus.ERROR,
        family="structural.intent",
        command_ref="segment-cue:front.homage",
        applied_refs=[
            "shm:hapax-compositor/homage-active-artefact.json",
            "shm:hapax-compositor/narrative-structural-intent.json",
        ]
        if applied
        else [],
        error_refs=[] if applied else ["front_homage_write_failed"],
        structural_reflex=True,
        path=_ACTION_RECEIPTS_JSONL,
    )
    log.info("cue_executor: front.homage → %s", name)


def _exec_front_cam() -> None:
    """front.cam — bring camera to foreground (default hero)."""
    # Read current hero or default to operator
    _exec_camera_hero("operator")
    log.info("cue_executor: front.cam")


def _exec_front_image(args: str) -> None:
    """front.image <url> — display an image. Writes to overlay-alpha-overrides."""
    url = args.strip()
    _atomic_write_json(
        _SHM_DIR / "overlay-alpha-overrides.json",
        {
            "segment_image_url": url,
            "alpha": 1.0,
            "set_at": time.time(),
            "ttl_s": 120.0,
        },
    )
    log.info("cue_executor: front.image → %s", url[:60])


def _exec_front_glyph(args: str) -> None:
    """front.glyph <text> — display text overlay via GEM ward."""
    text = args.strip().strip("'\"")
    _atomic_write_json(
        _SHM_DIR / "gem-frames.json",
        {
            "frames": [{"text": text, "hold_ms": 30000}],
        },
    )
    log.info("cue_executor: front.glyph → %s", text[:40])


# ── Depth control ────────────────────────────────────────────────────────

_MOOD_STATE = _SHM_DIR / "mood-state.json"


def _exec_scrim_push() -> None:
    """scrim.push — push current content deeper into background."""
    _atomic_write_json(
        _MOOD_STATE,
        {
            "pivot": "recede",
            "ttl_s": 60.0,
            "ts": time.time(),
            "source": "segment_cue",
        },
    )
    log.info("cue_executor: scrim.push")


def _exec_scrim_pull() -> None:
    """scrim.pull — bring content forward from background."""
    _atomic_write_json(
        _MOOD_STATE,
        {
            "pivot": "foreground",
            "ttl_s": 60.0,
            "ts": time.time(),
            "source": "segment_cue",
        },
    )
    log.info("cue_executor: scrim.pull")


# ── Composition / mood / transitions ─────────────────────────────────────

_COMPOSITION_STATE = _SHM_DIR / "composition-state.json"


def _exec_composition_reframe(args: str) -> None:
    """composition.reframe <variant>"""
    variant = args.strip().lower()
    variant_map = {"wide": "widen", "tight": "tighten", "standard": "recompose"}
    _atomic_write_json(
        _COMPOSITION_STATE,
        {
            "reframe": variant_map.get(variant, variant),
            "ttl_s": 60.0,
            "ts": time.time(),
        },
    )
    log.info("cue_executor: composition.reframe → %s", variant)


def _exec_mood_tone_pivot(args: str) -> None:
    """mood.tone_pivot <variant>"""
    variant = args.strip().lower()
    _atomic_write_json(
        _MOOD_STATE,
        {
            "pivot": variant,
            "ttl_s": 60.0,
            "ts": time.time(),
            "source": "segment_cue",
        },
    )
    log.info("cue_executor: mood.tone_pivot → %s", variant)


def _exec_transition(variant: str) -> None:
    """transition.cut or transition.dissolve"""
    from agents.studio_compositor.compositional_consumer import dispatch_transition

    dispatch_transition(f"transition.{variant}", 10.0)
    log.info("cue_executor: transition.%s", variant)


# ── Media control (react segments) ───────────────────────────────────────

_YT_AUDIO_STATE = _SHM_DIR / "yt-audio-state.json"


def _exec_media_play() -> None:
    """media.play — start/resume YouTube playback."""
    _atomic_write_json(
        _YT_AUDIO_STATE,
        {"state": "playing", "set_at": time.time()},
    )
    log.info("cue_executor: media.play")


def _exec_media_pause() -> None:
    """media.pause — pause YouTube playback for react commentary."""
    _atomic_write_json(
        _YT_AUDIO_STATE,
        {"state": "paused", "set_at": time.time()},
    )
    log.info("cue_executor: media.pause")


def _exec_media_resume() -> None:
    """media.resume — resume YouTube playback after commentary."""
    _exec_media_play()  # same effect


# ── GEM overlays ─────────────────────────────────────────────────────────


def _exec_gem_emphasis_stamp(args: str) -> None:
    """gem.emphasis stamp <text>"""
    # Strip 'stamp' prefix if present, then quotes
    text = args.strip()
    if text.lower().startswith("stamp"):
        text = text[5:].strip()
    text = text.strip("'\"")
    _atomic_write_json(
        _SHM_DIR / "gem-frames.json",
        {
            "frames": [{"text": text, "hold_ms": 15000}],
        },
    )
    log.info("cue_executor: gem.emphasis stamp → %s", text[:40])


def _exec_gem_spawn() -> None:
    """gem.spawn — trigger a GEM animation."""
    from agents.studio_compositor.compositional_consumer import dispatch_gem

    dispatch_gem("gem.spawn.segment", 10.0)
    log.info("cue_executor: gem.spawn")


# ── Main dispatcher ──────────────────────────────────────────────────────


def execute_cue(cue_string: str, *, request_id: str | None = None) -> None:
    """Parse and execute a segment_cue string.

    A cue string may contain multiple comma-separated directives:
        "front.youtube https://..., camera.hero tight, mood.tone_pivot warm"

    Also writes a segment-cue-hold.json file that suppresses ALL default
    director behaviors (camera, FX, overlays, homage) for the hold TTL.
    """
    if not cue_string or not cue_string.strip():
        return

    # Write the hold file FIRST — suppresses director overrides immediately
    _atomic_write_json(
        _SHM_DIR / "segment-cue-hold.json",
        {
            "set_at": time.time(),
            "ttl_s": 60.0,
            "cue": cue_string[:200],
        },
    )

    directives = [d.strip() for d in cue_string.split(",")]
    for directive in directives:
        if not directive:
            continue
        try:
            _dispatch_single(directive, request_id=request_id)
        except Exception:
            log.warning("cue_executor: failed directive: %s", directive, exc_info=True)


def _dispatch_single(directive: str, *, request_id: str | None = None) -> None:
    """Dispatch a single cue directive.

    Cue format: ``dotted.command args...``
    Examples: ``camera.hero tight``, ``front.youtube https://...``,
    ``scrim.push``, ``gem.emphasis stamp 'KEY POINT'``
    """
    parts = directive.split(None, 1)
    if not parts:
        return
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    match cmd:
        # Camera
        case "camera.hero":
            _exec_camera_hero(args)
        # Front assets
        case "front.youtube":
            _exec_front_youtube(args)
        case "front.homage":
            _exec_front_homage(args, request_id=request_id)
        case "front.image":
            _exec_front_image(args)
        case "front.glyph":
            _exec_front_glyph(args)
        case "front.cam":
            _exec_front_cam()
        # Depth
        case "scrim.push":
            _exec_scrim_push()
        case "scrim.pull":
            _exec_scrim_pull()
        # Composition
        case "composition.reframe":
            _exec_composition_reframe(args)
        case "composition.stable":
            pass  # no-op: keep current composition
        # Mood
        case "mood.tone_pivot":
            _exec_mood_tone_pivot(args)
        # Transitions
        case "transition.cut":
            _exec_transition("cut")
        case "transition.dissolve":
            _exec_transition("dissolve")
        # Media control
        case "media.play":
            _exec_media_play()
        case "media.pause":
            _exec_media_pause()
        case "media.resume":
            _exec_media_resume()
        # GEM
        case "gem.spawn":
            _exec_gem_spawn()
        case "gem.emphasis":
            _exec_gem_emphasis_stamp(args)
        case _:
            # Unhandled directives are silently ignored — the planner
            # may emit compositor-specific cues (e.g.
            # graphic.iceberg_layer_indicator) that only the compositor
            # reads. These aren't errors.
            log.debug("cue_executor: unhandled directive: %s", directive)

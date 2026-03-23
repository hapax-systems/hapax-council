"""Convert DemoScript → in-app demo format for DemoRunner playback.

Generates app-script.json with serializable bridge method references.
Actions are inferred from scene title + narration content using keyword matching.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agents.demo_models import DemoScript

log = logging.getLogger(__name__)

# Keywords in scene title + narration → terrain actions.
# Checked in priority order — first match wins.
# Each entry: (keywords_any_of, actions)
# Priority-ordered content → action mapping. First match wins.
# More specific patterns MUST come before broad ones.
CONTENT_ACTIONS: list[tuple[list[str], list[list[str | None]]]] = [
    # ── Specific proper nouns first (philosophy, research names) ──
    (["husserl", "heidegger", "merleau-ponty", "wittgenstein", "phenomenol"], []),
    (
        [
            "clark and brennan",
            "clark's",
            "brennan's",
            "grounding theory",
            "conversational grounding",
        ],
        [],
    ),
    (["sced", "pre-registration", "bayes factor", "single-case experimental"], []),
    (["stable band", "volatile band", "salience routing"], []),
    # ── Consent / Ethics BEFORE camera (ethics scenes mention cameras in consent context) ──
    (
        [
            "consent contract",
            "consent system",
            "ethics come first",
            "interpersonal transparency",
            "surveillance",
            "no persistent data",
            "revocable",
        ],
        [["focusRegion", "bedrock"], ["setRegionDepth", "bedrock", "core"]],
    ),
    # ── Visual effects (specific preset names before broad "camera") ──
    (
        [
            "ghost mode",
            "ghost effect",
            "screwed effect",
            "datamosh",
            "chopped-and-screwed",
            "compositor",
            "visual effect",
            "ring buffer",
            "12 visual",
            "preset",
        ],
        [["focusRegion", "ground"], ["setRegionDepth", "ground", "core"]],
    ),
    # ── Camera / Detection (specific detection phrases) ──
    (
        [
            "six camera",
            "hero camera",
            "camera grid",
            "gaze direction",
            "emotion classification",
            "detection box",
            "desaturated",
            "cyan when",
            "color coding",
        ],
        [["focusRegion", "ground"], ["setRegionDepth", "ground", "core"]],
    ),
    # ── Governance / Axioms ──
    (
        ["axiom", "governance", "constitutional", "tier zero", "precedent", "axiom compliance"],
        [["focusRegion", "bedrock"], ["setRegionDepth", "bedrock", "core"]],
    ),
    # ── Stimmung (hold current — borders visible everywhere) ──
    (["stimmung", "attunement", "system mood", "self-state vector"], []),
    # ── Perception canvas / Sensor fusion → field core ──
    (
        [
            "perception canvas",
            "signal categor",
            "sensor fusion",
            "zone overlay",
            "breathing animation",
        ],
        [["focusRegion", "field"], ["setRegionDepth", "field", "core"]],
    ),
    # ── Agents explicitly (specific count phrases) → field stratum ──
    (
        [
            "specialized agent",
            "33 agent",
            "45 agent",
            "forty-five",
            "briefing agent",
            "health monitor agent",
            "tier one",
            "tier two",
            "tier three",
        ],
        [["focusRegion", "field"], ["setRegionDepth", "field", "stratum"]],
    ),
    # ── Morning / Daily / Briefing / Routine → horizon core ──
    (
        [
            "morning",
            "07:00",
            "06:30",
            "daily briefing",
            "nudge",
            "open loop",
            "preparation without",
            "routine",
            "calendar",
        ],
        [["focusRegion", "horizon"], ["setRegionDepth", "horizon", "core"]],
    ),
    # ── Management / Relationship / 1:1 → field stratum ──
    (
        ["one-on-one", "1:1", "coaching", "team member", "managing work", "relationship"],
        [["focusRegion", "field"], ["setRegionDepth", "field", "stratum"]],
    ),
    # ── Knowledge / Indexed documents → watershed core ──
    (
        [
            "indexed",
            "246,528",
            "document",
            "obsidian",
            "knowledge build",
            "profile system",
            "profile track",
            "learns from",
        ],
        [["focusRegion", "watershed"], ["setRegionDepth", "watershed", "core"]],
    ),
    # ── ChatGPT comparison → show all regions ──
    (
        ["chatgpt memory", "chatgpt wrapper", "not just another", "gemini personal"],
        [["focusRegion", None]],
    ),
    # ── Research proven/not proven → field stratum ──
    (
        ["not proven", "proven", "remains to be", "under active development", "cycle two"],
        [["focusRegion", "field"], ["setRegionDepth", "field", "stratum"]],
    ),
    # ── Closing / Life impact → ambient ──
    (
        [
            "cognitive energy",
            "frees up",
            "family",
            "what it means for our",
            "none of this is finished",
            "that is hapax",
        ],
        [["focusRegion", "ground"]],
    ),
    # ── Executive function (broad — catch late) ──
    (["executive function"], [["focusRegion", "horizon"], ["setRegionDepth", "horizon", "core"]]),
    # ── Voice / RLHF (broad — catch late) ──
    (["rlhf", "voice assistant", "voice system"], []),
]

RESET_ACTIONS: list[list[str | None]] = [
    ["setRegionDepth", "horizon", "surface"],
    ["setRegionDepth", "field", "surface"],
    ["setRegionDepth", "ground", "surface"],
    ["setRegionDepth", "watershed", "surface"],
    ["setRegionDepth", "bedrock", "surface"],
    ["focusRegion", None],
    ["setOverlay", None],
]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:40]


def _infer_actions(
    scene_title: str, scene_narration: str, scene_url: str | None
) -> list[dict[str, Any]]:
    """Infer terrain actions from scene content (title + narration + URL)."""
    actions: list[dict[str, Any]] = []

    # Reset at start of scene
    actions.append({"at": 0.3, "calls": RESET_ACTIONS, "label": "reset"})

    # Try URL-based routing first (if screenshot spec has a URL)
    if scene_url:
        parsed = urlparse(scene_url)
        path = parsed.path.rstrip("/") or "/"
        query = parsed.query
        route_key = f"{path}?{query}" if query else path

        # Direct URL mapping
        url_actions: dict[str, list[list[str | None]]] = {
            "/": [["focusRegion", "ground"]],
            "/?overlay=investigation&tab=chat": [
                ["setOverlay", "investigation"],
                ["setInvestigationTab", "chat"],
            ],
            "/?region=ground&depth=core": [
                ["focusRegion", "ground"],
                ["setRegionDepth", "ground", "core"],
            ],
        }
        if route_key in url_actions:
            actions.append(
                {"at": 1.0, "calls": url_actions[route_key], "label": f"route:{route_key}"}
            )
            return actions

    # Content-based matching: scan title + narration for keywords
    search_text = (scene_title + " " + scene_narration).lower()

    for keywords, calls in CONTENT_ACTIONS:
        if any(kw in search_text for kw in keywords):
            if calls:
                actions.append({"at": 1.5, "calls": calls, "label": f"content:{keywords[0]}"})
            else:
                actions.append({"at": 1.5, "calls": [], "label": f"hold:{keywords[0]}"})
            return actions

    # Default: hold ambient
    actions.append({"at": 1.0, "calls": [["focusRegion", "ground"]], "label": "default:ambient"})
    return actions


def convert_to_app_scenes(
    script: DemoScript,
    demo_dir: Path,
    on_progress: Callable[[str], None] | None = None,
    choreography: list[list[dict]] | None = None,
) -> Path:
    """Convert a DemoScript to app-script.json for in-app DemoRunner playback.

    If choreography is provided (from Opus choreography pass), uses those actions directly.
    Otherwise falls back to keyword-based inference.
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        log.info(msg)

    scenes: list[dict[str, Any]] = []

    if script.intro_narration:
        scenes.append(
            {
                "title": "Introduction",
                "audioFile": "00-intro.wav",
                "actions": [],
            }
        )

    for i, scene in enumerate(script.scenes, 1):
        slug = _slugify(scene.title)
        audio_file = f"{i:02d}-{slug}.wav"

        # Use choreography if available, otherwise fall back to keyword inference
        if choreography and i - 1 < len(choreography) and choreography[i - 1]:
            # Force a reset at t=0 before choreographed actions to prevent state leaking
            reset_action = {"at": 0.0, "calls": RESET_ACTIONS, "label": "auto-reset"}
            choreographed = choreography[i - 1]
            # Only prepend if choreography doesn't already start with a reset
            has_reset = any(
                a.get("label", "") in ("reset", "auto-reset")
                or any(
                    c[0] == "setRegionDepth" and c[2] == "surface"
                    for c in a.get("calls", [])
                    if len(c) >= 3
                )
                for a in choreographed[:2]
            )
            actions = choreographed if has_reset else [reset_action] + choreographed
            source = "choreography"
        else:
            scene_url = scene.screenshot.url if scene.screenshot else None
            actions = _infer_actions(scene.title, scene.narration, scene_url)
            source = "inferred"

        scenes.append(
            {
                "title": scene.title,
                "audioFile": audio_file,
                "actions": actions,
            }
        )

        # Log matched action
        action_count = len([a for a in actions if a.get("calls")])
        progress(f"  Scene {i}: {scene.title} → {source} ({action_count} actions)")

    if script.outro_narration:
        scenes.append(
            {
                "title": "Thank You",
                "audioFile": "99-outro.wav",
                "actions": [{"at": 0.5, "calls": [["focusRegion", "ground"]], "label": "closing"}],
            }
        )

    output_path = demo_dir / "app-script.json"
    output_path.write_text(json.dumps(scenes, indent=2))
    progress(f"App script: {output_path} ({len(scenes)} scenes)")
    return output_path


def render_app_demo_audio(
    script: DemoScript,
    audio_dir: Path,
    speed_factor: float = 1.05,
    on_progress: Callable[[str], None] | None = None,
    backend: str = "auto",
) -> list[Path]:
    """Render TTS audio for all scenes, apply speed adjustment."""
    from agents.demo_pipeline.voice import generate_all_voice_segments

    audio_dir.mkdir(parents=True, exist_ok=True)

    segments: list[tuple[str, str]] = []
    if script.intro_narration:
        segments.append(("00-intro", script.intro_narration))
    for i, scene in enumerate(script.scenes, 1):
        slug = _slugify(scene.title)
        segments.append((f"{i:02d}-{slug}", scene.narration))
    if script.outro_narration:
        segments.append(("99-outro", script.outro_narration))

    paths = generate_all_voice_segments(
        segments, audio_dir, on_progress=on_progress, backend=backend
    )

    if speed_factor != 1.0 and shutil.which("ffmpeg"):
        if on_progress:
            on_progress(f"Applying {speed_factor:.0%} speed adjustment...")
        for path in paths:
            tmp = path.parent / f"_tmp_{path.name}"
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(path), "-filter:a", f"atempo={speed_factor}", str(tmp)],
                capture_output=True,
            )
            if result.returncode == 0:
                tmp.rename(path)
            else:
                tmp.unlink(missing_ok=True)

    return paths

"""Opus choreography pass — generates granular UI action timelines from narration.

Reads finalized narration text alongside the Logos UI reference and produces
a timed action sequence at 1-2 second granularity for each scene.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from shared.config import get_model

log = logging.getLogger(__name__)

UI_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "docs" / "logos-ui-reference.md"

SPEECH_RATE_WPM = 140.0

ACTION_VOCABULARY = """Available UI actions (JSON array format: ["method", ...args]):

REGION CONTROL:
- ["focusRegion", region] — visually emphasize a region. Values: "horizon", "field", "ground", "watershed", "bedrock", null (unfocus all)
- ["setRegionDepth", region, depth] — expand/collapse a region. depth: "surface" (minimal), "stratum" (panels), "core" (full detail)
- ["highlightRegion", region, durationMs] — amber pulse highlight drawing the eye to a region. Use 2000-4000ms typically. Pass null to clear.

OVERLAY CONTROL:
- ["setOverlay", overlay] — show overlay. Values: "investigation", null (close)
- ["setInvestigationTab", tab] — switch investigation tab. Values: "chat", "insight", "demos"

VISUAL EFFECTS:
- ["selectPreset", preset] — switch compositor effect. Values: "ghost", "trails", "screwed", "datamosh", "vhs", "neon", "nightvision", "thermal", "clean"

WHAT EACH REGION SHOWS:
- Horizon (top): briefing, nudges, goals, reactive engine. Expand for executive function content.
- Field (middle-left): agents, perception canvas, operator vitals. Expand for sensor/agent content.
- Ground (center): cameras, ambient canvas, visual effects. Expand for camera/detection/effects content.
- Watershed (middle-right): flow topology, profile dimensions. Expand for system flow/profile content.
- Bedrock (bottom): health, VRAM, containers, consent, governance, accommodations. Expand for infrastructure/governance/ethics content.

DEPTH LEVELS:
- surface: calm, minimal info. Good for conceptual narration, ambient backdrop.
- stratum: panels visible. Good for showing structure (agent grid, camera grid, panel lists).
- core: immersive full detail. Good for deep focus (perception canvas, hero camera, flow graph, governance panels).

CHOREOGRAPHY RULES:
1. Estimate timing from word position: word_N occurs at approximately N / (speech_rate / 60) seconds
2. When narration references a specific UI element, expand that region 1-2 seconds BEFORE the reference
3. Use highlightRegion to draw the eye when narration calls out a specific area (2-4 second pulse)
4. During conceptual/abstract narration (philosophy, research theory), hold the current view — no actions
5. Always reset regions to surface before expanding a different one: ["setRegionDepth", "X", "surface"] for each expanded region
6. Transition gradually: focusRegion first (0.5s), then setRegionDepth (1s later), then highlightRegion (0.5s later)
7. Don't change the UI more than once every 2 seconds — let the audience absorb
8. Ground at surface shows the ambient canvas (warm drifting shapes) — good visual backdrop for conceptual sections
"""

choreography_agent = Agent(
    get_model("claude-opus"),
    system_prompt=(
        "You are a demo choreographer. Given narration text for a scene and a UI reference document, "
        "produce a JSON array of timed UI actions that synchronize the visual display with what the narrator is saying. "
        "Each action has 'at' (seconds from scene start), 'calls' (array of method calls), and 'label' (description). "
        "Output ONLY the JSON array, no markdown, no explanation."
    ),
    output_type=str,
    model_settings={"max_tokens": 4096},
)


def _annotate_narration(text: str, speech_rate: float = SPEECH_RATE_WPM) -> str:
    """Add second markers to narration text for timing reference."""
    words = text.split()
    words_per_second = speech_rate / 60.0
    annotated_parts: list[str] = []
    for i, word in enumerate(words):
        if i % 20 == 0:
            t = i / words_per_second
            annotated_parts.append(f"[{t:.1f}s]")
        annotated_parts.append(word)
    total_t = len(words) / words_per_second
    annotated_parts.append(f"[END {total_t:.1f}s]")
    return " ".join(annotated_parts)


def _parse_actions(raw: str) -> list[dict[str, Any]]:
    """Parse LLM output into action list, tolerant of markdown wrapping."""
    text = raw.strip()
    # Strip markdown code fence if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        actions = json.loads(text)
        if isinstance(actions, list):
            return actions
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    log.warning("Failed to parse choreography output: %s", text[:200])
    return []


async def choreograph(
    script: DemoScript,
    speech_rate: float = SPEECH_RATE_WPM,
    on_progress: Callable[[str], None] | None = None,
) -> list[list[dict[str, Any]]]:
    """Generate granular UI action timelines for each scene.

    Returns a list of action arrays, one per scene (matching script.scenes order).
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        log.info(msg)

    # Load UI reference
    ui_ref = ""
    if UI_REFERENCE_PATH.exists():
        ui_ref = UI_REFERENCE_PATH.read_text()
    else:
        log.warning("UI reference not found at %s", UI_REFERENCE_PATH)

    all_actions: list[list[dict[str, Any]]] = []

    for i, scene in enumerate(script.scenes):
        annotated = _annotate_narration(scene.narration, speech_rate)
        word_count = len(scene.narration.split())
        duration_est = word_count / (speech_rate / 60.0)

        prompt = (
            f"## Scene {i + 1}: {scene.title}\n"
            f"Duration: ~{duration_est:.0f} seconds ({word_count} words at {speech_rate:.0f} WPM)\n\n"
            f"### Narration (with timing markers)\n{annotated}\n\n"
            f"### UI Reference\n{ui_ref}\n\n"
            f"### Action Vocabulary\n{ACTION_VOCABULARY}\n\n"
            f"Produce a JSON array of timed actions for this scene. "
            f"Start with a reset action at t=0 if the scene needs a different view than the previous scene. "
            f"Match actions to narration content — when the narrator mentions a specific UI element, "
            f"make that element visible and highlighted."
        )

        try:
            result = await choreography_agent.run(prompt)
            actions = _parse_actions(result.output)
            progress(
                f"  Scene {i + 1}: {scene.title} → {len(actions)} actions ({duration_est:.0f}s)"
            )
        except Exception as e:
            log.warning("Choreography failed for scene %d: %s", i + 1, e)
            actions = []
            progress(f"  Scene {i + 1}: {scene.title} → FAILED ({e})")

        all_actions.append(actions)

    return all_actions

"""Timeline-driven narrated demo orchestrator.

Renders narration audio first (via Kokoro or Chatterbox), measures durations,
then records Playwright screencasts or takes screenshots timed to match,
and assembles the final MP4.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class NarrationScene(BaseModel):
    """A single scene in a narrated demo."""

    narration: str = Field(description="Text to speak for this scene")
    recipe: str = Field(description="Recipe name from screencasts.RECIPES")
    title: str = Field(default="", description="Chapter title for this scene")
    extra_padding: float = Field(
        default=1.0, ge=0.0, description="Extra seconds of video after narration ends"
    )
    scene_type: Literal["screencast", "screenshot"] = Field(
        default="screenshot",
        description="screencast = Playwright video recording, screenshot = static image with audio",
    )


class NarratedDemoScript(BaseModel):
    """Full script for a narrated demo."""

    title: str
    subtitle: str = Field(default="", description="Subtitle on the title card")
    intro_narration: str = Field(default="", description="Narration over the title card")
    scenes: list[NarrationScene] = Field(min_length=1)
    outro_narration: str = Field(default="", description="Narration over the outro card")


class NarratedDemoResult(BaseModel):
    """Result of a narrated demo render."""

    mp4_path: str
    duration_seconds: float
    chapter_markers: list[tuple[str, float, float]]
    scene_count: int


def _slugify(text: str) -> str:
    """Create a filesystem-safe slug from text."""
    import re

    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:40]


async def _take_screenshot(url: str, output_path: Path, wait_ms: int = 3000) -> Path:
    """Take a single screenshot via Playwright."""
    from playwright.async_api import async_playwright

    output_path.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(wait_ms)
        await page.screenshot(path=str(output_path), full_page=False)
        await browser.close()
    return output_path


async def render_narrated_demo(
    script: NarratedDemoScript,
    output_dir: Path,
    voice_backend: Literal["chatterbox", "kokoro", "auto"] = "auto",
    on_progress: Callable[[str], None] | None = None,
) -> NarratedDemoResult:
    """Render a narrated demo: audio first, then visuals timed to match.

    Pipeline:
    1. Render all narration audio segments
    2. Measure each segment's duration
    3. For screencast scenes: record Playwright video timed to narration
    4. For screenshot scenes: take static screenshot (fast)
    5. Generate title cards (intro/outro)
    6. Assemble final MP4 with audio overlay
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir / "audio"
    video_dir = output_dir / "video"
    screenshot_dir = output_dir / "screenshots"

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        log.info(msg)

    # --- Phase 1: Render narration audio ---
    progress("Phase 1: Rendering narration audio...")

    from agents.demo_pipeline.voice import generate_all_voice_segments, get_wav_duration

    segments: list[tuple[str, str]] = []
    if script.intro_narration:
        segments.append(("00-intro", script.intro_narration))
    for i, scene in enumerate(script.scenes, 1):
        name = f"{i:02d}-{_slugify(scene.title or scene.recipe)}"
        segments.append((name, scene.narration))
    if script.outro_narration:
        segments.append(("99-outro", script.outro_narration))

    audio_paths = generate_all_voice_segments(
        segments, audio_dir, on_progress=on_progress, backend=voice_backend
    )

    # Build duration map keyed by segment name
    durations: dict[str, float] = {}
    for (seg_name, _text), audio_path in zip(segments, audio_paths, strict=True):
        durations[seg_name] = get_wav_duration(audio_path)
        progress(f"  {seg_name}: {durations[seg_name]:.1f}s")

    # --- Phase 2: Separate scenes by type ---
    progress("Phase 2: Computing scene timing...")

    from agents.demo_models import InteractionSpec, InteractionStep
    from agents.demo_pipeline.screencasts import MIN_SCREENCAST_SECONDS, RECIPES

    scene_names: list[str] = []
    screencast_specs: list[tuple[str, InteractionSpec]] = []
    screenshot_scenes: list[tuple[str, str, int]] = []  # (name, url, wait_ms)

    for i, scene in enumerate(script.scenes, 1):
        seg_name = f"{i:02d}-{_slugify(scene.title or scene.recipe)}"
        scene_names.append(seg_name)
        narration_dur = durations.get(seg_name, 10.0)
        target_dur = max(narration_dur + scene.extra_padding, MIN_SCREENCAST_SECONDS)

        if scene.scene_type == "screenshot":
            # Static screenshot — get URL from recipe or default
            base_recipe = RECIPES.get(scene.recipe)
            url = base_recipe.url if base_recipe else "http://localhost:5173/"
            # Execute recipe steps briefly (for nav), then screenshot
            wait_ms = 5000
            if base_recipe:
                # Sum wait steps to know how long to wait for page to settle
                total_wait = sum(
                    int(s.value or "0") for s in base_recipe.steps if s.action == "wait"
                )
                wait_ms = max(3000, min(total_wait, 15000))
            screenshot_scenes.append((seg_name, url, wait_ms))
            progress(f"  {seg_name}: screenshot ({narration_dur:.1f}s narration)")
        else:
            # Screencast — build timed spec
            base_recipe = RECIPES.get(scene.recipe)
            if base_recipe:
                existing_wait_ms = 0
                for step in base_recipe.steps:
                    if step.action == "wait":
                        try:
                            existing_wait_ms += int(step.value or "0")
                        except ValueError:
                            pass
                existing_wait_s = existing_wait_ms / 1000.0
                pad_s = max(0.0, target_dur - existing_wait_s)
                pad_ms = int(pad_s * 1000)

                steps = list(base_recipe.steps)
                if pad_ms > 500:
                    steps.append(InteractionStep(action="wait", value=str(pad_ms)))

                spec = InteractionSpec(
                    url=base_recipe.url,
                    steps=steps,
                    recipe="custom",  # bypass resolve_recipe replacement
                    max_duration=target_dur + 2.0,
                )
            else:
                spec = InteractionSpec(
                    url="http://localhost:5173/",
                    steps=[InteractionStep(action="wait", value=str(int(target_dur * 1000)))],
                    recipe="custom",
                    max_duration=target_dur + 2.0,
                )

            screencast_specs.append((seg_name, spec))
            progress(f"  {seg_name}: screencast target {target_dur:.1f}s")

    # --- Phase 3a: Take screenshots (fast) ---
    visual_paths: dict[str, Path] = {}

    if screenshot_scenes:
        progress(f"Phase 3a: Taking {len(screenshot_scenes)} screenshots...")
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            for seg_name, url, wait_ms in screenshot_scenes:
                page = await browser.new_page(viewport={"width": 1920, "height": 1080})
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(wait_ms)

                # Execute recipe steps for navigation (keyboard presses, etc.)
                # Find the matching scene to get its recipe
                scene_idx = next(j for j, n in enumerate(scene_names) if n == seg_name)
                scene = script.scenes[scene_idx]
                base_recipe = RECIPES.get(scene.recipe)
                if base_recipe:
                    for step in base_recipe.steps:
                        if step.action == "press":
                            await page.keyboard.press(step.value or "Enter")
                            await page.wait_for_timeout(800)
                        elif step.action == "click" and step.target:
                            try:
                                await page.click(step.target, timeout=3000)
                                await page.wait_for_timeout(500)
                            except Exception:
                                pass

                    # Final settle after all navigation
                    await page.wait_for_timeout(2000)

                img_path = screenshot_dir / f"{seg_name}.png"
                img_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(img_path), full_page=False)
                await page.close()
                visual_paths[seg_name] = img_path
                progress(f"  Screenshot: {seg_name}")
            await browser.close()

    # --- Phase 3b: Record screencasts (real-time) ---
    if screencast_specs:
        progress(f"Phase 3b: Recording {len(screencast_specs)} screencasts...")

        from agents.demo_pipeline.screencasts import record_screencasts

        video_results = await record_screencasts(
            screencast_specs, video_dir, on_progress=on_progress
        )
        for (seg_name, _spec), vid_path in zip(screencast_specs, video_results, strict=True):
            visual_paths[seg_name] = vid_path

    # --- Phase 4: Generate title cards ---
    progress("Phase 4: Generating title cards...")

    from agents.demo_pipeline.title_cards import generate_title_card

    intro_card = output_dir / "intro-card.png"
    outro_card = output_dir / "outro-card.png"
    generate_title_card(script.title, intro_card, subtitle=script.subtitle or None)
    generate_title_card(script.title, outro_card, subtitle="Thank you for watching")

    # --- Phase 5: Assemble final video ---
    progress("Phase 5: Assembling final video...")

    from agents.demo_pipeline.video import assemble_video

    # Build screenshots dict in scene order
    screenshots: dict[str, Path] = {}
    scene_durations: dict[str, float] = {}
    for seg_name in scene_names:
        scene_title = seg_name
        for scene in script.scenes:
            slug = _slugify(scene.title or scene.recipe)
            if slug in seg_name:
                scene_title = scene.title or scene.recipe
                break
        if seg_name in visual_paths:
            screenshots[scene_title] = visual_paths[seg_name]
            scene_durations[scene_title] = durations.get(seg_name, 10.0)

    output_path = output_dir / "demo.mp4"
    final_path, total_duration = await assemble_video(
        intro_card=intro_card,
        outro_card=outro_card,
        screenshots=screenshots,
        durations=scene_durations,
        audio_dir=audio_dir,
        output_path=output_path,
        on_progress=on_progress,
    )

    # --- Build chapter markers ---
    chapter_markers: list[tuple[str, float, float]] = []
    cursor = 0.0
    if script.intro_narration:
        intro_dur = durations.get("00-intro", 3.0)
        chapter_markers.append(("Intro", cursor, intro_dur))
        cursor += intro_dur
    for seg_name in scene_names:
        dur = durations.get(seg_name, 10.0)
        title = seg_name
        for scene in script.scenes:
            slug = _slugify(scene.title or scene.recipe)
            if slug in seg_name:
                title = scene.title or scene.recipe
                break
        chapter_markers.append((title, cursor, dur))
        cursor += dur
    if script.outro_narration:
        outro_dur = durations.get("99-outro", 3.0)
        chapter_markers.append(("Outro", cursor, outro_dur))

    progress(f"Demo complete: {final_path} ({total_duration:.1f}s, {len(script.scenes)} scenes)")

    return NarratedDemoResult(
        mp4_path=str(final_path),
        duration_seconds=total_duration,
        chapter_markers=chapter_markers,
        scene_count=len(script.scenes),
    )

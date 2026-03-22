"""Screencast recording pipeline using Playwright video capture."""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from playwright.async_api import Page, async_playwright

from agents.demo_models import InteractionSpec, InteractionStep
from agents.demo_pipeline.screenshots import _preflight_check, fix_localhost_url

log = logging.getLogger(__name__)

# Predefined reliable interaction recipes for common hapax-logos interactions.
# IMPORTANT: Only recipes are supported — custom steps from LLM are not allowed
# because LLMs generate bad timing (e.g. 3s wait for LLM streaming).
# Minimum screencast duration — ensures recordings aren't too short to be useful
MIN_SCREENCAST_SECONDS = 12.0

RECIPES: dict[str, InteractionSpec] = {
    "chat-health-query": InteractionSpec(
        url="http://localhost:5173/chat",
        steps=[
            InteractionStep(action="wait", value="2000"),
            InteractionStep(action="click", target="textarea"),
            InteractionStep(action="type", value="What is the current system health?"),
            InteractionStep(action="press", value="Enter"),
            InteractionStep(action="wait", value="25000"),  # LLM streaming needs time
        ],
        max_duration=40.0,
    ),
    "chat-briefing-query": InteractionSpec(
        url="http://localhost:5173/chat",
        steps=[
            InteractionStep(action="wait", value="2000"),
            InteractionStep(action="click", target="textarea"),
            InteractionStep(action="type", value="Give me today's briefing summary"),
            InteractionStep(action="press", value="Enter"),
            InteractionStep(action="wait", value="25000"),
        ],
        max_duration=40.0,
    ),
    "chat-system-overview": InteractionSpec(
        url="http://localhost:5173/chat",
        steps=[
            InteractionStep(action="wait", value="2000"),
            InteractionStep(action="click", target="textarea"),
            InteractionStep(action="type", value="What can you help me with?"),
            InteractionStep(action="press", value="Enter"),
            InteractionStep(action="wait", value="25000"),
        ],
        max_duration=40.0,
    ),
    "dashboard-overview": InteractionSpec(
        url="http://localhost:5173/",
        steps=[
            InteractionStep(action="wait", value="3000"),
            InteractionStep(action="scroll", value="400"),
            InteractionStep(action="wait", value="3000"),
            InteractionStep(action="scroll", value="400"),
            InteractionStep(action="wait", value="3000"),
            InteractionStep(action="scroll", value="400"),
            InteractionStep(action="wait", value="3000"),
        ],
        max_duration=25.0,
    ),
    "run-health-agent": InteractionSpec(
        url="http://localhost:5173/",
        steps=[
            InteractionStep(action="wait", value="2000"),
            InteractionStep(action="click", target="text=health_monitor"),
            InteractionStep(action="wait", value="20000"),
        ],
        max_duration=30.0,
    ),
}


def _url_to_default_recipe(url: str) -> str:
    """Map a URL to the best default recipe name."""
    from urllib.parse import urlparse

    path = urlparse(url).path.rstrip("/") or "/"
    if path == "/chat":
        return "chat-health-query"
    elif path == "/demos":
        return "dashboard-overview"  # best available fallback
    else:
        return "dashboard-overview"


def resolve_recipe(spec: InteractionSpec) -> InteractionSpec:
    """Resolve a recipe name into a full InteractionSpec.

    ALWAYS uses recipes — custom steps from LLM are replaced with the
    closest matching recipe because LLMs generate bad timing parameters.
    """
    recipe_name = spec.recipe

    # If no recipe specified, infer from URL
    if not recipe_name:
        recipe_name = _url_to_default_recipe(spec.url)
        log.info("No recipe specified for %s, using '%s'", spec.url, recipe_name)

    if recipe_name in RECIPES:
        recipe = RECIPES[recipe_name]
        return recipe.model_copy(
            update={
                "viewport_width": spec.viewport_width,
                "viewport_height": spec.viewport_height,
            }
        )

    # Unknown recipe — fall back to URL-based default
    fallback = _url_to_default_recipe(spec.url)
    log.warning(
        "Unknown recipe '%s', falling back to '%s'. Available: %s",
        recipe_name,
        fallback,
        list(RECIPES.keys()),
    )
    recipe = RECIPES[fallback]
    return recipe.model_copy(
        update={"viewport_width": spec.viewport_width, "viewport_height": spec.viewport_height}
    )


async def _execute_step(page: Page, step: InteractionStep) -> None:
    """Execute a single interaction step on the page."""
    if step.action == "click":
        target = step.target
        if target:
            await page.click(target, timeout=5_000)
        else:
            log.warning("Click step with no target, skipping")

    elif step.action == "type":
        # Type with visible delay so keystrokes appear in recording
        await page.keyboard.type(step.value, delay=50)

    elif step.action == "wait":
        try:
            wait_ms = int(step.value) if step.value else 1000
            await page.wait_for_timeout(min(wait_ms, 30_000))
        except ValueError:
            log.warning("Invalid wait value '%s', waiting 1s", step.value)
            await page.wait_for_timeout(1000)

    elif step.action == "scroll":
        try:
            distance = int(step.value) if step.value else 300
        except ValueError:
            distance = 300
        await page.evaluate(f"window.scrollBy(0, {distance})")

    elif step.action == "press":
        await page.keyboard.press(step.value or "Enter")

    else:
        log.warning("Unknown action '%s', skipping", step.action)


async def _webm_to_mp4(webm_path: Path, mp4_path: Path) -> Path:
    """Convert webm to mp4 using ffmpeg for broad browser compatibility."""
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg not found, returning webm file as-is")
        return webm_path

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(webm_path),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-an",
        str(mp4_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.warning("ffmpeg conversion failed: %s", stderr.decode()[:500])
        return webm_path

    # Clean up webm
    webm_path.unlink(missing_ok=True)
    return mp4_path


async def record_screencasts(
    specs: list[tuple[str, InteractionSpec]],
    output_dir: Path,
    on_progress: Callable[[str], None] | None = None,
) -> list[Path]:
    """Record screencast videos for each interaction spec.

    Each screencast gets its own BrowserContext (Playwright ties video to context lifecycle).

    Args:
        specs: List of (name, InteractionSpec) tuples.
        output_dir: Directory to save mp4 files.
        on_progress: Optional progress callback.

    Returns:
        List of saved mp4 file paths.
    """
    if not specs:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve recipes and fix URLs
    resolved: list[tuple[str, InteractionSpec]] = []
    for name, spec in specs:
        spec = resolve_recipe(spec)
        fixed_url = fix_localhost_url(spec.url)
        if fixed_url != spec.url:
            spec = spec.model_copy(update={"url": fixed_url})
        resolved.append((name, spec))

    # Preflight check — reuse screenshot infrastructure
    preflight_specs = [(name, type("_", (), {"url": spec.url})()) for name, spec in resolved]
    await _preflight_check(preflight_specs)

    paths: list[Path] = []
    video_tmp_dir = output_dir / "_video_tmp"
    video_tmp_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for i, (name, spec) in enumerate(resolved, 1):
                if on_progress:
                    on_progress(f"Recording screencast {i}/{len(resolved)}: {name}")

                # Each screencast gets its own context with video recording
                context = await browser.new_context(
                    viewport={"width": spec.viewport_width, "height": spec.viewport_height},
                    record_video_dir=str(video_tmp_dir),
                    record_video_size={
                        "width": spec.viewport_width,
                        "height": spec.viewport_height,
                    },
                )

                page = await context.new_page()

                try:
                    import time as _time

                    record_start = _time.monotonic()

                    # Navigate — use domcontentloaded for faster start
                    await page.goto(spec.url, wait_until="domcontentloaded")

                    # Execute interaction steps with a safety timeout
                    async def run_steps() -> None:
                        for step in spec.steps:
                            try:
                                await _execute_step(page, step)
                            except Exception as e:
                                log.warning(
                                    "Step %s/%s failed in %s: %s, continuing",
                                    step.action,
                                    step.target or step.value,
                                    name,
                                    e,
                                )

                    try:
                        await asyncio.wait_for(run_steps(), timeout=spec.max_duration)
                    except TimeoutError:
                        log.warning(
                            "Screencast %s hit max_duration (%.0fs), stopping",
                            name,
                            spec.max_duration,
                        )

                    # Enforce minimum recording duration
                    elapsed = _time.monotonic() - record_start
                    if elapsed < MIN_SCREENCAST_SECONDS:
                        pad = MIN_SCREENCAST_SECONDS - elapsed
                        log.info("Padding screencast %s with %.1fs to meet minimum", name, pad)
                        await page.wait_for_timeout(int(pad * 1000))

                    # Brief settle time after interactions
                    await page.wait_for_timeout(500)

                finally:
                    # Close context to finalize video
                    video = page.video
                    await context.close()

                    # Get the recorded video path
                    if video:
                        webm_path = Path(await video.path())
                        mp4_path = output_dir / f"{name}.mp4"
                        final_path = await _webm_to_mp4(webm_path, mp4_path)
                        paths.append(final_path)
                    else:
                        log.warning("No video recorded for %s", name)

        finally:
            await browser.close()

    # Clean up temp dir
    shutil.rmtree(video_tmp_dir, ignore_errors=True)

    return paths

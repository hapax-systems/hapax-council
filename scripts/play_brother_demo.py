"""Play the narrated Hapax/Logos demo LIVE — real browser + audio through speakers.

Rock-solid sync: audio is the master clock. Playwright actions are fire-and-forget.
If a Playwright action fails, audio keeps playing. No hiccups.

Key fix: "hold" recipes (terrain-ambient) do NOT navigate or reset. They preserve
whatever view the previous scene established. Only scenes with explicit navigation
recipes change the browser state.

Usage:
  uv run python scripts/play_brother_demo.py           # full demo
  uv run python scripts/play_brother_demo.py --start 4  # start from scene 4
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
import wave
from pathlib import Path

import sounddevice as sd
import soundfile as sf

log = logging.getLogger(__name__)

AUDIO_DIR = Path("output/demos/brother-demo/audio")

# Recipes that just hold the current view — NO navigation, NO actions
HOLD_RECIPES = {"terrain-ambient"}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:40]


def get_wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _play_audio_sync(path: Path) -> None:
    """Play audio synchronously through speakers."""
    data, samplerate = sf.read(str(path))
    sd.play(data, samplerate)
    sd.wait()


async def play_audio(path: Path) -> None:
    """Play audio non-blocking."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _play_audio_sync, path)


async def safe_action(page, action: str, **kwargs) -> None:
    """Execute a Playwright action, swallowing errors to prevent demo interruption."""
    try:
        if action == "press":
            await page.keyboard.press(kwargs["key"])
        elif action == "click":
            await page.click(kwargs["target"], timeout=3000)
        elif action == "type":
            await page.keyboard.type(kwargs["text"], delay=50)
        elif action == "goto":
            await page.goto(kwargs["url"], wait_until="domcontentloaded")
    except Exception as e:
        log.warning("Action %s failed (non-fatal): %s", action, e)


async def run_scene_actions(page, recipe_name: str, duration: float) -> None:
    """Execute recipe actions, then hold for remaining duration.

    HOLD_RECIPES (terrain-ambient) skip all actions — they just wait,
    preserving whatever the previous scene left on screen.
    """
    if recipe_name in HOLD_RECIPES:
        # Pure hold — don't touch the page at all
        await page.wait_for_timeout(int(duration * 1000))
        return

    from agents.demo_pipeline.screencasts import RECIPES

    recipe = RECIPES.get(recipe_name)
    if not recipe:
        await page.wait_for_timeout(int(duration * 1000))
        return

    # Navigate only if truly needed — avoid resetting terrain region depths
    current_url = page.url
    target_url = recipe.url
    if target_url and _should_navigate(current_url, target_url):
        await safe_action(page, "goto", url=target_url)
        await page.wait_for_timeout(2000)

    # Reset any expanded regions before executing new recipe steps
    # (prevents stacking — e.g. horizon stays expanded when field recipe runs)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)

    # Execute recipe steps
    scene_start = time.monotonic()
    for step in recipe.steps:
        elapsed = time.monotonic() - scene_start
        if elapsed > duration - 1.0:
            break

        if step.action == "wait":
            wait_ms = min(int(step.value or "1000"), 5000)
            await page.wait_for_timeout(wait_ms)
        elif step.action == "press":
            await safe_action(page, "press", key=step.value or "")
            await page.wait_for_timeout(800)
        elif step.action == "click":
            await safe_action(page, "click", target=step.target or "")
            await page.wait_for_timeout(500)
        elif step.action == "type":
            await safe_action(page, "type", text=step.value or "")
        elif step.action == "scroll":
            try:
                dist = int(step.value or "300")
                await page.evaluate(f"window.scrollBy(0, {dist})")
                await page.wait_for_timeout(500)
            except Exception:
                pass

    # Hold for remaining duration
    elapsed = time.monotonic() - scene_start
    remaining_ms = int((duration - elapsed) * 1000)
    if remaining_ms > 100:
        await page.wait_for_timeout(remaining_ms)


def _should_navigate(current_url: str, target_url: str) -> bool:
    """Decide whether we need to navigate. Conservative — avoid resetting terrain state.

    Rules:
    - If target is bare terrain (localhost:5173/ with no query params), NEVER navigate
      if we're already on the terrain. Keyboard shortcuts handle the rest.
    - If target has query params (e.g. ?overlay=investigation&tab=chat), navigate
      only if the current URL doesn't already have those params.
    - If target is a different path entirely, always navigate.
    """
    from urllib.parse import parse_qs, urlparse

    c = urlparse(current_url)
    t = urlparse(target_url)

    c_path = c.path.rstrip("/") or "/"
    t_path = t.path.rstrip("/") or "/"

    # Different host — navigate
    if c.netloc != t.netloc:
        return True

    # Different path — navigate
    if c_path != t_path and t_path not in ("/", "/terrain"):
        return True

    # Same path or both terrain — check if target has specific query params we need
    if not t.query:
        # Target is bare terrain — we're already there, skip navigation
        return False

    # Target has query params — check if current already has them
    t_params = parse_qs(t.query)
    c_params = parse_qs(c.query)
    return any(c_params.get(key) != vals for key, vals in t_params.items())


def _ensure_audio() -> None:
    """Render audio segments if not already present."""
    from scripts.render_brother_demo import SCRIPT

    expected_count = (
        (1 if SCRIPT.intro_narration else 0)
        + len(SCRIPT.scenes)
        + (1 if SCRIPT.outro_narration else 0)
    )
    existing = list(AUDIO_DIR.glob("*.wav"))
    if len(existing) >= expected_count:
        total_dur = sum(get_wav_duration(p) for p in existing)
        print(f"Audio ready: {len(existing)} segments, {total_dur:.0f}s ({total_dur / 60:.1f} min)")
        return

    print("Rendering narration audio (first run)...")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    from agents.demo_pipeline.voice import generate_all_voice_segments

    segments: list[tuple[str, str]] = []
    if SCRIPT.intro_narration:
        segments.append(("00-intro", SCRIPT.intro_narration))
    for i, scene in enumerate(SCRIPT.scenes, 1):
        name = f"{i:02d}-{_slugify(scene.title or scene.recipe)}"
        segments.append((name, scene.narration))
    if SCRIPT.outro_narration:
        segments.append(("99-outro", SCRIPT.outro_narration))

    generate_all_voice_segments(
        segments,
        AUDIO_DIR,
        on_progress=lambda msg: print(f"  {msg}"),
        backend="auto",
    )
    print(f"Audio rendered: {len(segments)} segments")


async def setup_browser_on_workspace(page) -> None:
    """Navigate to Logos and set up fullscreen on a dedicated workspace."""
    await page.goto("http://localhost:5173/", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    # Escape any existing overlays/expansions first
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)
    # Browser fullscreen
    try:
        await page.keyboard.press("F11")
    except Exception:
        pass
    await page.wait_for_timeout(1500)


async def pre_navigate_to_scene(page, scene_idx: int, scenes: list[dict]) -> None:
    """If starting mid-demo, set up the correct view for the target scene.

    Walks backward to find the last scene with an active recipe (not a hold),
    then executes that recipe's navigation to establish the right view.
    """
    from agents.demo_pipeline.screencasts import RECIPES

    # Find last non-hold recipe before the start scene
    for i in range(scene_idx - 1, -1, -1):
        recipe_name = scenes[i].get("recipe")
        if recipe_name and recipe_name not in HOLD_RECIPES:
            recipe = RECIPES.get(recipe_name)
            if recipe:
                print(f"  Pre-navigating: {scenes[i]['name']} [{recipe_name}]")
                await safe_action(page, "goto", url=recipe.url)
                await page.wait_for_timeout(2000)
                # Execute recipe steps quickly (no waits)
                for step in recipe.steps:
                    if step.action == "press":
                        await safe_action(page, "press", key=step.value or "")
                        await page.wait_for_timeout(600)
                    elif step.action == "click":
                        await safe_action(page, "click", target=step.target or "")
                        await page.wait_for_timeout(400)
                await page.wait_for_timeout(1000)
                return

    # No prior recipe found — just show terrain surface
    print("  Pre-navigating: terrain surface (default)")


async def main() -> None:
    from scripts.render_brother_demo import SCRIPT

    # Parse --start argument
    start_scene = 1
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--start" and i < len(sys.argv):
            start_scene = int(sys.argv[i + 1])

    _ensure_audio()

    # Build scene manifest
    scenes: list[dict] = []

    if SCRIPT.intro_narration:
        scenes.append({"name": "Intro", "audio": AUDIO_DIR / "00-intro.wav", "recipe": None})

    for i, scene in enumerate(SCRIPT.scenes, 1):
        seg_name = f"{i:02d}-{_slugify(scene.title or scene.recipe)}"
        scenes.append(
            {
                "name": scene.title or scene.recipe,
                "audio": AUDIO_DIR / f"{seg_name}.wav",
                "recipe": scene.recipe,
            }
        )

    if SCRIPT.outro_narration:
        scenes.append({"name": "Outro", "audio": AUDIO_DIR / "99-outro.wav", "recipe": None})

    # Verify all audio exists
    missing = [s["name"] for s in scenes if not s["audio"].exists()]
    if missing:
        print(f"ERROR: Missing audio for: {missing}")
        return

    total_dur = sum(get_wav_duration(s["audio"]) for s in scenes)
    skip_dur = sum(get_wav_duration(s["audio"]) for s in scenes[: start_scene - 1])
    play_dur = total_dur - skip_dur
    print(f"\n{'=' * 60}")
    print(f"LIVE DEMO: {len(scenes)} scenes, {total_dur:.0f}s total")
    if start_scene > 1:
        print(f"STARTING AT SCENE {start_scene}, skipping {skip_dur:.0f}s")
        print(f"PLAYING: {len(scenes) - start_scene + 1} scenes, {play_dur:.0f}s")
    print(f"{'=' * 60}")
    for i, s in enumerate(scenes, 1):
        dur = get_wav_duration(s["audio"])
        recipe = s["recipe"] or "(hold)"
        marker = " >>>" if i == start_scene else "    "
        hold = " [HOLD]" if recipe in HOLD_RECIPES else ""
        print(f"{marker}{i:2d}. {s['name']:<42s} {dur:5.1f}s  [{recipe}]{hold}")
    print(f"{'=' * 60}")

    print("\nLaunching browser in 2 seconds...")
    time.sleep(2)

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--start-fullscreen",
                "--window-size=2560,1440",
                "--disable-infobars",
                "--hide-scrollbars",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 2560, "height": 1440},
            no_viewport=True,
        )
        page = await context.new_page()

        await setup_browser_on_workspace(page)

        # If starting mid-demo, set up the correct view
        if start_scene > 1:
            await pre_navigate_to_scene(page, start_scene - 1, scenes)

        print("\nDemo playing...\n")

        for idx in range(start_scene - 1, len(scenes)):
            scene_info = scenes[idx]
            name = scene_info["name"]
            audio_path = scene_info["audio"]
            recipe_name = scene_info.get("recipe")
            duration = get_wav_duration(audio_path)

            hold_tag = " [HOLD]" if recipe_name in HOLD_RECIPES else ""
            print(f"  [{idx + 1:2d}/{len(scenes)}] {name} ({duration:.1f}s){hold_tag}")

            # Audio is master clock. Actions are concurrent but subordinate.
            if recipe_name and recipe_name not in HOLD_RECIPES:
                # Active recipe — run actions alongside audio
                audio_task = asyncio.create_task(play_audio(audio_path))
                action_task = asyncio.create_task(run_scene_actions(page, recipe_name, duration))
                await audio_task
                try:
                    await asyncio.wait_for(action_task, timeout=1.0)
                except (TimeoutError, asyncio.CancelledError):
                    action_task.cancel()
            else:
                # Hold or no recipe — just play audio, don't touch the page
                await play_audio(audio_path)

            # Brief breath between scenes
            await page.wait_for_timeout(600)

        # Final hold
        await page.wait_for_timeout(5000)
        print(f"\n{'=' * 60}")
        print("Demo complete.")
        print(f"{'=' * 60}")

        await browser.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())

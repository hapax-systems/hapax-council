"""Silent smoke test — runs every scene's Playwright actions headless, no audio.

Verifies: navigation, keyboard shortcuts, clicks, timing. Takes screenshots for review.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import wave
from pathlib import Path

log = logging.getLogger(__name__)

AUDIO_DIR = Path("output/demos/brother-demo/audio")
SMOKE_DIR = Path("output/demos/brother-demo/smoke-test")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:40]


def get_wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


async def main() -> None:
    from playwright.async_api import async_playwright

    from agents.demo_pipeline.screencasts import RECIPES
    from scripts.render_brother_demo import SCRIPT

    SMOKE_DIR.mkdir(parents=True, exist_ok=True)

    # Build scene list
    scenes: list[dict] = []
    if SCRIPT.intro_narration:
        scenes.append(
            {
                "name": "00-Intro",
                "audio": AUDIO_DIR / "00-intro.wav",
                "recipe": None,
            }
        )
    for i, scene in enumerate(SCRIPT.scenes, 1):
        seg_name = f"{i:02d}-{_slugify(scene.title or scene.recipe)}"
        scenes.append(
            {
                "name": f"{i:02d}-{scene.title or scene.recipe}",
                "audio": AUDIO_DIR / f"{seg_name}.wav",
                "recipe": scene.recipe,
            }
        )
    if SCRIPT.outro_narration:
        scenes.append(
            {
                "name": "99-Outro",
                "audio": AUDIO_DIR / "99-outro.wav",
                "recipe": None,
            }
        )

    total_dur = sum(get_wav_duration(s["audio"]) for s in scenes if s["audio"].exists())
    print(f"Smoke test: {len(scenes)} scenes, {total_dur:.0f}s narration")
    print("Running headless at 2560x1440 against localhost:5173\n")

    errors: list[str] = []
    timings: list[tuple[str, float, str]] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 2560, "height": 1440})
        page = await context.new_page()

        # Initial load
        print("  Loading Logos...")
        await page.goto("http://localhost:5173/", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Verify terrain rendered
        terrain_ok = await page.locator("[data-region='ground']").count() > 0
        if not terrain_ok:
            errors.append("FATAL: Terrain layout not rendered — [data-region='ground'] missing")
            print(f"  FAIL: {errors[-1]}")
            await browser.close()
            return

        print("  Terrain loaded OK\n")

        for idx, scene_info in enumerate(scenes):
            name = scene_info["name"]
            recipe_name = scene_info.get("recipe")
            audio_path = scene_info["audio"]
            audio_dur = get_wav_duration(audio_path) if audio_path.exists() else 0

            scene_start = time.monotonic()
            scene_errors: list[str] = []

            recipe = RECIPES.get(recipe_name) if recipe_name else None

            if recipe:
                # Navigate if needed
                current_path = await page.evaluate("window.location.pathname")
                from urllib.parse import urlparse

                target_path = urlparse(recipe.url).path.rstrip("/") or "/"
                current_path = current_path.rstrip("/") or "/"

                if target_path != current_path:
                    try:
                        await page.goto(recipe.url, wait_until="domcontentloaded")
                        await page.wait_for_timeout(2000)
                    except Exception as e:
                        scene_errors.append(f"nav to {recipe.url}: {e}")

                # Execute steps (capped at 15s for smoke test — don't wait full audio duration)
                for step_idx, step in enumerate(recipe.steps):
                    try:
                        if step.action == "wait":
                            # Cap waits at 2s for smoke test speed
                            wait_ms = min(int(step.value or "1000"), 2000)
                            await page.wait_for_timeout(wait_ms)
                        elif step.action == "press":
                            await page.keyboard.press(step.value or "")
                            await page.wait_for_timeout(600)
                        elif step.action == "click":
                            await page.click(step.target or "", timeout=3000)
                            await page.wait_for_timeout(400)
                        elif step.action == "type":
                            await page.keyboard.type(step.value or "", delay=30)
                        elif step.action == "scroll":
                            dist = int(step.value or "300")
                            await page.evaluate(f"window.scrollBy(0, {dist})")
                            await page.wait_for_timeout(300)
                    except Exception as e:
                        scene_errors.append(
                            f"step {step_idx} ({step.action} {step.target or step.value}): {e}"
                        )
            else:
                # No recipe — just brief hold
                await page.wait_for_timeout(1500)

            # Screenshot after scene
            screenshot_path = SMOKE_DIR / f"{name.replace(' ', '-').lower()}.png"
            await page.screenshot(path=str(screenshot_path))

            elapsed = time.monotonic() - scene_start
            status = "OK" if not scene_errors else f"WARN ({len(scene_errors)} issues)"
            timings.append((name, elapsed, status))

            if scene_errors:
                for err in scene_errors:
                    errors.append(f"{name}: {err}")

            icon = "  " if not scene_errors else "!!"
            print(
                f"  {icon} [{idx + 1:2d}/{len(scenes)}] {name:<45s} "
                f"{elapsed:5.1f}s (audio: {audio_dur:5.1f}s)  {status}"
            )

            # Brief reset between scenes
            await page.wait_for_timeout(300)

        # Final screenshot
        await page.screenshot(path=str(SMOKE_DIR / "final.png"))
        await browser.close()

    # Report
    print(f"\n{'=' * 70}")
    if errors:
        print(f"ISSUES ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")
    else:
        print("ALL SCENES PASSED — no Playwright errors")

    print(f"\nScreenshots saved to: {SMOKE_DIR}/")
    print(f"Total smoke test time: {sum(t for _, t, _ in timings):.1f}s")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())

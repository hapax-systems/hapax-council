"""Screenshot capture pipeline using Playwright."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from agents.demo_models import ScreenshotSpec

log = logging.getLogger(__name__)

# Known-good selectors for hapax-logos routes. The LLM-generated wait_for
# values are unreliable because the LLM guesses element text without DOM
# inspection. These selectors match text that is always rendered.
ROUTE_SELECTORS: dict[str, str] = {
    "/": "[data-region='ground']",  # Terrain layout — always present
    "/terrain": "[data-region='ground']",  # Explicit terrain route
    "/chat": "textarea",  # ChatInput textarea (placeholder not visible to text= selector)
    "/demos": "text=Demos",  # Page heading (loading detection handles the rest)
}

# Additional known services (not hapax-logos, different ports)
EXTRA_SERVICE_SELECTORS: dict[str, str] = {
    "localhost:3080": "textarea",  # Open WebUI — chat textarea
}

# Text patterns that indicate incomplete page load — retry if detected
LOADING_INDICATORS = [
    "Loading demos",
    "Loading...",
    "Connecting...",
    "Connecting",
    "loading",
    "Thinking...",
    "Generating...",
]

# Valid hapax-logos routes. LLM sometimes invents URLs (e.g. localhost:8080).
VALID_ROUTES = list(ROUTE_SELECTORS.keys())

# Default Playwright actions for routes that need seeding to show content.
# Chat page is 100% client-state — blank without user interaction.
# Multiple variants so different screenshots of /chat show different content.
CHAT_QUESTION_VARIANTS: list[str] = [
    # Use questions that get fast TEXT responses (no tool calls).
    # Tool-calling queries (health check, GPU memory, briefing) take 30-60s+
    # and screenshots capture "Thinking..." loading state.
    "What agents are available in this system?",
    "Explain the three-tier architecture",
    "What can the briefing agent do?",
    "How does the profile learning system work?",
    "What is the governance framework?",
]

_chat_variant_index = 0

ROUTE_DEFAULT_ACTIONS: dict[str, list[str]] = {
    "/chat": [
        "click textarea",
        "type Run a quick health check",
        "wait 1000",
    ],
}


def fix_localhost_url(url: str) -> str:
    """Fix localhost URLs to use the correct port and valid hapax-logos routes.

    Reusable by both screenshot and screencast pipelines.
    """
    parsed = urlparse(url)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        return url

    # Known valid ports: 5173 (hapax-logos), 8051 (logos API), 3080 (Open WebUI)
    if parsed.port not in (5173, 8051, 3080):
        url = f"http://localhost:5173{parsed.path or '/'}"
        log.warning("Rewrote invalid URL %s -> %s", parsed.geturl(), url)
        parsed = urlparse(url)

    # Fix unknown routes (only for hapax-logos, not other services)
    path = parsed.path.rstrip("/") or "/"
    if parsed.port in (5173, 8051) and path not in VALID_ROUTES:
        best = "/"
        for route in VALID_ROUTES:
            if route != "/" and route in path:
                best = route
                break
        url = f"http://localhost:{parsed.port}{best}"
        log.warning("Rewrote unknown route %s -> %s", parsed.geturl(), url)

    return url


def validate_screenshot_specs(
    specs: list[tuple[str, ScreenshotSpec]],
) -> list[tuple[str, ScreenshotSpec]]:
    """Validate and fix screenshot URLs.

    - Rewrites invalid localhost URLs to the closest valid hapax-logos route.
    - Injects default actions for routes that need seeding (e.g. /chat).
    """
    fixed: list[tuple[str, ScreenshotSpec]] = []
    for name, spec in specs:
        # Fix URL
        fixed_url = fix_localhost_url(spec.url)
        if fixed_url != spec.url:
            spec = spec.model_copy(update={"url": fixed_url})

        parsed = urlparse(spec.url)
        if parsed.hostname in ("localhost", "127.0.0.1"):
            # Override actions for routes with known-good seeding sequences.
            # LLM-generated actions use wrong syntax (e.g. type('text'), press('Enter'))
            # so we always replace them for known routes.
            path = parsed.path.rstrip("/") or "/"
            if path in ROUTE_DEFAULT_ACTIONS:
                if spec.actions:
                    log.info("Replacing LLM actions with known-good actions for %s", path)
                # Cycle through chat question variants for different screenshots
                if path == "/chat":
                    global _chat_variant_index
                    question = CHAT_QUESTION_VARIANTS[
                        _chat_variant_index % len(CHAT_QUESTION_VARIANTS)
                    ]
                    _chat_variant_index += 1
                    # Type but DON'T press Enter — the chat agent uses tool calls
                    # that take 20-45s to complete, so pressing Enter produces
                    # "Thinking..." screenshots.  A staged question in the input
                    # field looks intentional and avoids the loading state.
                    actions = [
                        "click textarea",
                        f"type {question}",
                        "wait 1000",
                    ]
                    spec = spec.model_copy(update={"actions": actions})
                else:
                    spec = spec.model_copy(update={"actions": ROUTE_DEFAULT_ACTIONS[path]})
                log.info("Injected default actions for %s", path)

        fixed.append((name, spec))
    return fixed


def _resolve_selector(spec: ScreenshotSpec) -> str | None:
    """Return a reliable wait-for selector for the given spec.

    Priority: known-good route selector > spec.wait_for > None.
    """
    # Check if URL matches a known route
    parsed = urlparse(spec.url)
    if parsed.hostname in ("localhost", "127.0.0.1"):
        if parsed.port in (5173, 8051):
            path = parsed.path.rstrip("/") or "/"
            if path in ROUTE_SELECTORS:
                return ROUTE_SELECTORS[path]
        # Check extra services
        netloc = f"{parsed.hostname}:{parsed.port}"
        if netloc in EXTRA_SERVICE_SELECTORS:
            return EXTRA_SERVICE_SELECTORS[netloc]

    # Fall back to spec's wait_for with syntax normalization
    if spec.wait_for:
        selector = spec.wait_for
        if not selector.startswith(("#", ".", "[", "text=", "css=")):
            selector = f"text={selector}"
        return selector

    return None


def _clear_chat_session() -> None:
    """Delete the persisted logos chat session so new sessions start in chat mode.

    The logos API loads persisted session state on every session create.
    If the last interactive session was in interview mode, demo screenshots
    would show "I'm the interview agent" responses instead of system tool responses.
    """
    try:
        from shared.config import LOGOS_STATE_DIR

        session_file = LOGOS_STATE_DIR / "chat-session.json"
        if session_file.exists():
            session_file.unlink()
            log.info("Cleared persisted chat session to ensure chat mode for screenshots")
    except Exception as e:
        log.warning("Could not clear chat session file: %s", e)


async def _preflight_check(specs: list[tuple[str, ScreenshotSpec]]) -> None:
    """Verify target URLs are reachable before launching browser."""
    import httpx

    checked: set[str] = set()
    async with httpx.AsyncClient(timeout=3) as client:
        for _, spec in specs:
            origin = f"{urlparse(spec.url).scheme}://{urlparse(spec.url).netloc}"
            if origin in checked:
                continue
            checked.add(origin)
            try:
                await client.get(origin)
            except httpx.HTTPError:
                hint = ""
                if "localhost:5173" in origin or "localhost:8051" in origin:
                    hint = " If this is hapax-logos, start it with: cd ~/projects/hapax-logos && pnpm dev"
                raise ConnectionError(f"Cannot reach {origin}.{hint}") from None


async def capture_screenshots(
    specs: list[tuple[str, ScreenshotSpec]],
    output_dir: Path,
    on_progress: Callable[[str], None] | None = None,
    max_retries: int = 2,
) -> list[Path]:
    """Capture screenshots for each spec. Returns list of saved file paths."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError  # noqa: F811
    from playwright.async_api import async_playwright

    specs = validate_screenshot_specs(specs)
    await _preflight_check(specs)

    # Clear persisted chat session so new sessions start in chat mode (not interview mode).
    # The logos API restores persisted sessions on creation, and if the last session
    # was in interview mode, new sessions will also be in interview mode.
    _clear_chat_session()

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()

            for i, (name, spec) in enumerate(specs, 1):
                if on_progress:
                    on_progress(f"Capturing screenshot {i}/{len(specs)}: {name}")

                # Chat pages need fresh context — SPA accumulates messages
                parsed_url = urlparse(spec.url)
                is_chat = parsed_url.path.rstrip("/") == "/chat" and parsed_url.hostname in (
                    "localhost",
                    "127.0.0.1",
                )
                if is_chat:
                    await page.close()
                    page = await browser.new_page()

                for attempt in range(max_retries + 1):
                    try:
                        await page.set_viewport_size(
                            {"width": spec.viewport_width, "height": spec.viewport_height}
                        )
                        await page.goto(spec.url, wait_until="networkidle", timeout=60_000)

                        selector = _resolve_selector(spec)
                        if selector:
                            try:
                                await page.wait_for_selector(selector, timeout=10_000)
                            except PlaywrightTimeoutError:
                                log.warning(
                                    "Selector %r not found on %s, capturing page as-is",
                                    selector,
                                    spec.url,
                                )
                                await asyncio.sleep(2)  # Brief settle time

                        # Wait for loading indicators to disappear
                        body_text = await page.text_content("body") or ""
                        if any(ind in body_text for ind in LOADING_INDICATORS):
                            log.info("Page still loading, waiting for content to settle...")
                            for _ in range(15):  # Up to 15 extra seconds
                                await asyncio.sleep(1)
                                body_text = await page.text_content("body") or ""
                                if not any(ind in body_text for ind in LOADING_INDICATORS):
                                    break
                            else:
                                log.warning("Page still shows loading state after 15s extra wait")

                        for action in spec.actions:
                            try:
                                parts = action.split(" ", 1)
                                cmd = parts[0]
                                arg = parts[1] if len(parts) > 1 else ""

                                # Normalize Playwright-style actions to simple commands
                                # e.g. "page.waitForTimeout(2000)" → wait 2000
                                # e.g. "page.click('.btn')" → click .btn
                                import re as _re

                                pw_match = _re.match(
                                    r"page\.(click|type|fill|waitForTimeout|locator)\((.*)\)",
                                    action,
                                )
                                if pw_match:
                                    pw_cmd = pw_match.group(1)
                                    pw_arg = pw_match.group(2).strip("'\"")
                                    if pw_cmd == "waitForTimeout":
                                        cmd, arg = "wait", pw_arg
                                    elif pw_cmd == "click":
                                        cmd, arg = "click", pw_arg
                                    elif pw_cmd in ("type", "fill"):
                                        cmd, arg = "type", pw_arg
                                    elif pw_cmd == "locator":
                                        # Skip complex locator chains
                                        log.info("Skipping complex Playwright locator action")
                                        continue

                                if cmd == "click":
                                    await page.click(arg, timeout=5_000)
                                elif cmd == "type":
                                    await page.keyboard.type(arg.strip("'\""))
                                elif cmd == "scroll":
                                    try:
                                        distance = int(arg) if arg else 400
                                        # Use mouse.wheel — works on SPA scroll containers
                                        # where window.scrollBy has no effect
                                        await page.mouse.move(960, 540)
                                        await page.mouse.wheel(0, distance)
                                        await asyncio.sleep(1)  # settle after scroll
                                    except ValueError:
                                        log.warning("Invalid scroll distance '%s', skipping", arg)
                                elif cmd == "press":
                                    await page.keyboard.press(arg.strip("'\""))
                                elif cmd == "wait":
                                    try:
                                        wait_ms = int(arg)
                                        await page.wait_for_timeout(min(wait_ms, 30000))
                                    except ValueError:
                                        log.warning("Invalid wait duration '%s', skipping", arg)
                                else:
                                    log.warning("Unknown action '%s', skipping", cmd)
                            except Exception as e:
                                log.warning("Action '%s' failed: %s, continuing", action, e)

                        # Post-action: wait for loading indicators to clear
                        if spec.actions:
                            await asyncio.sleep(1)  # Brief settle for React rendering
                            body_text = await page.text_content("body") or ""
                            if any(ind in body_text for ind in LOADING_INDICATORS):
                                log.info("Post-action loading detected, waiting for content...")
                                for _ in range(45):  # Up to 45s for LLM responses
                                    await asyncio.sleep(1)
                                    body_text = await page.text_content("body") or ""
                                    if not any(ind in body_text for ind in LOADING_INDICATORS):
                                        await asyncio.sleep(1)  # Extra settle
                                        break
                                else:
                                    log.warning(
                                        "Page still shows loading state after 45s post-action wait"
                                    )

                        filepath = output_dir / f"{name}.png"

                        if spec.capture == "fullpage":
                            await page.screenshot(path=str(filepath), full_page=True)
                        elif spec.capture == "viewport":
                            await page.screenshot(path=str(filepath))
                        else:
                            element = await page.query_selector(spec.capture)
                            if element:
                                await element.screenshot(path=str(filepath))
                            else:
                                log.warning(
                                    "Selector %s not found, falling back to viewport", spec.capture
                                )
                                await page.screenshot(path=str(filepath))

                        break
                    except Exception as e:
                        if attempt == max_retries:
                            raise
                        log.warning(
                            "Screenshot attempt %d failed for %s: %s, retrying...",
                            attempt + 1,
                            name,
                            e,
                        )
                        await asyncio.sleep(2)

                paths.append(filepath)
        finally:
            await browser.close()

    return paths

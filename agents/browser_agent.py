"""agents/browser_agent.py — Agent for web content interaction.

Takes a URL or natural language task, navigates the headless browser,
extracts the A11y tree, compresses via LLMLingua-2, and reasons with Claude.

Usage:
    uv run python -m agents.browser_agent --task "check PR 145"
    uv run python -m agents.browser_agent --url "https://github.com/ryanklee/hapax-council/pull/145"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

import httpx

from shared.browser_services import resolve_url
from shared.config import COCKPIT_API_URL
from shared.context_compression import _get_compressor

log = logging.getLogger(__name__)

DIRECTIVE_URL = f"{COCKPIT_API_URL}/api/logos/directive"
A11Y_PATH = Path("/dev/shm/hapax-logos/browser-a11y.txt")
RESPONSE_PATH = Path("/dev/shm/hapax-logos/browser-response.json")


async def post_directive(directive: dict) -> dict:
    """Post a directive to the Logos bridge."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(DIRECTIVE_URL, json=directive)
        resp.raise_for_status()
        return resp.json()


async def navigate_and_extract(url: str, source: str = "browser-agent") -> str:
    """Navigate to URL and extract A11y tree."""
    # Navigate
    await post_directive({"browser_navigate": url, "source": source})

    # Wait for navigation to complete
    await asyncio.sleep(2.0)

    # Extract A11y tree
    await post_directive({"browser_extract_a11y": True, "source": source})

    # Wait for extraction
    await asyncio.sleep(1.5)

    # Read the tree
    if A11Y_PATH.exists():
        return A11Y_PATH.read_text()
    return ""


def compress_a11y_tree(tree: str) -> str:
    """Compress A11y tree using LLMLingua-2 if available."""
    compressor = _get_compressor()
    if compressor is None:
        log.info("LLMLingua-2 not available, using raw A11y tree")
        return tree

    try:
        result = compressor.compress_prompt_llmlingua2(
            [tree],
            rate=0.33,
            force_tokens=["\n", "[", "]", "{", "}"],
        )
        compressed = result.get("compressed_prompt", tree)
        log.info(
            "A11y tree compressed: %d → %d chars (%.1fx)",
            len(tree),
            len(compressed),
            len(tree) / max(len(compressed), 1),
        )
        return compressed
    except Exception:
        log.warning("LLMLingua-2 compression failed, using raw tree", exc_info=True)
        return tree


def resolve_task_to_url(task: str) -> str | None:
    """Try to resolve a natural language task to a URL.

    Handles patterns like:
    - "check PR 145" → github pr 145
    - "show Grafana api-latency board" → grafana board
    """
    # PR pattern
    if match := re.search(r"(?:PR|pull request)\s*#?(\d+)", task, re.IGNORECASE):
        pr_id = match.group(1)
        return resolve_url("github", "pr", {"id": pr_id})

    # Issue pattern
    if match := re.search(r"(?:issue)\s*#?(\d+)", task, re.IGNORECASE):
        issue_id = match.group(1)
        return resolve_url("github", "issue", {"id": issue_id})

    # Grafana board
    if match := re.search(r"grafana.*?board\s+(\S+)", task, re.IGNORECASE):
        board_id = match.group(1)
        return resolve_url("grafana", "board", {"id": board_id})

    # Direct URL
    if re.match(r"https?://", task):
        return task

    return None


async def run_browser_task(task: str | None = None, url: str | None = None) -> dict:
    """Execute a browser task and return results."""
    if url is None and task:
        url = resolve_task_to_url(task)
        if url is None:
            return {"error": f"Could not resolve task to URL: {task}"}

    if url is None:
        return {"error": "No URL or task provided"}

    log.info("Browser task: navigating to %s", url)

    tree = await navigate_and_extract(url)
    if not tree:
        return {"error": "Failed to extract A11y tree", "url": url}

    compressed = compress_a11y_tree(tree)

    return {
        "url": url,
        "task": task,
        "a11y_tree_raw_len": len(tree),
        "a11y_tree_compressed_len": len(compressed),
        "a11y_tree": compressed,
    }


def main():
    parser = argparse.ArgumentParser(description="Hapax browser agent")
    parser.add_argument("--task", type=str, help="Natural language task (e.g. 'check PR 145')")
    parser.add_argument("--url", type=str, help="Direct URL to navigate to")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.task and not args.url:
        parser.error("Must provide --task or --url")

    result = asyncio.run(run_browser_task(task=args.task, url=args.url))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

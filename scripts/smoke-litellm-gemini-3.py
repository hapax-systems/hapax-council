#!/usr/bin/env python3
"""Smoke-test the Gemini 3 LiteLLM routes.

Closes the verification half of cc-task ``litellm-gemini-3-route-evaluation``.
The recommendation document is at
``docs/research/2026-05-01-litellm-gemini-3-route-evaluation.md``.

Sends a single low-cost prompt to each Gemini 3 alias the operator
wants to verify, prints the per-alias outcome (OK + latency, or ERR +
status snippet), and exits 0 on the first error so CI doesn't burn
quota chasing a misconfigured key.

The script never prints the API key. It uses the standard
``shared.config.get_model(alias)`` factory so it exercises the same
LiteLLM provider path the runtime uses.

Usage:

    LITELLM_API_KEY=$(pass show hapax/litellm-api-key) \
        uv run python scripts/smoke-litellm-gemini-3.py

By default, smokes the four new Gemini 3 aliases:
``fast-3``, ``long-context-3``, ``extraction``, ``scouting``.
Override with ``--alias`` (repeatable). Use ``--prompt`` to override
the smoke prompt; default is a one-token "ping" so the call cost is
~1 input token.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

DEFAULT_ALIASES: tuple[str, ...] = (
    "fast-3",
    "long-context-3",
    "extraction",
    "scouting",
)
DEFAULT_PROMPT = "ping"


async def _smoke_one(alias: str, prompt: str) -> tuple[str, float | None, str | None]:
    """Send ``prompt`` to ``alias``. Return (alias, latency_ms, error).

    On success, ``error`` is None and ``latency_ms`` is the wall-clock
    round-trip in ms. On failure, ``latency_ms`` is None and ``error``
    is a short string suitable for a single CLI line.
    """
    from pydantic_ai import Agent

    from shared.config import get_model

    try:
        model = get_model(alias)
    except Exception as e:
        return (alias, None, f"factory-error: {type(e).__name__}: {e}"[:120])

    agent = Agent(model)
    t0 = time.monotonic()
    try:
        result = await agent.run(prompt)
    except Exception as e:
        return (alias, None, f"{type(e).__name__}: {e}"[:120])

    elapsed_ms = (time.monotonic() - t0) * 1000.0
    # ``result.output`` is the canonical pydantic-ai surface; we don't print it
    # (the smoke is for availability, not output verification).
    if not getattr(result, "output", None):
        return (alias, None, "empty-output")
    return (alias, elapsed_ms, None)


def _format_row(alias: str, latency_ms: float | None, error: str | None) -> str:
    if error is not None:
        return f"{alias}: ERR {error}"
    assert latency_ms is not None
    return f"{alias}: OK (latency={latency_ms:.0f}ms)"


async def _smoke_all(aliases: list[str], prompt: str) -> list[tuple[str, float | None, str | None]]:
    """Smoke each alias serially. Serial (not gather) so one failing
    auth doesn't burn 4 redundant 401s before we surface it."""
    return [await _smoke_one(alias, prompt) for alias in aliases]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the Gemini 3 LiteLLM aliases.",
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=None,
        help=(f"Alias to smoke (repeatable). Default: {', '.join(DEFAULT_ALIASES)}."),
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Smoke prompt (default: %(default)r).",
    )
    args = parser.parse_args(argv)

    aliases = list(args.alias) if args.alias else list(DEFAULT_ALIASES)

    rows = asyncio.run(_smoke_all(aliases, args.prompt))
    any_error = False
    for row in rows:
        print(_format_row(*row))
        if row[2] is not None:
            any_error = True

    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

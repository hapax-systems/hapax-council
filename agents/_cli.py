"""shared/cli.py -- Common CLI boilerplate for agents.

Reduces per-agent argparse/output/notification boilerplate from
20-65 lines to 3-5 lines.

Usage:
    from agents._cli import add_common_args, handle_output

    parser = argparse.ArgumentParser(prog="python -m agents.briefing")
    add_common_args(parser, save=True, hours=True, notify=True)
    args = parser.parse_args()

    result = await generate_briefing(args.hours)
    handle_output(result, args, save_path=BRIEFING_FILE)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel


def add_common_args(
    parser: argparse.ArgumentParser,
    *,
    save: bool = False,
    hours: bool = False,
    notify: bool = False,
) -> None:
    """Add common agent CLI flags to an argument parser."""
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    if save:
        parser.add_argument("--save", action="store_true", help="Save output to disk")
    if hours:
        parser.add_argument("--hours", type=int, default=24, help="Lookback window (default: 24)")
    if notify:
        parser.add_argument("--notify", action="store_true", help="Send push notification")


def handle_output(
    result: BaseModel,
    args: argparse.Namespace,
    *,
    human_formatter: Callable[[Any], str] | None = None,
    save_path: Path | None = None,
    save_formatter: Callable[[Any], str] | None = None,
    notify_title: str = "",
    notify_formatter: Callable[[Any], str] | None = None,
) -> None:
    """Handle common output modes: --json, human, --save, --notify.

    Args:
        result: Pydantic model to output.
        args: Parsed CLI args (expects .json, optionally .save, .notify).
        human_formatter: Callable to format result for human display.
        save_path: Path to write output if --save is set.
        save_formatter: Callable to format result for saving. Defaults to JSON.
        notify_title: Title for push notifications.
        notify_formatter: Callable to format notification body.
    """
    # Output first — save/notify errors should never suppress user-visible output
    if getattr(args, "json", False):
        print(result.model_dump_json(indent=2))
    elif human_formatter:
        print(human_formatter(result))
    else:
        print(result.model_dump_json(indent=2))

    if getattr(args, "save", False) and save_path:
        content = save_formatter(result) if save_formatter else result.model_dump_json(indent=2)
        save_path.write_text(content)
        print(f"Saved to {save_path}", file=sys.stderr)

    if getattr(args, "notify", False) and notify_title:
        from agents._notify import send_notification

        body = notify_formatter(result) if notify_formatter else str(result)
        send_notification(notify_title, body[:500])

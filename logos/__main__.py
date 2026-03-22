"""Entry point for the logos: web dashboard API server or one-shot snapshot."""

from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="System logos — web dashboard API server for the agent stack",
        prog="logos",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print a snapshot and exit (no server)",
    )
    parser.add_argument(
        "--color",
        action="store_true",
        help="Enable color output in snapshot mode (default: plain text)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for API server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8051,
        help="Bind port for API server (default: 8051)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on file changes (dev mode)",
    )
    args = parser.parse_args()

    if args.once:
        from logos.snapshot import generate_snapshot, generate_snapshot_rich

        if args.color:
            from rich.console import Console

            console = Console()
            output = asyncio.run(generate_snapshot_rich())
            console.print(output)
        else:
            output = asyncio.run(generate_snapshot())
            print(output)
        sys.exit(0)

    # Launch API server (web dashboard backend)
    import uvicorn

    uvicorn.run(
        "logos.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

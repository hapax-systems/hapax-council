"""Run the cockpit API server.

Usage:
    uv run python -m cockpit.api
    uv run python -m cockpit.api --port 8051 --host 127.0.0.1
"""
from __future__ import annotations

import argparse
import logging

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cockpit API server",
        prog="python -m cockpit.api",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8051, help="Bind port (default: 8051)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on file changes")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    uvicorn.run(
        "cockpit.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

"""CLI entry point for the studio effects runner.

Usage:
    uv run python -m agents.studio_fx                    # Run all effects
    uv run python -m agents.studio_fx --effect ghost      # Run single effect (debug)
    uv run python -m agents.studio_fx --list              # List effects
    uv run python -m agents.studio_fx --benchmark         # Benchmark all effects
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from agents.studio_fx.effects import ALL_EFFECTS
from agents.studio_fx.runner import EffectRunner

log = logging.getLogger("agents.studio_fx")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="studio_fx",
        description="Studio visual effects runner (numpy/OpenCV)",
    )
    p.add_argument(
        "--effect",
        type=str,
        default=None,
        help="Run a single effect by name (debug mode)",
    )
    p.add_argument(
        "--active",
        type=str,
        default="clean",
        help="Initial active effect (default: clean)",
    )
    p.add_argument(
        "--fps",
        type=float,
        default=15.0,
        help="Target frames per second (default: 15)",
    )
    p.add_argument(
        "--v4l2",
        type=str,
        default="/dev/video50",
        help="v4l2 loopback device for active output (default: /dev/video50)",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List available effects and exit",
    )
    p.add_argument(
        "--benchmark",
        action="store_true",
        help="Benchmark all effects and exit",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    all_names = [cls.name for cls in ALL_EFFECTS]

    if args.list:
        for name in all_names:
            marker = " (default active)" if name == "clean" else ""
            print(f"  {name}{marker}")
        return

    # Build effect instances
    if args.effect:
        # Single effect debug mode
        matches = [cls for cls in ALL_EFFECTS if cls.name == args.effect]
        if not matches:
            print(f"Unknown effect: {args.effect}")
            print(f"Available: {', '.join(all_names)}")
            sys.exit(1)
        effect_classes = matches
        active = args.effect
    else:
        effect_classes = list(ALL_EFFECTS)
        active = args.active

    # Instantiate at default 1080p — runner will resize per tier
    effects = [cls(1920, 1080) for cls in effect_classes]

    runner = EffectRunner(
        effects,
        target_fps=args.fps,
        active_name=active,
        v4l2_device=args.v4l2,
    )

    if args.benchmark:
        results = runner.benchmark()
        print("\n--- Benchmark Results (avg ms per frame @ 1080p) ---")
        for name, ms in sorted(results.items(), key=lambda x: x[1]):
            budget = "OK" if ms < 10 else "SLOW" if ms < 20 else "OVER"
            print(f"  {name:12s}  {ms:7.2f}ms  [{budget}]")
        total = sum(results.values())
        print(f"  {'TOTAL':12s}  {total:7.2f}ms")
        return

    # Graceful shutdown on SIGTERM/SIGINT
    def _shutdown(sig: int, _frame: object) -> None:
        log.info("Received signal %d, shutting down", sig)
        runner.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    runner.run()


if __name__ == "__main__":
    main()

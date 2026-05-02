"""``python -m agents.runway_bigpitch`` CLI orchestrator.

Reads a prompt brief from a file, calls Runway Gen-3 via the typed
client, polls until terminal, downloads the result. Defaults are
contest-safe: watermark=True, model=gen3a_turbo, dry-run.

Operator runs::

    python -m agents.runway_bigpitch \\
      --prompt-file ~/Documents/Personal/30-areas/hapax-bigpitch/prompt.md \\
      --duration 60 \\
      --output ~/hapax-state/runway-bigpitch/trailer.mp4 \\
      --live

The ``--live`` flag is required to actually call the Runway API (and
spend credits / count against contest entry); without it the CLI
prints what it would do, validating the request body and checking
that ``RUNWAY_API_KEY`` is set, but does not POST.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.runway_gen3_client import (
    DEFAULT_MODEL,
    GenerateRequest,
    RunwayClientError,
    RunwayGen3Client,
    RunwayTaskStatus,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m agents.runway_bigpitch",
        description=(
            "Generate a Runway Gen-3 video for the Big Pitch contest. "
            "Watermark defaults to True (contest requirement). "
            "Submission is via social-media hashtag, NOT this script."
        ),
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        required=True,
        help="Markdown / text file containing the trailer prompt brief.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=10,
        help=(
            "Video length in seconds. Contest accepts 60-180. "
            "Default 10 for cheap dry-runs; bump for the real submission."
        ),
    )
    parser.add_argument(
        "--ratio",
        type=str,
        default="1280:768",
        help="Output aspect ratio (default landscape 16:10ish).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Runway model id. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for reproducibility. None lets Runway pick.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "hapax-state/runway-bigpitch/output.json",
        help="Where to write the final task JSON envelope (and signed URLs).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Actually call the Runway API. Without this flag the script "
            "prints the request body it would send and exits 0."
        ),
    )
    parser.add_argument(
        "--no-watermark",
        action="store_true",
        help=(
            "Disable Runway watermark. ONLY use for non-contest dry-runs — "
            "Big Pitch entries MUST carry the visible watermark."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.prompt_file.is_file():
        print(f"error: prompt file not found: {args.prompt_file}", file=sys.stderr)
        return 2
    prompt_text = args.prompt_file.read_text(encoding="utf-8").strip()
    if not prompt_text:
        print(f"error: prompt file is empty: {args.prompt_file}", file=sys.stderr)
        return 2

    request = GenerateRequest(
        promptText=prompt_text,
        model=args.model,
        duration=args.duration,
        ratio=args.ratio,
        seed=args.seed,
        watermark=not args.no_watermark,
    )

    if not args.live:
        print("DRY-RUN — would POST this request body to /v1/image_to_video:")
        print(json.dumps(request.model_dump(exclude_none=True), indent=2))
        print()
        print("Use --live to actually call the Runway API. Verify operator's")
        print("Runway account has an active app subscription FIRST — API")
        print("credits alone do not qualify for Big Pitch contest entry.")
        return 0

    try:
        client = RunwayGen3Client()
    except RunwayClientError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    print(f"calling Runway Gen-3 with prompt ({len(prompt_text)} chars)...")
    try:
        result = client.generate_and_wait(request)
    except RunwayClientError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    finally:
        client.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"task {result.id} → {result.status.value}")
    if result.status == RunwayTaskStatus.SUCCEEDED:
        for url in result.output or []:
            print(f"  output: {url}")
    print(f"envelope written to {args.output}")
    return 0 if result.status == RunwayTaskStatus.SUCCEEDED else 5


if __name__ == "__main__":
    sys.exit(main())

"""Module entry-point: ``uv run python -m agents.monetization_review``."""

from __future__ import annotations

import sys

from agents.monetization_review.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

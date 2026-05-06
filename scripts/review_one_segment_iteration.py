#!/usr/bin/env python3
"""Review the one-segment canary before any pool release."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agents.hapax_daimonion.daily_segment_prep import DEFAULT_PREP_DIR, load_prepped_programmes
from shared.segment_iteration_review import review_one_segment_iteration, review_segment_batch


def _load_team_receipts(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        receipts = data.get("team_critique_receipts") or data.get("receipts") or []
        if isinstance(receipts, list):
            return [item for item in receipts if isinstance(item, dict)]
    raise SystemExit(f"team receipt file must contain a list or receipts object: {path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review exactly one manifest-accepted prepared segment artifact."
    )
    parser.add_argument("--prep-dir", type=Path, default=DEFAULT_PREP_DIR)
    parser.add_argument("--team-receipts", type=Path, default=None)
    parser.add_argument("--receipt-out", type=Path, default=None)
    parser.add_argument(
        "--mode",
        choices=("canary", "batch"),
        default="canary",
        help="canary requires exactly one artifact and team receipts; batch reviews every accepted artifact",
    )
    args = parser.parse_args(argv)

    artifacts = load_prepped_programmes(args.prep_dir)
    if args.mode == "batch":
        receipt = review_segment_batch(artifacts)
        success = bool(receipt["ready_for_pool"])
    else:
        receipt = review_one_segment_iteration(
            artifacts,
            team_critique_receipts=_load_team_receipts(args.team_receipts),
        )
        success = bool(receipt["ready_for_pool_release"])
    rendered = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False)
    if args.receipt_out is not None:
        args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

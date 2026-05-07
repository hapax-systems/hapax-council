#!/usr/bin/env python3
"""Review the one-segment canary before any next-nine generation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agents.hapax_daimonion.daily_segment_prep import DEFAULT_PREP_DIR, load_prepped_programmes
from shared.segment_iteration_review import review_one_segment_iteration


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
    args = parser.parse_args(argv)

    artifacts = load_prepped_programmes(
        args.prep_dir,
        require_selected=False,
        strict_release_contract=True,
    )
    receipt = review_one_segment_iteration(
        artifacts,
        team_critique_receipts=_load_team_receipts(args.team_receipts),
    )
    rendered = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False)
    if args.receipt_out is not None:
        args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if receipt["ready_for_next_nine"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

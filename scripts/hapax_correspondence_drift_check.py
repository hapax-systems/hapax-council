#!/usr/bin/env python3
"""Correspondence drift check — alert when narration diverges from structural state.

Reads the rolling correspondence log and fires ntfy when score drops
below threshold. Designed to run as a systemd timer (5-minute cadence).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

FEEDBACK_LOG = Path("/dev/shm/hapax-daimonion/acceptance-feedback.jsonl")
RECEIPT_PATH = Path("/dev/shm/hapax-daimonion/utterance-receipt.json")
THRESHOLD = 0.5
WINDOW_SIZE = 10


def check_drift() -> dict:
    """Check rolling correspondence for drift."""
    if not FEEDBACK_LOG.exists():
        return {"status": "no_data", "score": 0.0, "window": 0}

    lines = FEEDBACK_LOG.read_text(encoding="utf-8").strip().split("\n")
    recent = [json.loads(line) for line in lines[-WINDOW_SIZE:] if line.strip()]

    if not recent:
        return {"status": "no_data", "score": 0.0, "window": 0}

    accept_count = sum(1 for e in recent if e.get("acceptance_type") == "ACCEPT")
    reject_count = sum(1 for e in recent if e.get("acceptance_type") == "REJECT")
    total = len(recent)

    score = accept_count / max(total, 1)

    if score < THRESHOLD:
        return {
            "status": "drifting",
            "score": round(score, 3),
            "window": total,
            "accept_count": accept_count,
            "reject_count": reject_count,
        }

    return {
        "status": "aligned",
        "score": round(score, 3),
        "window": total,
        "accept_count": accept_count,
        "reject_count": reject_count,
    }


def main() -> None:
    result = check_drift()

    if result["status"] == "drifting":
        try:
            from shared.notify import notify

            notify(
                title="Correspondence Drift",
                message=f"Score {result['score']:.2f} below {THRESHOLD} "
                f"({result['reject_count']} rejects in last {result['window']} turns)",
                priority="high",
            )
        except ImportError:
            print(f"DRIFT: {result}", file=sys.stderr)

    print(json.dumps(result))


if __name__ == "__main__":
    main()

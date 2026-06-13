"""Canary: lane-idle-watchdog quota-wall backoff must be robust to unusable reset times.

Regression guard for the thrash where a quota-wall receipt carries a resets_at
that is missing / ``unknown`` or computed in the PAST (observed: detected_at
03:38Z with resets_at 03:00Z — the prior 5h boundary, not the next). The
original future-only check returned "not walled" and the lane was re-nudged
every tick → re-walled → thrash.

``quota_walled_until()`` now falls back to ``detected_at`` + a backoff floor: a
FRESH wall (any unusable reset) is not immediately re-nudged, while a STALE
receipt still allows legitimate revival.
"""

from __future__ import annotations

import datetime
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog"


def _extract_function() -> str:
    """Pull the const + quota_walled_until() out of the script so it can be sourced alone."""
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("QUOTA_WALL_BACKOFF_FLOOR_S="))
    fn = next(i for i, l in enumerate(lines) if l.startswith("quota_walled_until()"))
    end = next(i for i in range(fn, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(int(epoch), datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_walled(home: Path, role: str, detected_epoch: float | None, resets: str | None) -> bool:
    receipts = home / ".cache/hapax/relay/receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    if detected_epoch is not None:
        (receipts / (role + "-quota-wall.yaml")).write_text(
            f"role: {role}\ndetected_at: {_iso(detected_epoch)}\nresets_at: {resets}\n",
            encoding="utf-8",
        )
    body = _extract_function() + '\nnow=$(date +%s)\nquota_walled_until "$1"\n'
    result = subprocess.run(
        ["bash", "-c", body, "bash", role],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
    )
    return result.returncode == 0


def test_fresh_past_reset_backs_off(tmp_path: Path) -> None:
    now = time.time()
    # The exact observed thrash: fresh detection, reset computed in the past.
    assert _is_walled(tmp_path, "r1", now - 60, _iso(now - 1800)) is True


def test_fresh_unknown_reset_backs_off(tmp_path: Path) -> None:
    now = time.time()
    assert _is_walled(tmp_path, "r2", now - 60, "unknown") is True


def test_fresh_future_reset_backs_off(tmp_path: Path) -> None:
    now = time.time()
    # Original behavior preserved.
    assert _is_walled(tmp_path, "r3", now - 60, _iso(now + 3600)) is True


def test_stale_past_reset_allows_revival(tmp_path: Path) -> None:
    now = time.time()
    # Old detection + no future reset → wall presumed expired → revive.
    assert _is_walled(tmp_path, "r4", now - 7200, _iso(now - 1800)) is False


def test_no_receipt_allows_dispatch(tmp_path: Path) -> None:
    assert _is_walled(tmp_path, "missing", None, None) is False

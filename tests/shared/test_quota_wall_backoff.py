"""Tests for quota-wall-aware backoff — the fix for the rate-limit restart thrash.

Covers ``shared.quota_wall.compute_backoff_seconds`` (resets_at honoring,
exponential streak growth, base floor + cap clamps, jitter) and the
``scripts/detect-quota-wall --streak`` CLI (prints the int backoff + exits 75 on a
wall; exits 0 silently when clean). Self-contained (no shared conftest).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest

from shared import quota_wall

REPO_ROOT = Path(__file__).resolve().parents[2]


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def _write_receipt(receipt_dir: Path, role: str, resets_at: str) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / f"{role}-quota-wall.yaml").write_text(
        f"role: {role}\nstatus: quota_blocked\nresets_at: {resets_at}\n", encoding="utf-8"
    )


# ── compute_backoff_seconds: resets_at branch ────────────────────────────────


def test_resets_at_future_waits_until_reset_plus_cushion(tmp_path: Path) -> None:
    now = 1_000_000.0
    receipts = tmp_path / "receipts"
    _write_receipt(receipts, "beta", _iso(now + 100))
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        assert quota_wall.compute_backoff_seconds("beta", 1, 30, 21600, now_epoch=now) == 130


def test_resets_at_far_future_clamped_to_cap(tmp_path: Path) -> None:
    now = 1_000_000.0
    receipts = tmp_path / "receipts"
    _write_receipt(receipts, "beta", _iso(now + 30_000))
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        assert quota_wall.compute_backoff_seconds("beta", 1, 30, 21600, now_epoch=now) == 21600


def test_resets_at_near_future_floored_to_base(tmp_path: Path) -> None:
    now = 1_000_000.0
    receipts = tmp_path / "receipts"
    _write_receipt(receipts, "beta", _iso(now + 1))  # 1 + 30 = 31 < base 60
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        assert quota_wall.compute_backoff_seconds("beta", 1, 60, 21600, now_epoch=now) == 60


def test_resets_at_past_falls_through_to_exponential(tmp_path: Path) -> None:
    now = 1_000_000.0
    receipts = tmp_path / "receipts"
    _write_receipt(receipts, "beta", _iso(now - 100))  # already passed
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        assert quota_wall.compute_backoff_seconds("beta", 3, 30, 21600, now_epoch=now) == 120


def test_resets_at_unknown_falls_through_to_exponential(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    _write_receipt(receipts, "beta", "unknown")
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        assert quota_wall.compute_backoff_seconds("beta", 2, 30, 21600, now_epoch=1.0) == 60


def test_no_receipt_uses_exponential(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"  # never created → no receipt
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        assert quota_wall.compute_backoff_seconds("gamma", 1, 30, 21600, now_epoch=1.0) == 30


# ── compute_backoff_seconds: exponential branch ──────────────────────────────


@pytest.mark.parametrize(
    "streak,expected",
    [(0, 30), (1, 30), (2, 60), (3, 120), (4, 240), (7, 1920), (8, 1920), (20, 1920)],
)
def test_exponential_growth_with_capped_exponent(
    tmp_path: Path, streak: int, expected: int
) -> None:
    receipts = tmp_path / "receipts"
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        assert quota_wall.compute_backoff_seconds("x", streak, 30, 21600, now_epoch=1.0) == expected


def test_cap_honored_on_large_streak(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        # streak 6 → 30 * 2**5 = 960, clamped to cap 500
        assert quota_wall.compute_backoff_seconds("x", 6, 30, 500, now_epoch=1.0) == 500


def test_jitter_added_to_exponential(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    with mock.patch.object(quota_wall, "RELAY_RECEIPT_DIR", receipts):
        assert quota_wall.compute_backoff_seconds("x", 1, 30, 21600, now_epoch=1.0, jitter=5) == 35


# ── detect-quota-wall --streak CLI ───────────────────────────────────────────


def _run_detect(tmp_path: Path, line: str, *args: str) -> subprocess.CompletedProcess[str]:
    output = tmp_path / "output.jsonl"
    output.write_text(line + "\n", encoding="utf-8")
    env = {**os.environ, "HAPAX_RELAY_RECEIPT_DIR": str(tmp_path / "receipts")}
    return subprocess.run(
        [sys.executable, "scripts/detect-quota-wall", "beta", "--output", str(output), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )


def test_detect_quota_wall_on_429_prints_int_and_exits_75(tmp_path: Path) -> None:
    line = '{"type":"system","subtype":"api_retry","error_status":429,"error":"rate_limit"}'
    proc = _run_detect(tmp_path, line, "--streak", "3", "--base", "30", "--cap", "21600")
    assert proc.returncode == 75, proc.stderr
    assert int(proc.stdout.strip()) >= 30  # an integer backoff was printed


def test_detect_quota_wall_clean_exits_0_silently(tmp_path: Path) -> None:
    proc = _run_detect(tmp_path, '{"type":"assistant","message":{}}')
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""

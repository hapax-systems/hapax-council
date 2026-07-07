"""Tests for ``scripts/hapax-agy-quota-admission``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-agy-quota-admission"


def test_agy_quota_admission_writes_short_lived_safe_receipt(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--receipt-dir",
            str(receipt_dir),
            "--now",
            "2026-07-07T13:00:00Z",
            "--evidence-ref",
            "agy-gemini31pro-smoke-20260707t1300z",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["route_id"] == "agy.review.direct"
    assert summary["supported_tool"] == "hapax-agy-reviewer"
    assert summary["model"] == "gemini-3.1-pro-preview"
    path = Path(summary["path"])
    receipt = path.read_text(encoding="utf-8")
    assert "schema: hapax.agy_quota_admission.v1" in receipt
    assert "status: quota_available" in receipt
    assert "secret_source: agy:operator-session" in receipt
    assert "secret_value_persisted: false" in receipt
    assert "prompt_or_output_persisted: false" in receipt
    assert "billing_mode: operator_session_subscription" in receipt
    assert "positive_admission: true" in receipt
    assert path.stat().st_mode & 0o777 == 0o600


def test_agy_quota_admission_rejects_secretish_evidence_ref(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "api-key-secret-token",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )

    assert result.returncode == 2
    assert "unsafe evidence-ref" in result.stderr
    assert not list(tmp_path.glob("*.yaml"))

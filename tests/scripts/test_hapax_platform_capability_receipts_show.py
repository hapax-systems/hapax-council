"""`hapax-platform-capability-receipts --show` — the read-only mode the seat refresher consults.

Review finding on #4624, round 9: the mode had no direct tests for an empty platform selection,
a missing receipt, plain-text output, or a directory the loader cannot read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-platform-capability-receipts"


def _show(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--show", *args],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_empty_platform_selection_is_refused_with_the_remedy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax" / "platform-capability-receipts").mkdir(parents=True)
    proc = _show(home, "--json")
    assert "Traceback" not in proc.stderr
    assert "--show needs at least one --platform" in proc.stdout + proc.stderr


def test_a_missing_receipt_for_the_named_platform_is_reported_not_invented(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax" / "platform-capability-receipts").mkdir(parents=True)
    proc = _show(home, "--platform", "glmcp", "--json")
    assert "Traceback" not in proc.stderr
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    (row,) = payload["receipts"]
    assert row["platform"] == "glmcp"
    assert row["accepted"] is False
    assert row["reason"] == "receipt_invalid:PlatformCapabilityReceiptError"
    assert payload["directory_error"] is None


@pytest.mark.parametrize("present", [False, True], ids=["missing", "accepted"])
def test_plain_text_mode_prints_a_quota_line_per_receipt(tmp_path: Path, present: bool) -> None:
    from shared.platform_capability_receipts import PlatformCapabilityReceipt

    home = tmp_path / "home"
    receipt_dir = home / ".cache/hapax/platform-capability-receipts"
    receipt_dir.mkdir(parents=True)
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if present:
        surface = {
            "status": "observed",
            "source": "test",
            "observed_at": now,
            "stale_after": "15m",
            "evidence_refs": ["platform-capability-registry:glmcp.review.direct:quota:observed"],
        }
        receipt = PlatformCapabilityReceipt.model_validate(
            {
                "receipt_id": "test-glmcp-show",
                "platform": "glmcp",
                "routes": ["glmcp.review.direct"],
                "observed_at": now,
                "stale_after": "15m",
                "cli": {"binary": "test", "available": True},
                "wrapper": {
                    "path": "scripts/hapax-glmcp-reviewer",
                    "exists": True,
                    "executable": True,
                },
                "capability": surface,
                "resource": surface,
                "quota": surface,
                "provider_docs": {
                    "refs": ["test:provider-docs"],
                    "fetched_at": now,
                    "stale_after": "30d",
                },
            }
        )
        (receipt_dir / "glmcp.json").write_text(receipt.model_dump_json())
    proc = _show(home, "--platform", "glmcp")
    assert "Traceback" not in proc.stderr
    assert proc.returncode == (0 if present else 1)
    if present:
        assert proc.stdout == (
            f"glmcp: accepted=True quota=observed observed_at={now} stale_after=15m\n"
        )
    else:
        assert proc.stdout == (
            "glmcp: accepted=False quota=? observed_at=? stale_after=? "
            "reason=receipt_invalid:PlatformCapabilityReceiptError\n"
        )


def test_an_unloadable_receipt_directory_is_not_accepted(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax").mkdir(parents=True)
    (home / ".cache" / "hapax" / "platform-capability-receipts").write_text("not a directory")
    proc = _show(home, "--platform", "glmcp", "--json")
    assert "Traceback" not in proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    rows = [row for row in payload["receipts"] if row.get("platform") == "glmcp"]
    assert rows and rows[0]["accepted"] is False and rows[0].get("reason"), payload

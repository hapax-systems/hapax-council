"""Read-only inspection uses the current receipt contract without running probes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-platform-capability-receipts"


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


@pytest.mark.parametrize("neighbor", [False, True], ids=["current-contract", "malformed-neighbor"])
def test_show_uses_current_contract_without_probes_or_writes(
    tmp_path, monkeypatch, capsys, neighbor
):
    import runpy

    from tests.scripts.test_hapax_glmcp_seat_refresh import _glmcp_receipt_json

    now = datetime.now(UTC).replace(microsecond=0)
    receipt_path = tmp_path / "glmcp.json"
    receipt_path.write_text(_glmcp_receipt_json(status="observed", remaining=900, age=0, now=now))
    assert "load_sets" in receipt_path.read_text()
    if neighbor:
        (tmp_path / "other.json").write_text('{"private_payload": "synthetic-secret-value"}')
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    main = runpy.run_path(str(SCRIPT))["main"]

    def forbidden(*args, **kwargs):
        pytest.fail("--show attempted a probe, writer, or registry refresh")

    for name in ("observe_cli", "write_receipt", "load_platform_capability_registry_for_dispatch"):
        monkeypatch.setitem(main.__globals__, name, forbidden)
    assert main(["--show", "--platform", "glmcp", "--receipt-dir", str(tmp_path), "--json"]) == int(
        neighbor
    )
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["receipts"][0]["accepted"] is (not neighbor)
    if neighbor:
        assert payload["directory_error"] == "receipt_dir_unloadable:PlatformCapabilityReceiptError"
    assert "synthetic-secret-value" not in output.out + output.err
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}

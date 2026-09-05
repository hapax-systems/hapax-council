"""`hapax-platform-capability-receipts --show` — the read-only mode the seat refresher consults.

Review finding on #4624, round 9: the mode had no direct tests for an empty platform selection,
a missing receipt, plain-text output, or a directory the loader cannot read.
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, current_thread

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-platform-capability-receipts"


@pytest.fixture
def publication_receipts():
    from shared.platform_capability_receipts import PlatformCapabilityReceipt

    now = datetime.now(UTC).replace(microsecond=0)
    surface = {
        "status": "observed",
        "source": "test",
        "observed_at": now,
        "stale_after": "15m",
        "evidence_refs": ["test:publication"],
    }
    receipt_a = PlatformCapabilityReceipt.model_validate(
        {
            "receipt_id": "writer-a",
            "platform": "glmcp",
            "routes": ["glmcp.review.direct"],
            "observed_at": now,
            "stale_after": "15m",
            "cli": {"binary": "test", "available": True},
            "wrapper": {"path": "test", "exists": True, "executable": True},
            "capability": surface,
            "resource": surface,
            "quota": surface,
            "provider_docs": {"refs": ["test:docs"], "fetched_at": now, "stale_after": "30d"},
        }
    )
    receipt_b = receipt_a.model_copy(
        update={"receipt_id": "writer-b", "known_unknowns": ["longer receipt" * 100]}
    )
    return receipt_a, receipt_b, now


def test_concurrent_receipt_publications_never_leave_a_json_tail(
    tmp_path: Path, monkeypatch, publication_receipts
):
    """Pause A after opening its output; let B publish a longer receipt before A writes."""
    from shared.platform_capability_receipts import load_platform_capability_receipts

    receipt_a, receipt_b, now = publication_receipts
    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    path = write_receipt(receipt_a, tmp_path)
    opened, finish = Event(), Event()
    real_path_open, real_fdopen = Path.open, os.fdopen

    def pause_writer_a(stream):
        if current_thread().name.startswith("receipt-a"):
            opened.set()
            if not finish.wait(30):
                stream.close()
                raise AssertionError("writer B did not finish while A was paused")
        return stream

    def path_open(self, mode="r", *args, **kwargs):
        stream = real_path_open(self, mode, *args, **kwargs)
        return pause_writer_a(stream) if "w" in mode or "x" in mode else stream

    def fdopen(fd, mode="r", *args, **kwargs):
        return pause_writer_a(real_fdopen(fd, mode, *args, **kwargs))

    monkeypatch.setattr(Path, "open", path_open)
    monkeypatch.setattr(os, "fdopen", fdopen)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="receipt-a") as pool:
        pending = pool.submit(write_receipt, receipt_a, tmp_path)
        try:
            assert opened.wait(30), "writer A never opened its output"
            # Both calls use the production writer; the plural loader sees B while A is open.
            assert write_receipt(receipt_b, tmp_path) == path
            assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_b
        finally:
            finish.set()
        assert pending.result(timeout=30) == path
    # A's shorter write must replace B's inode, never overwrite its prefix and leave a tail.
    assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_a
    assert sorted(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("failure", [None, "fsync", "replace"])
def test_receipt_publication_syncs_complete_private_temp_before_replace(
    tmp_path: Path, monkeypatch, publication_receipts, failure
):
    from shared.platform_capability_receipts import load_platform_capability_receipts

    receipt_a, receipt_b, now = publication_receipts
    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    path = write_receipt(receipt_a, tmp_path)
    original = path.read_bytes()
    real_fsync, real_replace = os.fsync, os.replace
    calls = []

    def fsync(fd):
        temporary = next(p for p in tmp_path.iterdir() if p != path)
        assert temporary.stat().st_ino == os.fstat(fd).st_ino
        assert temporary.stat().st_mode & 0o777 == 0o600
        assert temporary.suffix == ".tmp"  # the plural *.json loader cannot see this file
        assert json.loads(temporary.read_text()) == receipt_b.model_dump(mode="json")
        assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_a
        calls.append("fsync")
        if failure == "fsync":
            raise OSError("injected fsync failure")
        return real_fsync(fd)

    def replace(source, destination):
        assert calls == ["fsync"], "complete receipt must be flushed and fsynced before replace"
        assert Path(source).parent == path.parent
        assert destination == path
        calls.append("replace")
        if failure == "replace":
            raise OSError("injected replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    if failure:
        with pytest.raises(OSError, match=f"injected {failure} failure"):
            write_receipt(receipt_b, tmp_path)
        assert path.read_bytes() == original
    else:
        assert write_receipt(receipt_b, tmp_path) == path
        assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_b
    assert calls == (["fsync"] if failure == "fsync" else ["fsync", "replace"])
    assert sorted(tmp_path.iterdir()) == [path]


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

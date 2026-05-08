"""Tests for request-intake-consumer script.

ISAP: SLICE-003B-REQUEST-INTAKE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "request-intake-consumer"


def _write_request(path: Path, req_id: str, status: str = "captured", title: str = "Test") -> None:
    path.write_text(
        f"---\ntype: hapax-request\nrequest_id: {req_id}\n"
        f"title: {title}\nstatus: {status}\n"
        f"updated_at: 2026-05-08T15:00:00Z\n---\n",
        encoding="utf-8",
    )


def _run(
    tmp_path: Path, *args: str, receipts_dir: Path | None = None
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HAPAX_REQUESTS_DIR": str(tmp_path / "requests"),
        "HAPAX_REQUEST_RECEIPTS": str(receipts_dir or tmp_path / "receipts"),
        "CLAUDE_ROLE": "epsilon-test",
        "HAPAX_REQUEST_STALE_SECONDS": "1",
    }
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def test_no_requests_dir_exits_cleanly(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0


def test_empty_active_dir(tmp_path: Path) -> None:
    (tmp_path / "requests" / "active").mkdir(parents=True)
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "all requests have fresh read receipts" in result.stdout


def test_unread_request_detected(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    _write_request(active / "REQ-001.md", "REQ-001", title="Fix the widget")

    result = _run(tmp_path)
    assert "1 unread" in result.stdout
    assert "REQ-001" in result.stdout
    assert "Fix the widget" in result.stdout


def test_write_receipt_creates_yaml(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    receipts = tmp_path / "receipts"
    _write_request(active / "REQ-002.md", "REQ-002")

    result = _run(tmp_path, "--write-receipt", receipts_dir=receipts)
    assert result.returncode == 0

    receipt = receipts / "REQ-002.yaml"
    assert receipt.exists()
    content = receipt.read_text()
    assert "request_id: REQ-002" in content
    assert "reader_role: epsilon-test" in content
    assert "observed_status: captured" in content


def test_receipt_makes_request_read(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    receipts = tmp_path / "receipts"
    _write_request(active / "REQ-003.md", "REQ-003")

    _run(tmp_path, "--write-receipt", receipts_dir=receipts)
    result = _run(tmp_path, receipts_dir=receipts)
    assert "all requests have fresh read receipts" in result.stdout or "0 unread" in result.stdout


def test_preamble_mode_silent_when_empty(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    result = _run(tmp_path, "--session-preamble")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_preamble_mode_shows_unread(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    _write_request(active / "REQ-004.md", "REQ-004", title="Urgent thing")

    result = _run(tmp_path, "--session-preamble")
    assert "REQUEST INTAKE" in result.stdout
    assert "REQ-004" in result.stdout


def test_non_request_files_ignored(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    (active / "not-a-request.md").write_text("---\ntype: cc-task\ntask_id: T1\n---\n")

    result = _run(tmp_path)
    assert "all requests have fresh read receipts" in result.stdout

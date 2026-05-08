"""Tests for the addressed relay inbox bridge."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "hapax-relay-inbox"


def _run_inbox(relay_dir: Path, role: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--role", role, "--relay-dir", str(relay_dir), *extra],
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_frontmatter_to_role_prints_marks_seen_and_receipts(tmp_path: Path) -> None:
    relay = tmp_path / "relay"
    relay.mkdir()
    note = relay / "cross-coordinator-visibility-escalation.md"
    note.write_text(
        "\n".join(
            [
                "---",
                "from: codex-parent",
                "to: alpha",
                "created_utc: 2026-05-08T17:49:00Z",
                "---",
                "# Cross-Coordinator Visibility Escalation",
                "",
                "Body.",
            ]
        ),
        encoding="utf-8",
    )

    first = _run_inbox(relay, "alpha", "--mark-seen")

    assert first.returncode == 0, first.stderr
    assert "ADDRESSED RELAY INBOX (alpha):" in first.stdout
    assert "Cross-Coordinator Visibility Escalation" in first.stdout
    assert "from: codex-parent" in first.stdout
    assert (relay / ".seen" / "alpha-addressed-relay.seen").exists()

    receipts = (relay / "receipts" / "addressed-relay-read.jsonl").read_text().splitlines()
    assert len(receipts) == 1
    receipt = json.loads(receipts[0])
    assert receipt["receipt_type"] == "relay_addressed_read"
    assert receipt["recipient"] == "alpha"
    assert receipt["path"] == str(note)

    second = _run_inbox(relay, "alpha", "--mark-seen")

    assert second.returncode == 0, second.stderr
    assert second.stdout == ""


def test_filename_to_role_without_frontmatter_is_addressed(tmp_path: Path) -> None:
    relay = tmp_path / "relay"
    relay.mkdir()
    (relay / "codex-to-beta-slice7-unblock.md").write_text("# Slice 7 Unblock\n", encoding="utf-8")

    result = _run_inbox(relay, "beta")

    assert result.returncode == 0, result.stderr
    assert "Slice 7 Unblock" in result.stdout


def test_broadcast_target_prints_for_any_role(tmp_path: Path) -> None:
    relay = tmp_path / "relay"
    relay.mkdir()
    (relay / "team-update.md").write_text(
        "---\nto: coordinators\nfrom: rte\n---\n# Team Update\n",
        encoding="utf-8",
    )

    result = _run_inbox(relay, "cx-red")

    assert result.returncode == 0, result.stderr
    assert "ADDRESSED RELAY INBOX (cx-red):" in result.stdout
    assert "Team Update" in result.stdout


def test_edited_note_reappears_after_mark_seen(tmp_path: Path) -> None:
    relay = tmp_path / "relay"
    relay.mkdir()
    note = relay / "note-to-alpha.md"
    note.write_text("# First Version\n", encoding="utf-8")

    first = _run_inbox(relay, "alpha", "--mark-seen")
    assert first.returncode == 0, first.stderr
    assert "First Version" in first.stdout

    note.write_text("# Second Version\n\nAdditional material changes the key.\n", encoding="utf-8")
    second = _run_inbox(relay, "alpha", "--mark-seen")

    assert second.returncode == 0, second.stderr
    assert "Second Version" in second.stdout


def test_unaddressed_note_is_ignored(tmp_path: Path) -> None:
    relay = tmp_path / "relay"
    relay.mkdir()
    (relay / "plain-status.md").write_text("# Plain Status\n", encoding="utf-8")

    result = _run_inbox(relay, "alpha")

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""

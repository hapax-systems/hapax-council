"""Tests for scripts/archive-reenable.py (LRR Phase 2 item 1).

Pins the archival unit list against systemd/README.md § Disabled
Services and covers the dry-run-by-default safety guarantee.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "archive-reenable.py"

_spec = importlib.util.spec_from_file_location("archive_reenable", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
archive_reenable = importlib.util.module_from_spec(_spec)
sys.modules["archive_reenable"] = archive_reenable
_spec.loader.exec_module(archive_reenable)


README_DISABLED_UNITS: tuple[str, ...] = (
    "audio-recorder.service",
    "contact-mic-recorder.service",
    "rag-ingest.service",
    "audio-processor.timer",
    "video-processor.timer",
    "av-correlator.timer",
    "flow-journal.timer",
    "video-retention.timer",
)


class TestArchivalUnitListPin:
    def test_unit_list_matches_readme_disabled_services(self) -> None:
        assert set(archive_reenable.ARCHIVAL_UNITS) == set(README_DISABLED_UNITS), (
            "scripts/archive-reenable.py ARCHIVAL_UNITS drifted from "
            "systemd/README.md § Disabled Services. Update both in lockstep."
        )

    def test_unit_list_is_sorted_or_intentional(self) -> None:
        assert len(archive_reenable.ARCHIVAL_UNITS) == 8

    def test_readme_still_lists_all_units(self) -> None:
        readme_path = REPO_ROOT / "systemd" / "README.md"
        body = readme_path.read_text(encoding="utf-8")
        disabled_section = body.split("## Disabled Services", 1)[-1]
        for unit in archive_reenable.ARCHIVAL_UNITS:
            assert f"`{unit}`" in disabled_section, (
                f"Unit {unit!r} is in ARCHIVAL_UNITS but not in README § Disabled Services"
            )


class TestDryRunDefault:
    def test_enable_without_live_flag_is_dry_run(self, capsys: object) -> None:  # type: ignore[valid-type]
        with patch.object(archive_reenable.subprocess, "run") as mock_run:
            rc = archive_reenable.main(["enable"])
        assert rc == 0
        mock_run.assert_not_called()
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "dry-run" in captured.out
        assert "systemctl --user enable --now audio-recorder.service" in captured.out
        assert "--live" in captured.out

    def test_disable_without_live_flag_is_dry_run(self, capsys: object) -> None:  # type: ignore[valid-type]
        with patch.object(archive_reenable.subprocess, "run") as mock_run:
            rc = archive_reenable.main(["disable"])
        assert rc == 0
        mock_run.assert_not_called()
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "dry-run" in captured.out
        assert "systemctl --user disable --now contact-mic-recorder.service" in captured.out


class TestLiveMode:
    def test_enable_live_invokes_systemctl_per_unit(self) -> None:
        from subprocess import CompletedProcess

        calls = []

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(cmd)
            return CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.object(archive_reenable.subprocess, "run", side_effect=fake_run):
            rc = archive_reenable.main(["enable", "--live"])
        assert rc == 0
        enable_calls = [c for c in calls if len(c) >= 4 and c[2] == "enable"]
        assert len(enable_calls) == len(archive_reenable.ARCHIVAL_UNITS)
        for call in enable_calls:
            assert call[0] == "systemctl"
            assert call[1] == "--user"
            assert call[2] == "enable"
            assert call[3] == "--now"
            assert call[4] in archive_reenable.ARCHIVAL_UNITS

    def test_enable_live_reports_errors(self) -> None:
        from subprocess import CompletedProcess

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            if "rag-ingest.service" in cmd:
                return CompletedProcess(cmd, 1, stdout="", stderr="Unit masked")
            return CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch.object(archive_reenable.subprocess, "run", side_effect=fake_run):
            rc = archive_reenable.main(["enable", "--live"])
        assert rc == 1


class TestStatusCommand:
    def test_status_queries_each_unit_twice(self) -> None:
        from subprocess import CompletedProcess

        calls = []

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(cmd)
            if "is-enabled" in cmd:
                return CompletedProcess(cmd, 0, stdout="disabled\n", stderr="")
            return CompletedProcess(cmd, 0, stdout="inactive\n", stderr="")

        with patch.object(archive_reenable.subprocess, "run", side_effect=fake_run):
            rc = archive_reenable.main(["status"])
        assert rc == 0
        assert len(calls) == 2 * len(archive_reenable.ARCHIVAL_UNITS)


class TestRetentionPolicyInvariants:
    """Pin the retention policy doc — invariants must not silently drift."""

    def test_retention_policy_doc_exists(self) -> None:
        doc = (
            REPO_ROOT
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-04-14-lrr-phase-2-archive-retention.md"
        )
        assert doc.is_file()

    def test_retention_policy_declares_no_automatic_deletion(self) -> None:
        doc = (
            REPO_ROOT
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-04-14-lrr-phase-2-archive-retention.md"
        )
        body = doc.read_text(encoding="utf-8")
        assert "No automatic deletion" in body
        assert re.search(r"R[15].*No silent background purge|R5.*No silent", body, re.DOTALL) or (
            "R5" in body and "No silent background purge" in body
        )

    def test_retention_policy_documents_purge_audit_log(self) -> None:
        doc = (
            REPO_ROOT
            / "docs"
            / "superpowers"
            / "specs"
            / "2026-04-14-lrr-phase-2-archive-retention.md"
        )
        body = doc.read_text(encoding="utf-8")
        assert "purge.log" in body
        assert "audit" in body.lower()

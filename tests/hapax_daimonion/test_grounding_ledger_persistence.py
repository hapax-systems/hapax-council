"""Tests for GQI session persistence (save/load to disk)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.hapax_daimonion.grounding_ledger import GroundingLedger


@pytest.fixture()
def ledger() -> GroundingLedger:
    gl = GroundingLedger()
    gl.add_du(1, "first point")
    gl.update_from_acceptance("ACCEPT")
    gl.add_du(2, "second point")
    gl.update_from_acceptance("CLARIFY")
    return gl


@pytest.fixture()
def sessions_dir(tmp_path: Path) -> Path:
    return tmp_path / "grounding-sessions"


class TestSaveSession:
    def test_creates_directory_and_file(self, ledger: GroundingLedger, sessions_dir: Path) -> None:
        assert not sessions_dir.exists()
        path = ledger.save_session("sess-001", directory=sessions_dir)
        assert path == sessions_dir / "sess-001.json"
        assert path.is_file()

    def test_snapshot_contains_required_keys(
        self, ledger: GroundingLedger, sessions_dir: Path
    ) -> None:
        path = ledger.save_session("sess-002", directory=sessions_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in (
            "session_id",
            "timestamp",
            "final_gqi",
            "total_dus",
            "grounded_count",
            "ungrounded_count",
            "repair_count",
            "effort_level",
            "acceptance_trajectory",
            "units",
        ):
            assert key in data, f"missing key: {key}"

    def test_session_id_in_snapshot(self, ledger: GroundingLedger, sessions_dir: Path) -> None:
        ledger.save_session("my-session", directory=sessions_dir)
        data = json.loads((sessions_dir / "my-session.json").read_text(encoding="utf-8"))
        assert data["session_id"] == "my-session"

    def test_units_serialised(self, ledger: GroundingLedger, sessions_dir: Path) -> None:
        ledger.save_session("sess-units", directory=sessions_dir)
        data = json.loads((sessions_dir / "sess-units.json").read_text(encoding="utf-8"))
        assert len(data["units"]) == 2
        assert data["units"][0]["state"] == "GROUNDED"
        assert data["units"][1]["state"] == "REPAIR-1"

    def test_overwrites_existing(self, ledger: GroundingLedger, sessions_dir: Path) -> None:
        ledger.save_session("dup", directory=sessions_dir)
        ledger.add_du(3, "third point")
        ledger.update_from_acceptance("ACCEPT")
        ledger.save_session("dup", directory=sessions_dir)
        data = json.loads((sessions_dir / "dup.json").read_text(encoding="utf-8"))
        assert data["total_dus"] == 3

    def test_uses_default_directory_when_none(self, ledger: GroundingLedger) -> None:
        expected = Path.home() / "hapax-state" / "research" / "grounding-sessions"
        with patch.object(Path, "mkdir"), patch.object(Path, "write_text") as mock_write:
            path = ledger.save_session("default-dir-test")
        assert path == expected / "default-dir-test.json"
        mock_write.assert_called_once()


class TestLoadSession:
    def test_round_trip(self, ledger: GroundingLedger, sessions_dir: Path) -> None:
        ledger.save_session("rt", directory=sessions_dir)
        loaded = GroundingLedger.load_session("rt", directory=sessions_dir)
        assert loaded["session_id"] == "rt"
        assert loaded["total_dus"] == 2

    def test_missing_session_raises(self, sessions_dir: Path) -> None:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(FileNotFoundError):
            GroundingLedger.load_session("nonexistent", directory=sessions_dir)

    def test_uses_default_directory_when_none(self) -> None:
        with pytest.raises(FileNotFoundError):
            # Will fail because the file doesn't exist, but confirms
            # it looks in the default location.
            GroundingLedger.load_session("does-not-exist-default")


class TestEmptyLedgerPersistence:
    def test_empty_ledger_saves(self, sessions_dir: Path) -> None:
        gl = GroundingLedger()
        path = gl.save_session("empty", directory=sessions_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["total_dus"] == 0
        assert data["units"] == []
        assert data["grounded_count"] == 0

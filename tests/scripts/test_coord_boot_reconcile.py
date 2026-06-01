"""Tests for scripts/coord-boot-reconcile CLI."""

from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "coord-boot-reconcile"
_loader = SourceFileLoader("coord_boot_reconcile", str(_SCRIPT))
_spec = importlib.util.spec_from_loader("coord_boot_reconcile", _loader)
assert _spec is not None
mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(mod)


def test_boot_reconcile_cli_ingests_spool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    from shared.coord_event_log import CoordEvent, CoordWriter, default_event_log

    event = CoordEvent(
        event_id="evt-1",
        timestamp="2026-05-31T00:00:00Z",
        event_type="sdlc.stage_transition",
        actor="zeta",
        subject="task-x",
        payload={"to_stage": "S7"},
    )
    default_event_log().spool_fail_open(
        event, writer=CoordWriter.shim(lane="zeta"), reason="daemon_down"
    )

    assert mod.main([]) == 0
    assert "spool_ingested=1" in capsys.readouterr().out
    assert any(e.event_id == "evt-1" for e in default_event_log().replay().events)


def test_boot_reconcile_cli_json_on_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    assert mod.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["replayed"] == 0
    assert payload["spool_ingested"] == 0


def _isolate_coord(monkeypatch: pytest.MonkeyPatch, base: Path) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(base))
    monkeypatch.delenv("HAPAX_COORD_GRANT_DIR", raising=False)
    monkeypatch.delenv("HAPAX_COORD_GRANT_KEY", raising=False)


def test_provision_creates_tree_and_grant_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "coord"
    _isolate_coord(monkeypatch, base)

    assert mod.main(["--provision"]) == 0
    assert (base / "spool").is_dir()
    assert (base / "grants").is_dir()
    grant_key = base / "grant-key"
    assert grant_key.exists()
    assert oct(grant_key.stat().st_mode & 0o777) == "0o600"
    assert "provisioned" in capsys.readouterr().out


def test_provision_json_emits_both_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "coord"
    _isolate_coord(monkeypatch, base)

    assert mod.main(["--provision", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provision"]["key_created"] is True
    assert payload["provision"]["base_dir"] == str(base)
    assert payload["reconcile"]["replayed"] == 0


def test_provision_fails_loud_when_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A regular file where the base dir must go → provisioning cannot mkdir →
    # exit 2 LOUDLY on stderr (no silent degradation of an inert R2/R3).
    blocker = tmp_path / "blocked"
    blocker.write_text("not a dir", encoding="utf-8")
    _isolate_coord(monkeypatch, blocker / "coord")

    assert mod.main(["--provision"]) == 2
    assert "PROVISION FAILED" in capsys.readouterr().err

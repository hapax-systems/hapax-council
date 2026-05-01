from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "log-operator-quality-rating.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("log_operator_quality_rating", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dry_run_prints_event_without_writing(tmp_path: Path, capsys) -> None:
    mod = _load_script()
    path = tmp_path / "ratings.jsonl"

    rc = mod.main(
        [
            "4",
            "--dry-run",
            "--path",
            str(path),
            "--event-id",
            "oqr-dry-run",
            "--occurred-at",
            "2026-05-01T00:10:00Z",
            "--evidence-ref",
            "sample:dry-run",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["event_id"] == "oqr-dry-run"
    assert payload["rating"] == 4
    assert payload["source_surface"] == "cli"
    assert payload["evidence_refs"] == ["sample:dry-run"]
    assert not path.exists()


def test_cli_appends_rating(tmp_path: Path, capsys) -> None:
    mod = _load_script()
    path = tmp_path / "ratings.jsonl"

    rc = mod.main(
        [
            "5",
            "--path",
            str(path),
            "--event-id",
            "oqr-cli",
            "--occurred-at",
            "2026-05-01T00:11:00Z",
            "--axis",
            "overall",
            "--note",
            "worth replaying",
        ]
    )

    assert rc == 0
    assert "ok event_id=oqr-cli rating=5 axis=overall" in capsys.readouterr().out
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["event_id"] == "oqr-cli"
    assert payload["rating"] == 5
    assert payload["note"] == "worth replaying"

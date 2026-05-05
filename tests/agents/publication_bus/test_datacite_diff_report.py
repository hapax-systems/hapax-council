"""Tests for ``agents.publication_bus.datacite_diff_report``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agents.publication_bus.datacite_diff_report import (
    latest_snapshot_pair,
    main,
    write_diff_artifacts,
)


def _seed_snapshot(path: Path, nodes: list[dict]) -> None:
    payload = {"data": {"person": {"works": {"nodes": nodes}}}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_latest_snapshot_pair_returns_previous_and_current(tmp_path: Path):
    _seed_snapshot(tmp_path / "2026-05-01.json", [])
    _seed_snapshot(tmp_path / "2026-05-02.json", [])
    _seed_snapshot(tmp_path / "2026-05-03.json", [])

    pair = latest_snapshot_pair(tmp_path)

    assert pair is not None
    assert pair[0].name == "2026-05-02.json"
    assert pair[1].name == "2026-05-03.json"


def test_latest_snapshot_pair_requires_two_snapshots(tmp_path: Path):
    _seed_snapshot(tmp_path / "2026-05-01.json", [])

    assert latest_snapshot_pair(tmp_path) is None


def test_write_diff_artifacts_persists_json_and_markdown(tmp_path: Path):
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    output = tmp_path / "publication-state" / "diffs"
    _seed_snapshot(
        mirror / "2026-05-04.json",
        [
            {"doi": "10.x/1", "citations": {"totalCount": 1}},
            {"doi": "10.x/removed", "citations": {"totalCount": 0}},
        ],
    )
    _seed_snapshot(
        mirror / "2026-05-05.json",
        [
            {"doi": "10.x/1", "citations": {"totalCount": 3}},
            {"doi": "10.x/added", "citations": {"totalCount": 0}},
        ],
    )

    paths = write_diff_artifacts(
        mirror_dir=mirror,
        output_dir=output,
        generated_at=datetime(2026, 5, 5, 4, 30, tzinfo=UTC),
    )

    assert paths is not None
    json_path, markdown_path = paths
    assert json_path == output / "2026-05-05-diff.json"
    assert markdown_path == output / "2026-05-05-diff.md"
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["added_dois"] == ["10.x/added"]
    assert report["removed_dois"] == ["10.x/removed"]
    assert report["citation_count_delta"] == {"10.x/1": 2}
    assert report["summary"]["changed"] is True
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "DataCite citation graph diff" in markdown
    assert "`10.x/added`" in markdown
    assert "`10.x/1`: +2" in markdown


def test_main_reports_when_not_enough_snapshots(tmp_path: Path, capsys):
    rc = main(["--mirror-dir", str(tmp_path), "--output-dir", str(tmp_path / "out")])

    assert rc == 0
    captured = capsys.readouterr()
    assert "need at least two parseable snapshots" in captured.out

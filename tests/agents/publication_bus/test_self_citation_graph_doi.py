"""Tests for ``agents.publication_bus.self_citation_graph_doi``."""

from __future__ import annotations

import json
from pathlib import Path

from agents.publication_bus.self_citation_graph_doi import (
    _extract_topology_nodes,
    _latest_mirror_snapshot,
    assemble_deposit_metadata,
    graph_topology_fingerprint,
    main,
    material_change_detected,
    render_dry_run_report,
)


def _seed_snapshot(path: Path, nodes: list[tuple[str, int]]) -> None:
    payload = {
        "data": {
            "works": {
                "nodes": [{"doi": doi, "citationCount": cites} for doi, cites in nodes],
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_mirror_snapshot(path: Path, nodes: list[tuple[str, int]]) -> None:
    payload = {
        "data": {
            "person": {
                "works": {
                    "nodes": [
                        {"doi": doi, "citations": {"totalCount": cites}} for doi, cites in nodes
                    ],
                }
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_extract_topology_nodes_returns_doi_count_pairs():
    payload = {
        "data": {
            "works": {
                "nodes": [
                    {"doi": "10.5281/zenodo.1", "citationCount": 5},
                    {"doi": "10.5281/zenodo.2", "citationCount": 0},
                ]
            }
        }
    }
    assert _extract_topology_nodes(payload) == [
        ("10.5281/zenodo.1", 5),
        ("10.5281/zenodo.2", 0),
    ]


def test_extract_topology_nodes_supports_datacite_mirror_shape():
    payload = {
        "data": {
            "person": {
                "works": {
                    "nodes": [
                        {"doi": "10.5281/zenodo.1", "citations": {"totalCount": 5}},
                        {"doi": "10.5281/zenodo.2", "citations": {"totalCount": 0}},
                    ]
                }
            }
        }
    }
    assert _extract_topology_nodes(payload) == [
        ("10.5281/zenodo.1", 5),
        ("10.5281/zenodo.2", 0),
    ]


def test_extract_topology_nodes_handles_missing_path():
    assert _extract_topology_nodes({}) == []
    assert _extract_topology_nodes({"data": {"works": {}}}) == []


def test_fingerprint_stable_across_node_order(tmp_path: Path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    _seed_snapshot(a, [("10.x/y1", 1), ("10.x/y2", 2)])
    _seed_snapshot(b, [("10.x/y2", 2), ("10.x/y1", 1)])
    assert graph_topology_fingerprint(a) == graph_topology_fingerprint(b)


def test_fingerprint_changes_on_citation_count_diff(tmp_path: Path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    _seed_snapshot(a, [("10.x/y", 1)])
    _seed_snapshot(b, [("10.x/y", 2)])
    assert graph_topology_fingerprint(a) != graph_topology_fingerprint(b)


def test_fingerprint_accepts_datacite_mirror_snapshot_shape(tmp_path: Path):
    snapshot = tmp_path / "mirror.json"
    _seed_mirror_snapshot(snapshot, [("10.x/y", 2)])
    assert graph_topology_fingerprint(snapshot) is not None


def test_fingerprint_returns_none_for_empty_or_missing(tmp_path: Path):
    f = tmp_path / "empty.json"
    f.write_text("{}", encoding="utf-8")
    assert graph_topology_fingerprint(f) is None
    assert graph_topology_fingerprint(tmp_path / "missing.json") is None


def test_latest_mirror_snapshot_picks_newest(tmp_path: Path):
    (tmp_path / "2026-01-01.json").write_text("{}", encoding="utf-8")
    (tmp_path / "2026-04-26.json").write_text("{}", encoding="utf-8")
    (tmp_path / "2026-03-15.json").write_text("{}", encoding="utf-8")
    latest = _latest_mirror_snapshot(tmp_path)
    assert latest is not None
    assert latest.name == "2026-04-26.json"


def test_latest_mirror_snapshot_missing_dir(tmp_path: Path):
    assert _latest_mirror_snapshot(tmp_path / "absent") is None


def test_material_change_first_run(tmp_path: Path):
    # No last-fingerprint file → always material-change (will mint concept-DOI)
    assert material_change_detected(tmp_path, "abc123") is True


def test_material_change_unchanged(tmp_path: Path):
    (tmp_path / "last-fingerprint.txt").write_text("abc123\n", encoding="utf-8")
    assert material_change_detected(tmp_path, "abc123") is False


def test_material_change_changed(tmp_path: Path):
    (tmp_path / "last-fingerprint.txt").write_text("old\n", encoding="utf-8")
    assert material_change_detected(tmp_path, "new") is True


def test_assemble_deposit_metadata_first_version():
    md = assemble_deposit_metadata(
        snapshot_path=Path("/tmp/snap.json"),
        fingerprint="abc",
        is_first_version=True,
    )
    assert md["is_first_version"] is True
    assert md["topology_fingerprint"] == "abc"
    assert "constellation-graph" in md["keywords"]


def test_render_no_snapshot():
    text = render_dry_run_report(
        snapshot_path=None, fingerprint=None, has_change=False, metadata=None
    )
    assert "no DataCite mirror snapshot" in text


def test_render_no_change(tmp_path: Path):
    text = render_dry_run_report(
        snapshot_path=tmp_path / "snap.json",
        fingerprint="abc",
        has_change=False,
        metadata=None,
    )
    assert "no material change" in text


def test_render_with_change(tmp_path: Path):
    md = {
        "title": "Hapax constellation graph",
        "upload_type": "publication",
        "publication_type": "other",
        "keywords": ["x", "y"],
        "is_first_version": True,
    }
    text = render_dry_run_report(
        snapshot_path=tmp_path / "snap.json",
        fingerprint="abc",
        has_change=True,
        metadata=md,
    )
    assert "Would-mint" in text
    assert "Hapax constellation graph" in text


def test_main_dry_run_no_snapshot(tmp_path: Path, capsys):
    rc = main(["--mirror-dir", str(tmp_path / "absent"), "--graph-dir", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "no DataCite mirror snapshot" in captured.out


def test_main_dry_run_with_snapshot(tmp_path: Path, capsys):
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    _seed_snapshot(mirror / "2026-04-26.json", [("10.x/y", 1)])
    rc = main(["--mirror-dir", str(mirror), "--graph-dir", str(tmp_path / "graph")])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Material change:    True" in captured.out
    assert "Would-mint" in captured.out


def test_main_commit_no_token_skips_mint(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HAPAX_ZENODO_TOKEN", raising=False)
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    _seed_snapshot(mirror / "2026-04-26.json", [("10.x/y", 1)])
    rc = main(
        [
            "--mirror-dir",
            str(mirror),
            "--graph-dir",
            str(tmp_path / "graph"),
            "--commit",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "HAPAX_ZENODO_TOKEN" in captured.err


def test_main_commit_no_change_skips(tmp_path: Path, capsys, monkeypatch):
    """--commit no-ops when fingerprint matches last-fingerprint."""
    monkeypatch.setenv("HAPAX_ZENODO_TOKEN", "ztk")
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    graph = tmp_path / "graph"
    graph.mkdir()
    _seed_snapshot(mirror / "2026-04-26.json", [("10.x/y", 1)])
    # Pre-seed last-fingerprint matching the current snapshot to force no-change branch.
    from agents.publication_bus.self_citation_graph_doi import graph_topology_fingerprint

    fp = graph_topology_fingerprint(mirror / "2026-04-26.json")
    assert fp is not None
    (graph / "last-fingerprint.txt").write_text(fp + "\n", encoding="utf-8")

    rc = main(
        [
            "--mirror-dir",
            str(mirror),
            "--graph-dir",
            str(graph),
            "--commit",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "no material change" in captured.out


def test_main_commit_with_token_calls_publisher(tmp_path: Path, capsys, monkeypatch):
    """--commit with token + material change → calls mint_or_version + persists state."""
    monkeypatch.setenv("HAPAX_ZENODO_TOKEN", "ztk")
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    graph = tmp_path / "graph"
    _seed_snapshot(mirror / "2026-04-26.json", [("10.x/y", 1)])

    from unittest.mock import patch

    with patch(
        "agents.publication_bus.graph_publisher.mint_or_version",
        return_value=("10.5281/zenodo.99", "10.5281/zenodo.100", 100),
    ):
        rc = main(
            [
                "--mirror-dir",
                str(mirror),
                "--graph-dir",
                str(graph),
                "--commit",
            ]
        )
    assert rc == 0
    captured = capsys.readouterr()
    assert "minted concept-DOI=10.5281/zenodo.99" in captured.out
    assert "version-DOI=10.5281/zenodo.100" in captured.out
    # State persisted
    assert (graph / "concept-doi.txt").read_text().strip() == "10.5281/zenodo.99"

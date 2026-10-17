"""Tests for ``agents.publication_bus.self_citation_graph_doi``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from agents.publication_bus.self_citation_graph_doi import (
    _extract_topology_nodes,
    _latest_mirror_snapshot,
    assemble_deposit_metadata,
    graph_topology_fingerprint,
    main,
    material_change_detected,
    render_dry_run_report,
)


@pytest.fixture(autouse=True)
def isolated_publication_io(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Synthetic, Creator")
    monkeypatch.setenv("HAPAX_PUBLICATION_LOG_PATH", str(tmp_path / "witness.jsonl"))
    monkeypatch.setenv("HAPAX_REFUSALS_LOG_PATH", str(tmp_path / "refusals.jsonl"))

    def refuse_network(*args, **kwargs):
        raise AssertionError("real HTTP is forbidden in graph commit tests")

    monkeypatch.setattr("requests.sessions.Session.request", refuse_network)


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
    from agents.publication_bus.graph_publisher import persist_graph_state

    persist_graph_state(
        graph_dir=graph,
        concept_doi="10.5281/zenodo.99",
        version_doi="10.5281/zenodo.100",
        fingerprint=fp,
        deposit_id=100,
    )

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


@pytest.fixture
def commit_case(tmp_path, monkeypatch):
    from agents.publication_bus import graph_publisher

    monkeypatch.setenv("HAPAX_ZENODO_TOKEN", "synthetic-test-token")
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    snapshot = mirror / "2026-04-26.json"
    _seed_snapshot(snapshot, [("10.x/y", 1)])
    graph = tmp_path / "graph"
    http = Mock()
    http.RequestException = type("RequestException", (Exception,), {})

    def response(body, status=201):
        result = Mock(status_code=status, text="synthetic response")
        result.json.return_value = body
        return result

    http.post.side_effect = [
        response({"id": 100, "doi": "10.5281/zenodo.100"}),
        response({"id": 100, "doi": "10.5281/zenodo.100", "conceptdoi": "10.5281/zenodo.99"}),
        response(
            {
                "id": 100,
                "links": {"latest_draft": "https://zenodo.org/api/deposit/depositions/101"},
            }
        ),
        response({"id": 101, "doi": "10.5281/zenodo.101", "conceptdoi": "10.5281/zenodo.99"}),
    ]
    http.put.return_value = response({})
    monkeypatch.setattr(graph_publisher, "requests", http)
    argv = ["--mirror-dir", str(mirror), "--graph-dir", str(graph), "--commit"]
    return argv, graph, snapshot, http


def test_commit_creator_binding_reaches_outbound_metadata(commit_case, capsys, monkeypatch):
    argv, graph, snapshot, http = commit_case
    name = "Synthetic, Authorized Creator"
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", name)
    responses = iter(http.post.side_effect)

    def post(url, **kwargs):
        if url.endswith("/depositions"):
            assert kwargs["json"]["metadata"]["creators"] == [{"name": name}]
        return next(responses)

    def put(url, **kwargs):
        assert kwargs["json"]["metadata"]["creators"] == [{"name": name}]
        return Mock(status_code=200)

    http.post.side_effect = post
    http.put.side_effect = put
    assert main(argv) == 0
    _seed_snapshot(snapshot, [("10.x/y", 2)])
    assert main(argv) == 0
    assert http.post.call_count == 4
    assert http.put.call_count == 1
    output = capsys.readouterr()
    assert name not in output.out + output.err
    assert all(name not in p.read_text() for p in graph.iterdir())
    witness = Path(os.environ["HAPAX_PUBLICATION_LOG_PATH"]).read_text()
    assert name not in witness


@pytest.mark.parametrize("name", [None, "", "   ", "Synthetic\nCreator", "Synthetic\x7fCreator"])
@pytest.mark.parametrize("existing_version", [False, True])
def test_commit_missing_creator_holds_before_fence(
    commit_case, monkeypatch, capsys, name, existing_version
):
    argv, graph, snapshot, http = commit_case
    if existing_version:
        assert main(argv) == 0
        _seed_snapshot(snapshot, [("10.x/y", 2)])
    capsys.readouterr()
    prior = {p.name: p.read_bytes() for p in graph.iterdir()} if graph.exists() else {}
    http.reset_mock()
    if name is None:
        monkeypatch.delenv("HAPAX_OPERATOR_NAME")
    else:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", name)
    for _ in range(2):
        assert main(argv) == 1
        output = capsys.readouterr()
        assert "creator identity" in output.err
        assert "HAPAX_OPERATOR_NAME" in output.err
        assert "Next action" in output.err
        assert "minted" not in output.out
        http.post.assert_not_called()
        http.put.assert_not_called()
        actual = {p.name: p.read_bytes() for p in graph.iterdir()} if graph.exists() else {}
        assert actual == prior
        assert not (graph / "mint-attempt.json").exists()


@pytest.mark.parametrize("field", ["concept_doi", "version_doi"])
@pytest.mark.parametrize(
    "value", ["not-a-doi", "10.x/legacy", "10.5281/", "10.5281/legacy\x00", "10.5281/legacy "]
)
@pytest.mark.parametrize("changed", [False, True])
def test_commit_malformed_legacy_checkpoint_held(commit_case, capsys, field, value, changed):
    from agents.publication_bus.graph_publisher import persist_graph_state

    argv, graph, snapshot, http = commit_case
    identity = {"concept_doi": "10.5281/zenodo.99", "version_doi": "10.5281/zenodo.100"}
    identity[field] = value
    fingerprint = graph_topology_fingerprint(snapshot)
    persist_graph_state(graph_dir=graph, fingerprint=fingerprint, deposit_id=100, **identity)
    prior = {p.name: p.read_bytes() for p in graph.iterdir()}
    if changed:
        _seed_snapshot(snapshot, [("10.x/y", 2)])
    for _ in range(2):
        assert main(argv) == 1
        output = capsys.readouterr()
        assert "reconcile" in output.err
        assert "no material change" not in output.out
        assert "minted" not in output.out
        http.post.assert_not_called()
        http.put.assert_not_called()
        assert (graph / "mint-attempt.json").exists()
        assert {p.name for p in graph.iterdir()} == set(prior) | {"mint-attempt.json"}
        for filename, content in prior.items():
            assert (graph / filename).read_bytes() == content


def test_commit_refused_before_http_or_state(commit_case, monkeypatch, capsys):
    from agents.publication_bus.graph_publisher import GraphPublisher
    from agents.publication_bus.publisher_kit.allowlist import AllowlistGate

    argv, graph, _, http = commit_case
    monkeypatch.setattr(GraphPublisher, "allowlist", AllowlistGate(GraphPublisher.surface_name))
    counter = GraphPublisher._get_counter().labels(
        surface=GraphPublisher.surface_name, result="refused"
    )
    before = counter._value.get()
    assert main(argv) == 1
    error = capsys.readouterr().err
    assert "allowlist deny" in error
    assert "review target admission" in error
    assert counter._value.get() == before + 1
    http.post.assert_not_called()
    http.put.assert_not_called()
    assert not graph.exists()


def test_commit_first_version_then_version_and_duplicate(commit_case, capsys):
    argv, graph, snapshot, http = commit_case
    assert main(argv) == 0
    assert "deposit_id=100" in capsys.readouterr().out
    first_fp = graph_topology_fingerprint(snapshot)
    _seed_snapshot(snapshot, [("10.x/y", 2)])
    assert main(argv) == 0
    assert "deposit_id=101" in capsys.readouterr().out
    history = [
        json.loads(row) for row in (graph / "version-doi-history.jsonl").read_text().splitlines()
    ]
    assert history == [
        {
            "concept_doi": "10.5281/zenodo.99",
            "version_doi": "10.5281/zenodo.100",
            "deposit_id": 100,
            "fingerprint": first_fp,
        },
        {
            "concept_doi": "10.5281/zenodo.99",
            "version_doi": "10.5281/zenodo.101",
            "deposit_id": 101,
            "fingerprint": graph_topology_fingerprint(snapshot),
        },
    ]
    assert (graph / "concept-doi.txt").read_text().strip() == "10.5281/zenodo.99"
    assert (graph / "last-deposit-id.txt").read_text().strip() == "101"
    assert (graph / "last-fingerprint.txt").read_text().strip() == history[-1]["fingerprint"]
    urls = [call.args[0] for call in http.post.call_args_list]
    assert urls == [
        "https://zenodo.org/api/deposit/depositions",
        "https://zenodo.org/api/deposit/depositions/100/actions/publish",
        "https://zenodo.org/api/deposit/depositions/100/actions/newversion",
        "https://zenodo.org/api/deposit/depositions/101/actions/publish",
    ]
    http.put.assert_called_once()
    assert http.put.call_args.args[0].endswith("/101")
    assert history[-1]["fingerprint"] in http.put.call_args.kwargs["json"]["metadata"]["notes"]
    before = {path.name: path.read_bytes() for path in graph.iterdir()}
    assert main(argv) == 0
    assert "no material change" in capsys.readouterr().out
    assert len(http.post.call_args_list) == 4
    assert {path.name: path.read_bytes() for path in graph.iterdir()} == before


@pytest.mark.parametrize("depth", [1, 3])
def test_commit_first_run_creates_and_syncs_missing_parents(commit_case, monkeypatch, depth):
    argv, original_graph, _, http = commit_case
    graph = original_graph.joinpath(*(["new-parent"] * depth), "self-citation-graph")
    argv[argv.index("--graph-dir") + 1] = str(graph)
    assert not graph.parent.exists()
    synced = []
    real_fsync = os.fsync

    def record_sync(fd):
        real_fsync(fd)
        synced.append(Path(os.readlink(f"/proc/self/fd/{fd}")))

    responses = iter(http.post.side_effect)

    def post(*args, **kwargs):
        # The fence and every newly created directory entry must be durable
        # before the first remote side effect, including the existing ancestor.
        assert graph / "mint-attempt.json" in synced
        assert graph in synced
        assert set(graph.parents).issubset(synced)
        return next(responses)

    monkeypatch.setattr(os, "fsync", record_sync)
    http.post.side_effect = post
    assert main(argv) == 0
    assert http.post.call_count == 2
    assert (graph / "concept-doi.txt").read_text().strip() == "10.5281/zenodo.99"
    assert not (graph / "mint-attempt.json").exists()
    assert main(argv) == 0
    assert http.post.call_count == 2


def test_commit_missing_parent_sync_failure_keeps_fence(commit_case, monkeypatch, capsys):
    argv, original_graph, _, http = commit_case
    graph = original_graph / "publications" / "self-citation-graph"
    argv[argv.index("--graph-dir") + 1] = str(graph)
    real_fsync = os.fsync
    failures = []

    def fail_sync(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if path == graph.parent.parent:
            failures.append(path)
            raise OSError("synthetic ancestor sync failure")
        real_fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", fail_sync)
        assert main(argv) == 1
    assert failures
    assert "reconcile" in capsys.readouterr().err
    assert (graph / "mint-attempt.json").exists()
    assert main(argv) == 1
    http.post.assert_not_called()


@pytest.mark.parametrize("existing_version", [False, True])
@pytest.mark.parametrize("field", ["doi", "conceptdoi"])
@pytest.mark.parametrize(
    "value",
    [
        "not-a-doi",
        "10.x/zenodo.100",
        "10.5281/",
        "10.5281zenodo.100",
        "10..5281/zenodo.100",
        "https://doi.org/10.5281/zenodo.100",
        " 10.5281/zenodo.100",
        "10.5281/zenodo.100 ",
        "10.5281/zenodo.100\n",
        "10.5281/zenodo.\t100",
        "10.5281/zenodo.\x00100",
        "10.5281/zenodo.\x1b100",
        "10.5281/zenodo.\x7f100",
        "10.5281/zenodo.\x85100",
        "10.5281/zenodo.\u200b100",
    ],
)
def test_commit_rejects_malformed_doi(commit_case, capsys, existing_version, field, value):
    argv, graph, snapshot, http = commit_case
    if existing_version:
        assert main(argv) == 0
        _seed_snapshot(snapshot, [("10.x/y", 2)])
    capsys.readouterr()
    prior = {p.name: p.read_bytes() for p in graph.iterdir()} if graph.exists() else {}
    responses = list(http.post.side_effect)
    responses[1].json.return_value[field] = value
    http.post.side_effect = responses
    assert main(argv) == 1
    output = capsys.readouterr()
    assert f"remote response missing or invalid {field}" in output.err
    assert "minted" not in output.out
    assert (graph / "mint-attempt.json").exists()
    for name, content in prior.items():
        assert (graph / name).read_bytes() == content
    assert {p.name for p in graph.iterdir()} == set(prior) | {"mint-attempt.json"}
    calls = http.post.call_count
    assert main(argv) == 1
    assert http.post.call_count == calls


@pytest.mark.parametrize("prefix", ["10.5281", "10.5072"])
def test_commit_accepts_zenodo_doi_forms(commit_case, capsys, prefix):
    argv, graph, _, http = commit_case
    responses = list(http.post.side_effect)
    concept = f"{prefix}/zenodo.99"
    version = f"{prefix}/zenodo.100"
    responses[1].json.return_value.update(doi=version, conceptdoi=concept)
    http.post.side_effect = responses
    assert main(argv) == 0
    output = capsys.readouterr().out
    assert concept in output and version in output
    history = json.loads((graph / "version-doi-history.jsonl").read_text())
    assert history["concept_doi"] == concept
    assert history["version_doi"] == version


@pytest.mark.parametrize("existing_version", [False, True])
@pytest.mark.parametrize("failure", ["doi", "conceptdoi", "id", "json", "http", "transport"])
def test_commit_failed_publish_reports_known_deposit_only(
    commit_case, capsys, existing_version, failure
):
    argv, graph, snapshot, http = commit_case
    if existing_version:
        assert main(argv) == 0
        _seed_snapshot(snapshot, [("10.x/y", 2)])
    capsys.readouterr()
    responses = list(http.post.side_effect)
    private = "synthetic-private-response-contents"
    if failure == "transport":
        responses[1] = http.RequestException(private)
    elif failure == "http":
        responses[1].status_code = 503
        responses[1].text = private
    elif failure == "json":
        responses[1].json.side_effect = ValueError(private)
    else:
        responses[1].json.return_value[failure] = private
    http.post.side_effect = responses
    assert main(argv) == 1
    output = capsys.readouterr()
    assert f"deposit_id={101 if existing_version else 100}" in output.err
    assert "reconcile" in output.err
    assert "minted" not in output.out
    assert private not in output.err
    assert "synthetic-test-token" not in output.err
    assert (graph / "mint-attempt.json").exists()
    calls = http.post.call_count
    assert main(argv) == 1
    assert http.post.call_count == calls


@pytest.mark.parametrize("token", [None, "", "   "])
def test_commit_missing_token_has_no_transport_or_state(commit_case, monkeypatch, capsys, token):
    argv, graph, _, http = commit_case
    if token is None:
        monkeypatch.delenv("HAPAX_ZENODO_TOKEN")
    else:
        monkeypatch.setenv("HAPAX_ZENODO_TOKEN", token)
    assert main(argv) == 0
    assert "HAPAX_ZENODO_TOKEN" in capsys.readouterr().err
    http.post.assert_not_called()
    assert not graph.exists()


@pytest.mark.parametrize("failure_leg", [0, 1])
def test_commit_http_failure_does_not_persist_or_retry(commit_case, capsys, failure_leg):
    argv, graph, _, http = commit_case
    responses = list(http.post.side_effect)
    responses[failure_leg].status_code = 503
    http.post.side_effect = responses
    assert main(argv) == 1
    assert "HTTP 503" in capsys.readouterr().err
    assert http.post.call_count == failure_leg + 1
    assert not (graph / "version-doi-history.jsonl").exists()
    calls = http.post.call_count
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == calls


@pytest.mark.parametrize(
    "filename",
    [
        "version-doi-history.jsonl",
        "concept-doi.txt",
        "last-deposit-id.txt",
        "last-fingerprint.txt",
    ],
)
@pytest.mark.parametrize("existing_version", [False, True])
def test_commit_save_failure_reports_remote_identity(
    commit_case, monkeypatch, capsys, filename, existing_version
):
    argv, graph, snapshot, http = commit_case
    if existing_version:
        assert main(argv) == 0
        _seed_snapshot(snapshot, [("10.x/y", 2)])
    capsys.readouterr()
    real_open = Path.open
    failures = []

    def fail_write(path, mode="r", *args, **kwargs):
        if path == graph / filename and ("w" in mode or "a" in mode):
            failures.append(str(path))
            raise OSError("synthetic state write failure")
        return real_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "open", fail_write)
        assert main(argv) == 1
    output = capsys.readouterr()
    assert failures
    assert "state persistence failed" in output.err
    assert "reconcile" in output.err
    assert f"deposit_id={101 if existing_version else 100}" in output.err
    assert f"10.5281/zenodo.{101 if existing_version else 100}" in output.err
    assert "10.5281/zenodo.99" in output.err
    assert "minted" not in output.out
    assert http.post.call_count == (4 if existing_version else 2)
    # Even failure before the FIRST history write must durably block another
    # invocation after the write fault is removed (first mint and new version).
    calls = http.post.call_count
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == calls


@pytest.mark.parametrize("existing_version", [False, True])
@pytest.mark.parametrize(
    "response_leg,field,value",
    [
        (0, "id", None),
        (0, "id", 0),
        (0, "id", -1),
        (0, "id", True),
        (0, "id", 1.5),
        (0, "id", "bad"),
        (1, "id", None),
        (1, "id", 999),
        (1, "doi", None),
        (1, "doi", "   "),
        (1, "doi", 123),
        (1, "conceptdoi", None),
        (1, "conceptdoi", "   "),
        (1, "conceptdoi", []),
    ],
)
def test_commit_rejects_invalid_remote_identity(
    commit_case, capsys, existing_version, response_leg, field, value
):
    argv, graph, snapshot, http = commit_case
    if existing_version:
        assert main(argv) == 0
        _seed_snapshot(snapshot, [("10.x/y", 2)])
    capsys.readouterr()
    prior = {p.name: p.read_bytes() for p in graph.iterdir()} if graph.exists() else {}
    calls = http.post.call_count
    responses = list(http.post.side_effect)
    # A draft DOI must never substitute for missing published identifiers.
    responses[response_leg].json.return_value[field] = value
    http.post.side_effect = responses
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    for name, content in prior.items():
        assert (graph / name).read_bytes() == content
    if not existing_version:
        assert not (graph / "version-doi-history.jsonl").exists()
    assert http.post.call_count == calls + response_leg + 1
    calls = http.post.call_count
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == calls


@pytest.mark.parametrize(
    "filename,after_remote",
    [
        ("mint-attempt.json", False),
        (".", False),
        ("..", False),
        ("version-doi-history.jsonl", True),
        ("concept-doi.txt", True),
        ("last-deposit-id.txt", True),
        ("last-fingerprint.txt", True),
        (".", True),
    ],
)
def test_commit_sync_failure_holds_attempt(
    commit_case, monkeypatch, capsys, filename, after_remote
):
    argv, graph, _, http = commit_case
    target = (graph / filename).resolve()
    real_fsync = os.fsync
    failures = []

    def fail_sync(fd):
        if (
            Path(os.readlink(f"/proc/self/fd/{fd}")) == target
            and bool(http.post.call_count) == after_remote
        ):
            failures.append(target)
            raise OSError("synthetic durability failure")
        real_fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", fail_sync)
        assert main(argv) == 1
    assert failures
    assert "reconcile" in capsys.readouterr().err
    calls = http.post.call_count
    assert calls == (2 if after_remote else 0)
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == calls


def test_commit_attempt_creation_failure_makes_no_call(commit_case, monkeypatch, capsys):
    argv, graph, _, http = commit_case
    real_open = Path.open
    failures = []

    def fail_create(path, mode="r", *args, **kwargs):
        if path == graph / "mint-attempt.json" and mode == "x":
            failures.append(path)
            raise OSError("synthetic fence creation failure")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_create)
    assert main(argv) == 1
    assert failures
    assert "reconcile" in capsys.readouterr().err
    http.post.assert_not_called()


def test_commit_concurrent_invocation_refused_before_transport(commit_case, capsys):
    argv, _, _, http = commit_case
    responses = iter(http.post.side_effect)
    nested = []

    def remote(*args, **kwargs):
        if not nested:
            nested.append("entered")
            assert main(argv) == 1
            assert "reconcile" in capsys.readouterr().err
            assert http.post.call_count == 1
        return next(responses)

    http.post.side_effect = remote
    assert main(argv) == 0
    assert nested == ["entered"]
    assert http.post.call_count == 2


def test_commit_interrupted_remote_call_holds_attempt(commit_case, capsys):
    argv, _, _, http = commit_case
    http.post.side_effect = KeyboardInterrupt("synthetic crash after request started")
    with pytest.raises(KeyboardInterrupt):
        main(argv)
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == 1


@pytest.mark.parametrize("contents", ["", "{", '{"fingerprint": "unrelated"}'])
def test_commit_existing_attempt_is_never_expired_or_replaced(commit_case, capsys, contents):
    argv, graph, _, http = commit_case
    graph.mkdir()
    attempt = graph / "mint-attempt.json"
    attempt.write_text(contents)
    os.utime(attempt, (1, 1))
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert attempt.read_text() == contents
    http.post.assert_not_called()


@pytest.mark.parametrize("wrong_identity", ["deposit", "concept"])
def test_commit_version_must_preserve_concept_and_change_deposit(
    commit_case, capsys, wrong_identity
):
    argv, graph, snapshot, http = commit_case
    assert main(argv) == 0
    capsys.readouterr()
    original_history = (graph / "version-doi-history.jsonl").read_bytes()
    _seed_snapshot(snapshot, [("10.x/y", 2)])
    responses = list(http.post.side_effect)
    if wrong_identity == "deposit":
        responses[0].json.return_value["links"]["latest_draft"] = (
            "https://zenodo.org/api/deposit/depositions/100"
        )
    else:
        responses[1].json.return_value["conceptdoi"] = "10.x/different-concept"
    http.post.side_effect = responses
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert (graph / "version-doi-history.jsonl").read_bytes() == original_history
    calls = http.post.call_count
    assert calls == (3 if wrong_identity == "deposit" else 4)
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == calls


@pytest.mark.parametrize(
    "link",
    [
        None,
        "",
        [],
        "https://unrelated.invalid/api/deposit/depositions/101",
        "http://zenodo.org/api/deposit/depositions/101",
        "https://zenodo.org/api/deposit/depositions/0",
        "https://zenodo.org/api/deposit/depositions/-1",
        "https://zenodo.org/api/deposit/depositions/101?untrusted=1",
        "https://zenodo.org/api/deposit/depositions/101/extra",
    ],
)
def test_commit_rejects_invalid_draft_link_before_put(commit_case, capsys, link):
    argv, graph, snapshot, http = commit_case
    assert main(argv) == 0
    capsys.readouterr()
    prior_history = (graph / "version-doi-history.jsonl").read_bytes()
    _seed_snapshot(snapshot, [("10.x/y", 2)])
    responses = list(http.post.side_effect)
    responses[0].json.return_value["links"]["latest_draft"] = link
    http.post.side_effect = responses
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    http.put.assert_not_called()
    assert http.post.call_count == 3
    assert (graph / "version-doi-history.jsonl").read_bytes() == prior_history
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == 3


def test_commit_incomplete_matching_fingerprint_is_not_no_change(commit_case, capsys):
    argv, graph, snapshot, http = commit_case
    graph.mkdir()
    (graph / "last-fingerprint.txt").write_text(graph_topology_fingerprint(snapshot) + "\n")
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    http.post.assert_not_called()


@pytest.mark.parametrize("history", ["", "{", "[]\n", "{}\n"])
def test_commit_corrupt_history_does_not_skip_or_remint(commit_case, capsys, history):
    argv, graph, _, http = commit_case
    assert main(argv) == 0
    capsys.readouterr()
    (graph / "version-doi-history.jsonl").write_text(history)
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == 2


def test_commit_torn_history_append_retained_and_blocks_retry(commit_case, monkeypatch, capsys):
    argv, graph, snapshot, http = commit_case
    assert main(argv) == 0
    capsys.readouterr()
    _seed_snapshot(snapshot, [("10.x/y", 2)])
    history = graph / "version-doi-history.jsonl"
    original = history.read_bytes()
    real_open = Path.open

    def torn_append(path, mode="r", *args, **kwargs):
        if path == history and mode == "a":
            with real_open(path, mode, *args, **kwargs) as stream:
                stream.write('{"concept_doi":')
            raise OSError("synthetic partial history write")
        return real_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "open", torn_append)
        assert main(argv) == 1
    assert "deposit_id=101" in capsys.readouterr().err
    assert history.read_bytes() == original + b'{"concept_doi":'
    assert main(argv) == 1
    assert "reconcile" in capsys.readouterr().err
    assert http.post.call_count == 4

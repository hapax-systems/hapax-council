"""Tests for dynamic flow node discovery from agent manifests."""

from pathlib import Path

from logos.api.flow_discovery import (
    build_declared_edges,
    composite_edges,
    discover_pipeline_nodes,
    read_state_metrics,
)


def test_discover_finds_pipeline_agents(tmp_path: Path):
    """Only agents with pipeline_role appear as nodes."""
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()

    (manifest_dir / "perception.yaml").write_text(
        "id: perception\nname: Perception\npipeline_role: processor\n"
        "pipeline_layer: perception\npipeline_state:\n  path: /tmp/test.json\n  metrics: [flow]\n"
    )
    (manifest_dir / "backup.yaml").write_text("id: backup\nname: Backup\ncategory: maintenance\n")

    nodes = discover_pipeline_nodes(manifest_dir)
    assert len(nodes) == 1
    assert nodes[0]["id"] == "perception"
    assert nodes[0]["pipeline_layer"] == "perception"


def test_discover_reads_metrics(tmp_path: Path):
    """State file metrics are extracted correctly."""
    state_file = tmp_path / "state.json"
    state_file.write_text('{"flow": 0.75, "extra": "ignored", "timestamp": 1000}')

    metrics = read_state_metrics(str(state_file), ["flow"])
    assert metrics == {"flow": 0.75}


def test_discover_handles_missing_state(tmp_path: Path):
    """Missing state file returns empty metrics."""
    metrics = read_state_metrics("/nonexistent/path.json", ["flow"])
    assert metrics == {}


def test_discover_computes_age_and_status(tmp_path: Path):
    """Node status derived from state file age."""
    import json
    import time

    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"timestamp": time.time(), "flow": 1.0}))

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "test.yaml").write_text(
        f"id: test\nname: Test\npipeline_role: sensor\n"
        f"pipeline_layer: perception\npipeline_state:\n"
        f"  path: {state_file}\n  metrics: [flow]\n"
    )

    nodes = discover_pipeline_nodes(manifest_dir)
    assert len(nodes) == 1
    assert nodes[0]["status"] == "active"
    assert nodes[0]["age_s"] < 5
    assert nodes[0]["metrics"]["flow"] == 1.0


def test_layer_edges_perception_to_cognition():
    """Perception nodes connect to cognition nodes automatically."""
    nodes = [
        {"id": "perc", "pipeline_layer": "perception", "status": "active", "age_s": 1, "gates": []},
        {"id": "cog", "pipeline_layer": "cognition", "status": "active", "age_s": 2, "gates": []},
        {"id": "out", "pipeline_layer": "output", "status": "active", "age_s": 3, "gates": []},
    ]
    edges = build_declared_edges(nodes)
    sources_targets = [(e["source"], e["target"]) for e in edges]
    assert ("perc", "cog") in sources_targets
    assert ("cog", "out") in sources_targets
    assert ("perc", "out") not in sources_targets


def test_gate_edges():
    """Gates create explicit cross-connections."""
    nodes = [
        {
            "id": "consent",
            "pipeline_layer": "cognition",
            "status": "active",
            "age_s": 1,
            "gates": ["voice"],
        },
        {"id": "voice", "pipeline_layer": "output", "status": "active", "age_s": 2, "gates": []},
    ]
    edges = build_declared_edges(nodes)
    gate_edges = [e for e in edges if e.get("label") == "gate"]
    assert len(gate_edges) == 1
    assert gate_edges[0]["source"] == "consent"
    assert gate_edges[0]["target"] == "voice"


def test_composite_confirmed():
    """Declared + observed = confirmed."""
    declared = [{"source": "a", "target": "b", "active": True, "label": "flow"}]
    observed = {("a", "b")}
    result = composite_edges(declared, observed)
    assert result[0]["edge_type"] == "confirmed"


def test_composite_emergent():
    """Observed only = emergent."""
    declared: list[dict] = []
    observed = {("x", "y")}
    result = composite_edges(declared, observed)
    emergent = [e for e in result if e["edge_type"] == "emergent"]
    assert len(emergent) == 1
    assert emergent[0]["source"] == "x"


def test_composite_dormant():
    """Declared with stale source = dormant."""
    declared = [{"source": "a", "target": "b", "active": False, "label": "flow"}]
    observed: set[tuple[str, str]] = set()
    result = composite_edges(declared, observed)
    assert result[0]["edge_type"] == "dormant"


def test_composite_active_declared_is_confirmed():
    """Declared with active source = confirmed even without observation."""
    declared = [{"source": "a", "target": "b", "active": True, "label": "flow"}]
    observed: set[tuple[str, str]] = set()
    result = composite_edges(declared, observed)
    assert result[0]["edge_type"] == "confirmed"

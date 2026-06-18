import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"
SEED_PATH = ARCHITECTURE_DIR / "system-dynamics-map.seed.json"
VIEWER_PATH = ARCHITECTURE_DIR / "system-dynamics-map-viewer.html"


def _load_seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _load_viewer() -> tuple[str, dict]:
    html = VIEWER_PATH.read_text(encoding="utf-8")
    match = re.search(
        r'<script type="application/json" id="seed-data">\s*(.*?)\s*</script>',
        html,
        re.S,
    )
    assert match, "viewer must include an embedded JSON seed fallback"
    return html, json.loads(match.group(1))


def test_viewer_embedded_seed_matches_canonical_seed():
    _, embedded = _load_viewer()
    assert embedded == _load_seed()


def test_system_dynamics_seed_graph_is_referentially_valid():
    for name, data in (("seed", _load_seed()), ("embedded", _load_viewer()[1])):
        node_ids = [node["id"] for node in data["nodes"]]
        edge_ids = [edge["id"] for edge in data["edges"]]
        assert len(node_ids) == len(set(node_ids)), f"{name}: duplicate node IDs"
        assert len(edge_ids) == len(set(edge_ids)), f"{name}: duplicate edge IDs"

        layers = {layer["id"] for layer in data["layers"]}
        statuses = set(data["status_kinds"])
        node_set = set(node_ids)

        for node in data["nodes"]:
            assert node["layer"] in layers, f"{name}: invalid node layer {node['id']}"
            assert node["status"] in statuses, f"{name}: invalid node status {node['id']}"
            assert node.get("docs"), f"{name}: node missing docs {node['id']}"

        for edge in data["edges"]:
            assert edge["source"] in node_set, f"{name}: missing edge source {edge['id']}"
            assert edge["target"] in node_set, f"{name}: missing edge target {edge['id']}"
            assert edge["layer"] in layers, f"{name}: invalid edge layer {edge['id']}"
            assert edge["status"] in statuses, f"{name}: invalid edge status {edge['id']}"


def test_viewer_layout_uses_intrinsic_wrapping_without_conditional_at_rules():
    html, _ = _load_viewer()
    assert "flex-wrap: wrap" in html
    assert "@container" not in html
    assert "@media" not in html


def test_system_dynamics_artifacts_do_not_use_hardcoded_hex_colors():
    hex_color = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
    for path in (SEED_PATH, VIEWER_PATH, ARCHITECTURE_DIR / "system-dynamics-map-v0.md"):
        assert not hex_color.search(path.read_text(encoding="utf-8")), path

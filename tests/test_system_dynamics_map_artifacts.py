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
    assert match, (
        "viewer must include an embedded JSON seed fallback. "
        "Fix by restoring the seed-data script tag or removing the file-open fallback claim."
    )
    return html, json.loads(match.group(1))


def test_viewer_embedded_seed_matches_canonical_seed():
    _, embedded = _load_viewer()
    assert embedded == _load_seed(), (
        "embedded viewer fallback drifted from system-dynamics-map.seed.json. "
        "Fix by regenerating the seed-data script block from the canonical seed file."
    )


def test_system_dynamics_seed_graph_is_referentially_valid():
    for name, data in (("seed", _load_seed()), ("embedded", _load_viewer()[1])):
        node_ids = [node["id"] for node in data["nodes"]]
        edge_ids = [edge["id"] for edge in data["edges"]]
        assert len(node_ids) == len(set(node_ids)), (
            f"{name}: duplicate node IDs. Fix by assigning each node one stable ID."
        )
        assert len(edge_ids) == len(set(edge_ids)), (
            f"{name}: duplicate edge IDs. Fix by assigning each edge one stable ID."
        )

        layers = {layer["id"] for layer in data["layers"]}
        statuses = set(data["status_kinds"])
        node_set = set(node_ids)

        for node in data["nodes"]:
            assert node["layer"] in layers, (
                f"{name}: invalid node layer {node['id']}. "
                "Fix by using a declared layers[].id value."
            )
            assert node["status"] in statuses, (
                f"{name}: invalid node status {node['id']}. "
                "Fix by using a declared status_kinds value."
            )
            assert node.get("docs"), (
                f"{name}: node missing docs {node['id']}. Fix by adding at least one docs[] link."
            )

        for edge in data["edges"]:
            assert edge["source"] in node_set, (
                f"{name}: missing edge source {edge['id']}. "
                "Fix by adding the source node or correcting edge.source."
            )
            assert edge["target"] in node_set, (
                f"{name}: missing edge target {edge['id']}. "
                "Fix by adding the target node or correcting edge.target."
            )
            assert edge["layer"] in layers, (
                f"{name}: invalid edge layer {edge['id']}. "
                "Fix by using a declared layers[].id value."
            )
            assert edge["status"] in statuses, (
                f"{name}: invalid edge status {edge['id']}. "
                "Fix by using a declared status_kinds value."
            )


def test_viewer_layout_uses_intrinsic_wrapping_without_conditional_at_rules():
    html, _ = _load_viewer()
    assert "flex-wrap: wrap" in html, (
        "viewer layout no longer declares intrinsic wrapping. "
        "Fix by restoring flex wrapping or replacing this guard with a rendered layout test."
    )
    assert "@container" not in html, (
        "viewer reintroduced container queries. "
        "Fix by using intrinsic wrapping or updating the visual witnesses and review notes."
    )
    assert "@media" not in html, (
        "viewer reintroduced media queries. "
        "Fix by using intrinsic wrapping or updating the visual witnesses and review notes."
    )


def test_system_dynamics_artifacts_do_not_use_hardcoded_hex_colors():
    hex_color = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
    for path in (SEED_PATH, VIEWER_PATH, ARCHITECTURE_DIR / "system-dynamics-map-v0.md"):
        match = hex_color.search(path.read_text(encoding="utf-8"))
        assert not match, (
            f"{path}: hardcoded hex color {match.group(0)}. "
            "Fix by using existing CSS tokens, rgb(), or color-mix() values."
        )

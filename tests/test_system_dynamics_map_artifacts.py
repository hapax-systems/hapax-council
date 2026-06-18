import json
import re
import subprocess
import sys
from pathlib import Path

from rdflib import RDF, Dataset, Graph, Literal, Namespace, URIRef

from scripts import system_dynamics_map_materialize as materialize

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"
SEED_PATH = ARCHITECTURE_DIR / "system-dynamics-map.seed.json"
VIEWER_PATH = ARCHITECTURE_DIR / "system-dynamics-map-viewer.html"
VENDOR_PATH = ARCHITECTURE_DIR / "vendor" / "cytoscape-3.34.0.min.js"
TRIG_PATH = ARCHITECTURE_DIR / "system-dynamics-map.canonical.trig"
SHACL_PATH = ARCHITECTURE_DIR / "system-dynamics-map.shacl.ttl"
MANIFEST_PATH = ARCHITECTURE_DIR / "system-dynamics-map.view-manifest.json"
EXPECTED_NODE_COUNT = 29
EXPECTED_EDGE_COUNT = 35
BASE = Namespace("https://hapax.local/system-dynamics-map/v0/")
SD = Namespace("https://hapax.local/ns/system-dynamics-map#")
SH = Namespace("http://www.w3.org/ns/shacl#")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
XSD_STRING = URIRef("http://www.w3.org/2001/XMLSchema#string")
XSD_INTEGER = URIRef("http://www.w3.org/2001/XMLSchema#integer")
XSD_DECIMAL = URIRef("http://www.w3.org/2001/XMLSchema#decimal")


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


def _shape_property(shapes: Graph, shape: URIRef, path: URIRef):
    for property_shape in shapes.objects(shape, SH.property):
        if (property_shape, SH.path, path) in shapes:
            return property_shape
    raise AssertionError(f"{SHACL_PATH}: {shape} missing property path {path}")


def _assert_shape_property(
    shapes: Graph,
    shape: URIRef,
    path: URIRef,
    *,
    datatype: URIRef | None = None,
    node_kind: URIRef | None = None,
) -> None:
    property_shape = _shape_property(shapes, shape, path)
    assert (property_shape, SH.minCount, Literal(1)) in shapes
    if datatype is not None:
        assert (property_shape, SH.datatype, datatype) in shapes
    if node_kind is not None:
        assert (property_shape, SH.nodeKind, node_kind) in shapes


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
        assert len(node_ids) == EXPECTED_NODE_COUNT, (
            f"{name}: expected {EXPECTED_NODE_COUNT} nodes, found {len(node_ids)}. "
            "Fix by restoring the documented v0 graph shape or updating the count constant "
            "with the intentional graph change."
        )
        assert len(edge_ids) == EXPECTED_EDGE_COUNT, (
            f"{name}: expected {EXPECTED_EDGE_COUNT} edges, found {len(edge_ids)}. "
            "Fix by restoring the documented v0 graph shape or updating the count constant "
            "with the intentional graph change."
        )
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
            assert edge.get("relation"), (
                f"{name}: edge missing relation {edge['id']}. "
                "Fix by adding the relation field used by the viewer details panel."
            )
            assert "confidence" in edge, (
                f"{name}: edge missing confidence {edge['id']}. "
                "Fix by adding a numeric confidence value for the relation claim."
            )
            assert edge.get("docs"), (
                f"{name}: edge missing docs/evidence links {edge['id']}. "
                "Fix by adding at least one docs[] link for the relation source."
            )


def test_viewer_uses_committed_local_cytoscape_asset():
    html, _ = _load_viewer()
    assert "https://unpkg.com/cytoscape" not in html, (
        "viewer still depends on CDN-hosted Cytoscape. "
        "Fix by loading the committed ./vendor/cytoscape-3.34.0.min.js asset."
    )
    assert "./vendor/cytoscape-3.34.0.min.js" in html, (
        "viewer does not reference the committed Cytoscape asset. "
        "Fix by restoring the local script tag."
    )
    assert VENDOR_PATH.exists(), (
        f"{VENDOR_PATH}: missing local Cytoscape asset. "
        "Fix by restoring the vendored 3.34.0 minified file."
    )
    assert materialize._sha384_sri(VENDOR_PATH) == (
        "sha384-K+k+ywfDuvV9dwg+bwsVE0WGkrTnqFamaER+ydBgMFQTtlI0jdI9no9AjkQHwh/T"
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


def test_materialized_semantic_artifacts_are_current():
    result = subprocess.run(
        [sys.executable, "scripts/system_dynamics_map_materialize.py", "--check"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "system dynamics persisted artifacts are stale. "
        "Fix by running scripts/system_dynamics_map_materialize.py.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_materializer_write_and_stale_detection_paths(tmp_path, monkeypatch):
    seed_path = tmp_path / "system-dynamics-map.seed.json"
    vendor_path = tmp_path / "cytoscape-3.34.0.min.js"
    trig_path = tmp_path / "system-dynamics-map.canonical.trig"
    shacl_path = tmp_path / "system-dynamics-map.shacl.ttl"
    manifest_path = tmp_path / "system-dynamics-map.view-manifest.json"
    seed_path.write_text(SEED_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    vendor_path.write_bytes(VENDOR_PATH.read_bytes())

    monkeypatch.setattr(materialize, "SEED_PATH", seed_path)
    monkeypatch.setattr(materialize, "VENDOR_PATH", vendor_path)
    monkeypatch.setattr(materialize, "TRIG_PATH", trig_path)
    monkeypatch.setattr(materialize, "SHACL_PATH", shacl_path)
    monkeypatch.setattr(materialize, "MANIFEST_PATH", manifest_path)

    materialize.write_artifacts()
    assert trig_path.exists()
    assert shacl_path.exists()
    assert manifest_path.exists()
    assert materialize.check_artifacts() == []

    trig_path.write_text("stale\n", encoding="utf-8")
    assert any("stale" in error for error in materialize.check_artifacts())
    shacl_path.unlink()
    errors = materialize.check_artifacts()
    assert any("stale" in error for error in errors)
    assert any("missing" in error for error in errors)


def test_materialized_rdf_artifacts_keep_valid_prefix_directives():
    for path in (TRIG_PATH, SHACL_PATH):
        text = path.read_text(encoding="utf-8")
        prefix_lines = [line for line in text.splitlines() if line.startswith("@prefix ")]
        assert text.startswith("@prefix "), (
            f"{path}: expected RDF prefix declarations. Fix by regenerating the semantic artifact."
        )
        assert len(prefix_lines) >= 5, (
            f"{path}: expected namespace prefix declarations. "
            "Fix by regenerating the semantic artifact."
        )
        assert all(line.endswith(" .") for line in prefix_lines)


def test_materialized_rdf_artifacts_parse_and_match_seed_contract():
    seed = _load_seed()
    dataset = Dataset()
    dataset.parse(TRIG_PATH, format="trig")
    shapes = Graph()
    shapes.parse(SHACL_PATH, format="turtle")

    graph_ids = {str(graph.identifier) for graph in dataset.graphs()}
    for graph_name in (*seed["status_kinds"], "provenance"):
        assert str(BASE[f"graph/{graph_name}"]) in graph_ids, (
            f"{TRIG_PATH}: missing parseable named graph {graph_name}. "
            "Fix by regenerating the canonical TriG artifact."
        )

    asserted = dataset.graph(URIRef(BASE["graph/asserted"]))
    assert (URIRef(BASE["map"]), RDF.type, SD.SystemDynamicsMap) in asserted
    for node in seed["nodes"]:
        partition = dataset.graph(URIRef(BASE[f"graph/{node['status']}"]))
        subject = URIRef(BASE[f"node/{node['id']}"])
        assert (subject, RDF.type, SD.Node) in partition
        assert (subject, SD.stableId, Literal(node["id"])) in partition
        assert (subject, RDFS.label, Literal(node["label"])) in partition
        assert (subject, SD.kind, Literal(node["kind"])) in partition
        assert (
            subject,
            SD.resolution,
            Literal(str(node["resolution"]), datatype=XSD_INTEGER),
        ) in partition
        assert (subject, DCTERMS.description, Literal(node["summary"])) in partition
        assert (subject, SD.context, Literal(node["context"])) in partition
        assert (subject, SD.documentationLink, None) in partition
        for doc in node["docs"]:
            assert (subject, SD.documentationLink, URIRef(doc["url"])) in partition
        for note in node.get("hardening", []):
            assert (subject, SD.hardeningNote, Literal(note)) in partition
        for alias in node.get("aliases", []):
            assert (subject, SD.alias, Literal(alias)) in partition
        for tag in node.get("tags", []):
            assert (subject, SD.tag, Literal(tag)) in partition

    for edge in seed["edges"]:
        partition = dataset.graph(URIRef(BASE[f"graph/{edge['status']}"]))
        subject = URIRef(BASE[f"edge/{edge['id']}"])
        assert (subject, RDF.type, SD.Edge) in partition
        assert (subject, SD.source, URIRef(BASE[f"node/{edge['source']}"])) in partition
        assert (subject, SD.target, URIRef(BASE[f"node/{edge['target']}"])) in partition
        assert (subject, SD.relation, Literal(edge["relation"])) in partition
        assert (subject, SD.layer, URIRef(BASE[f"layer/{edge['layer']}"])) in partition
        assert (
            subject,
            SD.resolution,
            Literal(str(edge["resolution"]), datatype=XSD_INTEGER),
        ) in partition
        assert (subject, SD.status, Literal(edge["status"])) in partition
        assert (
            subject,
            SD.confidence,
            Literal(str(edge["confidence"]), datatype=XSD_DECIMAL),
        ) in partition
        assert (subject, DCTERMS.description, Literal(edge["summary"])) in partition
        for doc in edge["docs"]:
            assert (subject, SD.documentationLink, URIRef(doc["url"])) in partition

    provenance = dataset.graph(URIRef(BASE["graph/provenance"]))
    activity = URIRef(BASE["activity/materialize-v1"])
    assert (activity, RDF.type, PROV.Activity) in provenance
    assert (activity, PROV.used, Literal("system-dynamics-map.seed.json")) in provenance
    assert (activity, PROV.generated, Literal("system-dynamics-map.canonical.trig")) in provenance
    assert (activity, PROV.generated, Literal("system-dynamics-map.shacl.ttl")) in provenance
    assert (
        activity,
        PROV.generated,
        Literal("system-dynamics-map.view-manifest.json"),
    ) in provenance
    assert (
        activity,
        PROV.wasAssociatedWith,
        Literal("scripts/system_dynamics_map_materialize.py"),
    ) in provenance

    for shape, target_class in (
        (SD.NodeShape, SD.Node),
        (SD.EdgeShape, SD.Edge),
        (SD.RenderedViewShape, SD.RenderedView),
        (SD.ProvenanceActivityShape, PROV.Activity),
    ):
        assert (shape, RDF.type, SH.NodeShape) in shapes
        assert (shape, SH.targetClass, target_class) in shapes

    for path, datatype, node_kind in (
        (SD.stableId, XSD_STRING, None),
        (RDFS.label, XSD_STRING, None),
        (SD.kind, XSD_STRING, None),
        (SD.layer, None, SH.IRI),
        (SD.resolution, XSD_INTEGER, None),
        (SD.status, XSD_STRING, None),
        (DCTERMS.description, XSD_STRING, None),
        (SD.context, XSD_STRING, None),
        (SD.documentationLink, None, SH.IRI),
    ):
        _assert_shape_property(shapes, SD.NodeShape, path, datatype=datatype, node_kind=node_kind)

    for path, datatype, node_kind in (
        (SD.stableId, XSD_STRING, None),
        (SD.source, None, SH.IRI),
        (SD.target, None, SH.IRI),
        (SD.relation, XSD_STRING, None),
        (SD.layer, None, SH.IRI),
        (SD.resolution, XSD_INTEGER, None),
        (SD.status, XSD_STRING, None),
        (SD.confidence, XSD_DECIMAL, None),
        (DCTERMS.description, XSD_STRING, None),
        (SD.documentationLink, None, SH.IRI),
    ):
        _assert_shape_property(shapes, SD.EdgeShape, path, datatype=datatype, node_kind=node_kind)

    for path, datatype, node_kind in (
        (SD.sourceMap, None, SH.IRI),
        (SD.viewer, XSD_STRING, None),
        (SD.viewManifest, XSD_STRING, None),
    ):
        _assert_shape_property(
            shapes, SD.RenderedViewShape, path, datatype=datatype, node_kind=node_kind
        )

    for path in (PROV.used, PROV.generated, PROV.wasAssociatedWith):
        _assert_shape_property(shapes, SD.ProvenanceActivityShape, path)

    for path in (SD.hardeningNote, SD.alias, SD.tag):
        property_shape = _shape_property(shapes, SD.NodeShape, path)
        assert (property_shape, SH.datatype, XSD_STRING) in shapes


def test_shacl_shapes_and_view_manifest_cover_the_durable_contract():
    seed = _load_seed()
    shapes = SHACL_PATH.read_text(encoding="utf-8")
    for token in (
        "sd:NodeShape",
        "sd:EdgeShape",
        "sd:RenderedViewShape",
        "sd:ProvenanceActivityShape",
    ):
        assert token in shapes, (
            f"{SHACL_PATH}: missing {token}. Fix by regenerating the SHACL shape file."
        )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema"] == "system-dynamics-map-view-manifest-v1"
    assert manifest["source_snapshot"]["node_count"] == EXPECTED_NODE_COUNT
    assert manifest["source_snapshot"]["edge_count"] == EXPECTED_EDGE_COUNT
    assert manifest["claim_partitions"] == seed["status_kinds"]
    assert manifest["default_projection"]["runtime_asset"] == "vendor/cytoscape-3.34.0.min.js"
    assert manifest["default_projection"]["runtime_asset_sri"] == materialize._sha384_sri(
        VENDOR_PATH
    )
    assert (
        manifest["validation"]["browser"]
        == "uv run --extra ci pytest tests/test_system_dynamics_map_viewer_playwright.py"
    )
    assert manifest["provenance"] == {
        "activity": "https://hapax.local/system-dynamics-map/v0/activity/materialize-v1",
        "agent": "scripts/system_dynamics_map_materialize.py",
        "generated": [
            "system-dynamics-map.canonical.trig",
            "system-dynamics-map.shacl.ttl",
            "system-dynamics-map.view-manifest.json",
        ],
        "used": ["system-dynamics-map.seed.json"],
    }

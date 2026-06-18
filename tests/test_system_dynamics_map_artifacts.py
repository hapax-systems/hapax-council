import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
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
CLAIMS_PATH = ARCHITECTURE_DIR / "system-dynamics-map.claims.json"
OBSERVATIONS_PATH = ARCHITECTURE_DIR / "system-dynamics-map.observations.jsonl"
LENSES_PATH = ARCHITECTURE_DIR / "system-dynamics-map.lenses.json"
RELATIONS_PATH = ARCHITECTURE_DIR / "system-dynamics-map.relations.json"
PACKAGE_PATH = ARCHITECTURE_DIR / "system-dynamics-map.package.json"
LOCK_PATH = ARCHITECTURE_DIR / "system-dynamics-map.lock.json"
DOC_PATH = ARCHITECTURE_DIR / "system-dynamics-map-v1.md"
SDLC_FIXTURE_PATH = (
    ARCHITECTURE_DIR / "fixtures" / "system-dynamics-map" / "sdlc-operating-slice.json"
)
SCHEMA_DIR = REPO_ROOT / "schemas" / "system-dynamics-map"
EXPECTED_NODE_COUNT = 35
EXPECTED_EDGE_COUNT = 42
EXPECTED_LAYER_IDS = {
    "source-models",
    "decision-modeling",
    "execution-surfaces",
    "semantic-backbone",
    "observation-state",
    "projection",
}
BASE = Namespace("https://hapax.local/system-dynamics-map/v1/")
SD = Namespace("https://hapax.local/ns/system-dynamics-map#")
SH = Namespace("http://www.w3.org/ns/shacl#")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
XSD_STRING = URIRef("http://www.w3.org/2001/XMLSchema#string")
XSD_INTEGER = URIRef("http://www.w3.org/2001/XMLSchema#integer")
XSD_DECIMAL = URIRef("http://www.w3.org/2001/XMLSchema#decimal")
XSD_DATETIME = URIRef("http://www.w3.org/2001/XMLSchema#dateTime")


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


def _embedded_viewer_json(block_id: str) -> object:
    html = VIEWER_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf'<script type="application/json" id="{re.escape(block_id)}">\s*(.*?)\s*</script>',
        html,
        re.S,
    )
    assert match, (
        f"viewer must include embedded {block_id}. "
        "Fix by restoring the supplemental data script tag or removing direct-open claims."
    )
    return json.loads(match.group(1))


def _load_observations() -> list[dict]:
    return [
        json.loads(line)
        for line in OBSERVATIONS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _contract_error_text(
    *,
    seed: dict | None = None,
    relation_vocabulary: dict | None = None,
    claims: dict | None = None,
    observations: list[dict] | None = None,
    lenses: dict | None = None,
) -> str:
    return "\n".join(
        materialize._contract_errors(
            seed or _load_seed(),
            relation_vocabulary=relation_vocabulary,
            claims=claims,
            observations=observations,
            lenses=lenses,
        )
    )


def _schema_errors(instance: object, schema: dict) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [error.message for error in sorted(validator.iter_errors(instance), key=str)]


def _assert_schema_valid(instance: object, schema: dict) -> None:
    errors = _schema_errors(instance, schema)
    assert not errors, "schema validation failed:\n" + "\n".join(errors)


def _shape_property(shapes: Graph, shape: URIRef, path: URIRef):
    for property_shape in shapes.objects(shape, SH.property):
        if (property_shape, SH.path, path) in shapes:
            return property_shape
    raise AssertionError(
        f"{SHACL_PATH}: {shape} missing property path {path}. "
        "Fix by regenerating the SHACL artifact from the seed contract."
    )


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


def test_viewer_embedded_supplemental_data_matches_canonical_artifacts():
    assert _embedded_viewer_json("claims-data") == json.loads(
        CLAIMS_PATH.read_text(encoding="utf-8")
    ), (
        "embedded viewer claims fallback drifted from system-dynamics-map.claims.json. "
        "Fix by regenerating the claims-data script block from the canonical claims file."
    )
    assert _embedded_viewer_json("lenses-data") == json.loads(
        LENSES_PATH.read_text(encoding="utf-8")
    ), (
        "embedded viewer lenses fallback drifted from system-dynamics-map.lenses.json. "
        "Fix by regenerating the lenses-data script block from the canonical lenses file."
    )
    assert _embedded_viewer_json("observations-data") == _load_observations(), (
        "embedded viewer observations fallback drifted from system-dynamics-map.observations.jsonl. "
        "Fix by regenerating the observations-data script block from the canonical observations file."
    )
    assert _embedded_viewer_json("relations-data") == json.loads(
        RELATIONS_PATH.read_text(encoding="utf-8")
    ), (
        "embedded viewer relation fallback drifted from system-dynamics-map.relations.json. "
        "Fix by regenerating the relations-data script block from the canonical relation vocabulary."
    )


def test_system_dynamics_seed_graph_is_referentially_valid():
    for name, data in (("seed", _load_seed()), ("embedded", _load_viewer()[1])):
        assert "entrypoint" not in data, (
            f"{name}: graph contract reintroduced entrypoint. "
            "Fix by using default_focus for a neutral initial viewer focus."
        )
        node_ids = [node["id"] for node in data["nodes"]]
        edge_ids = [edge["id"] for edge in data["edges"]]
        assert len(node_ids) == EXPECTED_NODE_COUNT, (
            f"{name}: expected {EXPECTED_NODE_COUNT} nodes, found {len(node_ids)}. "
            "Fix by restoring the documented v1 graph shape or updating the count constant "
            "with the intentional graph change."
        )
        assert len(edge_ids) == EXPECTED_EDGE_COUNT, (
            f"{name}: expected {EXPECTED_EDGE_COUNT} edges, found {len(edge_ids)}. "
            "Fix by restoring the documented v1 graph shape or updating the count constant "
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
        assert layers == EXPECTED_LAYER_IDS, (
            f"{name}: layer IDs drifted from the source-neutral v1 contract. "
            "Fix by using source-models, decision-modeling, execution-surfaces, "
            "semantic-backbone, observation-state, and projection unless the v1 "
            "contract and tests are intentionally updated together."
        )
        assert data["default_focus"] == "rdf-owl-kg", (
            f"{name}: default focus must stay on the semantic backbone, not a source notation. "
            "Fix by setting default_focus to rdf-owl-kg."
        )
        assert data["default_focus"] in node_set, (
            f"{name}: default_focus does not name a node. "
            "Fix by adding the default_focus node or correcting default_focus."
        )
        for required_node in (
            "sdlc-intake",
            "cc-task-claim",
            "review-dossier",
            "pr-ci-checks",
            "merge-release",
            "operating-lens",
        ):
            assert required_node in node_set, (
                f"{name}: missing concrete SDLC operating-slice node {required_node}. "
                "Fix by preserving the v1 operating-slice fixture in the seed graph."
            )
        layer_labels = {layer["label"] for layer in data["layers"]}
        assert "DMN Layer" not in layer_labels, (
            f"{name}: layer labels still frame the map as DMN-centered. "
            "Fix by using source-neutral layer labels."
        )
        assert "Layer Up" not in layer_labels, (
            f"{name}: layer labels still describe topology relative to DMN. "
            "Fix by naming the actual source-model layer."
        )
        assert "Layer Down" not in layer_labels, (
            f"{name}: layer labels still describe topology relative to DMN. "
            "Fix by naming the actual execution/artifact layer."
        )
        for layer in data["layers"]:
            assert "above DMN" not in layer["description"], (
                f"{name}: layer {layer['id']} still describes itself as above DMN. "
                "Fix by describing its role in the source-neutral graph."
            )
            assert "below DMN" not in layer["description"], (
                f"{name}: layer {layer['id']} still describes itself as below DMN. "
                "Fix by describing its role in the source-neutral graph."
            )

        for node in data["nodes"]:
            assert node["layer"] in layers, (
                f"{name}: invalid node layer {node['id']}. "
                "Fix by using a declared layers[].id value."
            )
            assert node["status"] in statuses, (
                f"{name}: invalid node status {node['id']}. "
                "Fix by using a declared status_kinds value."
            )
            assert node["status"] != "observed", (
                f"{name}: node {node['id']} marks topology as observed. "
                "Fix by representing observed state in system-dynamics-map.observations.jsonl."
            )
            assert node.get("docs"), (
                f"{name}: node missing docs {node['id']}. Fix by adding at least one docs[] link."
            )
            assert "layer-up" not in node.get("tags", []), (
                f"{name}: node {node['id']} still uses a DMN-relative layer-up tag. "
                "Fix by replacing it with a neutral source-model tag."
            )
            assert "layer-down" not in node.get("tags", []), (
                f"{name}: node {node['id']} still uses a DMN-relative layer-down tag. "
                "Fix by replacing it with a neutral execution-surface tag."
            )
            if node["id"] == "dmn":
                assert "entrypoint" not in node.get("tags", []), (
                    f"{name}: DMN still carries the entrypoint tag. "
                    "Fix by keeping the graph default on default_focus and source-neutral backbone tags."
                )
                assert node["resolution"] > 1, (
                    f"{name}: DMN must not be the only overview/default-focus node. "
                    "Fix by keeping a neutral backbone node at overview resolution."
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
            assert edge["status"] != "observed", (
                f"{name}: edge {edge['id']} marks topology as observed. "
                "Fix by representing observed state in system-dynamics-map.observations.jsonl."
            )
            assert edge.get("relation"), (
                f"{name}: edge missing relation {edge['id']}. "
                "Fix by adding the relation field used by the viewer details panel."
            )
            assert "confidence" in edge, (
                f"{name}: edge missing confidence {edge['id']}. "
                "Fix by adding a numeric confidence value for the relation claim."
            )
            confidence = edge["confidence"]
            assert isinstance(confidence, int | float) and not isinstance(confidence, bool), (
                f"{name}: edge confidence is not numeric {edge['id']}. "
                "Fix by using a JSON number between 0 and 1."
            )
            assert 0 <= confidence <= 1, (
                f"{name}: edge confidence out of range {edge['id']}. "
                "Fix by using a confidence value between 0 and 1."
            )
            assert edge.get("docs"), (
                f"{name}: edge missing docs/evidence links {edge['id']}. "
                "Fix by adding at least one docs[] link for the relation source."
            )
            assert not (
                edge["target"] == "dmn"
                and edge["source"] in {"bpmn", "cmmn", "archimate", "sysml-v2"}
            ), (
                f"{name}: {edge['id']} recenters source-model context on DMN. "
                "Fix by mapping source models into the semantic backbone or a specific source cluster."
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
    assert "DMN is the entry point" not in html, (
        "viewer still contains DMN-entrypoint framing. "
        "Fix by describing the source-neutral semantic backbone as the default focus."
    )
    assert "seed.entrypoint" not in html, (
        "viewer still references the removed entrypoint contract. "
        "Fix by using seed.default_focus for initial selection and directed layout roots."
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
    for path in (SEED_PATH, VIEWER_PATH, DOC_PATH):
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
    viewer_path = tmp_path / "system-dynamics-map-viewer.html"
    vendor_path = tmp_path / "cytoscape-3.34.0.min.js"
    trig_path = tmp_path / "system-dynamics-map.canonical.trig"
    shacl_path = tmp_path / "system-dynamics-map.shacl.ttl"
    manifest_path = tmp_path / "system-dynamics-map.view-manifest.json"
    claims_path = tmp_path / "system-dynamics-map.claims.json"
    observations_path = tmp_path / "system-dynamics-map.observations.jsonl"
    lenses_path = tmp_path / "system-dynamics-map.lenses.json"
    relations_path = tmp_path / "system-dynamics-map.relations.json"
    package_path = tmp_path / "system-dynamics-map.package.json"
    lock_path = tmp_path / "system-dynamics-map.lock.json"
    fixture_path = tmp_path / "fixtures" / "system-dynamics-map" / "sdlc-operating-slice.json"
    schema_dir = tmp_path / "schemas"
    seed_path.write_text(SEED_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    viewer_path.write_text(VIEWER_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    vendor_path.write_bytes(VENDOR_PATH.read_bytes())

    monkeypatch.setattr(materialize, "SEED_PATH", seed_path)
    monkeypatch.setattr(materialize, "VIEWER_PATH", viewer_path)
    monkeypatch.setattr(materialize, "VENDOR_PATH", vendor_path)
    monkeypatch.setattr(materialize, "TRIG_PATH", trig_path)
    monkeypatch.setattr(materialize, "SHACL_PATH", shacl_path)
    monkeypatch.setattr(materialize, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(materialize, "CLAIMS_PATH", claims_path)
    monkeypatch.setattr(materialize, "OBSERVATIONS_PATH", observations_path)
    monkeypatch.setattr(materialize, "LENSES_PATH", lenses_path)
    monkeypatch.setattr(materialize, "RELATIONS_PATH", relations_path)
    monkeypatch.setattr(materialize, "PACKAGE_PATH", package_path)
    monkeypatch.setattr(materialize, "LOCK_PATH", lock_path)
    monkeypatch.setattr(materialize, "SDLC_FIXTURE_PATH", fixture_path)
    monkeypatch.setattr(materialize, "SEED_SCHEMA_PATH", schema_dir / "seed.schema.json")
    monkeypatch.setattr(materialize, "CLAIM_SCHEMA_PATH", schema_dir / "claim-fragment.schema.json")
    monkeypatch.setattr(
        materialize, "OBSERVATION_SCHEMA_PATH", schema_dir / "observation.schema.json"
    )
    monkeypatch.setattr(materialize, "LENS_SCHEMA_PATH", schema_dir / "lens.schema.json")
    monkeypatch.setattr(
        materialize, "RELATION_SCHEMA_PATH", schema_dir / "relation-vocabulary.schema.json"
    )
    monkeypatch.setattr(
        materialize, "VIEW_MANIFEST_SCHEMA_PATH", schema_dir / "view-manifest.schema.json"
    )
    monkeypatch.setattr(materialize, "PACKAGE_SCHEMA_PATH", schema_dir / "package.schema.json")

    materialize.write_artifacts()
    for path in (
        trig_path,
        shacl_path,
        manifest_path,
        claims_path,
        observations_path,
        lenses_path,
        relations_path,
        package_path,
        lock_path,
        fixture_path,
        schema_dir / "seed.schema.json",
    ):
        assert path.exists()
    assert materialize.check_artifacts() == []

    trig_path.write_text("stale\n", encoding="utf-8")
    assert any("stale" in error for error in materialize.check_artifacts())
    shacl_path.unlink()
    errors = materialize.check_artifacts()
    assert any("stale" in error for error in errors)
    assert any("missing" in error for error in errors)


def test_materializer_reports_next_action_for_missing_embedded_viewer_block(tmp_path, monkeypatch):
    viewer_path = tmp_path / "system-dynamics-map-viewer.html"
    viewer_path.write_text(
        VIEWER_PATH.read_text(encoding="utf-8").replace(
            'id="claims-data"', 'id="missing-claims-data"', 1
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(materialize, "VIEWER_PATH", viewer_path)

    with pytest.raises(RuntimeError, match="Fix by restoring the supplemental JSON script tag"):
        materialize.generate_viewer(_load_seed())


def test_contract_rejects_invalid_relation_and_orphan_edge():
    seed = copy.deepcopy(_load_seed())
    seed["edges"][0]["relation"] = "not_declared_by_relation_vocabulary"
    relation_vocabulary = materialize.generate_relation_vocabulary(_load_seed())
    assert "undeclared relation" in _contract_error_text(
        seed=seed,
        relation_vocabulary=relation_vocabulary,
    )

    seed = copy.deepcopy(_load_seed())
    seed["edges"][0]["target"] = "missing-node"
    errors = _contract_error_text(seed=seed)
    assert "missing target" in errors


def test_contract_rejects_missing_claim_provenance():
    claims = materialize.generate_claims(_load_seed())
    claims["claims"][0]["provenance"].pop("source_hash")
    errors = _contract_error_text(claims=claims)
    assert "provenance missing source_hash" in errors


def test_contract_rejects_duplicate_slug_collisions_and_unsafe_docs():
    seed = copy.deepcopy(_load_seed())
    seed["nodes"][0]["id"] = "same value"
    seed["nodes"][1]["id"] = "same/value"
    seed["nodes"][2]["docs"][0]["url"] = "javascript:alert(1)"
    errors = _contract_error_text(seed=seed)
    assert "slug collision" in errors
    assert "unsafe documentation URL" in errors


def test_contract_rejects_invalid_observation_temporal_state():
    observations = materialize.generate_observations(_load_seed())
    observations[0]["valid_time"]["to"] = "2026-06-17T00:00:00Z"
    observations[1]["expires_at"] = observations[1]["transaction_time"]
    observations[1]["freshness"] = "fresh"
    observations[2]["expires_at"] = "2026-06-19T00:00:00Z"
    observations[2]["freshness"] = "stale"
    errors = _contract_error_text(observations=observations)
    assert "invalid valid_time interval" in errors
    assert "fresh observation is expired" in errors
    assert "stale observation expires after transaction_time" in errors
    assert "Fix by setting valid_time.to after valid_time.from or null." in errors
    assert "Fix by setting expires_at after transaction_time" in errors
    assert "Fix by setting expires_at at or before transaction_time" in errors


def test_contract_rejects_schema_required_lens_fields_and_hidden_endpoints():
    lenses = materialize.generate_lenses(_load_seed())
    topology = next(lens for lens in lenses["lenses"] if lens["id"] == "topology")
    topology.pop("visible_statuses")
    topology["visible_node_ids"].remove("dmn")
    topology["visible_edge_ids"] = ["dmn-to-drd"]
    errors = _contract_error_text(lenses=lenses)
    assert "missing required fields visible_statuses" in errors
    assert "Fix by regenerating the artifact or adding the required contract fields." in errors
    assert "visible edge dmn-to-drd has hidden endpoint" in errors


def test_generated_schemas_validate_artifacts_and_reject_bad_shapes():
    schemas = materialize.generate_schema_artifacts()
    seed_schema = json.loads(schemas[materialize.SEED_SCHEMA_PATH])
    claim_schema = json.loads(schemas[materialize.CLAIM_SCHEMA_PATH])
    observation_schema = json.loads(schemas[materialize.OBSERVATION_SCHEMA_PATH])
    lens_schema = json.loads(schemas[materialize.LENS_SCHEMA_PATH])
    relation_schema = json.loads(schemas[materialize.RELATION_SCHEMA_PATH])
    view_manifest_schema = json.loads(schemas[materialize.VIEW_MANIFEST_SCHEMA_PATH])
    package_schema = json.loads(schemas[materialize.PACKAGE_SCHEMA_PATH])

    assert lens_schema["required"] == materialize.LENS_REQUIRED
    assert package_schema["title"] == "System dynamics package"

    _assert_schema_valid(_load_seed(), seed_schema)
    for claim in json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))["claims"]:
        _assert_schema_valid(claim, claim_schema)
    for observation in _load_observations():
        _assert_schema_valid(observation, observation_schema)
    for lens in json.loads(LENSES_PATH.read_text(encoding="utf-8"))["lenses"]:
        _assert_schema_valid(lens, lens_schema)
    _assert_schema_valid(json.loads(RELATIONS_PATH.read_text(encoding="utf-8")), relation_schema)
    _assert_schema_valid(
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")), view_manifest_schema
    )
    _assert_schema_valid(json.loads(PACKAGE_PATH.read_text(encoding="utf-8")), package_schema)

    bad_claim = copy.deepcopy(json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))["claims"][0])
    bad_claim["provenance"] = "not-an-object"
    bad_claim["confidence_basis"]["score"] = 2
    assert _schema_errors(bad_claim, claim_schema)

    bad_observation = copy.deepcopy(_load_observations()[0])
    bad_observation["freshness"] = "forever"
    bad_observation["valid_time"] = "not-an-object"
    assert _schema_errors(bad_observation, observation_schema)

    bad_lens = copy.deepcopy(json.loads(LENSES_PATH.read_text(encoding="utf-8"))["lenses"][0])
    bad_lens["visible_statuses"] = ["not-a-status"]
    bad_lens["max_resolution"] = 0
    bad_lens.pop("hidden_node_ids")
    bad_lens.pop("hidden_edge_ids")
    bad_lens.pop("state_mode")
    bad_lens.pop("source_snapshot")
    bad_lens.pop("validation_status")
    lens_errors = "\n".join(_schema_errors(bad_lens, lens_schema))
    assert "not-a-status" in lens_errors
    assert "hidden_node_ids" in lens_errors
    assert "hidden_edge_ids" in lens_errors
    assert "state_mode" in lens_errors
    assert "source_snapshot" in lens_errors
    assert "validation_status" in lens_errors

    bad_relations = copy.deepcopy(json.loads(RELATIONS_PATH.read_text(encoding="utf-8")))
    bad_relations["relations"][0].pop("source_kinds")
    bad_relations["relations"][0].pop("target_kinds")
    bad_relations["relations"][0].pop("allowed_claim_types")
    relation_errors = "\n".join(_schema_errors(bad_relations, relation_schema))
    assert "source_kinds" in relation_errors
    assert "target_kinds" in relation_errors
    assert "allowed_claim_types" in relation_errors

    bad_manifest = copy.deepcopy(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    bad_manifest["source_snapshot"] = {}
    bad_manifest["default_projection"] = {}
    bad_manifest["provenance"] = {}
    bad_manifest.pop("claim_contract")
    bad_manifest.pop("lenses")
    bad_manifest.pop("validation")
    manifest_errors = "\n".join(_schema_errors(bad_manifest, view_manifest_schema))
    assert "seed_sha256" in manifest_errors
    assert "visible_node_ids" in manifest_errors
    assert "hidden_node_ids" in manifest_errors
    assert "claim_contract" in manifest_errors
    assert "lenses" in manifest_errors
    assert "validation" in manifest_errors
    assert "generated" in manifest_errors

    bad_package = copy.deepcopy(json.loads(PACKAGE_PATH.read_text(encoding="utf-8")))
    bad_package["artifacts"][0]["sha256"] = "not-a-sha"
    bad_package["git_sha_role"] = "final_head"
    assert _schema_errors(bad_package, package_schema)


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
    for graph_name in (*seed["status_kinds"], "claims", "provenance"):
        assert str(BASE[f"graph/{graph_name}"]) in graph_ids, (
            f"{TRIG_PATH}: missing parseable named graph {graph_name}. "
            "Fix by regenerating the canonical TriG artifact."
        )

    asserted = dataset.graph(URIRef(BASE["graph/asserted"]))
    assert (URIRef(BASE["map"]), RDF.type, SD.SystemDynamicsMap) in asserted
    assert (
        URIRef(BASE["map"]),
        SD.defaultFocus,
        URIRef(BASE[f"node/{seed['default_focus']}"]),
    ) in asserted
    for node in seed["nodes"]:
        partition = dataset.graph(URIRef(BASE[f"graph/{node['status']}"]))
        subject = URIRef(BASE[f"node/{node['id']}"])
        assert (subject, RDF.type, SD.Node) in partition
        assert (subject, SD.stableId, Literal(node["id"])) in partition
        assert (subject, RDFS.label, Literal(node["label"])) in partition
        assert (subject, SD.kind, Literal(node["kind"])) in partition
        assert (subject, SD.layer, URIRef(BASE[f"layer/{node['layer']}"])) in partition
        assert (
            subject,
            SD.resolution,
            Literal(str(node["resolution"]), datatype=XSD_INTEGER),
        ) in partition
        assert (subject, SD.status, Literal(node["status"])) in partition
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

    observed = dataset.graph(URIRef(BASE["graph/observed"]))
    claims_graph = dataset.graph(URIRef(BASE["graph/claims"]))
    assert (None, RDF.type, SD.Observation) in observed
    assert (None, RDF.type, SD.Claim) in claims_graph
    assert len(list(claims_graph.triples((None, RDF.type, SD.Claim)))) == (
        EXPECTED_NODE_COUNT + EXPECTED_EDGE_COUNT
    )

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
        (SD.ClaimShape, SD.Claim),
        (SD.ObservationShape, SD.Observation),
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

    for path, datatype in (
        (SD.stableId, XSD_STRING),
        (SD.claimType, XSD_STRING),
        (SD.claimSubject, XSD_STRING),
        (SD.claimPredicate, XSD_STRING),
        (SD.claimObject, XSD_STRING),
        (SD.confidence, XSD_DECIMAL),
        (SD.confidenceBasis, XSD_STRING),
        (SD.validFrom, XSD_DATETIME),
        (SD.transactionTime, XSD_DATETIME),
        (SD.freshness, XSD_STRING),
        (SD.contradictionState, XSD_STRING),
    ):
        _assert_shape_property(shapes, SD.ClaimShape, path, datatype=datatype)

    for path, datatype, node_kind in (
        (SD.stableId, XSD_STRING, None),
        (SD.observationSubject, None, SH.IRI),
        (SD.state, XSD_STRING, None),
        (SD.observedAt, XSD_DATETIME, None),
        (SD.validFrom, XSD_DATETIME, None),
        (SD.transactionTime, XSD_DATETIME, None),
        (SD.freshness, XSD_STRING, None),
    ):
        _assert_shape_property(
            shapes, SD.ObservationShape, path, datatype=datatype, node_kind=node_kind
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
        "sd:ClaimShape",
        "sd:ObservationShape",
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
    assert manifest["claim_contract"] == {
        "claim_count": EXPECTED_NODE_COUNT + EXPECTED_EDGE_COUNT,
        "claims": "system-dynamics-map.claims.json",
        "observation_count": len(_load_observations()),
        "relation_count": len(json.loads(RELATIONS_PATH.read_text(encoding="utf-8"))["relations"]),
    }
    assert manifest["default_projection"]["default_focus"] == seed["default_focus"]
    assert manifest["default_projection"]["lens"] == "topology"
    assert manifest["default_projection"]["runtime_asset"] == "vendor/cytoscape-3.34.0.min.js"
    assert manifest["default_projection"]["runtime_asset_sri"] == materialize._sha384_sri(
        VENDOR_PATH
    )
    assert (
        manifest["validation"]["browser"]
        == "uv run --extra ci pytest tests/test_system_dynamics_map_viewer_playwright.py"
    )
    assert manifest["provenance"] == {
        "activity": "https://hapax.local/system-dynamics-map/v1/activity/materialize-v1",
        "agent": "scripts/system_dynamics_map_materialize.py",
        "generated": [
            "system-dynamics-map.canonical.trig",
            "system-dynamics-map.shacl.ttl",
            "system-dynamics-map.view-manifest.json",
            "system-dynamics-map.claims.json",
            "system-dynamics-map.package.json",
            "system-dynamics-map.lock.json",
        ],
        "used": [
            "system-dynamics-map.seed.json",
            "system-dynamics-map.relations.json",
            "system-dynamics-map.observations.jsonl",
            "system-dynamics-map.lenses.json",
        ],
    }


def test_v1_contract_artifacts_cover_claims_observations_lenses_and_package():
    seed = _load_seed()
    node_ids = {node["id"] for node in seed["nodes"]}
    edge_ids = {edge["id"] for edge in seed["edges"]}
    relation_ids = {edge["relation"] for edge in seed["edges"]}

    relations = json.loads(RELATIONS_PATH.read_text(encoding="utf-8"))
    assert relations["schema"] == "system-dynamics-map-relation-vocabulary-v1"
    assert {relation["id"] for relation in relations["relations"]} == relation_ids
    assert all(relation["directionality"] == "directed" for relation in relations["relations"])

    claims = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    assert claims["schema"] == "system-dynamics-map-claims-v1"
    assert len(claims["claims"]) == EXPECTED_NODE_COUNT + EXPECTED_EDGE_COUNT
    for claim in claims["claims"]:
        assert claim["provenance"]["source_hash"]
        assert claim["valid_time"]["from"]
        assert claim["transaction_time"]
        assert 0 <= claim["confidence_basis"]["score"] <= 1
        assert claim["contradiction_state"] == "none"

    observations = _load_observations()
    assert {item["subject"] for item in observations} <= node_ids
    assert any(item["freshness"] == "stale" for item in observations)
    assert all(item["observed_at"] and item["source_hash"] for item in observations)

    lenses = json.loads(LENSES_PATH.read_text(encoding="utf-8"))
    assert lenses["schema"] == "system-dynamics-map-lenses-v1"
    assert lenses["default_lens"] == "topology"
    assert {lens["id"] for lens in lenses["lenses"]} == {
        "topology",
        "operating-slice",
        "evidence-risk",
    }
    operating = next(lens for lens in lenses["lenses"] if lens["id"] == "operating-slice")
    assert set(operating["visible_node_ids"]) >= {
        "sdlc-intake",
        "cc-task-claim",
        "review-dossier",
        "pr-ci-checks",
        "merge-release",
    }
    for lens in lenses["lenses"]:
        assert set(lens["visible_node_ids"]) <= node_ids
        assert set(lens["visible_edge_ids"]) <= edge_ids
        visible = set(lens["visible_node_ids"])
        for edge in seed["edges"]:
            if edge["id"] in set(lens["visible_edge_ids"]):
                assert edge["source"] in visible and edge["target"] in visible

    package = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert package["schema"] == "system-dynamics-map-package-v1"
    assert lock["schema"] == "system-dynamics-map-lock-v1"
    assert package["git_sha_role"] == "generation_head"
    assert lock["git_sha_role"] == "generation_head"
    assert "content hashes are the staleness key" in package["git_sha_policy"]
    assert "PR history carries commit provenance" in package["git_sha_policy"]
    assert "self-referential future commit SHA" in lock["staleness_policy"]
    assert package["git_sha"] == "unknown"
    assert lock["git_sha"] == "unknown"
    package_paths = {artifact["path"] for artifact in package["artifacts"]}
    for required in (
        "docs/architecture/system-dynamics-map.claims.json",
        "docs/architecture/system-dynamics-map.observations.jsonl",
        "docs/architecture/system-dynamics-map.lenses.json",
        "docs/architecture/system-dynamics-map.relations.json",
        "schemas/system-dynamics-map/claim-fragment.schema.json",
    ):
        assert required in package_paths
    assert lock["source_hashes"]["seed"] == materialize._sha256(SEED_PATH)

    package_with_new_generation_head = copy.deepcopy(package)
    package_with_new_generation_head["git_sha"] = "0" * 40
    assert materialize._normalise_for_check(PACKAGE_PATH, json.dumps(package)) == (
        materialize._normalise_for_check(PACKAGE_PATH, json.dumps(package_with_new_generation_head))
    )
    lock_with_new_generation_head = copy.deepcopy(lock)
    lock_with_new_generation_head["git_sha"] = "0" * 40
    assert materialize._normalise_for_check(LOCK_PATH, json.dumps(lock)) == (
        materialize._normalise_for_check(LOCK_PATH, json.dumps(lock_with_new_generation_head))
    )

    fixture = json.loads(SDLC_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["schema"] == "system-dynamics-map-sdlc-operating-slice-fixture-v1"
    assert len(fixture["operator_questions"]) >= 5

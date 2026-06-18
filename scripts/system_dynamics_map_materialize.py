#!/usr/bin/env python3
"""Materialize durable system-dynamics map artifacts from the seed JSON."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"
SEED_PATH = ARCHITECTURE_DIR / "system-dynamics-map.seed.json"
VIEWER_PATH = ARCHITECTURE_DIR / "system-dynamics-map-viewer.html"
VENDOR_PATH = ARCHITECTURE_DIR / "vendor" / "cytoscape-3.34.0.min.js"
TRIG_PATH = ARCHITECTURE_DIR / "system-dynamics-map.canonical.trig"
SHACL_PATH = ARCHITECTURE_DIR / "system-dynamics-map.shacl.ttl"
MANIFEST_PATH = ARCHITECTURE_DIR / "system-dynamics-map.view-manifest.json"
BASE_IRI = "https://hapax.local/system-dynamics-map/v0/"
SD_IRI = "https://hapax.local/ns/system-dynamics-map#"


def _load_seed() -> dict[str, Any]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _stable_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.~-]+", "-", value.strip())
    return slug.strip("-") or "unnamed"


def _iri(path: str) -> str:
    return f"<{BASE_IRI}{path}>"


def _literal(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def _decimal(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=True) + "^^xsd:decimal"


def _integer(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=True) + "^^xsd:integer"


def _date_time(value: str) -> str:
    return json.dumps(value, ensure_ascii=True) + "^^xsd:dateTime"


def _doc_iris(docs: list[dict[str, str]]) -> str:
    return ", ".join(f"<{doc['url']}>" for doc in docs)


def _statement(subject: str, pairs: list[tuple[str, str]]) -> str:
    lines = [f"{subject}"]
    for index, (predicate, value) in enumerate(pairs):
        suffix = " ." if index == len(pairs) - 1 else " ;"
        lines.append(f"  {predicate} {value}{suffix}")
    return "\n".join(lines)


def _node_statement(node: dict[str, Any]) -> str:
    pairs = [
        ("a", "sd:Node"),
        ("sd:stableId", _literal(node["id"])),
        ("rdfs:label", _literal(node["label"])),
        ("sd:kind", _literal(node["kind"])),
        ("sd:layer", _iri(f"layer/{_stable_slug(node['layer'])}")),
        ("sd:resolution", _integer(node["resolution"])),
        ("sd:status", _literal(node["status"])),
        ("dcterms:description", _literal(node["summary"])),
        ("sd:context", _literal(node["context"])),
        ("sd:documentationLink", _doc_iris(node["docs"])),
    ]
    pairs.extend(("sd:hardeningNote", _literal(note)) for note in node.get("hardening", []))
    pairs.extend(("sd:alias", _literal(alias)) for alias in node.get("aliases", []))
    pairs.extend(("sd:tag", _literal(tag)) for tag in node.get("tags", []))
    return _statement(
        _iri(f"node/{_stable_slug(node['id'])}"),
        pairs,
    )


def _edge_statement(edge: dict[str, Any]) -> str:
    return _statement(
        _iri(f"edge/{_stable_slug(edge['id'])}"),
        [
            ("a", "sd:Edge"),
            ("sd:stableId", _literal(edge["id"])),
            ("sd:source", _iri(f"node/{_stable_slug(edge['source'])}")),
            ("sd:target", _iri(f"node/{_stable_slug(edge['target'])}")),
            ("sd:relation", _literal(edge["relation"])),
            ("sd:layer", _iri(f"layer/{_stable_slug(edge['layer'])}")),
            ("sd:resolution", _integer(edge["resolution"])),
            ("sd:status", _literal(edge["status"])),
            ("sd:confidence", _decimal(edge["confidence"])),
            ("dcterms:description", _literal(edge["summary"])),
            ("sd:documentationLink", _doc_iris(edge["docs"])),
        ],
    )


def _claim_partition_statement(status: str) -> str:
    return _statement(
        _iri(f"partition/{_stable_slug(status)}"),
        [
            ("a", "sd:ClaimPartition"),
            ("sd:status", _literal(status)),
            ("sd:namedGraph", _iri(f"graph/{_stable_slug(status)}")),
        ],
    )


def generate_trig(seed: dict[str, Any]) -> str:
    lines = [
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        f"@prefix sd: <{SD_IRI}> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"{_iri('graph/asserted')} {{",
        _statement(
            _iri("map"),
            [
                ("a", "sd:SystemDynamicsMap"),
                ("sd:mapId", _literal(seed["map_id"])),
                ("sd:version", _literal(seed["version"])),
                ("sd:entrypoint", _iri(f"node/{_stable_slug(seed['entrypoint'])}")),
                ("sd:nodeCount", _integer(len(seed["nodes"]))),
                ("sd:edgeCount", _integer(len(seed["edges"]))),
                ("dcterms:description", _literal(seed["thesis"])),
                ("prov:generatedAtTime", _date_time(seed["generated_at"])),
            ],
        ),
    ]

    for layer in seed["layers"]:
        lines.append("")
        lines.append(
            _statement(
                _iri(f"layer/{_stable_slug(layer['id'])}"),
                [
                    ("a", "sd:Layer"),
                    ("sd:stableId", _literal(layer["id"])),
                    ("rdfs:label", _literal(layer["label"])),
                    ("dcterms:description", _literal(layer["description"])),
                ],
            )
        )

    for scale in seed["view_scales"]:
        lines.append("")
        lines.append(
            _statement(
                _iri(f"scale/{_stable_slug(scale['id'])}"),
                [
                    ("a", "sd:ViewScale"),
                    ("sd:stableId", _literal(scale["id"])),
                    ("sd:resolution", _integer(scale["resolution"])),
                    ("rdfs:label", _literal(scale["label"])),
                    ("dcterms:description", _literal(scale["description"])),
                ],
            )
        )

    lines.append("")
    lines.append(_claim_partition_statement("asserted"))
    for node in seed["nodes"]:
        if node["status"] == "asserted":
            lines.append("")
            lines.append(_node_statement(node))
    for edge in seed["edges"]:
        if edge["status"] == "asserted":
            lines.append("")
            lines.append(_edge_statement(edge))
    lines.append("}")
    lines.append("")

    for status in seed["status_kinds"]:
        if status == "asserted":
            continue
        lines.append(f"{_iri(f'graph/{_stable_slug(status)}')} {{")
        lines.append(_claim_partition_statement(status))
        for node in seed["nodes"]:
            if node["status"] == status:
                lines.append("")
                lines.append(_node_statement(node))
        for edge in seed["edges"]:
            if edge["status"] == status:
                lines.append("")
                lines.append(_edge_statement(edge))
        if status == "rendered":
            lines.append("")
            lines.append(
                _statement(
                    _iri("view/system-dynamics-map-viewer"),
                    [
                        ("a", "sd:RenderedView"),
                        ("sd:sourceMap", _iri("map")),
                        ("sd:viewer", _literal("system-dynamics-map-viewer.html")),
                        (
                            "sd:viewManifest",
                            _literal("system-dynamics-map.view-manifest.json"),
                        ),
                        ("sd:layoutEngine", _literal("Cytoscape.js 3.34.0")),
                    ],
                )
            )
        lines.append("}")
        lines.append("")

    lines.extend(
        [
            f"{_iri('graph/provenance')} {{",
            _statement(
                _iri("activity/materialize-v1"),
                [
                    ("a", "prov:Activity"),
                    ("prov:used", _literal("system-dynamics-map.seed.json")),
                    ("prov:generated", _literal("system-dynamics-map.canonical.trig")),
                    ("prov:generated", _literal("system-dynamics-map.shacl.ttl")),
                    ("prov:generated", _literal("system-dynamics-map.view-manifest.json")),
                    (
                        "prov:wasAssociatedWith",
                        _literal("scripts/system_dynamics_map_materialize.py"),
                    ),
                    ("prov:generatedAtTime", _date_time(seed["generated_at"])),
                ],
            ),
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def generate_shacl() -> str:
    return """@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sd: <https://hapax.local/ns/system-dynamics-map#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

sd:NodeShape
  a sh:NodeShape ;
  sh:targetClass sd:Node ;
  sh:property [ sh:path sd:stableId ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path rdfs:label ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:kind ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:layer ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path sd:resolution ; sh:minCount 1 ; sh:datatype xsd:integer ] ;
  sh:property [ sh:path sd:status ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path dcterms:description ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:context ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:documentationLink ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path sd:hardeningNote ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:alias ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:tag ; sh:datatype xsd:string ] .

sd:EdgeShape
  a sh:NodeShape ;
  sh:targetClass sd:Edge ;
  sh:property [ sh:path sd:stableId ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:source ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path sd:target ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path sd:relation ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:layer ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path sd:resolution ; sh:minCount 1 ; sh:datatype xsd:integer ] ;
  sh:property [ sh:path sd:status ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:confidence ; sh:minCount 1 ; sh:datatype xsd:decimal ] ;
  sh:property [ sh:path dcterms:description ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:documentationLink ; sh:minCount 1 ; sh:nodeKind sh:IRI ] .

sd:RenderedViewShape
  a sh:NodeShape ;
  sh:targetClass sd:RenderedView ;
  sh:property [ sh:path sd:sourceMap ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path sd:viewer ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:viewManifest ; sh:minCount 1 ; sh:datatype xsd:string ] .

sd:ProvenanceActivityShape
  a sh:NodeShape ;
  sh:targetClass prov:Activity ;
  sh:property [ sh:path prov:used ; sh:minCount 1 ] ;
  sh:property [ sh:path prov:generated ; sh:minCount 1 ] ;
  sh:property [ sh:path prov:wasAssociatedWith ; sh:minCount 1 ] .
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha384_sri(path: Path) -> str:
    digest = hashlib.sha384(path.read_bytes()).digest()
    return "sha384-" + base64.b64encode(digest).decode("ascii")


def generate_manifest(seed: dict[str, Any]) -> str:
    manifest = {
        "schema": "system-dynamics-map-view-manifest-v1",
        "map_id": seed["map_id"],
        "version": seed["version"],
        "authority_case": seed["authority_case"],
        "generated_at": seed["generated_at"],
        "source_snapshot": {
            "seed": "system-dynamics-map.seed.json",
            "seed_sha256": _sha256(SEED_PATH),
            "canonical_graph": "system-dynamics-map.canonical.trig",
            "shacl_shapes": "system-dynamics-map.shacl.ttl",
            "node_count": len(seed["nodes"]),
            "edge_count": len(seed["edges"]),
        },
        "claim_partitions": seed["status_kinds"],
        "default_projection": {
            "viewer": "system-dynamics-map-viewer.html",
            "runtime_asset": "vendor/cytoscape-3.34.0.min.js",
            "runtime_asset_sri": _sha384_sri(VENDOR_PATH),
            "layout": "cose",
            "entrypoint": seed["entrypoint"],
            "resolution": 5,
            "visible_layers": [layer["id"] for layer in seed["layers"]],
            "visible_statuses": seed["status_kinds"],
        },
        "provenance": {
            "activity": f"{BASE_IRI}activity/materialize-v1",
            "agent": "scripts/system_dynamics_map_materialize.py",
            "used": ["system-dynamics-map.seed.json"],
            "generated": [
                "system-dynamics-map.canonical.trig",
                "system-dynamics-map.shacl.ttl",
                "system-dynamics-map.view-manifest.json",
            ],
        },
        "validation": {
            "pytest": "uv run pytest tests/test_system_dynamics_map_artifacts.py",
            "browser": "uv run --extra ci pytest tests/test_system_dynamics_map_viewer_playwright.py",
        },
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def rendered_artifacts() -> dict[Path, str]:
    seed = _load_seed()
    return {
        TRIG_PATH: generate_trig(seed),
        SHACL_PATH: generate_shacl(),
        MANIFEST_PATH: generate_manifest(seed),
    }


def write_artifacts() -> None:
    for path, content in rendered_artifacts().items():
        path.write_text(content, encoding="utf-8")


def check_artifacts() -> list[str]:
    errors: list[str] = []
    for path, expected in rendered_artifacts().items():
        if not path.exists():
            errors.append(
                f"{path}: missing. Fix by running scripts/system_dynamics_map_materialize.py."
            )
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            errors.append(
                f"{path}: stale. Fix by running scripts/system_dynamics_map_materialize.py."
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if generated artifacts are stale"
    )
    args = parser.parse_args()

    if args.check:
        errors = check_artifacts()
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("system dynamics map artifacts are current")
        return 0

    write_artifacts()
    for path in rendered_artifacts():
        print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

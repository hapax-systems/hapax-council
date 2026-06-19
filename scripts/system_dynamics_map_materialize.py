#!/usr/bin/env python3
"""Materialize durable system-dynamics map artifacts from the seed JSON."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
FIXTURE_DIR = ARCHITECTURE_DIR / "fixtures" / "system-dynamics-map"
SDLC_FIXTURE_PATH = FIXTURE_DIR / "sdlc-operating-slice.json"
SCHEMA_DIR = REPO_ROOT / "schemas" / "system-dynamics-map"
SEED_SCHEMA_PATH = SCHEMA_DIR / "seed.schema.json"
CLAIM_SCHEMA_PATH = SCHEMA_DIR / "claim-fragment.schema.json"
OBSERVATION_SCHEMA_PATH = SCHEMA_DIR / "observation.schema.json"
LENS_SCHEMA_PATH = SCHEMA_DIR / "lens.schema.json"
RELATION_SCHEMA_PATH = SCHEMA_DIR / "relation-vocabulary.schema.json"
VIEW_MANIFEST_SCHEMA_PATH = SCHEMA_DIR / "view-manifest.schema.json"
PACKAGE_SCHEMA_PATH = SCHEMA_DIR / "package.schema.json"
BASE_IRI = "https://hapax.local/system-dynamics-map/v1/"
SD_IRI = "https://hapax.local/ns/system-dynamics-map#"
GENERATED_PATHS = (
    TRIG_PATH,
    SHACL_PATH,
    MANIFEST_PATH,
    CLAIMS_PATH,
    OBSERVATIONS_PATH,
    LENSES_PATH,
    RELATIONS_PATH,
    PACKAGE_PATH,
    LOCK_PATH,
    SDLC_FIXTURE_PATH,
    SEED_SCHEMA_PATH,
    CLAIM_SCHEMA_PATH,
    OBSERVATION_SCHEMA_PATH,
    LENS_SCHEMA_PATH,
    RELATION_SCHEMA_PATH,
    VIEW_MANIFEST_SCHEMA_PATH,
    PACKAGE_SCHEMA_PATH,
)
GENERATED_NAMES = {path.name for path in GENERATED_PATHS}
OBSERVED_AT = "2026-06-18T14:56:02Z"
DEFAULT_VALID_FROM = "2026-06-18T00:00:00Z"
FRESH_EXPIRES_AT = "2030-01-01T00:00:00Z"
STALE_EXPIRES_AT = "2026-06-18T01:00:00Z"
STATUS_KINDS = ["asserted", "inferred", "observed", "simulated", "rendered", "candidate"]
OBSERVATION_FRESHNESS = ["fresh", "stale", "historical"]
CLAIM_FRESHNESS = ["timeless", *OBSERVATION_FRESHNESS]
SEED_REQUIRED = [
    "map_id",
    "version",
    "generated_at",
    "authority_case",
    "default_focus",
    "nodes",
    "edges",
]
CLAIM_REQUIRED = [
    "id",
    "claim_type",
    "subject",
    "predicate",
    "object",
    "provenance",
    "valid_time",
    "transaction_time",
    "confidence_basis",
    "freshness",
    "contradiction_state",
]
OBSERVATION_REQUIRED = [
    "id",
    "subject",
    "state",
    "observed_at",
    "valid_time",
    "transaction_time",
    "expires_at",
    "freshness",
    "source_ref",
    "source_hash",
]
LENS_REQUIRED = [
    "id",
    "label",
    "visible_layers",
    "visible_statuses",
    "max_resolution",
    "layout",
    "state_mode",
    "visible_node_ids",
    "visible_edge_ids",
    "hidden_node_ids",
    "hidden_edge_ids",
    "validation_status",
    "source_snapshot",
    "aggregation",
]
RELATION_VOCABULARY_REQUIRED = ["schema", "relations"]
VIEW_MANIFEST_REQUIRED = [
    "schema",
    "map_id",
    "version",
    "source_snapshot",
    "default_projection",
    "claim_contract",
    "workbench_contract",
    "lenses",
    "validation",
    "provenance",
]
PACKAGE_REQUIRED = [
    "schema",
    "map_id",
    "version",
    "artifacts",
    "validation",
    "git_sha",
    "git_sha_role",
]


def _load_seed() -> dict[str, Any]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _git_sha() -> str:
    return "unknown"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def _date_time_or_none(value: str | None) -> str | None:
    return None if value is None else _date_time(value)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _source_ref_hash(source_ref: str) -> str:
    if source_ref.startswith("docs/") or source_ref.startswith("scripts/"):
        candidate = REPO_ROOT / source_ref
        if candidate.exists():
            return _sha256(candidate)
    return _sha256_text(source_ref)


def _safe_url(url: str) -> bool:
    if any(char.isspace() for char in url):
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _claim_type(status: str) -> str:
    if status in {"asserted", "candidate", "rendered", "inferred", "simulated"}:
        return status
    return "asserted"


def _relation_category(relation: str) -> str:
    if any(token in relation for token in ("telemetry", "trace", "observ", "event")):
        return "observational"
    if any(token in relation for token in ("render", "project", "view")):
        return "projection"
    if any(token in relation for token in ("compiled", "runtime", "api", "deploy")):
        return "execution"
    if any(token in relation for token in ("future", "candidate")):
        return "roadmap"
    if any(token in relation for token in ("advances", "admits", "guards", "produces")):
        return "governance"
    return "structural"


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


def generate_relation_vocabulary(seed: dict[str, Any]) -> dict[str, Any]:
    node_by_id = {node["id"]: node for node in seed["nodes"]}
    relations: list[dict[str, Any]] = []
    for relation_id in sorted({edge["relation"] for edge in seed["edges"]}):
        edges = [edge for edge in seed["edges"] if edge["relation"] == relation_id]
        source_kinds = sorted({node_by_id[edge["source"]]["kind"] for edge in edges})
        target_kinds = sorted({node_by_id[edge["target"]]["kind"] for edge in edges})
        relations.append(
            {
                "id": relation_id,
                "iri": f"{SD_IRI}relation/{_stable_slug(relation_id)}",
                "label": relation_id.replace("_", " ").title(),
                "category": _relation_category(relation_id),
                "directionality": "directed",
                "source_kinds": source_kinds,
                "target_kinds": target_kinds,
                "layers": sorted({edge["layer"] for edge in edges}),
                "allowed_claim_types": sorted({_claim_type(edge["status"]) for edge in edges}),
                "edge_ids": sorted(edge["id"] for edge in edges),
                "semantics": (
                    "Declared relation vocabulary entry generated from curated seed edges. "
                    "Review before using it as an adapter emission contract."
                ),
            }
        )
    return {
        "schema": "system-dynamics-map-relation-vocabulary-v1",
        "map_id": seed["map_id"],
        "version": seed["version"],
        "generated_at": seed["generated_at"],
        "relations": relations,
    }


def _claim_provenance(seed_hash: str, pointer: str) -> dict[str, Any]:
    return {
        "source_ref": f"system-dynamics-map.seed.json{pointer}",
        "source_hash": seed_hash,
        "source_type": "manual_seed",
        "agent": "scripts/system_dynamics_map_materialize.py",
        "activity": "seed_claim_projection",
        "authority_ceiling": "architecture_contract",
    }


def generate_claims(seed: dict[str, Any]) -> dict[str, Any]:
    seed_hash = _sha256(SEED_PATH)
    claims: list[dict[str, Any]] = []
    for index, node in enumerate(seed["nodes"]):
        claims.append(
            {
                "id": f"claim-node-{_stable_slug(node['id'])}",
                "claim_type": _claim_type(node["status"]),
                "subject": node["id"],
                "predicate": "declares_node",
                "object": node["kind"],
                "element_id": node["id"],
                "element_kind": "node",
                "confidence_basis": {
                    "method": "curated_seed",
                    "score": 1.0 if node["status"] == "asserted" else 0.75,
                    "directness": "curated architecture source",
                    "recency": "seed generation timestamp",
                },
                "valid_time": {"from": DEFAULT_VALID_FROM, "to": None},
                "transaction_time": seed["generated_at"],
                "freshness": {"state": "timeless", "expires_at": None},
                "contradiction_state": "none",
                "provenance": _claim_provenance(seed_hash, f"#/nodes/{index}"),
            }
        )
    for index, edge in enumerate(seed["edges"]):
        claims.append(
            {
                "id": f"claim-edge-{_stable_slug(edge['id'])}",
                "claim_type": _claim_type(edge["status"]),
                "subject": edge["source"],
                "predicate": edge["relation"],
                "object": edge["target"],
                "element_id": edge["id"],
                "element_kind": "edge",
                "confidence_basis": {
                    "method": "curated_seed_edge",
                    "score": edge["confidence"],
                    "directness": "source documentation plus architecture judgment",
                    "recency": "seed generation timestamp",
                },
                "valid_time": {"from": DEFAULT_VALID_FROM, "to": None},
                "transaction_time": seed["generated_at"],
                "freshness": {"state": "timeless", "expires_at": None},
                "contradiction_state": "none",
                "provenance": _claim_provenance(seed_hash, f"#/edges/{index}"),
            }
        )
    return {
        "schema": "system-dynamics-map-claims-v1",
        "map_id": seed["map_id"],
        "version": seed["version"],
        "generated_at": seed["generated_at"],
        "claims": claims,
    }


def generate_sdlc_fixture(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "system-dynamics-map-sdlc-operating-slice-fixture-v1",
        "slice_id": "hapax-sdlc-intake-review-release",
        "generated_at": seed["generated_at"],
        "purpose": (
            "Concrete operating slice used to prove the map can represent topology, "
            "state, evidence, and release readiness without centering a source notation."
        ),
        "operator_questions": [
            "why is this work stuck?",
            "what changed since the prior snapshot?",
            "which evidence supports this state?",
            "which observations are stale?",
            "which path gates release readiness?",
        ],
        "instances": [
            {
                "id": "sdlc-intake",
                "role": "intake",
                "source_ref": "docs/architecture/system-dynamics-map-v1.md",
            },
            {
                "id": "cc-task-claim",
                "role": "claim",
                "source_ref": "scripts/cc-claim",
            },
            {
                "id": "review-dossier",
                "role": "review",
                "source_ref": "scripts/review_team.py",
            },
            {
                "id": "pr-ci-checks",
                "role": "release_signal",
                "source_ref": "https://github.com/hapax-systems/hapax-council/pull/4179",
            },
            {
                "id": "merge-release",
                "role": "closure",
                "source_ref": "https://github.com/hapax-systems/hapax-council/commit/1522faae8212ddbc63da64140a12f86117f30c2d",
            },
        ],
    }


def generate_workbench_contract(seed: dict[str, Any]) -> dict[str, Any]:
    _ = seed
    return {
        "schema": "system-dynamics-map-workbench-contract-v1",
        "purpose": (
            "Question-first sensemaking and explanation contract for rendering topology, "
            "state, evidence, projection scope, and trust caveats without centering any "
            "single source notation."
        ),
        "inquiry_modes": [
            {
                "id": "release-gates",
                "label": "What gates release?",
                "answer_shape": [
                    "ordered gate path",
                    "first non-ready state",
                    "evidence basis",
                    "scope caveat",
                ],
            },
            {
                "id": "stuck-work",
                "label": "What is stuck?",
                "answer_shape": [
                    "first waiting or blocking state",
                    "upstream context",
                    "downstream consequence",
                    "supporting observation",
                ],
            },
            {
                "id": "changed",
                "label": "What changed?",
                "answer_shape": [
                    "snapshot identity",
                    "prior snapshot requirement",
                    "current export basis",
                    "diff-tranche caveat",
                ],
            },
            {
                "id": "stale-evidence",
                "label": "What is stale?",
                "answer_shape": [
                    "visible stale evidence",
                    "hidden stale evidence",
                    "expiry basis",
                    "state/topology separation",
                ],
            },
            {
                "id": "trust",
                "label": "What do I trust?",
                "answer_shape": [
                    "confidence basis",
                    "authority ceiling",
                    "candidate elements",
                    "contradiction readiness",
                ],
            },
            {
                "id": "missing-context",
                "label": "What am I missing?",
                "answer_shape": [
                    "hidden nodes",
                    "hidden edges",
                    "aggregation/lossiness",
                    "invalid conclusions",
                ],
            },
        ],
        "audience_modes": [
            "operator",
            "newcomer",
            "collaborator",
            "reviewer",
            "executive",
        ],
        "explanation_paths": [
            {
                "id": "release-readiness",
                "scene_count": 5,
                "must_include": [
                    "source-neutral identity",
                    "temporal state separation",
                    "gate path",
                    "trust basis",
                    "what this does not prove",
                ],
            },
            {
                "id": "evidence-trust",
                "scene_count": 3,
                "must_include": [
                    "explicit claim records",
                    "validation before trust",
                    "stale evidence visibility",
                ],
            },
        ],
        "follow_on_tranches": [
            "bitemporal snapshot registry and diff lens",
            "causality, guard, evidence, correlation, containment, and projection relation semantics",
            "uncertainty classes, contradiction groups, competing evidence, and confidence basis categories",
            "source adapter provenance chains and verification receipts",
            "visible invariant registry and aggregation/lossiness ledger",
        ],
    }


def _observation(
    *,
    observation_id: str,
    subject: str,
    state: str,
    source_ref: str,
    observed_at: str,
    valid_from: str,
    valid_to: str | None,
    expires_at: str | None,
    freshness: str,
    evidence_label: str,
) -> dict[str, Any]:
    return {
        "id": observation_id,
        "subject": subject,
        "state": state,
        "observed_at": observed_at,
        "valid_time": {"from": valid_from, "to": valid_to},
        "transaction_time": OBSERVED_AT,
        "expires_at": expires_at,
        "freshness": freshness,
        "source_ref": source_ref,
        "source_hash": _source_ref_hash(source_ref),
        "source_type": "fixture" if source_ref.startswith("docs/") else "external_evidence",
        "evidence": [
            {
                "label": evidence_label,
                "url": source_ref if source_ref.startswith("https://") else None,
            }
        ],
    }


def generate_observations(seed: dict[str, Any]) -> list[dict[str, Any]]:
    _ = seed
    return [
        _observation(
            observation_id="obs-sdlc-intake-offered",
            subject="sdlc-intake",
            state="offered",
            source_ref="docs/architecture/system-dynamics-map-v1.md",
            observed_at=OBSERVED_AT,
            valid_from=OBSERVED_AT,
            valid_to=None,
            expires_at=FRESH_EXPIRES_AT,
            freshness="fresh",
            evidence_label="v1 enhancement task intake",
        ),
        _observation(
            observation_id="obs-cc-task-claimed",
            subject="cc-task-claim",
            state="claimed",
            source_ref="scripts/cc-claim",
            observed_at=OBSERVED_AT,
            valid_from=OBSERVED_AT,
            valid_to=None,
            expires_at=FRESH_EXPIRES_AT,
            freshness="fresh",
            evidence_label="claim gate script",
        ),
        _observation(
            observation_id="obs-review-pending",
            subject="review-dossier",
            state="pending",
            source_ref="scripts/review_team.py",
            observed_at=OBSERVED_AT,
            valid_from=OBSERVED_AT,
            valid_to=None,
            expires_at=FRESH_EXPIRES_AT,
            freshness="fresh",
            evidence_label="review team script",
        ),
        _observation(
            observation_id="obs-pr-ci-not-open",
            subject="pr-ci-checks",
            state="not_open",
            source_ref="https://github.com/hapax-systems/hapax-council/pull/4179",
            observed_at=OBSERVED_AT,
            valid_from=OBSERVED_AT,
            valid_to=None,
            expires_at=FRESH_EXPIRES_AT,
            freshness="fresh",
            evidence_label="prior landed PR as slice reference",
        ),
        _observation(
            observation_id="obs-release-not-ready",
            subject="merge-release",
            state="not_released",
            source_ref="https://github.com/hapax-systems/hapax-council/commit/1522faae8212ddbc63da64140a12f86117f30c2d",
            observed_at=OBSERVED_AT,
            valid_from=OBSERVED_AT,
            valid_to=None,
            expires_at=FRESH_EXPIRES_AT,
            freshness="fresh",
            evidence_label="prior merge commit as release evidence reference",
        ),
        _observation(
            observation_id="obs-view-manifest-stale-fixture",
            subject="view-manifest",
            state="stale_fixture",
            source_ref="docs/architecture/system-dynamics-map.seed.json",
            observed_at=DEFAULT_VALID_FROM,
            valid_from=DEFAULT_VALID_FROM,
            valid_to=STALE_EXPIRES_AT,
            expires_at=STALE_EXPIRES_AT,
            freshness="stale",
            evidence_label="stale observation canary",
        ),
    ]


def generate_observations_jsonl(seed: dict[str, Any]) -> str:
    return (
        "\n".join(json.dumps(item, sort_keys=True) for item in generate_observations(seed)) + "\n"
    )


def _visible_by_lens(seed: dict[str, Any], lens: dict[str, Any]) -> tuple[list[str], list[str]]:
    node_ids = {node["id"] for node in seed["nodes"]}
    explicit = set(lens.get("focus_node_ids") or [])
    if explicit:
        visible_nodes = sorted(node_ids & explicit)
    else:
        layers = set(lens["visible_layers"])
        statuses = set(lens["visible_statuses"])
        visible_nodes = sorted(
            node["id"]
            for node in seed["nodes"]
            if node["layer"] in layers
            and node["status"] in statuses
            and int(node["resolution"]) <= int(lens["max_resolution"])
        )
    visible_node_set = set(visible_nodes)
    visible_edges = sorted(
        edge["id"]
        for edge in seed["edges"]
        if edge["source"] in visible_node_set
        and edge["target"] in visible_node_set
        and edge["layer"] in set(lens["visible_layers"])
        and edge["status"] in set(lens["visible_statuses"])
        and int(edge["resolution"]) <= int(lens["max_resolution"])
    )
    return visible_nodes, visible_edges


def generate_lenses(seed: dict[str, Any]) -> dict[str, Any]:
    layers = [layer["id"] for layer in seed["layers"]]
    statuses = list(seed["status_kinds"])
    lens_specs = [
        {
            "id": "topology",
            "label": "Topology",
            "description": "Source-neutral topology and modeling context.",
            "visible_layers": layers,
            "visible_statuses": [status for status in statuses if status != "observed"],
            "max_resolution": 5,
            "layout": "cose",
            "state_mode": "topology",
            "aggregation": {"mode": "none", "lossy": False, "reversible": True},
        },
        {
            "id": "operating-slice",
            "label": "Operating Slice",
            "description": "SDLC intake, claim, review, PR/CI, and release evidence path.",
            "visible_layers": [
                "observation-state",
                "semantic-backbone",
                "execution-surfaces",
                "projection",
            ],
            "visible_statuses": ["asserted", "rendered"],
            "max_resolution": 5,
            "layout": "breadthfirst",
            "state_mode": "observed",
            "focus_node_ids": [
                "temporal-state-events",
                "prov-o",
                "sdlc-intake",
                "cc-task-claim",
                "review-dossier",
                "pr-ci-checks",
                "merge-release",
                "operating-lens",
            ],
            "aggregation": {"mode": "path", "lossy": False, "reversible": True},
        },
        {
            "id": "evidence-risk",
            "label": "Evidence Risk",
            "description": "Provenance, validation, rendered views, and stale observation cues.",
            "visible_layers": ["semantic-backbone", "observation-state", "projection"],
            "visible_statuses": statuses,
            "max_resolution": 5,
            "layout": "cose",
            "state_mode": "evidence",
            "focus_node_ids": [
                "rdf-owl-kg",
                "shacl-contracts",
                "prov-o",
                "temporal-state-events",
                "view-manifest",
                "operating-lens",
                "review-dossier",
            ],
            "aggregation": {"mode": "evidence", "lossy": False, "reversible": True},
        },
    ]
    lenses: list[dict[str, Any]] = []
    all_node_ids = {node["id"] for node in seed["nodes"]}
    all_edge_ids = {edge["id"] for edge in seed["edges"]}
    for lens in lens_specs:
        visible_nodes, visible_edges = _visible_by_lens(seed, lens)
        lens = {
            **lens,
            "visible_node_ids": visible_nodes,
            "hidden_node_ids": sorted(all_node_ids - set(visible_nodes)),
            "visible_edge_ids": visible_edges,
            "hidden_edge_ids": sorted(all_edge_ids - set(visible_edges)),
            "validation_status": "generated",
            "source_snapshot": "system-dynamics-map.seed.json",
        }
        lenses.append(lens)
    return {
        "schema": "system-dynamics-map-lenses-v1",
        "map_id": seed["map_id"],
        "version": seed["version"],
        "generated_at": seed["generated_at"],
        "default_lens": "topology",
        "lenses": lenses,
    }


def _schema_object(schema_id: str, title: str, required: list[str]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://hapax.local/schema/system-dynamics-map/{schema_id}",
        "title": title,
        "type": "object",
        "required": required,
        "additionalProperties": True,
    }


def _string_array_schema(*, enum: list[str] | None = None) -> dict[str, Any]:
    items: dict[str, Any] = {"type": "string"}
    if enum is not None:
        items["enum"] = enum
    return {"type": "array", "items": items}


def _nullable_datetime_schema() -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "string", "format": "date-time"},
            {"type": "null"},
        ]
    }


def _valid_time_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["from", "to"],
        "additionalProperties": True,
        "properties": {
            "from": {"type": "string", "format": "date-time"},
            "to": _nullable_datetime_schema(),
        },
    }


def _provenance_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "source_ref",
            "source_hash",
            "source_type",
            "agent",
            "activity",
            "authority_ceiling",
        ],
        "additionalProperties": True,
        "properties": {
            "source_ref": {"type": "string", "minLength": 1},
            "source_hash": {"type": "string", "minLength": 1},
            "source_type": {"type": "string", "minLength": 1},
            "agent": {"type": "string", "minLength": 1},
            "activity": {"type": "string", "minLength": 1},
            "authority_ceiling": {"type": "string", "minLength": 1},
        },
    }


def generate_schema_artifacts() -> dict[Path, str]:
    seed_schema = _schema_object("seed.schema.json", "System dynamics map seed", SEED_REQUIRED)
    seed_schema["properties"] = {
        "map_id": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "generated_at": {"type": "string", "format": "date-time"},
        "authority_case": {"type": "string", "minLength": 1},
        "default_focus": {"type": "string", "minLength": 1},
        "status_kinds": _string_array_schema(enum=STATUS_KINDS),
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "label", "kind", "layer", "resolution", "status", "docs"],
                "additionalProperties": True,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "minLength": 1},
                    "layer": {"type": "string", "minLength": 1},
                    "resolution": {"type": "integer", "minimum": 1},
                    "status": {"type": "string", "enum": STATUS_KINDS},
                    "docs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["label", "url"],
                            "properties": {
                                "label": {"type": "string", "minLength": 1},
                                "url": {"type": "string", "format": "uri"},
                            },
                        },
                    },
                },
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "source",
                    "target",
                    "relation",
                    "layer",
                    "resolution",
                    "status",
                    "confidence",
                    "docs",
                ],
                "additionalProperties": True,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "source": {"type": "string", "minLength": 1},
                    "target": {"type": "string", "minLength": 1},
                    "relation": {"type": "string", "minLength": 1},
                    "layer": {"type": "string", "minLength": 1},
                    "resolution": {"type": "integer", "minimum": 1},
                    "status": {"type": "string", "enum": STATUS_KINDS},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "docs": {"type": "array", "minItems": 1},
                },
            },
        },
    }

    claim_schema = _schema_object(
        "claim-fragment.schema.json", "System dynamics claim fragment", CLAIM_REQUIRED
    )
    claim_schema["properties"] = {
        "id": {"type": "string", "minLength": 1},
        "claim_type": {"type": "string", "enum": STATUS_KINDS},
        "subject": {"type": "string", "minLength": 1},
        "predicate": {"type": "string", "minLength": 1},
        "object": {"type": "string", "minLength": 1},
        "provenance": _provenance_schema(),
        "valid_time": _valid_time_schema(),
        "transaction_time": {"type": "string", "format": "date-time"},
        "confidence_basis": {
            "type": "object",
            "required": ["method", "score"],
            "additionalProperties": True,
            "properties": {
                "method": {"type": "string", "minLength": 1},
                "score": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
        "freshness": {
            "type": "object",
            "required": ["state", "expires_at"],
            "additionalProperties": True,
            "properties": {
                "state": {"type": "string", "enum": CLAIM_FRESHNESS},
                "expires_at": _nullable_datetime_schema(),
            },
        },
        "contradiction_state": {"type": "string", "minLength": 1},
    }

    observation_schema = _schema_object(
        "observation.schema.json", "System dynamics temporal observation", OBSERVATION_REQUIRED
    )
    observation_schema["properties"] = {
        "id": {"type": "string", "minLength": 1},
        "subject": {"type": "string", "minLength": 1},
        "state": {"type": "string", "minLength": 1},
        "observed_at": {"type": "string", "format": "date-time"},
        "valid_time": _valid_time_schema(),
        "transaction_time": {"type": "string", "format": "date-time"},
        "expires_at": _nullable_datetime_schema(),
        "freshness": {"type": "string", "enum": OBSERVATION_FRESHNESS},
        "source_ref": {"type": "string", "minLength": 1},
        "source_hash": {"type": "string", "minLength": 1},
    }

    lens_schema = _schema_object("lens.schema.json", "System dynamics map lens", LENS_REQUIRED)
    lens_schema["properties"] = {
        "id": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
        "visible_layers": _string_array_schema(),
        "visible_statuses": _string_array_schema(enum=STATUS_KINDS),
        "max_resolution": {"type": "integer", "minimum": 1},
        "layout": {"type": "string", "minLength": 1},
        "state_mode": {"type": "string", "minLength": 1},
        "visible_node_ids": _string_array_schema(),
        "visible_edge_ids": _string_array_schema(),
        "hidden_node_ids": _string_array_schema(),
        "hidden_edge_ids": _string_array_schema(),
        "validation_status": {"type": "string", "minLength": 1},
        "source_snapshot": {"type": "string", "minLength": 1},
        "aggregation": {
            "type": "object",
            "required": ["mode", "lossy", "reversible"],
            "properties": {
                "mode": {"type": "string", "minLength": 1},
                "lossy": {"type": "boolean"},
                "reversible": {"type": "boolean"},
            },
        },
    }

    relation_schema = _schema_object(
        "relation-vocabulary.schema.json",
        "System dynamics relation vocabulary",
        RELATION_VOCABULARY_REQUIRED,
    )
    relation_schema["properties"] = {
        "schema": {"type": "string", "const": "system-dynamics-map-relation-vocabulary-v1"},
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "iri",
                    "category",
                    "directionality",
                    "source_kinds",
                    "target_kinds",
                    "allowed_claim_types",
                    "layers",
                    "edge_ids",
                ],
                "additionalProperties": True,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "iri": {"type": "string", "format": "uri"},
                    "category": {"type": "string", "minLength": 1},
                    "directionality": {"type": "string", "enum": ["directed"]},
                    "source_kinds": _string_array_schema(),
                    "target_kinds": _string_array_schema(),
                    "allowed_claim_types": _string_array_schema(enum=STATUS_KINDS),
                    "layers": _string_array_schema(),
                    "edge_ids": _string_array_schema(),
                },
            },
        },
    }

    view_manifest_schema = _schema_object(
        "view-manifest.schema.json", "System dynamics view manifest", VIEW_MANIFEST_REQUIRED
    )
    view_manifest_schema["properties"] = {
        "schema": {"type": "string", "const": "system-dynamics-map-view-manifest-v1"},
        "map_id": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "source_snapshot": {
            "type": "object",
            "required": [
                "seed",
                "seed_sha256",
                "node_count",
                "edge_count",
                "canonical_graph",
                "claims",
                "observations",
                "relations",
                "lenses",
                "shacl_shapes",
            ],
            "additionalProperties": True,
            "properties": {
                "seed": {"type": "string", "minLength": 1},
                "seed_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "node_count": {"type": "integer", "minimum": 1},
                "edge_count": {"type": "integer", "minimum": 1},
                "canonical_graph": {"type": "string", "minLength": 1},
                "claims": {"type": "string", "minLength": 1},
                "observations": {"type": "string", "minLength": 1},
                "relations": {"type": "string", "minLength": 1},
                "lenses": {"type": "string", "minLength": 1},
                "shacl_shapes": {"type": "string", "minLength": 1},
            },
        },
        "default_projection": {
            "type": "object",
            "required": [
                "lens",
                "default_focus",
                "visible_node_ids",
                "hidden_node_ids",
                "visible_edge_ids",
                "hidden_edge_ids",
                "visible_layers",
                "visible_statuses",
                "layout",
                "resolution",
                "aggregation",
                "viewer",
                "runtime_asset",
                "runtime_asset_sri",
            ],
            "additionalProperties": True,
            "properties": {
                "lens": {"type": "string", "minLength": 1},
                "default_focus": {"type": "string", "minLength": 1},
                "visible_node_ids": _string_array_schema(),
                "hidden_node_ids": _string_array_schema(),
                "visible_edge_ids": _string_array_schema(),
                "hidden_edge_ids": _string_array_schema(),
                "visible_layers": _string_array_schema(),
                "visible_statuses": _string_array_schema(enum=STATUS_KINDS),
                "layout": {"type": "string", "minLength": 1},
                "resolution": {"type": "integer", "minimum": 1},
                "aggregation": {
                    "type": "object",
                    "required": ["mode", "lossy", "reversible"],
                },
                "viewer": {"type": "string", "minLength": 1},
                "runtime_asset": {"type": "string", "minLength": 1},
                "runtime_asset_sri": {"type": "string", "minLength": 1},
            },
        },
        "lenses": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "label",
                    "layout",
                    "state_mode",
                    "visible_node_count",
                    "visible_edge_count",
                    "aggregation",
                ],
                "additionalProperties": True,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "layout": {"type": "string", "minLength": 1},
                    "state_mode": {"type": "string", "minLength": 1},
                    "visible_node_count": {"type": "integer", "minimum": 0},
                    "visible_edge_count": {"type": "integer", "minimum": 0},
                    "aggregation": {"type": "object"},
                },
            },
        },
        "claim_contract": {
            "type": "object",
            "required": ["claim_count", "claims", "observation_count", "relation_count"],
        },
        "workbench_contract": {
            "type": "object",
            "required": [
                "schema",
                "purpose",
                "inquiry_modes",
                "audience_modes",
                "explanation_paths",
                "follow_on_tranches",
            ],
            "additionalProperties": True,
            "properties": {
                "schema": {
                    "type": "string",
                    "const": "system-dynamics-map-workbench-contract-v1",
                },
                "purpose": {"type": "string", "minLength": 1},
                "inquiry_modes": {
                    "type": "array",
                    "minItems": 6,
                    "items": {
                        "type": "object",
                        "required": ["id", "label", "answer_shape"],
                        "additionalProperties": True,
                        "properties": {
                            "id": {"type": "string", "minLength": 1},
                            "label": {"type": "string", "minLength": 1},
                            "answer_shape": _string_array_schema(),
                        },
                    },
                },
                "audience_modes": _string_array_schema(),
                "explanation_paths": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["id", "scene_count", "must_include"],
                        "additionalProperties": True,
                    },
                },
                "follow_on_tranches": _string_array_schema(),
            },
        },
        "validation": {
            "type": "object",
            "required": ["pytest", "browser", "package_gate"],
        },
        "provenance": {
            "type": "object",
            "required": ["activity", "agent", "generated", "used"],
            "properties": {
                "activity": {"type": "string", "format": "uri"},
                "agent": {"type": "string", "minLength": 1},
                "generated": _string_array_schema(),
                "used": _string_array_schema(),
            },
        },
    }

    package_schema = _schema_object(
        "package.schema.json", "System dynamics package", PACKAGE_REQUIRED
    )
    package_schema["properties"] = {
        "schema": {"type": "string", "const": "system-dynamics-map-package-v1"},
        "map_id": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "artifacts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "sha256", "bytes"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "bytes": {"type": "integer", "minimum": 0},
                },
            },
        },
        "validation": {"type": "object"},
        "git_sha": {"type": "string", "const": "unknown"},
        "git_sha_role": {"type": "string", "const": "not_recorded"},
    }

    schemas = {
        SEED_SCHEMA_PATH: seed_schema,
        CLAIM_SCHEMA_PATH: claim_schema,
        OBSERVATION_SCHEMA_PATH: observation_schema,
        LENS_SCHEMA_PATH: lens_schema,
        RELATION_SCHEMA_PATH: relation_schema,
        VIEW_MANIFEST_SCHEMA_PATH: view_manifest_schema,
        PACKAGE_SCHEMA_PATH: package_schema,
    }
    return {path: _json(schema) for path, schema in schemas.items()}


def _claim_partition_statement(status: str) -> str:
    return _statement(
        _iri(f"partition/{_stable_slug(status)}"),
        [
            ("a", "sd:ClaimPartition"),
            ("sd:status", _literal(status)),
            ("sd:namedGraph", _iri(f"graph/{_stable_slug(status)}")),
        ],
    )


def _claim_statement(claim: dict[str, Any]) -> str:
    pairs = [
        ("a", "sd:Claim"),
        ("sd:stableId", _literal(claim["id"])),
        ("sd:claimType", _literal(claim["claim_type"])),
        ("sd:claimSubject", _literal(claim["subject"])),
        ("sd:claimPredicate", _literal(claim["predicate"])),
        ("sd:claimObject", _literal(claim["object"])),
        ("sd:elementId", _literal(claim["element_id"])),
        ("sd:elementKind", _literal(claim["element_kind"])),
        ("sd:confidence", _decimal(claim["confidence_basis"]["score"])),
        ("sd:confidenceBasis", _literal(claim["confidence_basis"]["method"])),
        ("sd:validFrom", _date_time(claim["valid_time"]["from"])),
        ("sd:transactionTime", _date_time(claim["transaction_time"])),
        ("sd:freshness", _literal(claim["freshness"]["state"])),
        ("sd:contradictionState", _literal(claim["contradiction_state"])),
        ("prov:wasDerivedFrom", _literal(claim["provenance"]["source_ref"])),
        ("prov:wasAssociatedWith", _literal(claim["provenance"]["agent"])),
    ]
    valid_to = _date_time_or_none(claim["valid_time"]["to"])
    if valid_to is not None:
        pairs.append(("sd:validTo", valid_to))
    expires_at = _date_time_or_none(claim["freshness"]["expires_at"])
    if expires_at is not None:
        pairs.append(("sd:expiresAt", expires_at))
    return _statement(_iri(f"claim/{_stable_slug(claim['id'])}"), pairs)


def _observation_statement(observation: dict[str, Any]) -> str:
    pairs = [
        ("a", "sd:Observation"),
        ("sd:stableId", _literal(observation["id"])),
        ("sd:observationSubject", _iri(f"node/{_stable_slug(observation['subject'])}")),
        ("sd:state", _literal(observation["state"])),
        ("sd:observedAt", _date_time(observation["observed_at"])),
        ("sd:validFrom", _date_time(observation["valid_time"]["from"])),
        ("sd:transactionTime", _date_time(observation["transaction_time"])),
        ("sd:freshness", _literal(observation["freshness"])),
        ("prov:wasDerivedFrom", _literal(observation["source_ref"])),
    ]
    valid_to = _date_time_or_none(observation["valid_time"]["to"])
    if valid_to is not None:
        pairs.append(("sd:validTo", valid_to))
    expires_at = _date_time_or_none(observation["expires_at"])
    if expires_at is not None:
        pairs.append(("sd:expiresAt", expires_at))
    return _statement(_iri(f"observation/{_stable_slug(observation['id'])}"), pairs)


def generate_trig(seed: dict[str, Any]) -> str:
    claims = generate_claims(seed)["claims"]
    observations = generate_observations(seed)
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
                ("sd:defaultFocus", _iri(f"node/{_stable_slug(seed['default_focus'])}")),
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
        if status == "observed":
            for observation in observations:
                lines.append("")
                lines.append(_observation_statement(observation))
        lines.append("}")
        lines.append("")

    lines.append(f"{_iri('graph/claims')} {{")
    for claim in claims:
        lines.append("")
        lines.append(_claim_statement(claim))
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

sd:ClaimShape
  a sh:NodeShape ;
  sh:targetClass sd:Claim ;
  sh:property [ sh:path sd:stableId ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:claimType ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:claimSubject ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:claimPredicate ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:claimObject ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:confidence ; sh:minCount 1 ; sh:datatype xsd:decimal ] ;
  sh:property [ sh:path sd:confidenceBasis ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:validFrom ; sh:minCount 1 ; sh:datatype xsd:dateTime ] ;
  sh:property [ sh:path sd:transactionTime ; sh:minCount 1 ; sh:datatype xsd:dateTime ] ;
  sh:property [ sh:path sd:freshness ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:contradictionState ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path prov:wasDerivedFrom ; sh:minCount 1 ] ;
  sh:property [ sh:path prov:wasAssociatedWith ; sh:minCount 1 ] .

sd:ObservationShape
  a sh:NodeShape ;
  sh:targetClass sd:Observation ;
  sh:property [ sh:path sd:stableId ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:observationSubject ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path sd:state ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path sd:observedAt ; sh:minCount 1 ; sh:datatype xsd:dateTime ] ;
  sh:property [ sh:path sd:validFrom ; sh:minCount 1 ; sh:datatype xsd:dateTime ] ;
  sh:property [ sh:path sd:transactionTime ; sh:minCount 1 ; sh:datatype xsd:dateTime ] ;
  sh:property [ sh:path sd:freshness ; sh:minCount 1 ; sh:datatype xsd:string ] ;
  sh:property [ sh:path prov:wasDerivedFrom ; sh:minCount 1 ] .

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
    lenses = generate_lenses(seed)
    default_lens = next(item for item in lenses["lenses"] if item["id"] == lenses["default_lens"])
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
            "claims": "system-dynamics-map.claims.json",
            "observations": "system-dynamics-map.observations.jsonl",
            "relations": "system-dynamics-map.relations.json",
            "lenses": "system-dynamics-map.lenses.json",
            "node_count": len(seed["nodes"]),
            "edge_count": len(seed["edges"]),
        },
        "claim_partitions": seed["status_kinds"],
        "claim_contract": {
            "claims": "system-dynamics-map.claims.json",
            "claim_count": len(generate_claims(seed)["claims"]),
            "observation_count": len(generate_observations(seed)),
            "relation_count": len(generate_relation_vocabulary(seed)["relations"]),
        },
        "workbench_contract": generate_workbench_contract(seed),
        "default_projection": {
            "viewer": "system-dynamics-map-viewer.html",
            "runtime_asset": "vendor/cytoscape-3.34.0.min.js",
            "runtime_asset_sri": _sha384_sri(VENDOR_PATH),
            "layout": default_lens["layout"],
            "default_focus": seed["default_focus"],
            "lens": default_lens["id"],
            "resolution": default_lens["max_resolution"],
            "visible_layers": default_lens["visible_layers"],
            "visible_statuses": default_lens["visible_statuses"],
            "visible_node_ids": default_lens["visible_node_ids"],
            "hidden_node_ids": default_lens["hidden_node_ids"],
            "visible_edge_ids": default_lens["visible_edge_ids"],
            "hidden_edge_ids": default_lens["hidden_edge_ids"],
            "aggregation": default_lens["aggregation"],
        },
        "lenses": [
            {
                "id": lens["id"],
                "label": lens["label"],
                "layout": lens["layout"],
                "state_mode": lens["state_mode"],
                "visible_node_count": len(lens["visible_node_ids"]),
                "visible_edge_count": len(lens["visible_edge_ids"]),
                "aggregation": lens["aggregation"],
            }
            for lens in lenses["lenses"]
        ],
        "provenance": {
            "activity": f"{BASE_IRI}activity/materialize-v1",
            "agent": "scripts/system_dynamics_map_materialize.py",
            "used": [
                "system-dynamics-map.seed.json",
                "system-dynamics-map.relations.json",
                "system-dynamics-map.observations.jsonl",
                "system-dynamics-map.lenses.json",
            ],
            "generated": [
                "system-dynamics-map.canonical.trig",
                "system-dynamics-map.shacl.ttl",
                "system-dynamics-map.view-manifest.json",
                "system-dynamics-map.claims.json",
                "system-dynamics-map.package.json",
                "system-dynamics-map.lock.json",
            ],
        },
        "validation": {
            "pytest": "uv run pytest tests/test_system_dynamics_map_artifacts.py",
            "browser": "uv run --extra ci pytest tests/test_system_dynamics_map_viewer_playwright.py",
            "package_gate": "scripts/system-dynamics-map-gate",
        },
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _rendered_without_package(seed: dict[str, Any]) -> dict[Path, str]:
    rendered = {
        TRIG_PATH: generate_trig(seed),
        SHACL_PATH: generate_shacl(),
        MANIFEST_PATH: generate_manifest(seed),
        CLAIMS_PATH: _json(generate_claims(seed)),
        OBSERVATIONS_PATH: generate_observations_jsonl(seed),
        LENSES_PATH: _json(generate_lenses(seed)),
        RELATIONS_PATH: _json(generate_relation_vocabulary(seed)),
        SDLC_FIXTURE_PATH: _json(generate_sdlc_fixture(seed)),
    }
    rendered.update(generate_schema_artifacts())
    return rendered


def _artifact_entry(path: Path, content: str | None = None) -> dict[str, Any]:
    if content is None:
        digest = _sha256(path)
        size = path.stat().st_size
    else:
        digest = _sha256_text(content)
        size = len(content.encode("utf-8"))
    return {
        "path": _relative(path),
        "sha256": digest,
        "bytes": size,
    }


def generate_package(seed: dict[str, Any], rendered: dict[Path, str]) -> str:
    artifact_entries = [
        _artifact_entry(SEED_PATH),
        _artifact_entry(VIEWER_PATH, rendered.get(VIEWER_PATH)),
        _artifact_entry(VENDOR_PATH),
    ]
    artifact_entries.extend(
        _artifact_entry(path, rendered[path])
        for path in sorted(rendered, key=lambda item: _relative(item))
        if path not in {PACKAGE_PATH, LOCK_PATH, VIEWER_PATH}
    )
    package = {
        "schema": "system-dynamics-map-package-v1",
        "map_id": seed["map_id"],
        "version": seed["version"],
        "authority_case": seed["authority_case"],
        "generated_at": seed["generated_at"],
        "git_sha": _git_sha(),
        "git_sha_role": "not_recorded",
        "git_sha_policy": (
            "Committed artifacts intentionally record git_sha as unknown. Artifact "
            "commits cannot embed their own future commit SHA, so content hashes are "
            "the staleness key and PR history carries commit provenance."
        ),
        "generator": {
            "command": "python3 scripts/system_dynamics_map_materialize.py",
            "check_command": "python3 scripts/system_dynamics_map_materialize.py --check",
        },
        "artifacts": artifact_entries,
        "validation": {
            "seed_contract": "manual contract checks",
            "rdf_parse": "rdflib Dataset.parse(format='trig')",
            "shacl_parse": "rdflib Graph.parse(format='turtle')",
            "viewer_smoke": "uv run --extra ci pytest tests/test_system_dynamics_map_viewer_playwright.py",
            "package_gate": "scripts/system-dynamics-map-gate",
        },
    }
    return _json(package)


def generate_lock(seed: dict[str, Any], rendered: dict[Path, str], package_content: str) -> str:
    lock = {
        "schema": "system-dynamics-map-lock-v1",
        "map_id": seed["map_id"],
        "version": seed["version"],
        "generated_at": seed["generated_at"],
        "git_sha": _git_sha(),
        "git_sha_role": "not_recorded",
        "source_hashes": {
            "seed": _sha256(SEED_PATH),
            "viewer": _sha256_text(rendered[VIEWER_PATH]),
            "vendor": _sha256(VENDOR_PATH),
        },
        "generated_hashes": {
            _relative(path): _sha256_text(content)
            for path, content in sorted(rendered.items(), key=lambda item: _relative(item[0]))
            if path not in {PACKAGE_PATH, LOCK_PATH}
        },
        "package_hash": _sha256_text(package_content),
        "staleness_policy": (
            "Generated hashes must match rendered materializer output. git_sha is "
            "intentionally unknown and is not a staleness key because an artifact "
            "committed to Git cannot contain its own self-referential future commit "
            "SHA."
        ),
    }
    return _json(lock)


def generate_viewer(seed: dict[str, Any]) -> str:
    html = VIEWER_PATH.read_text(encoding="utf-8")
    embedded_blocks = {
        "seed-data": seed,
        "claims-data": generate_claims(seed),
        "lenses-data": generate_lenses(seed),
        "observations-data": generate_observations(seed),
        "relations-data": generate_relation_vocabulary(seed),
    }
    updated = html
    for block_id, payload in embedded_blocks.items():
        block_json = json.dumps(payload, indent=2, sort_keys=False)
        replacement = f'<script type="application/json" id="{block_id}">\n{block_json}\n  </script>'
        updated, replacements = re.subn(
            rf'<script type="application/json" id="{re.escape(block_id)}">\s*.*?\s*</script>',
            replacement,
            updated,
            count=1,
            flags=re.S,
        )
        if replacements != 1:
            raise RuntimeError(
                f"viewer {block_id} script tag not found. "
                "Fix by restoring the supplemental JSON script tag in "
                "system-dynamics-map-viewer.html before regenerating artifacts."
            )
    return updated


def _read_observations(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _slug_collision_errors(label: str, values: list[str]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for value in values:
        slug = _stable_slug(value)
        if slug in seen and seen[slug] != value:
            errors.append(
                f"{label}: slug collision {_stable_slug(value)!r} for {seen[slug]!r} and {value!r}. "
                "Fix by assigning collision-free stable IDs."
            )
        seen[slug] = value
    return errors


def _missing_required_errors(label: str, item: dict[str, Any], required: list[str]) -> list[str]:
    missing = [field for field in required if field not in item]
    if not missing:
        return []
    return [
        f"{label}: missing required fields {', '.join(missing)}. "
        "Fix by regenerating the artifact or adding the required contract fields."
    ]


def _contract_errors(
    seed: dict[str, Any],
    *,
    relation_vocabulary: dict[str, Any] | None = None,
    claims: dict[str, Any] | None = None,
    observations: list[dict[str, Any]] | None = None,
    lenses: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    node_ids = [node["id"] for node in seed.get("nodes", [])]
    edge_ids = [edge["id"] for edge in seed.get("edges", [])]
    layer_ids = [layer["id"] for layer in seed.get("layers", [])]
    statuses = set(seed.get("status_kinds", []))
    node_set = set(node_ids)
    edge_set = set(edge_ids)
    layer_set = set(layer_ids)

    errors.extend(_missing_required_errors("seed", seed, SEED_REQUIRED))
    if "entrypoint" in seed:
        errors.append("seed: entrypoint is not allowed. Fix by using source-neutral default_focus.")
    if seed.get("default_focus") not in node_set:
        errors.append(
            "seed: default_focus must name an existing node. "
            "Fix by setting default_focus to a stable nodes[].id."
        )
    for label, values in (("nodes", node_ids), ("edges", edge_ids), ("layers", layer_ids)):
        if len(values) != len(set(values)):
            errors.append(
                f"seed: duplicate {label} IDs. Fix by assigning each {label[:-1]} one ID."
            )
        errors.extend(_slug_collision_errors(label, values))

    for node in seed.get("nodes", []):
        if node.get("status") == "observed":
            errors.append(
                f"seed node {node['id']}: topology nodes must not be status=observed. "
                "Fix by moving observed state into system-dynamics-map.observations.jsonl."
            )
        if node.get("layer") not in layer_set:
            errors.append(
                f"seed node {node.get('id')}: undeclared layer {node.get('layer')!r}. "
                "Fix by using a declared layers[].id."
            )
        if node.get("status") not in statuses:
            errors.append(
                f"seed node {node.get('id')}: undeclared status {node.get('status')!r}. "
                "Fix by using a declared status_kinds[] value."
            )
        for doc in node.get("docs", []):
            if not _safe_url(doc.get("url", "")):
                errors.append(
                    f"seed node {node.get('id')}: unsafe documentation URL {doc.get('url')!r}. "
                    "Fix by using an absolute https:// documentation URL without whitespace."
                )

    relation_bundle = relation_vocabulary
    if relation_bundle is None:
        try:
            relation_bundle = generate_relation_vocabulary(seed)
        except KeyError as exc:
            relation_bundle = {
                "schema": "system-dynamics-map-relation-vocabulary-v1",
                "relations": [],
            }
            errors.append(
                f"relation vocabulary: cannot derive from invalid seed edge endpoint {exc}. "
                "Fix by correcting edge.source/edge.target before generating relations."
            )
    errors.extend(
        _missing_required_errors(
            "relation vocabulary", relation_bundle, RELATION_VOCABULARY_REQUIRED
        )
    )
    relation_ids = {relation["id"] for relation in relation_bundle.get("relations", [])}
    for edge in seed.get("edges", []):
        if edge.get("status") == "observed":
            errors.append(
                f"seed edge {edge['id']}: topology edges must not be status=observed. "
                "Fix by moving observed state into system-dynamics-map.observations.jsonl."
            )
        if edge.get("source") not in node_set:
            errors.append(
                f"seed edge {edge.get('id')}: missing source {edge.get('source')!r}. "
                "Fix by using an existing source nodes[].id."
            )
        if edge.get("target") not in node_set:
            errors.append(
                f"seed edge {edge.get('id')}: missing target {edge.get('target')!r}. "
                "Fix by using an existing target nodes[].id."
            )
        if edge.get("layer") not in layer_set:
            errors.append(
                f"seed edge {edge.get('id')}: undeclared layer {edge.get('layer')!r}. "
                "Fix by using a declared layers[].id."
            )
        if edge.get("status") not in statuses:
            errors.append(
                f"seed edge {edge.get('id')}: undeclared status {edge.get('status')!r}. "
                "Fix by using a declared status_kinds[] value."
            )
        if edge.get("relation") not in relation_ids:
            errors.append(
                f"seed edge {edge.get('id')}: undeclared relation {edge.get('relation')!r}. "
                "Fix by regenerating system-dynamics-map.relations.json from the seed."
            )
        confidence = edge.get("confidence")
        if not isinstance(confidence, int | float) or isinstance(confidence, bool):
            errors.append(
                f"seed edge {edge.get('id')}: confidence must be numeric. "
                "Fix by using a JSON number between 0 and 1."
            )
        elif not 0 <= confidence <= 1:
            errors.append(
                f"seed edge {edge.get('id')}: confidence must be between 0 and 1. "
                "Fix by using a confidence value in the inclusive 0..1 range."
            )
        for doc in edge.get("docs", []):
            if not _safe_url(doc.get("url", "")):
                errors.append(
                    f"seed edge {edge.get('id')}: unsafe documentation URL {doc.get('url')!r}. "
                    "Fix by using an absolute https:// documentation URL without whitespace."
                )

    claim_items = (claims or generate_claims(seed))["claims"]
    expected_claim_count = len(node_ids) + len(edge_ids)
    if len(claim_items) != expected_claim_count:
        errors.append(
            f"claims: expected {expected_claim_count} claims, found {len(claim_items)}. "
            "Fix by regenerating claim fragments from seed nodes and edges."
        )
    for claim in claim_items:
        errors.extend(
            _missing_required_errors(f"claim {claim.get('id', '<missing>')}", claim, CLAIM_REQUIRED)
        )
        if claim.get("claim_type") != "asserted" and not claim.get("provenance"):
            errors.append(
                f"claim {claim.get('id')}: non-asserted claim lacks provenance. "
                "Fix by attaching provenance for generated, inferred, rendered, or candidate claims."
            )
        provenance = claim.get("provenance")
        if not isinstance(provenance, dict):
            errors.append(
                f"claim {claim.get('id')}: provenance must be an object. "
                "Fix by using a provenance object with source_ref, source_hash, agent, and activity."
            )
        else:
            for field in (
                "source_ref",
                "source_hash",
                "source_type",
                "agent",
                "activity",
                "authority_ceiling",
            ):
                if not provenance.get(field):
                    errors.append(
                        f"claim {claim.get('id')}: provenance missing {field}. "
                        "Fix by preserving the complete provenance record."
                    )
        score = claim.get("confidence_basis", {}).get("score")
        if not isinstance(score, int | float) or isinstance(score, bool) or not 0 <= score <= 1:
            errors.append(
                f"claim {claim.get('id')}: confidence_basis.score must be 0..1. "
                "Fix by using a JSON number in the inclusive 0..1 range."
            )

    observation_items = observations if observations is not None else generate_observations(seed)
    if not observation_items:
        errors.append(
            "observations: at least one temporal observation is required. "
            "Fix by adding an observation record or regenerating observations."
        )
    if not any(item.get("freshness") == "stale" for item in observation_items):
        errors.append(
            "observations: stale-state canary missing. "
            "Fix by preserving a stale observation canary for expiry-path validation."
        )
    for observation in observation_items:
        observation_id = observation.get("id", "<missing>")
        errors.extend(
            _missing_required_errors(
                f"observation {observation_id}", observation, OBSERVATION_REQUIRED
            )
        )
        subject = observation.get("subject")
        if subject not in node_set:
            errors.append(
                f"observation {observation_id}: subject {subject!r} is not a seed node. "
                "Fix by using an existing nodes[].id or adding the observed subject "
                "to system-dynamics-map.seed.json."
            )
        valid_time = observation.get("valid_time") or {}
        valid_from = valid_time.get("from")
        valid_to = valid_time.get("to")
        if not observation.get("observed_at"):
            errors.append(
                f"observation {observation_id}: missing observed_at. "
                "Fix by adding the observation capture timestamp."
            )
        if not valid_from:
            errors.append(
                f"observation {observation_id}: missing valid_time.from. "
                "Fix by adding the start of the observation validity interval."
            )
        if valid_from and valid_to and valid_from > valid_to:
            errors.append(
                f"observation {observation_id}: invalid valid_time interval. "
                "Fix by setting valid_time.to after valid_time.from or null."
            )
        if observation.get("freshness") not in {"fresh", "stale", "historical"}:
            errors.append(
                f"observation {observation_id}: invalid freshness. "
                "Fix by using fresh, stale, or historical."
            )
        if not observation.get("source_ref") or not observation.get("source_hash"):
            errors.append(
                f"observation {observation_id}: missing source reference/hash. "
                "Fix by carrying source_ref and source_hash from the evidence source."
            )
        try:
            observed_at = _parse_datetime(observation.get("observed_at"))
            transaction_time = _parse_datetime(observation.get("transaction_time"))
            parsed_valid_from = _parse_datetime(valid_from)
            parsed_valid_to = _parse_datetime(valid_to)
            expires_at = _parse_datetime(observation.get("expires_at"))
        except ValueError as exc:
            errors.append(
                f"observation {observation_id}: invalid timestamp {exc}. "
                "Fix by using ISO-8601 UTC timestamps with a Z suffix."
            )
            continue
        if parsed_valid_from and observed_at and parsed_valid_from > observed_at:
            errors.append(
                f"observation {observation_id}: valid_time.from is after observed_at. "
                "Fix by moving valid_time.from to or before observed_at."
            )
        if parsed_valid_to and parsed_valid_from and parsed_valid_to < parsed_valid_from:
            errors.append(
                f"observation {observation_id}: invalid parsed valid_time interval. "
                "Fix by setting valid_time.to after valid_time.from or null."
            )
        if expires_at and parsed_valid_from and expires_at < parsed_valid_from:
            errors.append(
                f"observation {observation_id}: expires_at is before valid_time.from. "
                "Fix by setting expires_at at or after valid_time.from."
            )
        if observation.get("freshness") == "fresh":
            if expires_at is None:
                errors.append(
                    f"observation {observation_id}: fresh observations require expires_at. "
                    "Fix by adding the freshness expiry timestamp."
                )
            elif transaction_time and expires_at <= transaction_time:
                errors.append(
                    f"observation {observation_id}: fresh observation is expired. "
                    "Fix by setting expires_at after transaction_time or marking the "
                    "observation stale."
                )
        if observation.get("freshness") == "stale":
            if expires_at is None:
                errors.append(
                    f"observation {observation_id}: stale observations require expires_at. "
                    "Fix by adding the timestamp that made the observation stale."
                )
            elif transaction_time and expires_at > transaction_time:
                errors.append(
                    f"observation {observation_id}: stale observation expires after transaction_time. "
                    "Fix by setting expires_at at or before transaction_time or marking "
                    "the observation fresh."
                )

    lens_bundle = lenses or generate_lenses(seed)
    lens_ids = {lens["id"] for lens in lens_bundle["lenses"]}
    if lens_bundle.get("default_lens") not in lens_ids:
        errors.append(
            "lenses: default_lens must name an existing lens. "
            "Fix by setting default_lens to one of lenses[].id."
        )
    for lens in lens_bundle["lenses"]:
        lens_id = lens.get("id", "<missing>")
        errors.extend(_missing_required_errors(f"lens {lens_id}", lens, LENS_REQUIRED))
        unknown_layers = set(lens.get("visible_layers", [])) - layer_set
        unknown_statuses = set(lens.get("visible_statuses", [])) - statuses
        unknown_nodes = set(lens.get("visible_node_ids", [])) - node_set
        unknown_edges = set(lens.get("visible_edge_ids", [])) - edge_set
        if unknown_layers:
            errors.append(
                f"lens {lens_id}: unknown layers {sorted(unknown_layers)}. "
                "Fix by using declared layers[].id values."
            )
        if unknown_statuses:
            errors.append(
                f"lens {lens_id}: unknown statuses {sorted(unknown_statuses)}. "
                "Fix by using declared status_kinds[] values."
            )
        if unknown_nodes:
            errors.append(
                f"lens {lens_id}: unknown nodes {sorted(unknown_nodes)}. "
                "Fix by using visible/hidden node IDs from seed nodes[].id."
            )
        if unknown_edges:
            errors.append(
                f"lens {lens_id}: unknown edges {sorted(unknown_edges)}. "
                "Fix by using visible/hidden edge IDs from seed edges[].id."
            )
        visible_nodes = set(lens.get("visible_node_ids", []))
        for edge in seed["edges"]:
            if edge["id"] in set(lens.get("visible_edge_ids", [])) and (
                edge["source"] not in visible_nodes or edge["target"] not in visible_nodes
            ):
                errors.append(
                    f"lens {lens_id}: visible edge {edge['id']} has hidden endpoint. "
                    "Fix by regenerating the lens projection."
                )
    return errors


def _normalise_for_check(path: Path, text: str) -> str:
    if path not in {PACKAGE_PATH, LOCK_PATH}:
        return text
    data = json.loads(text)
    data["git_sha"] = "<recorded>"
    if path == LOCK_PATH:
        data["package_hash"] = "<recorded>"
    return _json(data)


def rendered_artifacts() -> dict[Path, str]:
    seed = _load_seed()
    rendered = _rendered_without_package(seed)
    rendered[VIEWER_PATH] = generate_viewer(seed)
    package_content = generate_package(seed, rendered)
    rendered[PACKAGE_PATH] = package_content
    rendered[LOCK_PATH] = generate_lock(seed, rendered, package_content)
    return rendered


def write_artifacts() -> None:
    seed = _load_seed()
    errors = _contract_errors(seed)
    if errors:
        raise RuntimeError("\n".join(errors))
    for path, content in rendered_artifacts().items():
        _atomic_write_text(path, content)


def check_artifacts() -> list[str]:
    errors: list[str] = []
    seed = _load_seed()
    relation_vocabulary = _load_json(RELATIONS_PATH) if RELATIONS_PATH.exists() else None
    claims = _load_json(CLAIMS_PATH) if CLAIMS_PATH.exists() else None
    observations = _read_observations(OBSERVATIONS_PATH)
    lenses = _load_json(LENSES_PATH) if LENSES_PATH.exists() else None
    errors.extend(
        _contract_errors(
            seed,
            relation_vocabulary=relation_vocabulary,
            claims=claims,
            observations=observations if observations else None,
            lenses=lenses,
        )
    )
    for path, expected in rendered_artifacts().items():
        if not path.exists():
            errors.append(
                f"{path}: missing. Fix by running scripts/system_dynamics_map_materialize.py."
            )
            continue
        actual = path.read_text(encoding="utf-8")
        if _normalise_for_check(path, actual) != _normalise_for_check(path, expected):
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

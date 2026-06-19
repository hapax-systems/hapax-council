"""Cache-only HKP bundle exporter.

HKP export output is derived projection state. This module writes only shadow
bundles and local derived indexes under ``~/.cache/hapax``; it does not mutate
source authority, vault authority, Qdrant, dashboards, runtime state, release
gates, public surfaces, or provider-spend paths.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.hkp_bundle_schema import FORBIDDEN_CONSUMERS, STALE_SOURCE_STATES, validate_bundle

PROFILE_VERSION = "hkp-v1"
GENERATOR_ID = "hkp-shadow-exporter"
GENERATOR_VERSION = "0.1.0"
SOURCE_REF_STALE_AFTER = "P7D"
UNKNOWN_DENY_CONSUMER = "unknown"
SHADOW_INDEX_DIRNAME = "hkp-shadow-index"
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
_SAFE_BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
ROUTE_METADATA_GAP_ERROR_CLASSES = {
    "planning",
    "source_mutation",
    "runtime_mutation",
    "public_claim",
    "provider_spend",
}
UNPARSEABLE_FRONTMATTER_ERROR_CLASSES = {
    "source_mutation",
    "runtime_mutation",
    "public_claim",
    "provider_spend",
}
TREE_HASH_EXCLUDED_PATHS = {"_hkp/checksums.json", "_hkp/manifest.yaml"}
_FRONTMATTER_TYPE_MAP = {
    "cc-task": "cc-task",
    "authority-case-s5-packet": "authority-case",
    "authority-case": "authority-case",
    "hapax-request": "spec",
    "support-design": "spec",
}
_ROUTE_METADATA_KEYS = (
    "authority_case",
    "parent_spec",
    "route_metadata_schema",
    "quality_floor",
    "mutation_surface",
    "authority_level",
)


@dataclass(frozen=True)
class HkpExportInput:
    path: Path
    logical_uri: str
    content_hash: str
    frontmatter: dict[str, Any]
    parse_error: str | None


@dataclass(frozen=True)
class HkpIndexFinding:
    code: str
    severity: str
    subject: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "subject": self.subject,
            "message": self.message,
        }


@dataclass(frozen=True)
class HkpExportResult:
    bundle_path: Path
    index_path: Path
    bundle_uid: str
    output_tree_hash: str
    input_ref_hash: str
    concept_count: int
    edge_count: int
    findings: tuple[HkpIndexFinding, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_path": str(self.bundle_path),
            "index_path": str(self.index_path),
            "bundle_uid": self.bundle_uid,
            "output_tree_hash": self.output_tree_hash,
            "input_ref_hash": self.input_ref_hash,
            "concept_count": self.concept_count,
            "edge_count": self.edge_count,
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class HkpCatalogResult:
    catalog_path: Path
    shadow_root: Path
    index_root: Path
    bundle_count: int
    finding_count: int
    error_count: int
    bundles: tuple[dict[str, Any], ...]

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "catalog_path": str(self.catalog_path),
            "shadow_root": str(self.shadow_root),
            "index_root": str(self.index_root),
            "bundle_count": self.bundle_count,
            "finding_count": self.finding_count,
            "error_count": self.error_count,
            "bundles": list(self.bundles),
        }


def default_shadow_root() -> Path:
    return Path.home() / ".cache" / "hapax" / "hkp-shadow"


def default_index_root() -> Path:
    return Path.home() / ".cache" / "hapax" / SHADOW_INDEX_DIRNAME


def export_shadow_bundle(
    source_paths: list[Path],
    *,
    bundle_id: str,
    source_root: Path,
    source_root_id: str = "repo:hapax-council",
    source_commit: str | None = None,
    output_root: Path | None = None,
    index_root: Path | None = None,
    generated_at: str | None = None,
) -> HkpExportResult:
    """Export selected source files into a deterministic cache-only HKP bundle."""

    generated_at = generated_at or _now_utc()
    output_root = output_root or default_shadow_root()
    index_root = index_root or default_index_root()
    _ensure_cache_child(output_root, default_shadow_root(), "HKP bundle output")
    _ensure_cache_child(index_root, default_index_root(), "HKP derived index")

    normalized_bundle_id = _safe_bundle_id(bundle_id)
    bundle_uid = f"hkp:bundle:{normalized_bundle_id}"
    bundle_path = output_root / normalized_bundle_id
    tmp_path = output_root / f".{normalized_bundle_id}.tmp"
    backup_path = output_root / f".{normalized_bundle_id}.previous"
    _ensure_cache_child(bundle_path, default_shadow_root(), "HKP bundle output")
    _ensure_cache_child(tmp_path, default_shadow_root(), "HKP bundle output")
    _ensure_cache_child(backup_path, default_shadow_root(), "HKP bundle output")
    _ensure_replaceable_directory(bundle_path, "HKP bundle output", trusted_root=output_root)
    prior_log_entries = _read_log_entries(bundle_path / "log.md")
    _remove_cache_path(tmp_path, "HKP bundle temporary path", trusted_root=output_root)
    _remove_cache_path(backup_path, "HKP bundle backup path", trusted_root=output_root)
    (tmp_path / "concepts").mkdir(parents=True)
    (tmp_path / "references").mkdir()
    (tmp_path / "_hkp").mkdir()

    inputs = [
        _load_input(path, source_root=source_root, source_root_id=source_root_id)
        for path in sorted(source_paths, key=lambda p: p.as_posix())
    ]
    input_ref_hash = _input_ref_hash(inputs)
    concepts: list[dict[str, Any]] = []
    findings: list[HkpIndexFinding] = []
    concept_paths: set[str] = set()
    for index, source in enumerate(inputs):
        concept = _concept_for_source(
            source,
            bundle_uid=bundle_uid,
            generated_at=generated_at,
            sequence=index,
        )
        concept["concept_path"] = _unique_concept_path(
            str(concept["concept_path"]),
            seen=concept_paths,
            source=source,
            sequence=index,
        )
        concepts.append(concept)
        concept_filename = f"{concept['concept_path']}.md"
        findings.extend(_route_metadata_findings(source, concept["concept_uid"]))
        if source.parse_error:
            findings.append(
                HkpIndexFinding(
                    code="source_frontmatter_unparseable",
                    severity=_unparseable_frontmatter_severity(source),
                    subject=concept["concept_uid"],
                    message=_source_frontmatter_unparseable_message(source.parse_error),
                )
            )
        _write_markdown(
            tmp_path / "concepts" / concept_filename,
            concept,
            _concept_body(source, concept),
        )

    edges = _edges_for_concepts(concepts)
    events = _events_for_export(
        bundle_uid=bundle_uid,
        concept_uids=[str(concept["concept_uid"]) for concept in concepts],
        edge_count=len(edges),
        generated_at=generated_at,
    )
    _write_text(tmp_path / "index.md", _index_markdown(bundle_uid, concepts, generated_at))
    _write_text(
        tmp_path / "log.md",
        _log_markdown(
            bundle_uid,
            generated_at,
            inputs,
            prior_entries=prior_log_entries,
        ),
    )
    _write_yaml(tmp_path / "_hkp" / "consumer_policy.yaml", _consumer_policy())
    _write_jsonl(tmp_path / "_hkp" / "edges.jsonl", edges)
    _write_jsonl(tmp_path / "_hkp" / "events.jsonl", events)
    _write_json(
        tmp_path / "_hkp" / "snapshot.json",
        {
            "hkp_schema": 1,
            "bundle_uid": bundle_uid,
            "generated_at": generated_at,
            "concept_count": len(concepts),
            "edge_count": len(edges),
        },
    )
    output_tree_hash = _tree_hash(tmp_path)
    _write_yaml(
        tmp_path / "_hkp" / "manifest.yaml",
        {
            "bundle_uid": bundle_uid,
            "hkp_schema": 1,
            "profile_version": PROFILE_VERSION,
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "source_root": source_root_id,
            "source_commit": source_commit,
            "input_ref_hash": input_ref_hash,
            "output_tree_hash": output_tree_hash,
            "cache_only": True,
            "allowed_consumers": ["research_viewer", "local_prompt_context"],
            "forbidden_consumers": sorted(
                FORBIDDEN_CONSUMERS | {"qdrant_rag", "public_export", UNKNOWN_DENY_CONSUMER}
            ),
            "created_at": generated_at,
            "generated_at": generated_at,
        },
    )
    _write_json(tmp_path / "_hkp" / "checksums.json", _checksums(tmp_path))
    _replace_cache_directory(
        tmp_path,
        bundle_path,
        backup_path,
        label="HKP bundle output",
        trusted_root=output_root,
    )
    validation = validate_bundle(bundle_path)
    findings.extend(
        HkpIndexFinding(
            code=finding.code,
            severity=finding.severity.value,
            subject=finding.path,
            message=finding.message,
        )
        for finding in validation.findings
    )
    index_path = _write_index(
        index_root=index_root,
        bundle_id=normalized_bundle_id,
        bundle_path=bundle_path,
        concepts=concepts,
        findings=findings,
        generated_at=generated_at,
        output_tree_hash=output_tree_hash,
    )
    return HkpExportResult(
        bundle_path=bundle_path,
        index_path=index_path,
        bundle_uid=bundle_uid,
        output_tree_hash=output_tree_hash,
        input_ref_hash=input_ref_hash,
        concept_count=len(concepts),
        edge_count=len(edges),
        findings=tuple(findings),
    )


def build_derived_index(bundle_path: Path, *, index_path: Path) -> tuple[HkpIndexFinding, ...]:
    """Write a JSONL derived index for an existing bundle and return findings."""

    _ensure_cache_child(bundle_path, default_shadow_root(), "HKP bundle input")
    _ensure_cache_child(index_path.parent, default_index_root(), "HKP derived index")
    concepts = _read_concepts(bundle_path)
    findings = _bundle_index_findings(bundle_path, concepts)
    _write_index(
        index_root=index_path.parent,
        bundle_id=index_path.stem,
        bundle_path=bundle_path,
        concepts=concepts,
        findings=findings,
        generated_at=_now_utc(),
        output_tree_hash=_tree_hash(bundle_path),
        explicit_index_path=index_path,
    )
    return tuple(findings)


def build_shadow_catalog(
    *,
    shadow_root: Path | None = None,
    index_root: Path | None = None,
    generated_at: str | None = None,
) -> HkpCatalogResult:
    """Discover shadow bundles and write an aggregate cache-only JSONL catalog."""

    generated_at = generated_at or _now_utc()
    shadow_root = shadow_root or default_shadow_root()
    index_root = index_root or default_index_root()
    _ensure_cache_child(shadow_root, default_shadow_root(), "HKP shadow catalog input")
    _ensure_cache_child(index_root, default_index_root(), "HKP shadow catalog")
    if shadow_root.exists() and not shadow_root.is_dir():
        raise ValueError(
            f"HKP shadow catalog input must be a directory: {shadow_root}; next-action: "
            "remove the non-directory cache path or pass the HKP shadow bundle root"
        )
    if index_root.exists() and not index_root.is_dir():
        raise ValueError(
            f"HKP shadow catalog output must be a directory: {index_root}; next-action: "
            "remove the non-directory cache path or pass the HKP shadow index root"
        )
    shadow_root.mkdir(parents=True, exist_ok=True)
    index_root.mkdir(parents=True, exist_ok=True)
    catalog_path = index_root / "catalog.jsonl"
    _reject_symlink_components(catalog_path, "HKP shadow catalog", trusted_root=index_root)

    bundle_rows: list[dict[str, Any]] = []
    finding_rows: list[dict[str, Any]] = []
    for bundle_path in _discover_shadow_bundles(shadow_root):
        concepts = _read_concepts(bundle_path)
        validation = validate_bundle(bundle_path)
        findings = _bundle_index_findings(bundle_path, concepts)
        manifest = _manifest_summary(bundle_path)
        severity_counts = _severity_counts(findings)
        bundle_row = {
            "record_type": "bundle_summary",
            "bundle_id": bundle_path.name,
            "bundle_path": str(bundle_path),
            "bundle_uid": manifest.get("bundle_uid"),
            "generated_at": generated_at,
            "concept_count": len(concepts),
            "edge_count": _jsonl_row_count(bundle_path / "_hkp" / "edges.jsonl"),
            "finding_count": len(findings),
            "error_count": severity_counts["error"],
            "warning_count": severity_counts["warning"],
            "input_ref_hash": manifest.get("input_ref_hash"),
            "output_tree_hash": manifest.get("output_tree_hash"),
            "validator_ok": validation.ok,
            "catalog_ok": severity_counts["error"] == 0,
        }
        bundle_rows.append(bundle_row)
        finding_rows.extend(
            {
                "record_type": "finding",
                "bundle_id": bundle_path.name,
                **finding.as_dict(),
            }
            for finding in findings
        )

    error_count = sum(int(row["error_count"]) for row in bundle_rows)
    rows = [
        {
            "record_type": "catalog",
            "generated_at": generated_at,
            "shadow_root": str(shadow_root),
            "bundle_count": len(bundle_rows),
            "finding_count": len(finding_rows),
            "error_count": error_count,
        },
        *bundle_rows,
        *finding_rows,
    ]
    _write_jsonl_atomic(catalog_path, rows, label="HKP shadow catalog", trusted_root=index_root)
    return HkpCatalogResult(
        catalog_path=catalog_path,
        shadow_root=shadow_root,
        index_root=index_root,
        bundle_count=len(bundle_rows),
        finding_count=len(finding_rows),
        error_count=error_count,
        bundles=tuple(bundle_rows),
    )


def _load_input(path: Path, *, source_root: Path, source_root_id: str) -> HkpExportInput:
    source_path = path.resolve()
    source_root = source_root.resolve()
    if not source_path.is_file():
        raise ValueError(
            f"source path is not a file: {path}; next-action: verify the path exists "
            "and points to a file under --source-root"
        )
    if not source_path.is_relative_to(source_root):
        raise ValueError(
            f"source path must be under source_root: {path}; next-action: pass a source "
            "inside --source-root or adjust --source-root to the intended input tree"
        )
    raw = source_path.read_bytes()
    parsed = parse_frontmatter_with_diagnostics(source_path)
    relative = source_path.relative_to(source_root).as_posix()
    return HkpExportInput(
        path=source_path,
        logical_uri=f"{source_root_id}/{relative}",
        content_hash="sha256:" + sha256(raw).hexdigest(),
        frontmatter=parsed.frontmatter if parsed.ok and parsed.frontmatter is not None else {},
        parse_error=parsed.error_message if not parsed.ok else None,
    )


def _concept_for_source(
    source: HkpExportInput,
    *,
    bundle_uid: str,
    generated_at: str,
    sequence: int,
) -> dict[str, Any]:
    source_id = _source_id(source, sequence)
    concept_uid = f"hkp:{_concept_namespace(source.frontmatter)}:{source_id}"
    concept_path = _safe_id(source_id)
    event_id = _projection_event_id(
        bundle_uid=bundle_uid,
        sequence=sequence + 1,
        event_type="concept_emitted",
        subject_uid=concept_uid,
    )
    title = str(source.frontmatter.get("title") or source.path.stem).strip()
    if not title:
        title = source.path.stem
    route_gaps = _route_metadata_gaps(source.frontmatter)
    return {
        "hkp_schema": 1,
        "type": _concept_type(source),
        "concept_uid": concept_uid,
        "concept_path": concept_path,
        "title": title,
        "description": f"Derived HKP projection for {source.logical_uri}.",
        "resource": "file",
        "tags": sorted({"hkp", "shadow-mode", _concept_type(source)}),
        "source_refs": [
            {
                "ref_id": f"src:{source_id}",
                "data_role": "authority_source",
                "source_authority_class": _source_authority_class(source),
                "uri": source.logical_uri,
                "content_hash": source.content_hash,
                "hash_scope": "full_content",
                "hash_algorithm": "sha256",
                "observed_at": generated_at,
                "checked_at": generated_at,
                # Shadow projections should be refreshed quickly, but not on every prompt read.
                "stale_after": SOURCE_REF_STALE_AFTER,
                "freshness_state": "fresh",
            }
        ],
        "posture": {
            "privacy_class": _privacy_class(source.frontmatter),
            "consent_label_ref": _scalar_or_none(source.frontmatter.get("consent_label_ref")),
            "provenance_expr": None,
            "rights_state": "operator_controlled",
            "egress_state": "private",
            "public_export_allowed": False,
            "redaction_policy": "local_path_root_redaction",
            "allowed_consumers": ["research_viewer", "local_prompt_context"],
            "forbidden_consumers": sorted(FORBIDDEN_CONSUMERS),
        },
        "authority": {
            "level": "support_non_authoritative",
            "may_authorize": False,
            "ceiling_family": "evidence",
            "ceiling": "support_only",
            "promotion_required": "cc-task-with-authority-case",
        },
        "freshness": {
            "state": "fresh",
            "valid_from": None,
            "valid_until": None,
            "checked_at": generated_at,
        },
        "projection_provenance": {
            "producer": GENERATOR_ID,
            "generated_at": generated_at,
            "projection_event_ids": [event_id],
            "evidence_refs": [f"src:{source_id}"],
            "citation_refs": [],
        },
        "summary_invariants": {
            "preserve_authority_ceiling": True,
            "preserve_cannot_prove": True,
            "preserve_source_refs": True,
            "preserve_public_private_posture": True,
        },
        "extensions": {
            "hapax": {
                "source_uri": source.logical_uri,
                "source_hash": source.content_hash,
                "route_metadata_gaps": route_gaps,
                "depends_on": _listify(source.frontmatter.get("depends_on")),
                "export_status": "shadow_cache_only",
                "title_leak_policy": "title_allowed_internal_only",
                "path_leak_policy": "logical_uri_only",
            }
        },
    }


def _edges_for_concepts(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for concept in concepts:
        route = concept["extensions"]["hapax"]
        source_id = str(concept["source_refs"][0]["ref_id"])
        for dep in _listify(route.get("depends_on")):
            target = f"cc-task:{_safe_id(dep)}"
            edge_seed = f"{concept['concept_uid']}|depends_on|{target}"
            edges.append(
                {
                    "hkp_schema": 1,
                    "edge_id": "hkp-edge:" + sha256(edge_seed.encode()).hexdigest()[:24],
                    "from_uid": concept["concept_uid"],
                    "rel_family": "dependency",
                    "rel": "depends_on",
                    "direction": "outbound",
                    "to_uid": None,
                    "target_ref": target,
                    "target_path": None,
                    "source_refs": [source_id],
                    "authority_ceiling": "evidence_bound",
                    "freshness": {"state": "fresh"},
                    "generated_from": {
                        "projection_event_id": concept["projection_provenance"][
                            "projection_event_ids"
                        ][0],
                        "generator_id": GENERATOR_ID,
                    },
                }
            )
    return edges


def _events_for_export(
    *,
    bundle_uid: str,
    concept_uids: list[str],
    edge_count: int,
    generated_at: str,
) -> list[dict[str, Any]]:
    event_specs = [
        (
            "bundle_generated",
            bundle_uid,
            {"concept_count": len(concept_uids), "edge_count": edge_count},
        )
    ]
    event_specs.extend(("concept_emitted", uid, {}) for uid in concept_uids)
    events: list[dict[str, Any]] = []
    previous_hash: str | None = None
    for sequence, (event_type, subject_uid, payload) in enumerate(event_specs):
        event = {
            "schema_version": 1,
            "event_id": _projection_event_id(
                bundle_uid=bundle_uid,
                sequence=sequence,
                event_type=event_type,
                subject_uid=subject_uid,
            ),
            "sequence": sequence,
            "timestamp": generated_at,
            "event_type": event_type,
            "actor": GENERATOR_ID,
            "subject_uid": subject_uid,
            "payload": payload,
            "previous_event_hash": previous_hash,
        }
        events.append(event)
        previous_hash = _json_hash(event)
    return events


def _projection_event_id(
    *,
    bundle_uid: str,
    sequence: int,
    event_type: str,
    subject_uid: str,
) -> str:
    seed = f"{bundle_uid}:{sequence}:{event_type}:{subject_uid}"
    return f"event:{sha256(seed.encode()).hexdigest()[:24]}"


def _consumer_policy() -> dict[str, Any]:
    defaults = {
        "research_viewer": "allow_read_only",
        "local_prompt_context": "allow_with_ceiling",
        "dashboard": "deny",
        "qdrant_rag": "deny",
        "public_export": "deny",
        "release_gate": "deny",
        "dispatcher": "deny",
        "close_gate": "deny",
        "runtime_loader": "deny",
        "provider_spend_gate": "deny",
        UNKNOWN_DENY_CONSUMER: "deny",
    }
    return {
        "hkp_schema": 1,
        "consumers": [
            {
                "consumer": consumer,
                "default": default,
                "allowed_fields": ["title", "description", "source_refs", "authority"]
                if default != "deny"
                else [],
                "forbidden_fields": ["body", "private_source_path", "secret"],
                "title_leak_policy": "internal_only",
                "body_leak_policy": "drop_private",
                "path_redaction_policy": "local_path_root_redaction",
                "embedding_allowed": False,
                "retrieval_allowed": False,
            }
            for consumer, default in sorted(defaults.items())
        ],
    }


def _route_metadata_findings(
    source: HkpExportInput, concept_uid: str
) -> tuple[HkpIndexFinding, ...]:
    return tuple(
        HkpIndexFinding(
            code="route_metadata_gap",
            severity=_route_metadata_gap_severity(source),
            subject=concept_uid,
            message=_route_metadata_gap_message(gap),
        )
        for gap in _route_metadata_gaps(source.frontmatter)
    )


def _bundle_index_findings(
    bundle_path: Path, concepts: list[dict[str, Any]]
) -> tuple[HkpIndexFinding, ...]:
    findings: list[HkpIndexFinding] = []
    validation = validate_bundle(bundle_path)
    findings.extend(
        HkpIndexFinding(
            code=finding.code,
            severity=finding.severity.value,
            subject=finding.path,
            message=finding.message,
        )
        for finding in validation.findings
    )
    for concept in concepts:
        freshness = concept.get("freshness") or {}
        if freshness.get("state") in STALE_SOURCE_STATES:
            findings.append(
                HkpIndexFinding(
                    code=f"source_{freshness['state']}",
                    severity="warning",
                    subject=str(concept.get("concept_uid") or ""),
                    message=f"concept freshness is {freshness['state']}",
                )
            )
        gaps = ((concept.get("extensions") or {}).get("hapax") or {}).get("route_metadata_gaps", [])
        for gap in _listify(gaps):
            findings.append(
                HkpIndexFinding(
                    code="route_metadata_gap",
                    severity=_route_metadata_gap_severity_for_concept(concept),
                    subject=str(concept.get("concept_uid") or ""),
                    message=_route_metadata_gap_message(gap),
                )
            )
    return tuple(findings)


def _write_index(
    *,
    index_root: Path,
    bundle_id: str,
    bundle_path: Path,
    concepts: list[dict[str, Any]],
    findings: list[HkpIndexFinding] | tuple[HkpIndexFinding, ...],
    generated_at: str,
    output_tree_hash: str,
    explicit_index_path: Path | None = None,
) -> Path:
    index_root.mkdir(parents=True, exist_ok=True)
    index_path = explicit_index_path or index_root / f"{bundle_id}.jsonl"
    _reject_symlink_components(index_path, "HKP derived index", trusted_root=index_root)
    if index_path.exists() and not index_path.is_file():
        raise ValueError(
            f"HKP derived index path must be a file: {index_path}; next-action: "
            "remove the non-file cache path or choose a different index filename"
        )
    rows = [
        {
            "record_type": "bundle",
            "bundle_id": bundle_id,
            "bundle_path": str(bundle_path),
            "generated_at": generated_at,
            "output_tree_hash": output_tree_hash,
            "concept_count": len(concepts),
            "finding_count": len(findings),
        }
    ]
    rows.extend(
        {
            "record_type": "concept",
            "concept_uid": concept["concept_uid"],
            "concept_path": concept["concept_path"],
            "type": concept["type"],
            "title": concept["title"],
            "source_refs": concept["source_refs"],
            "authority": concept["authority"],
            "freshness": concept["freshness"],
            "posture": concept["posture"],
            "extensions": concept["extensions"],
        }
        for concept in concepts
    )
    rows.extend({"record_type": "finding", **finding.as_dict()} for finding in findings)
    _write_jsonl_atomic(index_path, rows, label="HKP derived index", trusted_root=index_root)
    return index_path


def _discover_shadow_bundles(shadow_root: Path) -> tuple[Path, ...]:
    bundles: list[Path] = []
    for path in sorted(shadow_root.iterdir(), key=lambda item: item.name):
        _reject_symlink_components(path, "HKP shadow catalog input", trusted_root=shadow_root)
        if path.name.startswith(".") or not path.is_dir():
            continue
        if (path / "_hkp").exists() or (path / "index.md").exists():
            bundles.append(path)
    return tuple(bundles)


def _manifest_summary(bundle_path: Path) -> dict[str, Any]:
    manifest_path = bundle_path / "_hkp" / "manifest.yaml"
    if not manifest_path.is_file():
        return {}
    try:
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _jsonl_row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def _severity_counts(findings: tuple[HkpIndexFinding, ...]) -> dict[str, int]:
    return {
        "error": sum(1 for finding in findings if finding.severity == "error"),
        "warning": sum(1 for finding in findings if finding.severity == "warning"),
    }


def _read_concepts(bundle_path: Path) -> list[dict[str, Any]]:
    concepts: list[dict[str, Any]] = []
    concepts_root = bundle_path / "concepts"
    if not concepts_root.is_dir():
        return concepts
    for path in sorted(concepts_root.rglob("*.md")):
        parsed = parse_frontmatter_with_diagnostics(path)
        if parsed.ok and parsed.frontmatter is not None:
            concepts.append(parsed.frontmatter)
    return concepts


def _concept_body(source: HkpExportInput, concept: dict[str, Any]) -> str:
    return (
        f"# {concept['title']}\n\n"
        "Derived HKP projection. This body intentionally omits private source body text.\n\n"
        f"- Source ref: `{source.logical_uri}`\n"
        f"- Source hash: `{source.content_hash}`\n"
        "- Authority: support-non-authoritative\n"
        "- Export status: shadow cache only\n"
    )


def _index_markdown(bundle_uid: str, concepts: list[dict[str, Any]], generated_at: str) -> str:
    lines = [
        "# HKP Shadow Bundle",
        "",
        f"Bundle: `{bundle_uid}`",
        f"Generated: `{generated_at}`",
        "",
        "## Concepts",
        "",
    ]
    lines.extend(f"- `{concept['concept_uid']}` - {concept['title']}" for concept in concepts)
    return "\n".join(lines) + "\n"


def _log_markdown(
    bundle_uid: str,
    generated_at: str,
    inputs: list[HkpExportInput],
    *,
    prior_entries: list[str] | None = None,
) -> str:
    entry = f"- `{generated_at}` `{bundle_uid}` generated from {len(inputs)} source ref(s)."
    entries = list(prior_entries or [])
    if entry not in entries:
        entries.append(entry)
    lines = [
        "# HKP Projection Log",
        "",
        *entries,
    ]
    return "\n".join(lines) + "\n"


def _read_log_entries(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


def _checksums(bundle: Path) -> dict[str, Any]:
    relative_paths = [
        "index.md",
        "log.md",
        "_hkp/manifest.yaml",
        "_hkp/consumer_policy.yaml",
        "_hkp/edges.jsonl",
        "_hkp/events.jsonl",
        "_hkp/snapshot.json",
    ]
    relative_paths.extend(
        str(path.relative_to(bundle)) for path in sorted((bundle / "concepts").rglob("*.md"))
    )
    relative_paths.extend(
        str(path.relative_to(bundle))
        for path in sorted((bundle / "references").rglob("*"))
        if path.is_file()
    )
    return {
        "hkp_schema": 1,
        "artifacts": {
            relative_path: {
                "hash": _file_hash(bundle / relative_path),
                "hash_scope": "full_content",
                "hash_algorithm": "sha256",
            }
            for relative_path in relative_paths
        },
    }


def _tree_hash(bundle: Path) -> str:
    rows: list[dict[str, str]] = []
    for path in sorted(bundle.rglob("*")):
        relative_path = path.relative_to(bundle).as_posix()
        if not path.is_file() or relative_path in TREE_HASH_EXCLUDED_PATHS:
            continue
        rows.append({"path": relative_path, "hash": _file_hash(path)})
    return "sha256:" + sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _input_ref_hash(inputs: list[HkpExportInput]) -> str:
    rows = [
        {"uri": source.logical_uri, "content_hash": source.content_hash}
        for source in sorted(inputs, key=lambda item: item.logical_uri)
    ]
    return "sha256:" + sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _json_hash(payload: dict[str, Any]) -> str:
    return "sha256:" + sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _write_markdown(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(_jsonl_payload(rows), encoding="utf-8")


def _write_jsonl_atomic(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    label: str,
    trusted_root: Path,
) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise ValueError(
            f"{label} parent must be a directory: {path.parent}; next-action: remove the "
            "non-directory cache path or choose a different output root"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(path, label, trusted_root=trusted_root)
    if path.exists() and not path.is_file():
        raise ValueError(
            f"{label} path must be a file: {path}; next-action: remove the non-file cache path "
            "or choose a different output filename"
        )
    tmp_path = path.with_name(f".{path.name}.tmp")
    _remove_cache_path(tmp_path, f"{label} temporary path", trusted_root=trusted_root)
    tmp_path.write_text(_jsonl_payload(rows), encoding="utf-8")
    try:
        tmp_path.replace(path)
    except Exception as exc:
        if tmp_path.exists():
            _remove_cache_path(tmp_path, f"{label} temporary path", trusted_root=trusted_root)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(
            f"failed to write {label} atomically: {exc}; next-action: verify cache permissions "
            "and remove stale temporary index files"
        ) from exc


def _jsonl_payload(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _ensure_replaceable_directory(path: Path, label: str, *, trusted_root: Path) -> None:
    _reject_symlink_components(path, label, trusted_root=trusted_root)
    if path.exists() and not path.is_dir():
        raise ValueError(
            f"{label} path collision is not a directory: {path}; next-action: remove the "
            "non-directory cache path before rerunning HKP export"
        )


def _remove_cache_path(path: Path, label: str, *, trusted_root: Path) -> None:
    _reject_symlink_components(path, label, trusted_root=trusted_root)
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    if path.is_file():
        path.unlink()
        return
    raise ValueError(
        f"{label} has unsupported cache path type: {path}; next-action: remove the stale "
        "cache path manually, then rerun HKP export"
    )


def _replace_cache_directory(
    tmp_path: Path,
    target_path: Path,
    backup_path: Path,
    *,
    label: str,
    trusted_root: Path,
) -> None:
    _ensure_replaceable_directory(tmp_path, f"{label} temporary path", trusted_root=trusted_root)
    _ensure_replaceable_directory(target_path, label, trusted_root=trusted_root)
    _remove_cache_path(backup_path, f"{label} backup path", trusted_root=trusted_root)
    backup_created = False
    try:
        if target_path.exists():
            target_path.replace(backup_path)
            backup_created = True
        tmp_path.replace(target_path)
    except Exception as exc:
        if backup_created:
            _restore_cache_backup(
                target_path,
                backup_path,
                label=label,
                trusted_root=trusted_root,
            )
        if tmp_path.exists():
            _remove_cache_path(tmp_path, f"{label} temporary path", trusted_root=trusted_root)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(
            f"failed to replace {label} atomically: {exc}; next-action: verify cache permissions "
            "and remove stale temporary or backup paths under the HKP cache root"
        ) from exc

    _remove_cache_path(backup_path, f"{label} backup path", trusted_root=trusted_root)


def _restore_cache_backup(
    target_path: Path,
    backup_path: Path,
    *,
    label: str,
    trusted_root: Path,
) -> None:
    if target_path.exists():
        _remove_cache_path(target_path, label, trusted_root=trusted_root)
    if backup_path.exists():
        backup_path.replace(target_path)


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def _ensure_cache_child(path: Path, cache_root: Path, label: str) -> None:
    path = _absolute_without_symlink_resolution(path)
    cache_root = _absolute_without_symlink_resolution(cache_root)
    if path != cache_root and not _is_relative_to(path, cache_root):
        raise ValueError(
            f"{label} must be under {cache_root}; next-action: omit the path to use "
            "the default cache location or pass a path under that cache root"
        )
    _reject_symlink_components(path, label, trusted_root=cache_root)


def _absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _reject_symlink_components(path: Path, label: str, *, trusted_root: Path) -> None:
    path = _absolute_without_symlink_resolution(path)
    current = _absolute_without_symlink_resolution(trusted_root)
    if current.is_symlink():
        raise ValueError(
            f"{label} must not traverse symlink component: {current}; next-action: "
            "remove the symlink or choose a real directory under the Hapax cache root"
        )
    parts = path.relative_to(current).parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(
                f"{label} must not traverse symlink component: {current}; next-action: "
                "remove the symlink or choose a real directory under the Hapax cache root"
            )


def _source_id(source: HkpExportInput, sequence: int) -> str:
    for key in ("task_id", "packet_id", "case_id", "request_id"):
        raw = source.frontmatter.get(key)
        if raw:
            return _safe_id(str(raw))
    rel_hash = sha256(source.logical_uri.encode()).hexdigest()[:12]
    return _safe_id(f"source-{sequence}-{source.path.stem}-{rel_hash}")


def _concept_namespace(frontmatter: dict[str, Any]) -> str:
    concept_type = _FRONTMATTER_TYPE_MAP.get(str(frontmatter.get("type") or ""), "source-module")
    return _safe_id(concept_type)


def _concept_type(source: HkpExportInput) -> str:
    if source.path.suffix == ".py":
        return "source-module"
    return _FRONTMATTER_TYPE_MAP.get(str(source.frontmatter.get("type") or ""), "reference")


def _source_authority_class(source: HkpExportInput) -> str:
    if source.path.suffix == ".py":
        return "source_mutation"
    if source.frontmatter.get("type") == "cc-task":
        return "planning"
    return "authoritative_docs" if source.frontmatter else "none"


def _route_metadata_gap_severity_for_concept(concept: dict[str, Any]) -> str:
    source_refs = concept.get("source_refs") or []
    source_classes: list[str] = []
    for source_ref in source_refs:
        if not isinstance(source_ref, dict):
            continue
        source_classes.append(str(source_ref.get("source_authority_class") or "none"))
    return _route_metadata_gap_severity_for_classes(tuple(source_classes))


def _route_metadata_gap_severity(source: HkpExportInput) -> str:
    return _route_metadata_gap_severity_for_classes((_source_authority_class(source),))


def _route_metadata_gap_severity_for_classes(source_classes: tuple[str, ...]) -> str:
    return (
        "error"
        if any(source_class in ROUTE_METADATA_GAP_ERROR_CLASSES for source_class in source_classes)
        else "warning"
    )


def _route_metadata_gap_message(gap: str) -> str:
    return (
        f"source lacks {gap}; next-action: add {gap} to governed source frontmatter "
        "or remove the file from the governed HKP source set"
    )


def _source_frontmatter_unparseable_message(parse_error: str) -> str:
    return (
        f"{parse_error}; next-action: repair the source frontmatter YAML "
        "or remove the malformed frontmatter fence"
    )


def _unparseable_frontmatter_severity(source: HkpExportInput) -> str:
    source_class = _source_authority_class(source)
    return "error" if source_class in UNPARSEABLE_FRONTMATTER_ERROR_CLASSES else "warning"


def _privacy_class(frontmatter: dict[str, Any]) -> str:
    raw = str(frontmatter.get("privacy_class") or "internal")
    return raw if raw in {"public", "internal", "private", "secret"} else "internal"


def _route_metadata_gaps(frontmatter: dict[str, Any]) -> list[str]:
    if frontmatter.get("type") != "cc-task":
        return []
    return [key for key in _ROUTE_METADATA_KEYS if frontmatter.get(key) in (None, "", [])]


def _listify(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _scalar_or_none(value: object) -> str | None:
    if value in (None, "", [], {}):
        return None
    return str(value)


def _safe_id(value: str) -> str:
    safe = _SAFE_ID_RE.sub("-", value.strip()).strip("-")
    return safe or "unnamed"


def _unique_concept_path(
    base: str,
    *,
    seen: set[str],
    source: HkpExportInput,
    sequence: int,
) -> str:
    if base not in seen:
        seen.add(base)
        return base
    source_hash = sha256(source.logical_uri.encode()).hexdigest()[:8]
    suffix = f"{sequence}-{source_hash}"
    candidate = f"{base}-{suffix}"
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{suffix}-{counter}"
        counter += 1
    seen.add(candidate)
    return candidate


def _safe_bundle_id(value: str) -> str:
    safe = value
    if (
        not _SAFE_BUNDLE_ID_RE.fullmatch(safe)
        or safe in {".", ".."}
        or not safe.strip(".")
        or safe != safe.strip()
        or any(part in {".", ".."} for part in Path(safe).parts)
    ):
        raise ValueError(
            f"bundle_id is not a safe cache path component: {value!r}; next-action: "
            "use an id beginning with a letter or digit, such as hkp-shadow-20260618"
        )
    return safe


def _now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

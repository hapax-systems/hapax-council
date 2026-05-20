"""YAML config assertion extractor.

Schema-aware walker for constraints, enums, and semantically loaded
defaults in YAML configuration files.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

from shared.assertion_model import (
    Assertion,
    AssertionType,
    GovernanceStatus,
    ProvenanceRecord,
    SourceType,
)

log = logging.getLogger(__name__)

CONSTRAINT_KEYS = frozenset(
    {
        "min",
        "max",
        "minimum",
        "maximum",
        "required",
        "enum",
        "pattern",
        "const",
        "default",
        "allowed",
        "forbidden",
        "threshold",
        "limit",
        "budget",
        "ceiling",
        "floor",
    }
)


def _content_hash(text: str, source: str) -> str:
    return hashlib.sha256(f"{source}:{text}".encode()).hexdigest()[:16]


def extract_from_yaml_file(path: Path, *, repo_root: Path | None = None) -> list[Assertion]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []

    if not isinstance(data, dict):
        return []

    rel_path = (
        str(path.relative_to(repo_root))
        if repo_root and path.is_relative_to(repo_root)
        else str(path)
    )
    now = datetime.now(UTC)
    results: list[Assertion] = []
    _walk_dict(data, rel_path, "", results, now)
    return results


def _walk_dict(
    obj: dict,
    source_uri: str,
    prefix: str,
    results: list[Assertion],
    now: datetime,
) -> None:
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        key_lower = str(key).lower()

        if key_lower in CONSTRAINT_KEYS:
            text = f"{path}: {value}"
            results.append(
                Assertion(
                    assertion_id=f"config-constraint-{_content_hash(text, source_uri)}",
                    text=text,
                    source_type=SourceType.CONFIG,
                    source_uri=source_uri,
                    assertion_type=AssertionType.CONSTRAINT,
                    governance_status=GovernanceStatus.DERIVED,
                    provenance=ProvenanceRecord(
                        extraction_method="yaml_constraint_walker",
                        extracted_at=now,
                    ),
                    tags=["yaml_constraint", key_lower],
                )
            )

        if isinstance(value, dict):
            _walk_dict(value, source_uri, path, results, now)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    _walk_dict(item, source_uri, f"{path}[{i}]", results, now)


def extract_from_config_directory(
    root: Path,
    *,
    repo_root: Path | None = None,
) -> list[Assertion]:
    all_assertions: list[Assertion] = []
    seen_ids: set[str] = set()

    for path in sorted(root.rglob("*.yaml")):
        for assertion in extract_from_yaml_file(path, repo_root=repo_root):
            if assertion.assertion_id not in seen_ids:
                seen_ids.add(assertion.assertion_id)
                all_assertions.append(assertion)

    for path in sorted(root.rglob("*.json")):
        if path.name.endswith(".schema.json"):
            continue
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        now = datetime.now(UTC)
        rel = (
            str(path.relative_to(repo_root))
            if repo_root and path.is_relative_to(repo_root)
            else str(path)
        )
        results: list[Assertion] = []
        _walk_dict(data, rel, "", results, now)
        for a in results:
            if a.assertion_id not in seen_ids:
                seen_ids.add(a.assertion_id)
                all_assertions.append(a)

    return all_assertions


__all__ = [
    "extract_from_config_directory",
    "extract_from_yaml_file",
]

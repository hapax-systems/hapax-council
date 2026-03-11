"""Document registry loader — parses document-registry.yaml for drift enforcement.

Provides typed dataclasses for archetypes, repo declarations, coverage rules,
and mutual awareness constraints. Zero LLM calls, pure parsing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


@dataclass
class Archetype:
    """A document archetype with required structural sections."""

    description: str = ""
    required_sections: list[str] = field(default_factory=list)
    composite: bool = False


@dataclass
class RepoDeclaration:
    """A declared repo with its required documents."""

    path: str = ""
    required_docs: list[dict] = field(default_factory=list)
    ci_sources: dict[str, str] = field(default_factory=dict)


@dataclass
class CoverageRule:
    """A CI-to-document coverage assertion."""

    ci_type: str = ""
    reference_doc: str = ""
    reference_section: str = ""
    match_by: str = "name"
    severity: str = "medium"
    description: str = ""


@dataclass
class MutualAwarenessRule:
    """A cross-repo awareness constraint."""

    type: str = ""
    description: str = ""
    registry_doc: str = ""
    registry_section: str = ""
    target_phrase: str = ""
    docs: list[str] = field(default_factory=list)
    severity: str = "medium"


@dataclass
class DocumentRegistry:
    """Parsed document registry."""

    version: int = 1
    archetypes: dict[str, Archetype] = field(default_factory=dict)
    repos: dict[str, RepoDeclaration] = field(default_factory=dict)
    coverage_rules: list[CoverageRule] = field(default_factory=list)
    mutual_awareness: list[MutualAwarenessRule] = field(default_factory=list)


def load_registry(
    *,
    path: Path | None = None,
    yaml_content: str | None = None,
) -> DocumentRegistry | None:
    """Load and parse a document registry from file or string.

    Returns None if the file doesn't exist or YAML is invalid.
    """
    if yaml_content is None:
        if path is None or not path.is_file():
            return None
        try:
            yaml_content = path.read_text()
        except OSError as e:
            log.warning("Cannot read registry file %s: %s", path, e)
            return None

    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        log.warning("Invalid registry YAML: %s", e)
        return None

    if not isinstance(data, dict):
        return None

    reg = DocumentRegistry(version=data.get("version", 1))

    # Parse archetypes
    for name, info in data.get("archetypes", {}).items():
        reg.archetypes[name] = Archetype(
            description=info.get("description", ""),
            required_sections=info.get("required_sections", []),
            composite=info.get("composite", False),
        )

    # Parse repos
    for name, info in data.get("repos", {}).items():
        reg.repos[name] = RepoDeclaration(
            path=info.get("path", ""),
            required_docs=info.get("required_docs", []),
            ci_sources=info.get("ci_sources", {}),
        )

    # Parse coverage rules
    for rule_data in data.get("coverage_rules", []):
        reg.coverage_rules.append(
            CoverageRule(
                ci_type=rule_data.get("ci_type", ""),
                reference_doc=rule_data.get("reference_doc", ""),
                reference_section=rule_data.get("reference_section", ""),
                match_by=rule_data.get("match_by", "name"),
                severity=rule_data.get("severity", "medium"),
                description=rule_data.get("description", ""),
            )
        )

    # Parse mutual awareness
    for ma_data in data.get("mutual_awareness", []):
        reg.mutual_awareness.append(
            MutualAwarenessRule(
                type=ma_data.get("type", ""),
                description=ma_data.get("description", ""),
                registry_doc=ma_data.get("registry_doc", ""),
                registry_section=ma_data.get("registry_section", ""),
                target_phrase=ma_data.get("target_phrase", ""),
                docs=ma_data.get("docs", []),
                severity=ma_data.get("severity", "medium"),
            )
        )

    return reg

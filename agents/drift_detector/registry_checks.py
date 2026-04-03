"""Document registry enforcement checks."""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

from .ci_discovery import (
    discover_agents,
    discover_mcp_servers,
    discover_repos,
    discover_services,
    discover_timers,
)
from .config import HAPAX_CONSTITUTION_DIR
from .document_registry import DocumentRegistry, load_registry
from .models import DriftItem
from .registry_awareness import check_mutual_awareness

log = logging.getLogger(__name__)


def _expand_path(p: str) -> Path:
    """Expand ~ in a path string to the actual home directory."""
    return Path(p.replace("~", str(Path.home())))


def check_required_docs(registry: DocumentRegistry) -> list[DriftItem]:
    """Check that every declared required_doc exists on disk."""
    items: list[DriftItem] = []
    for repo_name, repo in registry.repos.items():
        repo_path = _expand_path(repo.path)
        for doc in repo.required_docs:
            doc_path = repo_path / doc["path"]
            if not doc_path.is_file():
                items.append(
                    DriftItem(
                        severity="medium",
                        category="missing-required-doc",
                        doc_file=f"{repo_name}/{doc['path']}",
                        doc_claim=f"Registry requires {doc['path']} in {repo_name}",
                        reality="File does not exist",
                        suggestion=f"Create {doc['path']} in {repo_name} with archetype '{doc.get('archetype', 'unknown')}'",
                    )
                )
    return items


def check_archetype_sections(registry: DocumentRegistry) -> list[DriftItem]:
    """Check that documents have the required sections for their archetype."""
    items: list[DriftItem] = []
    for repo_name, repo in registry.repos.items():
        repo_path = _expand_path(repo.path)
        for doc in repo.required_docs:
            archetype_name = doc.get("archetype", "")
            if archetype_name not in registry.archetypes:
                continue
            archetype = registry.archetypes[archetype_name]
            if not archetype.required_sections:
                continue

            doc_path = repo_path / doc["path"]
            if not doc_path.is_file():
                continue

            try:
                content = doc_path.read_text(errors="replace")
            except OSError:
                continue

            for section in archetype.required_sections:
                if section not in content:
                    items.append(
                        DriftItem(
                            severity="medium",
                            category="missing-section",
                            doc_file=f"{repo_name}/{doc['path']}",
                            doc_claim=f"Archetype '{archetype_name}' requires section: {section}",
                            reality=f"Section '{section}' not found in {doc['path']}",
                            suggestion=f"Add '{section}' section to {repo_name}/{doc['path']}",
                        )
                    )
    return items


def check_coverage_rules(
    registry: DocumentRegistry,
    *,
    discovered_cis: dict[str, list[str]] | None = None,
) -> list[DriftItem]:
    """Check that every discovered CI is referenced in its coverage doc."""
    if discovered_cis is None:
        discovered_cis = {
            "agent": discover_agents(),
            "timer": discover_timers(),
            "service": discover_services(),
            "repo": discover_repos(),
            "mcp_server": discover_mcp_servers(),
        }

    items: list[DriftItem] = []

    for rule in registry.coverage_rules:
        ci_names = discovered_cis.get(rule.ci_type, [])
        if not ci_names:
            continue

        ref_path = _expand_path(rule.reference_doc)
        if not ref_path.is_file():
            log.debug("Coverage rule reference doc not found: %s", rule.reference_doc)
            continue

        try:
            content = ref_path.read_text(errors="replace")
        except OSError:
            continue

        search_text = content
        if rule.reference_section:
            section_start = content.find(rule.reference_section)
            if section_start >= 0:
                rest = content[section_start + len(rule.reference_section) :]
                next_section = rest.find("\n## ")
                if next_section >= 0:
                    search_text = rest[:next_section]
                else:
                    search_text = rest
            else:
                search_text = ""

        for ci_name in ci_names:
            if any(fnmatch.fnmatch(ci_name, pat) for pat in rule.exclude_patterns):
                continue
            name_variants = {ci_name, ci_name.replace("-", "_"), ci_name.replace("_", "-")}
            found = any(variant in search_text for variant in name_variants)

            if not found:
                short_ref = rule.reference_doc.replace(str(Path.home()), "~")
                items.append(
                    DriftItem(
                        severity=rule.severity,
                        category="coverage-gap",
                        doc_file=short_ref,
                        doc_claim=rule.description,
                        reality=f"{rule.ci_type} '{ci_name}' not found in {rule.reference_section or 'document'}",
                        suggestion=f"Add '{ci_name}' to {short_ref}",
                    )
                )

    return items


def check_document_registry(
    *,
    registry: DocumentRegistry | None = None,
    registry_path: Path | None = None,
) -> list[DriftItem]:
    """Run all document registry checks and return DriftItems."""
    if registry is None:
        if registry_path is None:
            registry_path = HAPAX_CONSTITUTION_DIR / "docs" / "document-registry.yaml"
        registry = load_registry(path=registry_path)

    if registry is None:
        log.info("No document registry found, skipping registry checks")
        return []

    items: list[DriftItem] = []
    items.extend(check_required_docs(registry))
    items.extend(check_archetype_sections(registry))
    items.extend(check_coverage_rules(registry))
    items.extend(check_mutual_awareness(registry))
    return items

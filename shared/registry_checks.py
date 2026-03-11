"""Registry enforcement checks — produces DriftItems from document registry rules.

Four sub-checks:
1. Required document existence
2. Archetype section validation
3. CI coverage rules
4. Mutual awareness constraints
"""

from __future__ import annotations

import logging
from pathlib import Path

from agents.drift_detector import DriftItem
from shared.ci_discovery import (
    discover_agents,
    discover_mcp_servers,
    discover_repos,
    discover_services,
    discover_timers,
)
from shared.document_registry import (
    DocumentRegistry,
    load_registry,
)

log = logging.getLogger(__name__)


def _expand_path(p: str) -> Path:
    """Expand ~ in a path string to the actual home directory."""
    return Path(p.replace("~", str(Path.home())))


# ── Sub-check 1: Required document existence ─────────────────────────


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


# ── Sub-check 2: Archetype section validation ────────────────────────


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
                continue  # Already caught by check_required_docs

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


# ── Sub-check 3: CI coverage rules ──────────────────────────────────


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

        # If a section is specified, only search within that section
        search_text = content
        if rule.reference_section:
            section_start = content.find(rule.reference_section)
            if section_start >= 0:
                # Find the next ## heading after this section
                rest = content[section_start + len(rule.reference_section) :]
                next_section = rest.find("\n## ")
                if next_section >= 0:
                    search_text = rest[:next_section]
                else:
                    search_text = rest
            else:
                search_text = ""  # Section not found — all CIs will be gaps

        for ci_name in ci_names:
            # Check if CI name appears in the search text
            # Try both hyphenated and underscored forms
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


# ── Sub-check 4: Mutual awareness ───────────────────────────────────


def check_mutual_awareness(
    registry: DocumentRegistry,
    *,
    known_repos: dict[str, Path] | None = None,
) -> list[DriftItem]:
    """Check cross-repo awareness constraints."""
    items: list[DriftItem] = []

    if known_repos is None:
        known_repos = {}
        for repo_name, repo in registry.repos.items():
            repo_path = _expand_path(repo.path)
            if repo_path.is_dir():
                known_repos[repo_name] = repo_path

    for rule in registry.mutual_awareness:
        if rule.type == "byte_identical":
            paths = [_expand_path(d) for d in rule.docs]
            if len(paths) < 2:
                continue
            if not all(p.is_file() for p in paths):
                missing = [str(p) for p in paths if not p.is_file()]
                for m in missing:
                    items.append(
                        DriftItem(
                            severity=rule.severity,
                            category="boundary-mismatch",
                            doc_file=m.replace(str(Path.home()), "~"),
                            doc_claim=rule.description,
                            reality="File does not exist",
                            suggestion=f"Create or copy file: {m}",
                        )
                    )
                continue
            contents = [p.read_bytes() for p in paths]
            if len(set(contents)) > 1:
                items.append(
                    DriftItem(
                        severity=rule.severity,
                        category="boundary-mismatch",
                        doc_file=", ".join(str(p).replace(str(Path.home()), "~") for p in paths),
                        doc_claim=rule.description,
                        reality="Files differ",
                        suggestion="Diff and reconcile the files, then copy to both locations",
                    )
                )

        elif rule.type == "spec_reference":
            phrase = rule.target_phrase
            if not phrase:
                continue
            for repo_name, repo_path in known_repos.items():
                claude_md = repo_path / "CLAUDE.md"
                if not claude_md.is_file():
                    continue
                try:
                    content = claude_md.read_text(errors="replace")
                except OSError:
                    continue
                if phrase.lower() not in content.lower():
                    items.append(
                        DriftItem(
                            severity=rule.severity,
                            category="spec-reference-gap",
                            doc_file=f"{repo_name}/CLAUDE.md",
                            doc_claim=rule.description,
                            reality=f"'{phrase}' not found in {repo_name}/CLAUDE.md",
                            suggestion=f"Add reference to {phrase} in {repo_name}/CLAUDE.md",
                        )
                    )

        elif rule.type == "repo_registry":
            registry_path = _expand_path(rule.registry_doc)
            if not registry_path.is_file():
                continue
            try:
                content = registry_path.read_text(errors="replace")
            except OSError:
                continue

            for repo_name in known_repos:
                # Check if repo name appears in registry doc
                if repo_name not in content:
                    items.append(
                        DriftItem(
                            severity=rule.severity,
                            category="repo-awareness-gap",
                            doc_file=rule.registry_doc.replace(str(Path.home()), "~"),
                            doc_claim=rule.description,
                            reality=f"Repo '{repo_name}' not found in registry document",
                            suggestion=f"Add '{repo_name}' to {rule.registry_section or 'document'}",
                        )
                    )

    return items


# ── Main entry point ─────────────────────────────────────────────────


def check_document_registry(
    *,
    registry: DocumentRegistry | None = None,
    registry_path: Path | None = None,
) -> list[DriftItem]:
    """Run all document registry checks and return DriftItems.

    If no registry is provided, loads from the default path at
    hapaxromana/docs/document-registry.yaml.
    """
    if registry is None:
        if registry_path is None:
            from shared.config import HAPAXROMANA_DIR

            registry_path = HAPAXROMANA_DIR / "docs" / "document-registry.yaml"
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

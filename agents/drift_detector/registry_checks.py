"""Vendored from shared/registry_checks.py — document registry enforcement checks.

Includes inlined CI discovery functions from shared/ci_discovery.py.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .config import (
    AI_AGENTS_DIR,
    CLAUDE_CONFIG_DIR,
    HAPAX_CONSTITUTION_DIR,
    HAPAX_PROJECTS_DIR,
    LLM_STACK_DIR,
)
from .document_registry import DocumentRegistry, load_registry
from .models import DriftItem

log = logging.getLogger(__name__)


def _expand_path(p: str) -> Path:
    """Expand ~ in a path string to the actual home directory."""
    return Path(p.replace("~", str(Path.home())))


# ── Inlined CI discovery (from shared/ci_discovery.py) ─────────────────────


def discover_agents(agents_dir: Path | None = None) -> list[str]:
    """Discover agent modules by scanning for files with __main__ blocks."""
    if agents_dir is None:
        agents_dir = AI_AGENTS_DIR / "agents"

    if not agents_dir.is_dir():
        return []

    agents: list[str] = []
    for py_file in sorted(agents_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            content = py_file.read_text(errors="replace")
            if "__name__" in content and "__main__" in content:
                name = py_file.stem.replace("_", "-")
                agents.append(name)
        except OSError:
            continue
    return agents


def discover_timers() -> list[str]:
    """Discover active systemd user timers."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "*.timer", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        timers: list[str] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if parts:
                name = parts[0].removesuffix(".timer")
                timers.append(name)
        return timers
    except (OSError, subprocess.TimeoutExpired):
        return []


def discover_services(compose_dir: Path | None = None) -> list[str]:
    """Discover running Docker Compose services."""
    if compose_dir is None:
        compose_dir = LLM_STACK_DIR

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(compose_dir) if compose_dir.is_dir() else None,
        )
        if result.returncode != 0:
            return []
        return [s.strip() for s in result.stdout.strip().splitlines() if s.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def discover_repos(projects_dir: Path | None = None) -> list[str]:
    """Discover hapax-related git repos."""
    if projects_dir is None:
        projects_dir = HAPAX_PROJECTS_DIR

    if not projects_dir.is_dir():
        return []

    repos: list[str] = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        if entry.name.startswith("hapax-"):
            repos.append(entry.name)
            continue
        claude_md = entry / "CLAUDE.md"
        if claude_md.is_file():
            try:
                content = claude_md.read_text(errors="replace")[:2000]
                if "hapax" in content.lower():
                    repos.append(entry.name)
            except OSError:
                continue
    return repos


def discover_mcp_servers(config_path: Path | None = None) -> list[str]:
    """Discover configured MCP servers from Claude Code config."""
    if config_path is None:
        config_path = CLAUDE_CONFIG_DIR / "mcp_servers.json"

    if not config_path.is_file():
        return []

    try:
        data = json.loads(config_path.read_text())
        return sorted(data.keys()) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []


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

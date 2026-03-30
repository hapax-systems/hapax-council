"""Build archetype/registry context for the fix agent."""

from __future__ import annotations

from pathlib import Path

from .config import HAPAXROMANA_DIR
from .models import DriftItem

REGISTRY_CATEGORIES = frozenset(
    {
        "missing-required-doc",
        "missing-section",
        "coverage-gap",
        "repo-awareness-gap",
        "spec-reference-gap",
        "boundary-mismatch",
    }
)


def _build_fix_context(
    doc_path: str,
    items: list[DriftItem],
    *,
    registry: object | None = None,
) -> str:
    """Build archetype/registry context for the fix agent."""
    if not any(d.category in REGISTRY_CATEGORIES for d in items):
        return ""

    if registry is None:
        try:
            from .document_registry import load_registry

            registry = load_registry(path=HAPAXROMANA_DIR / "docs" / "document-registry.yaml")
        except Exception:
            return ""

    if registry is None:
        return ""

    lines = ["## Document context (from registry)"]
    archetype_name = ""
    repo_name = ""

    for rname, repo in registry.repos.items():
        for doc in repo.required_docs:
            if doc["path"] in doc_path or doc_path.endswith(doc["path"]):
                archetype_name = doc.get("archetype", "")
                repo_name = rname
                break
        if archetype_name:
            break

    if repo_name:
        lines.append(f"- Repository: {repo_name}")

    if archetype_name and archetype_name in registry.archetypes:
        arch = registry.archetypes[archetype_name]
        lines.append(f"- Document archetype: **{archetype_name}** — {arch.description}")
        if arch.required_sections:
            lines.append(f"- Required sections: {', '.join(arch.required_sections)}")
        if arch.composite:
            lines.append("- This is a composite document (may blend multiple concerns)")
        else:
            lines.append("- This is a single-purpose document (should stay focused)")

    coverage_items = [d for d in items if d.category == "coverage-gap"]
    if coverage_items:
        lines.append("")
        lines.append("### Coverage context")
        for rule in registry.coverage_rules:
            for ci in coverage_items:
                if (
                    rule.reference_doc.replace("~", str(Path.home())) in ci.doc_file
                    or ci.doc_file in rule.reference_doc
                ):
                    lines.append(f"- Rule: {rule.description}")
                    if rule.reference_section:
                        lines.append(f"  Target section: {rule.reference_section}")
                    lines.append(f"  Match strategy: {rule.match_by}")
                    break

    return "\n".join(lines)

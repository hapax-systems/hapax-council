"""Mutual awareness checks for document registry enforcement."""

from __future__ import annotations

from pathlib import Path

from .document_registry import DocumentRegistry
from .models import DriftItem


def _expand_path(p: str) -> Path:
    """Expand ~ in a path string to the actual home directory."""
    return Path(p.replace("~", str(Path.home())))


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

"""Modification classification matrix.

Classifies file paths as AUTO_FIX, REVIEW_REQUIRED, or NEVER_MODIFY.
Enforces the safety boundary: oversight systems are never auto-modified.
"""

from __future__ import annotations

import fnmatch
import re
from enum import StrEnum


class ModificationClass(StrEnum):
    AUTO_FIX = "auto_fix"
    REVIEW_REQUIRED = "review_required"
    NEVER_MODIFY = "never_modify"


# Rules are ordered most-specific-first. First match wins.
CLASSIFICATION_RULES: list[tuple[str, ModificationClass]] = [
    # NEVER MODIFY — oversight mechanisms (checked first)
    ("agents/health_monitor.py", ModificationClass.NEVER_MODIFY),
    ("shared/alert_state.py", ModificationClass.NEVER_MODIFY),
    ("shared/axiom_enforcement.py", ModificationClass.NEVER_MODIFY),
    ("shared/axiom_registry.py", ModificationClass.NEVER_MODIFY),
    ("shared/axiom_tools.py", ModificationClass.NEVER_MODIFY),
    ("shared/config.py", ModificationClass.NEVER_MODIFY),
    ("axioms/*", ModificationClass.NEVER_MODIFY),
    ("hooks/*", ModificationClass.NEVER_MODIFY),
    ("systemd/*", ModificationClass.NEVER_MODIFY),
    ("hapax-backup-*.sh", ModificationClass.NEVER_MODIFY),
    (".github/*", ModificationClass.NEVER_MODIFY),
    # REVIEW REQUIRED — application code and config
    ("agents/*", ModificationClass.REVIEW_REQUIRED),
    ("shared/*", ModificationClass.REVIEW_REQUIRED),
    ("cockpit/*", ModificationClass.REVIEW_REQUIRED),
    ("scripts/*", ModificationClass.REVIEW_REQUIRED),
    ("tests/*", ModificationClass.REVIEW_REQUIRED),
    ("configs/*", ModificationClass.REVIEW_REQUIRED),
    ("pyproject.toml", ModificationClass.REVIEW_REQUIRED),
    # AUTO FIX — documentation
    ("docs/*", ModificationClass.AUTO_FIX),
    ("*.md", ModificationClass.AUTO_FIX),
    ("*.txt", ModificationClass.AUTO_FIX),
]


def classify_path(path: str) -> ModificationClass:
    """Return the modification class for a file path (first match wins)."""
    for pattern, classification in CLASSIFICATION_RULES:
        if fnmatch.fnmatch(path, pattern):
            return classification
    # Default: review required for unknown files.
    return ModificationClass.REVIEW_REQUIRED


def classify_paths(paths: list[str]) -> ModificationClass:
    """Return the most restrictive class across all paths."""
    if not paths:
        return ModificationClass.AUTO_FIX

    priority = {
        ModificationClass.NEVER_MODIFY: 2,
        ModificationClass.REVIEW_REQUIRED: 1,
        ModificationClass.AUTO_FIX: 0,
    }
    classifications = [classify_path(p) for p in paths]
    return max(classifications, key=lambda c: priority[c])


def classify_diff(diff_text: str) -> ModificationClass:
    """Return the most restrictive class across all files in a diff."""
    # Extract file paths from unified diff headers.
    paths = []
    for match in re.finditer(r"^(?:---|\+\+\+) [ab]/(.+)$", diff_text, re.MULTILINE):
        path = match.group(1)
        if path != "/dev/null":
            paths.append(path)
    return classify_paths(list(set(paths)))


def has_never_modify(paths: list[str]) -> list[str]:
    """Return list of paths classified as NEVER_MODIFY."""
    return [p for p in paths if classify_path(p) == ModificationClass.NEVER_MODIFY]

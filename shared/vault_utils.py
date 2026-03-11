"""Shared utilities for reading Obsidian vault content."""

from __future__ import annotations

from pathlib import Path

import yaml


def parse_frontmatter(path: Path) -> dict:
    """Extract YAML frontmatter from a markdown file.

    Returns empty dict on any parse failure (missing file, missing markers,
    invalid YAML, etc.).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    if not text.startswith("---"):
        return {}

    end = text.find("---", 3)
    if end == -1:
        return {}

    yaml_text = text[3:end].strip()
    if not yaml_text:
        return {}

    try:
        data = yaml.safe_load(yaml_text)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}

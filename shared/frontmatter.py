"""shared/frontmatter.py — Canonical frontmatter parser.

Returns (metadata_dict, body_text) tuple. Supersedes vault_utils.parse_frontmatter
which returns only the dict.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def parse_frontmatter(path_or_text: Path | str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from a markdown file or string.

    Args:
        path_or_text: A Path to read from disk, or a string to parse directly.

    Returns:
        (frontmatter_dict, body_text). Returns ({}, full_text) on any failure.
    """
    if isinstance(path_or_text, Path):
        try:
            text = path_or_text.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {}, ""
    else:
        text = path_or_text

    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end == -1:
        return {}, text

    yaml_text = text[3:end].strip()
    if not yaml_text:
        return {}, text[end + 3 :].lstrip("\n")

    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return {}, text
        body = text[end + 3 :].lstrip("\n")
        return data, body
    except yaml.YAMLError:
        return {}, text

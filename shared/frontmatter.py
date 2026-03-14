"""shared/frontmatter.py — Canonical frontmatter parser.

Returns (metadata_dict, body_text) tuple. Supersedes vault_utils.parse_frontmatter
which returns only the dict.

Extended with consent label extraction (DD-11) and labeled file reading (DD-12)
for IFC enforcement at filesystem boundaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.consent_label import ConsentLabel
from shared.labeled import Labeled


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


def extract_consent_label(frontmatter: dict[str, Any]) -> ConsentLabel | None:
    """Extract a ConsentLabel from frontmatter metadata (DD-11).

    Expects frontmatter format:
        consent_label:
          policies:
            - owner: "alice"
              readers: ["bob", "carol"]

    Returns None if no consent_label field is present.
    Returns ConsentLabel.bottom() if the field exists but is empty.
    """
    raw = frontmatter.get("consent_label")
    if raw is None:
        return None

    if not isinstance(raw, dict):
        return ConsentLabel.bottom()

    policies_raw = raw.get("policies", [])
    if not isinstance(policies_raw, list):
        return ConsentLabel.bottom()

    policies: set[tuple[str, frozenset[str]]] = set()
    for entry in policies_raw:
        if not isinstance(entry, dict):
            continue
        owner = entry.get("owner", "")
        readers = entry.get("readers", [])
        if owner:
            policies.add((owner, frozenset(readers)))

    return ConsentLabel(frozenset(policies))


def extract_provenance(frontmatter: dict[str, Any]) -> frozenset[str]:
    """Extract why-provenance contract IDs from frontmatter (DD-20).

    Expects: provenance: ["contract-1", "contract-2"]
    Returns empty frozenset if not present.
    """
    raw = frontmatter.get("provenance", [])
    if isinstance(raw, list):
        return frozenset(str(x) for x in raw)
    return frozenset()


def labeled_read(path: Path) -> Labeled[str]:
    """Read a file and wrap its body in a Labeled[str] with consent metadata (DD-12).

    This is the IFC enforcement boundary at file reads. The returned
    Labeled value carries the file's consent label and provenance,
    enabling downstream governance checks via GovernorWrapper.

    Files without consent_label get ConsentLabel.bottom() (public data).
    """
    fm, body = parse_frontmatter(path)
    label = extract_consent_label(fm) or ConsentLabel.bottom()
    provenance = extract_provenance(fm)
    return Labeled(value=body, label=label, provenance=provenance)

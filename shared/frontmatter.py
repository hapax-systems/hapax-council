"""shared/frontmatter.py — Canonical frontmatter parser.

Returns (metadata_dict, body_text) tuple. Supersedes vault_utils.parse_frontmatter
which returns only the dict.

Extended with consent label extraction (DD-11) and labeled file reading (DD-12)
for IFC enforcement at filesystem boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from shared.governance.consent_label import ConsentLabel
from shared.governance.labeled import Labeled
from shared.sdlc_lifecycle import is_frontmatter_fence

FrontmatterErrorKind = Literal[
    "read_error",
    "missing_frontmatter",
    "missing_closing_marker",
    "yaml_error",
    "not_mapping",
]


@dataclass(frozen=True)
class FrontmatterParseResult:
    """Canonical diagnostic result for markdown YAML frontmatter parsing."""

    frontmatter: dict[str, Any] | None
    body: str
    error_kind: FrontmatterErrorKind | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_kind is None and self.frontmatter is not None


def parse_frontmatter(path_or_text: Path | str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from a markdown file or string.

    Args:
        path_or_text: A Path to read from disk, or a string to parse directly.

    Returns:
        (frontmatter_dict, body_text). Returns ({}, full_text) on any failure.
    """
    result = parse_frontmatter_with_diagnostics(path_or_text)
    if not result.ok:
        if isinstance(path_or_text, Path):
            return {}, result.body
        return {}, path_or_text
    return result.frontmatter or {}, result.body


def parse_frontmatter_with_diagnostics(path_or_text: Path | str) -> FrontmatterParseResult:
    """Extract YAML frontmatter with structured failure information."""
    if isinstance(path_or_text, Path):
        try:
            text = path_or_text.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return FrontmatterParseResult(
                frontmatter=None,
                body="",
                error_kind="read_error",
                error_message=str(exc),
            )
    else:
        text = path_or_text

    # Fence detection is the SHARED grammar (``is_frontmatter_fence``): ``---``
    # at column 0, followed by end-of-line or whitespace. A substring scan for
    # "\n---" also matched `---extra: abc` (a legal mapping key) and an indented
    # `---` inside a literal scalar, truncating the block there and silently
    # dropping every field below — on the SDLC path, a task's declared review
    # requirement, so a row closed unreviewed because its metadata was cut in
    # half. Importing the predicate rather than restating it is deliberate: this
    # parser and the SDLC one disagreeing about what a fence is was itself a
    # defect.
    lines = text.split("\n")
    if not is_frontmatter_fence(lines[0]):
        return FrontmatterParseResult(
            frontmatter=None,
            body=text,
            error_kind="missing_frontmatter",
            error_message="document does not start with YAML frontmatter",
        )

    close_index = None
    for index in range(1, len(lines)):
        if is_frontmatter_fence(lines[index]):
            close_index = index
            break
    if close_index is None:
        return FrontmatterParseResult(
            frontmatter=None,
            body=text,
            error_kind="missing_closing_marker",
            error_message="frontmatter closing marker is missing",
        )

    yaml_text = "\n".join(lines[1:close_index]).strip()
    body = "\n".join(lines[close_index + 1 :]).lstrip("\n")
    if not yaml_text:
        return FrontmatterParseResult(frontmatter={}, body=body)

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return FrontmatterParseResult(
            frontmatter=None,
            body=text,
            error_kind="yaml_error",
            error_message=str(exc),
        )
    if not isinstance(data, dict):
        return FrontmatterParseResult(
            frontmatter=None,
            body=text,
            error_kind="not_mapping",
            error_message="frontmatter must be a YAML mapping",
        )
    return FrontmatterParseResult(frontmatter=data, body=body)


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

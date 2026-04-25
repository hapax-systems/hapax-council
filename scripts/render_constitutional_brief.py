#!/usr/bin/env python3
"""Render the Constitutional Brief publish-side artifacts.

Reads ``docs/audience/constitutional-brief.md`` (or any markdown file
declaring the V5 byline-variant + unsettled-variant +
surface-deviation-matrix-key frontmatter), composes the publish-time
:class:`AttributionBlock` per
:data:`shared.attribution_block.SURFACE_DEVIATION_MATRIX`, and returns
the publish-shaped artifact metadata.

Per the V5 weave Constitutional Brief outline §Approval queue:
    full draft (wk1 d5-6) lands as docs/audience/constitutional-brief.md
    — 9-12k word source-of-truth, then PDF render via Pandoc + Eisvogel
    template.

This module closes the source-to-publish substrate: the brief source
(#1436) declares variant references; this renderer assembles the
publish-time attribution block with the operator's legal name (from
``HAPAX_OPERATOR_NAME`` env var) and ORCID iD (from
``shared.orcid.operator_orcid()``). Pandoc PDF render is a follow-on
that consumes the assembled artifact metadata.

Per the operator-referent policy: the legal name lives in pass-store /
env, never in markdown source — the source carries variant references,
publish-time injection produces the final attribution. This separation
is also why ``pii-guard.sh`` rejects markdown files containing the
legal-name pattern: source files must point at the variant, not bake
in the rendered prose.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agents.authoring.byline import (
    Byline,
    BylineCoauthor,
    BylineVariant,
)
from shared.attribution_block import (
    SURFACE_DEVIATION_MATRIX,
    AttributionBlock,
    NonEngagementForm,
    UnsettledContributionVariant,
    render_attribution_block,
)

OPERATOR_NAME_ENV: str = "HAPAX_OPERATOR_NAME"
OPERATOR_NAME_FALLBACK: str = "The Operator"


@dataclass(frozen=True)
class PublishArtifact:
    """Bundle of everything a publisher needs at publish-time.

    Carries the rendered :class:`AttributionBlock` plus the surface
    key and the source body (frontmatter-stripped). Publishers compose
    the final on-surface text from these fields.
    """

    surface_key: str
    attribution: AttributionBlock
    body: str
    frontmatter: dict[str, Any]


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown text into (frontmatter dict, body str).

    Returns ``({}, text)`` if no frontmatter delimiter pair is found.
    Frontmatter is the first ``---`` ... ``---`` block at the top of
    the file.
    """
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    # Strip the leading delimiter and find the closing one.
    after_open = text.split("\n", 1)[1] if "\n" in text else ""
    end_idx = after_open.find("\n---\n")
    if end_idx == -1:
        end_idx = after_open.find("\n---\r\n")
    if end_idx == -1:
        return {}, text
    fm_text = after_open[:end_idx]
    body = after_open[end_idx + len("\n---\n") :]
    parsed = yaml.safe_load(fm_text)
    if not isinstance(parsed, dict):
        return {}, text
    return parsed, body


def _resolve_byline_variant(name: str) -> BylineVariant:
    """Map a frontmatter string ('V2') to the enum value."""
    return BylineVariant[name]


def _resolve_unsettled_variant(name: str) -> UnsettledContributionVariant:
    """Map a frontmatter string ('V3') to the enum value."""
    return UnsettledContributionVariant[name]


def _resolve_non_engagement_form(name: str | None) -> NonEngagementForm | None:
    """Map a frontmatter string ('LONG' / 'SHORT') to the enum value, or None."""
    if name is None:
        return None
    return NonEngagementForm[name.upper()]


def _operator_legal_name() -> str:
    """Return the operator's legal name from env, or a placeholder.

    The render scaffold uses ``HAPAX_OPERATOR_NAME``; if absent, falls
    back to a non-formal placeholder. Publishers that require a real
    legal name (Zenodo creators, ORCID-bearing entries) must validate
    the env separately and fail loudly when it is unset.
    """
    name = os.environ.get(OPERATOR_NAME_ENV, "").strip()
    return name or OPERATOR_NAME_FALLBACK


def render_publish_artifact(md_path: Path) -> PublishArtifact:
    """Compose the publish-time artifact metadata for ``md_path``.

    Reads the markdown file, parses frontmatter, looks up the surface
    matrix entry, constructs a :class:`Byline` with the operator's
    legal name and Hapax + Claude Code as coauthors, calls
    :func:`render_attribution_block`, and returns the
    :class:`PublishArtifact` bundle.

    Frontmatter shape required:

      authors:
        byline_variant: <V0..V5>
        unsettled_variant: <V1..V5>
        surface_deviation_matrix_key: <matrix key>

    Optional:

      non_engagement_clause_form: <SHORT | LONG>  # overrides matrix entry
    """
    text = md_path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)

    authors_block = fm.get("authors", {}) if isinstance(fm.get("authors"), dict) else {}
    byline_variant_name = authors_block.get("byline_variant", "V2")
    unsettled_variant_name = authors_block.get("unsettled_variant", "V3")
    surface_key = authors_block.get("surface_deviation_matrix_key", "philarchive")

    byline_variant = _resolve_byline_variant(byline_variant_name)
    unsettled_variant = _resolve_unsettled_variant(unsettled_variant_name)

    # Per-artifact override of the matrix's non-engagement form, if declared.
    fm_form = _resolve_non_engagement_form(fm.get("non_engagement_clause_form"))
    if fm_form is None:
        matrix_entry = SURFACE_DEVIATION_MATRIX.get(surface_key)
        non_engagement_form = matrix_entry["non_engagement_form"] if matrix_entry else None
    else:
        non_engagement_form = fm_form

    byline = Byline(
        operator_legal_name=_operator_legal_name(),
        coauthors=(
            BylineCoauthor(name="Hapax", role="co-publisher"),
            BylineCoauthor(name="Claude Code", role="substrate"),
        ),
    )
    attribution = render_attribution_block(
        byline,
        byline_variant=byline_variant,
        unsettled_variant=unsettled_variant,
        non_engagement_form=non_engagement_form,
    )

    return PublishArtifact(
        surface_key=surface_key,
        attribution=attribution,
        body=body,
        frontmatter=fm,
    )


def compose_publish_markdown(artifact: PublishArtifact, *, title: str) -> str:
    """Compose the publish-ready markdown form for ``artifact``.

    The publish-ready form is what downstream renderers (Pandoc HTML,
    Pandoc PDF, mkdocs, plain markdown) consume. It carries:

      - title heading
      - byline line (rendered per BylineVariant)
      - unsettled-contribution sentence (italicized)
      - the body (frontmatter-stripped)
      - non-engagement clause footer (when bound)

    No YAML frontmatter is re-emitted in the output. Frontmatter is
    operator-internal (variant references, matrix keys); the publish-
    ready form carries the rendered prose. Re-emitting frontmatter on
    a public surface would leak the operator-internal artifact shape.
    """
    parts: list[str] = []

    parts.append(f"# {title}")
    parts.append("")
    parts.append(f"**{artifact.attribution.byline_text}**")
    parts.append("")
    parts.append(f"*{artifact.attribution.unsettled_sentence}*")
    parts.append("")
    parts.append("---")
    parts.append("")

    body = artifact.body.lstrip("\n")
    # Strip a duplicate top-level title from the body when the source
    # body opens with the same H1; the composed output already has one
    # at the top so we don't want a second below the byline.
    body_lines = body.split("\n")
    if body_lines and body_lines[0].startswith("# "):
        body_lines = body_lines[1:]
        # Drop the leading blank line that typically follows the H1.
        if body_lines and body_lines[0].strip() == "":
            body_lines = body_lines[1:]
    parts.append("\n".join(body_lines))

    if artifact.attribution.non_engagement_clause:
        parts.append("")
        parts.append("---")
        parts.append("")
        parts.append(f"**Non-engagement clause.** {artifact.attribution.non_engagement_clause}")

    parts.append("")
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    """CLI entry point.

    Usage:
      uv run python scripts/render_constitutional_brief.py [<md_path>]

    Default ``md_path`` is ``docs/audience/constitutional-brief.md``.
    Prints the rendered byline + unsettled sentence + non-engagement
    clause to stdout, one labeled line each. Suitable for a CI smoke
    that asserts the brief renders cleanly.
    """
    if len(argv) > 1:
        path = Path(argv[1])
    else:
        path = Path("docs/audience/constitutional-brief.md")

    if not path.exists():
        sys.stderr.write(f"ERROR: source not found: {path}\n")
        return 2

    result = render_publish_artifact(path)
    print(f"surface: {result.surface_key}")
    print(f"byline: {result.attribution.byline_text}")
    print(f"byline_variant: {result.attribution.byline_variant.name}")
    print(f"unsettled_variant: {result.attribution.unsettled_variant.name}")
    print(f"unsettled_sentence: {result.attribution.unsettled_sentence}")
    if result.attribution.non_engagement_clause:
        print(
            "non_engagement_clause:",
            result.attribution.non_engagement_clause[:120] + "...",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


__all__ = [
    "OPERATOR_NAME_ENV",
    "OPERATOR_NAME_FALLBACK",
    "PublishArtifact",
    "compose_publish_markdown",
    "render_publish_artifact",
]

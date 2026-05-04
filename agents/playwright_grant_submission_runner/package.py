"""Universal grant-package reader.

The operator authors a single grant-application-package markdown file
in the vault (cc-task ``immediate-q2-2026-grant-submission-batch``).
This module parses that file into a typed :class:`UniversalGrantPackage`
that recipes consume to assemble portal-specific form fields.

Format expectations (operator-vault convention, kept loose to avoid
churn on minor heading edits):

* YAML frontmatter with at minimum ``project_name``, ``applicant_name``,
  ``applicant_entity``, ``contact_email``. Other operator-curated
  fields flow through as free-form keys.
* Markdown body containing canonical sections delimited by
  ``## <section_name>`` headers. Recognised section names:
  ``abstract``, ``problem_statement``, ``approach``, ``constitutional_disclosure``,
  ``budget``, ``timeline``, ``team``. Unknown sections are kept in
  ``extra_sections`` for recipe-specific framing.

The constitutional-disclosure section is treated specially: the
runner verifies it appears verbatim in every submission's preview.
A missing or empty disclosure section is a HARD ERROR — the runner
refuses to continue.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Per the operator-vault convention.
DEFAULT_PACKAGE_VAULT_PATH: Path = Path.home() / (
    "Documents/Personal/20-projects/hapax-cc-tasks/active/grant-application-package-q2-2026.md"
)

CANONICAL_SECTIONS: frozenset[str] = frozenset(
    {
        "abstract",
        "problem_statement",
        "approach",
        "constitutional_disclosure",
        "budget",
        "timeline",
        "team",
    }
)


@dataclass(frozen=True)
class UniversalGrantPackage:
    """The operator's grant-application package, parsed.

    Recipes read fields off this instance to fill portal form fields.
    Pydantic-equivalent invariants (frontmatter shape, disclosure
    presence) are enforced at parse time in :func:`load_universal_package`.
    """

    project_name: str
    applicant_name: str
    applicant_entity: str
    contact_email: str
    abstract: str
    problem_statement: str
    approach: str
    constitutional_disclosure: str
    budget: str = ""
    timeline: str = ""
    team: str = ""
    extra_sections: dict[str, str] = field(default_factory=dict)
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def primary_text_for_section(self, section: str) -> str:
        """Return the body text for ``section``, falling back to extras."""

        canonical = getattr(self, section, None)
        if canonical:
            return canonical
        return self.extra_sections.get(section, "")


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<frontmatter>.*?)\n---\s*\n(?P<body>.*)\Z",
    flags=re.DOTALL,
)
_SECTION_RE = re.compile(r"^##\s+(?P<title>[^\n]+?)\s*$", flags=re.MULTILINE)


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Lightweight YAML-frontmatter parser.

    The operator vault's grant package frontmatter is shallow (string
    values, no nested mappings) so a full PyYAML dependency is overkill.
    Lines like ``key: value`` are split on the first colon. Comments
    and blank lines are skipped.
    """

    out: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _split_sections(body: str) -> dict[str, str]:
    """Split markdown body on ``## <heading>`` markers.

    Section keys are normalised to ``snake_case`` so canonical lookups
    work regardless of how the operator capitalised the heading.
    """

    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return sections
    for idx, match in enumerate(matches):
        title = match.group("title").strip().lower()
        # Normalise to snake_case (spaces / dashes → underscore).
        key = re.sub(r"[^a-z0-9]+", "_", title).strip("_")
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        section_body = body[start:end].strip()
        if key:
            sections[key] = section_body
    return sections


def load_universal_package(
    path: Path | None = None,
    *,
    text: str | None = None,
) -> UniversalGrantPackage:
    """Parse the universal grant package markdown into a typed instance.

    Either ``path`` (read from disk) or ``text`` (parse a string in-
    memory, used by tests) must be supplied. The function validates
    that the constitutional-disclosure section is present and non-
    empty — a missing disclosure is a hard error so the runner cannot
    submit without it.
    """

    if text is None:
        target = path if path is not None else DEFAULT_PACKAGE_VAULT_PATH
        if not target.exists():
            raise FileNotFoundError(
                f"universal grant package not found at {target} — "
                "operator authors this file under cc-task "
                "immediate-q2-2026-grant-submission-batch"
            )
        text = target.read_text(encoding="utf-8")

    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError("grant package missing YAML frontmatter — first line must be '---'")

    frontmatter = _parse_frontmatter(match.group("frontmatter"))
    sections = _split_sections(match.group("body"))

    required_frontmatter = (
        "project_name",
        "applicant_name",
        "applicant_entity",
        "contact_email",
    )
    missing_fm = [key for key in required_frontmatter if not frontmatter.get(key)]
    if missing_fm:
        raise ValueError(f"grant package frontmatter missing required keys: {missing_fm}")

    required_sections = ("abstract", "problem_statement", "approach", "constitutional_disclosure")
    missing_sections = [key for key in required_sections if not sections.get(key)]
    if missing_sections:
        raise ValueError(f"grant package missing required sections: {missing_sections}")

    extras = {key: value for key, value in sections.items() if key not in CANONICAL_SECTIONS}

    return UniversalGrantPackage(
        project_name=frontmatter["project_name"],
        applicant_name=frontmatter["applicant_name"],
        applicant_entity=frontmatter["applicant_entity"],
        contact_email=frontmatter["contact_email"],
        abstract=sections["abstract"],
        problem_statement=sections["problem_statement"],
        approach=sections["approach"],
        constitutional_disclosure=sections["constitutional_disclosure"],
        budget=sections.get("budget", ""),
        timeline=sections.get("timeline", ""),
        team=sections.get("team", ""),
        extra_sections=extras,
        extra_metadata={
            key: value for key, value in frontmatter.items() if key not in required_frontmatter
        },
    )


__all__ = [
    "CANONICAL_SECTIONS",
    "DEFAULT_PACKAGE_VAULT_PATH",
    "UniversalGrantPackage",
    "load_universal_package",
]

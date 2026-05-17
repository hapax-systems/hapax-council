"""Typed queryable refusal registry — indexes all refusal briefs.

Parses the 47 refusal brief markdown files and exposes them as typed
Pydantic models queryable by axiom, surface, and status. The registry
is the single source of truth for refusal governance at runtime.
"""

from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

BRIEFS_DIR = Path(__file__).resolve().parent.parent / "docs" / "refusal-briefs"


class RefusalStatus(StrEnum):
    REFUSED = "refused"
    LIFTED = "lifted"
    REGRESSED = "regressed"


class RefusalEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str
    file: str
    title: str
    status: RefusalStatus
    axiom_tags: list[str]
    classification: str
    date: str
    ci_guard: str | None = None
    receive_only_exception: str | None = None
    lift_condition_type: str | None = None


def _parse_header_field(content: str, field: str) -> str:
    pattern = rf"^\*\*{re.escape(field)}:\*\*\s*(.+)$"
    match = re.search(pattern, content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _parse_brief(path: Path) -> RefusalEntry | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    slug_raw = _parse_header_field(content, "Slug")
    slug = re.sub(r"[`\s]", "", slug_raw) if slug_raw else path.stem

    axiom_raw = _parse_header_field(content, "Axiom tag")
    axiom_tags: list[str] = []
    if axiom_raw:
        for chunk in re.split(r"[,;]", axiom_raw):
            chunk = re.sub(r"[`]", "", chunk).strip()
            for tag in chunk.split("+"):
                tag = tag.strip()
                if tag:
                    axiom_tags.append(tag)

    status_raw = _parse_header_field(content, "Status")
    if "REFUSED" in status_raw.upper():
        status = RefusalStatus.REFUSED
    elif "LIFTED" in status_raw.upper():
        status = RefusalStatus.LIFTED
    elif "REGRESSED" in status_raw.upper():
        status = RefusalStatus.REGRESSED
    else:
        status = RefusalStatus.REFUSED

    classification = _parse_header_field(content, "Refusal classification")
    date = _parse_header_field(content, "Date")
    ci_guard = _parse_header_field(content, "CI guard") or None

    receive_only = None
    if "Receive-Only Exception" in content:
        receive_only = slug

    lift_type = None
    if "Lift conditions" in content:
        lift_section = content.split("## Lift conditions")[-1][:500]
        if "permanent" in lift_section.lower():
            lift_type = "permanent"
        elif "conditional" in lift_section.lower() or "when" in lift_section.lower():
            lift_type = "conditional"
        else:
            lift_type = "lifecycle_probe"

    return RefusalEntry(
        slug=slug,
        file=path.name,
        title=title,
        status=status,
        axiom_tags=axiom_tags,
        classification=classification,
        date=date,
        ci_guard=ci_guard,
        receive_only_exception=receive_only,
        lift_condition_type=lift_type,
    )


@lru_cache(maxsize=1)
def load_registry(briefs_dir: Path | None = None) -> list[RefusalEntry]:
    """Load and parse all refusal briefs into typed entries."""
    d = briefs_dir or BRIEFS_DIR
    entries: list[RefusalEntry] = []
    for path in sorted(d.glob("*.md")):
        if path.name.startswith("_"):
            continue
        entry = _parse_brief(path)
        if entry is not None:
            entries.append(entry)
    return entries


def query_by_axiom(axiom: str, *, registry: list[RefusalEntry] | None = None) -> list[RefusalEntry]:
    """Return all entries tagged with the given axiom."""
    entries = registry if registry is not None else load_registry()
    return [e for e in entries if axiom in e.axiom_tags]


def query_by_status(status: RefusalStatus, *, registry: list[RefusalEntry] | None = None) -> list[RefusalEntry]:
    """Return all entries with the given status."""
    entries = registry if registry is not None else load_registry()
    return [e for e in entries if e.status == status]


def query_by_surface(surface: str, *, registry: list[RefusalEntry] | None = None) -> list[RefusalEntry]:
    """Return entries whose slug or classification contains the surface term."""
    entries = registry if registry is not None else load_registry()
    term = surface.lower()
    return [e for e in entries if term in e.slug.lower() or term in e.classification.lower()]

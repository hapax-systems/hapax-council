"""Refusal Brief Zenodo deposit publisher.

Per cc-task ``xprom-refusal-as-related-identifier`` and drop-5 fresh-
pattern §2: each Refusal Brief gets its own Zenodo deposit whose
``related_identifiers`` graph carries refusal-shaped edges
(``IsRequiredBy`` to the target surface's hypothetical deposit;
``IsObsoletedBy`` to sibling refusals). This makes refusal nodes
first-class participants in the DataCite citation graph.

This module ships the substrate:

  - ``RefusalBriefPublisher(Publisher)`` — Zenodo deposit publisher
    specialized for the refusal-brief deposit type
  - ``compose_refusal_related_identifiers(target, siblings)`` — builds
    the refusal-shaped RelatedIdentifier graph edges
  - ``scan_refused_cc_tasks(active_dir)`` — yields ``RefusedTaskSummary``
    for every cc-task with ``automation_status: REFUSED``

Daemon path (was previously called "Phase 2") has shipped:

  - ``agents/publication_bus/refusal_brief_daemon.py`` — vault scanner
    over ``active/`` + ``closed/`` cc-task dirs with ``--dry-run`` (default)
    and ``--commit`` (opt-in mint) modes; depends on a ``zenodo/api-token``
    pass entry to mint live deposits.
  - ``agents/refusal_brief_zenodo_adapter/`` — orchestrator-side
    adapter so the publish-orchestrator queue can dispatch refusal
    artifacts through this publisher.

Open gap: there is no ``hapax-refusal-brief-daemon.{service,timer}``
mounting the daemon on a cadence today (the existing
``hapax-refusal-brief-rotate.{service,timer}`` is for log rotation,
not deposit minting). When the operator wants continuous Phase 2
minting, a follow-up cc-task should mount the daemon as a systemd
user unit + timer alongside the other publication-bus daemons.

The deposit shape:
- type=publication, subtype=other, title="Refused: <slug>"
- description carries the constitutional + TOS rationale
- creators = Hapax + Claude Code (authorship-indeterminacy stance)
- related_identifiers = compose_refusal_related_identifiers(...)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)
from agents.publication_bus.related_identifier import (
    IdentifierType,
    RelatedIdentifier,
    RelationType,
)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

REFUSAL_DEPOSIT_SURFACE: str = "zenodo-refusal-deposit"
"""Stable surface identifier; mirrored in the canonical
:data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

REFUSAL_DEPOSIT_TYPE: str = "refusal-brief"
"""Hapax-internal deposit-type tag carried in the deposit description
+ keywords. Surfaces in DataCite as a discoverable refusal artefact."""

ZENODO_DEPOSIT_ENDPOINT: str = "https://zenodo.org/api/deposit/depositions"
"""Zenodo REST API depositions endpoint. Refusal-deposits use the
same endpoint as standard deposits; the deposit-type discrimination
is metadata-side."""

ZENODO_REQUEST_TIMEOUT_S: float = 60.0
"""Refusal deposits are small JSON; 60s is generous."""

DEFAULT_REFUSAL_DEPOSIT_ALLOWLIST: AllowlistGate = load_allowlist(
    REFUSAL_DEPOSIT_SURFACE,
    permitted=[
        # cc-task ``refusal-brief-article-50-case-study`` (2026-05-04).
        # Operator-curated entry: the Article 50 case-study deposit is
        # the first concrete refusal-brief shipped through this surface.
        "refusal-brief-article-50-case-study",
        # cc-task ``polysemic-7-channel-artifact-compounder`` (2026-05-05).
        # Repository-staged refusal artifact; pure composer + metadata only.
        "polysemic-7-channel-artifact-compounder",
    ],
)
"""Operator-curated refusal-brief allowlist — entries here are
authorized to mint a Zenodo refusal-deposit DOI. Subclass publishers
may extend via class-level reassignment."""


@dataclass(frozen=True)
class RefusedTaskSummary:
    """One scan result: a cc-task note with ``automation_status: REFUSED``.

    Carries the minimum info the publisher daemon needs to compose a
    Refusal Brief deposit: the task slug for cross-linking back to the
    vault, the title for human-readable deposit naming, the
    refusal_reason for the description, and the source path for the
    frontmatter writeback in Phase 2.
    """

    task_id: str
    title: str
    refusal_reason: str
    file_path: Path


def compose_refusal_related_identifiers(
    *,
    target_surface_doi: str,
    sibling_refusal_dois: list[str],
) -> list[RelatedIdentifier]:
    """Build the refusal-shaped RelatedIdentifier graph edges.

    Returns one ``IsRequiredBy`` edge to the target surface's
    hypothetical deposit DOI (showing what would be required for the
    refusal to lift), plus one ``IsObsoletedBy`` edge per sibling
    refusal DOI (a DataCite-shaped representation of the refusal-
    superseding pattern).

    All edges use ``IdentifierType.DOI``; PLACEHOLDER DOIs for
    surfaces that don't yet have deposits are valid — DataCite
    accepts unresolved DOIs in the graph (they appear as orphan
    nodes until the target deposit lands).
    """
    edges: list[RelatedIdentifier] = []
    edges.append(
        RelatedIdentifier(
            identifier=target_surface_doi,
            identifier_type=IdentifierType.DOI,
            relation_type=RelationType.IS_REQUIRED_BY,
        )
    )
    edges.extend(
        RelatedIdentifier(
            identifier=sibling_doi,
            identifier_type=IdentifierType.DOI,
            relation_type=RelationType.IS_OBSOLETED_BY,
        )
        for sibling_doi in sibling_refusal_dois
    )
    return edges


_FRONTMATTER_DELIM_RE = re.compile(r"^---\s*$", re.MULTILINE)


def scan_refused_cc_tasks(active_dir: Path) -> Iterator[RefusedTaskSummary]:
    """Yield :class:`RefusedTaskSummary` for every refused cc-task.

    Walks ``active_dir`` for ``*.md`` files, parses YAML frontmatter
    (no PyYAML dep — minimal regex-based parser sufficient for the
    flat-key shape cc-tasks use), and yields one summary per file
    with ``automation_status: REFUSED``.

    Returns nothing for missing directories — refusal scanning is
    best-effort; the daemon should not crash on a missing vault.
    """
    if not active_dir.is_dir():
        return
    for md_file in sorted(active_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        frontmatter = _extract_frontmatter(text)
        if not frontmatter:
            continue
        if frontmatter.get("automation_status", "").strip().strip("'\"") != "REFUSED":
            continue
        yield RefusedTaskSummary(
            task_id=frontmatter.get("task_id", md_file.stem).strip().strip("'\""),
            title=frontmatter.get("title", "").strip().strip("'\""),
            refusal_reason=frontmatter.get("refusal_reason", "").strip().strip("'\""),
            file_path=md_file,
        )


def _extract_frontmatter(text: str) -> dict[str, str]:
    """Parse the flat-key YAML frontmatter from a cc-task note.

    Minimal parser sufficient for the cc-task shape: top-level
    ``key: value`` lines between two ``---`` delimiters. Does not
    handle nested structures or multiline values — cc-tasks don't
    use them at the top level.
    """
    matches = list(_FRONTMATTER_DELIM_RE.finditer(text))
    if len(matches) < 2:
        return {}
    body = text[matches[0].end() : matches[1].start()]
    out: dict[str, str] = {}
    for line in body.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


class RefusalBriefPublisher(Publisher):
    """Zenodo-backed refusal-brief deposit publisher.

    ``payload.target`` is the cc-task slug being refused (e.g.,
    ``bandcamp-upload``); ``payload.text`` is the refusal description
    body (typically rendered from the cc-task's `refusal_reason`
    + constitutional context). ``payload.metadata`` may include
    ``title`` and ``related_identifiers`` (list of dicts in Zenodo's
    REST shape).

    Refusal-as-data on missing Zenodo token. ``requires_legal_name=True``
    because Zenodo's creators array uses the formal name (legal-name
    leak guard skipped on this surface).
    """

    surface_name: ClassVar[str] = REFUSAL_DEPOSIT_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_REFUSAL_DEPOSIT_ALLOWLIST
    requires_legal_name: ClassVar[bool] = True

    def __init__(self, *, zenodo_token: str) -> None:
        self.zenodo_token = zenodo_token

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not self.zenodo_token:
            return PublisherResult(
                refused=True,
                detail=(
                    "missing Zenodo credentials "
                    "(operator-action queue: configure Zenodo PAT in pass)"
                ),
            )
        if requests is None:
            return PublisherResult(error=True, detail="requests library not available")

        title = str(payload.metadata.get("title") or f"Refused: {payload.target}")
        deposit_metadata = {
            "title": title,
            "upload_type": "publication",
            "publication_type": "other",
            "description": payload.text,
            "keywords": [REFUSAL_DEPOSIT_TYPE, "refusal-as-data", payload.target],
        }
        if "related_identifiers" in payload.metadata:
            deposit_metadata["related_identifiers"] = payload.metadata["related_identifiers"]
        body = {"metadata": deposit_metadata}
        headers = {
            "Authorization": f"Bearer {self.zenodo_token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                ZENODO_DEPOSIT_ENDPOINT,
                json=body,
                headers=headers,
                timeout=ZENODO_REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            log.warning("Zenodo refusal-deposit POST raised: %s", exc)
            return PublisherResult(error=True, detail=f"transport failure: {exc}")

        status = response.status_code
        if 200 <= status < 300:
            try:
                doi = response.json().get("doi", "<unknown>")
            except (ValueError, AttributeError):
                doi = "<unparseable>"
            return PublisherResult(
                ok=True,
                detail=f"refusal deposit minted: {doi} for {payload.target!r}",
            )
        return PublisherResult(
            error=True,
            detail=f"Zenodo refusal-deposit POST HTTP {status}: {response.text[:160]}",
        )


__all__ = [
    "DEFAULT_REFUSAL_DEPOSIT_ALLOWLIST",
    "REFUSAL_DEPOSIT_SURFACE",
    "REFUSAL_DEPOSIT_TYPE",
    "RefusalBriefPublisher",
    "RefusedTaskSummary",
    "ZENODO_DEPOSIT_ENDPOINT",
    "ZENODO_REQUEST_TIMEOUT_S",
    "compose_refusal_related_identifiers",
    "scan_refused_cc_tasks",
]

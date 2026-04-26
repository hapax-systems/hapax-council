"""Canonical V5 publication-bus surface registry.

Per V5 weave §2.1 PUB-P0-B follow-on
(``pub-bus-zenodo-related-identifier-graph`` task). Single source of
truth for which surfaces the publication-bus engages, refuses, or
treats as conditional.

Three automation tiers:

- ``FULL_AUTO`` — daemon-side end-to-end; no operator action per
  publish-event after one-time credential bootstrap
- ``CONDITIONAL_ENGAGE`` — bootstrap-on-first-use (one-time human
  action per surface, e.g., logging into Playwright session daemon)
- ``REFUSED`` — surface declined per Refusal Brief; subclass exists
  to record refusal, never to attempt publication

The registry is operator-curated and committed; runtime mutation is
forbidden per the single_user axiom. Each entry references the
appropriate Refusal Brief docs/refusal-briefs/ entry when
``automation_status == REFUSED``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class AutomationStatus(Enum):
    """Automation tier for a publication-bus surface."""

    FULL_AUTO = "FULL_AUTO"
    CONDITIONAL_ENGAGE = "CONDITIONAL_ENGAGE"
    REFUSED = "REFUSED"


@dataclass(frozen=True)
class SurfaceSpec:
    """One publication-bus surface specification.

    Carries the surface's automation status, API style, and (when
    refused) a link to the Refusal Brief docs entry documenting
    why. ``api`` is informational; the actual transport is owned by
    the surface's Publisher subclass.
    """

    automation_status: AutomationStatus
    api: str | None = None
    refusal_link: str | None = None
    scope_note: str | None = None


# Canonical registry. Sorted by automation status, then alphabetically
# within each tier for predictable diff review.
SURFACE_REGISTRY: Final[dict[str, SurfaceSpec]] = {
    # ── FULL_AUTO ──────────────────────────────────────────────────
    "bluesky-atproto-multi-identity": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="ATProto",
    ),
    "bridgy-webmention-publish": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webmention",
    ),
    "datacite-graphql-mirror": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="GraphQL",
    ),
    "internet-archive-ias3": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="S3",
    ),
    "marketing-refusal-annex": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="local-file",
        scope_note="renders refusal annex markdown to ~/hapax-state/publications/",
    ),
    "omg-lol-weblog-bearer-fanout": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
    ),
    "orcid-auto-update": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="OAuth+REST",
        scope_note="concept-DOI granularity only",
    ),
    "osf-prereg": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        scope_note="OSF preregistrations with named-related-work cross-references",
    ),
    "zenodo-deposit": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
    ),
    "zenodo-related-identifier-graph": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
    ),
    # ── CONDITIONAL_ENGAGE ─────────────────────────────────────────
    "philarchive-deposit": SurfaceSpec(
        automation_status=AutomationStatus.CONDITIONAL_ENGAGE,
        api="Playwright",
        scope_note="bootstrap login via Playwright session daemon (one-time)",
    ),
    "alphaxiv-deposit": SurfaceSpec(
        automation_status=AutomationStatus.CONDITIONAL_ENGAGE,
        api="Playwright",
        scope_note="bootstrap login via Playwright session daemon (one-time)",
    ),
    # ── REFUSED ────────────────────────────────────────────────────
    "bandcamp-upload": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/bandcamp-no-upload-api.md",
    ),
    "discogs-submission": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/discogs-tos-forbids.md",
    ),
    "rym-submission": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/rym-no-api.md",
    ),
    "crossref-event-data": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/crossref-event-data-sunset.md",
        scope_note="superseded by DataCite Commons GraphQL surface",
    ),
}


def is_engageable(surface_name: str) -> bool:
    """Return True iff ``surface_name`` has automation_status FULL_AUTO
    or CONDITIONAL_ENGAGE.

    Useful for runtime gates that should not attempt to publish to a
    REFUSED surface even when called erroneously. The Publisher ABC
    does not consult this registry directly (the AllowlistGate is the
    runtime mechanism); this is a higher-level dispatch helper.
    """
    spec = SURFACE_REGISTRY.get(surface_name)
    if spec is None:
        return False
    return spec.automation_status in (
        AutomationStatus.FULL_AUTO,
        AutomationStatus.CONDITIONAL_ENGAGE,
    )


def refused_surfaces() -> list[str]:
    """Return the sorted list of REFUSED surface names.

    Consumed by the Refusal Brief renderer + the operator dashboard's
    "what we don't engage with" panel.
    """
    return sorted(
        name
        for name, spec in SURFACE_REGISTRY.items()
        if spec.automation_status == AutomationStatus.REFUSED
    )


def auto_surfaces() -> list[str]:
    """Return the sorted list of FULL_AUTO surface names."""
    return sorted(
        name
        for name, spec in SURFACE_REGISTRY.items()
        if spec.automation_status == AutomationStatus.FULL_AUTO
    )


__all__ = [
    "SURFACE_REGISTRY",
    "AutomationStatus",
    "SurfaceSpec",
    "auto_surfaces",
    "is_engageable",
    "refused_surfaces",
]

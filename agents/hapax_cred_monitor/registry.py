"""Credential-entry → unblocked-service registry.

Pure data, no I/O. Maps each FileStore secret name (the blob name ``hapax-secret --list``
prints, e.g. ``api-anthropic``) to the set of services or surfaces that gain capability
when the entry arrives.

The registry is the single source of truth for "what does this credential
unblock?" Health-monitor checks, operator-unblocker reports, and the
optional auto-resume path all read this dict.

Adding a new credential: add an ``ExpectedEntry`` to ``EXPECTED_ENTRIES``
naming the entry and the services it unblocks; the remediation is derived
(the one ``hapax-secret`` put instruction). Do NOT include sample values,
partial fingerprints, or any secret material — entry NAMES only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.secrets import put_instruction


@dataclass(frozen=True)
class ExpectedEntry:
    """One FileStore secret the system expects to be populated.

    Attributes:
        name: The secret's blob name, as ``hapax-secret --list`` prints it and as the
            operator types it into the put dialogue (e.g., ``"orcid-orcid"``,
            ``"bluesky-operator-app-password"``).
        unblocks: Services, daemons, or surfaces that gain capability
            when this entry is present. Free-form identifiers
            (systemd unit names, publisher slugs, registry keys).
        category: High-level grouping for operator dashboards.
    """

    name: str
    unblocks: tuple[str, ...]
    category: str = "other"
    notes: str = ""

    @property
    def remediation(self) -> str:
        """The one operator next-action: put this entry with ``hapax-secret``."""
        return put_instruction(self.name)


# Canonical registry of credentials the system can use, by descending
# value-unlocked (per docs/research/operator-action-queue-acceleration.md
# §"Optimal Arrival Order"). Operator-curated; runtime mutation is
# forbidden.
EXPECTED_ENTRIES: tuple[ExpectedEntry, ...] = (
    # ── publication / attribution surfaces ─────────────────────────
    ExpectedEntry(
        name="zenodo-api-token",
        unblocks=(
            "zenodo-deposit-publisher",
            "zenodo-refusal-deposit-publisher",
            "datacite-mirror-phase-2",
            "iscitedby-touch-phase-2",
            "refusal-as-related-identifier-phase-2",
        ),
        category="publication",
        notes="Highest value-unlocked entry: 6 Phase 2 publication-bus tasks.",
    ),
    ExpectedEntry(
        name="orcid-orcid",
        unblocks=(
            "hapax-orcid-verifier.timer",
            "hapax-datacite-mirror.timer",
            "hapax-datacite-snapshot.timer",
            "hapax-self-federate-rss.timer",
        ),
        category="attribution",
        notes="ORCID iD (public identifier; not a secret value but stored uniformly).",
    ),
    ExpectedEntry(
        name="omg-lol-api-key",
        unblocks=(
            "omg-lol-weblog-bearer-fanout",
            "omg_rss_fanout-multi-target",
            "omg-credits-publisher",
        ),
        category="publication",
    ),
    ExpectedEntry(
        name="bluesky-operator-app-password",
        unblocks=("bluesky-atproto-multi-identity",),
        category="publication",
    ),
    ExpectedEntry(
        name="bluesky-operator-did",
        unblocks=("bluesky-atproto-multi-identity",),
        category="publication",
    ),
    ExpectedEntry(
        name="osf-api-token",
        unblocks=(
            "osf-prereg-publisher",
            "osf-related-works-selection-daemon",
        ),
        category="publication",
    ),
    ExpectedEntry(
        name="ia-access-key",
        unblocks=("internet-archive-ias3-publisher",),
        category="archival",
    ),
    ExpectedEntry(
        name="ia-secret-key",
        unblocks=("internet-archive-ias3-publisher",),
        category="archival",
    ),
    ExpectedEntry(
        name="crossref-depositor-credentials",
        unblocks=("crossref-depositor",),
        category="publication",
        notes="Membership-required; unlikely bottleneck.",
    ),
    ExpectedEntry(
        name="philarchive-session-cookie",
        unblocks=("philarchive-deposit-publisher",),
        category="publication",
    ),
    ExpectedEntry(
        name="philarchive-author-id",
        unblocks=("philarchive-deposit-publisher",),
        category="publication",
    ),
    # ── core infra (already typically present) ─────────────────────
    ExpectedEntry(
        name="api-anthropic",
        unblocks=("litellm-claude-routes",),
        category="infra",
    ),
    ExpectedEntry(
        name="api-google",
        unblocks=("litellm-gemini-routes",),
        category="infra",
    ),
    ExpectedEntry(
        name="litellm-master-key",
        unblocks=("litellm-gateway",),
        category="infra",
    ),
    ExpectedEntry(
        name="langfuse-public-key",
        unblocks=("langfuse-tracing",),
        category="infra",
    ),
    ExpectedEntry(
        name="langfuse-secret-key",
        unblocks=("langfuse-tracing",),
        category="infra",
    ),
)


def expected_entry_names() -> frozenset[str]:
    """Return the canonical set of expected entry names."""
    return frozenset(e.name for e in EXPECTED_ENTRIES)


def lookup(entry_name: str) -> ExpectedEntry | None:
    """Return the registry entry for ``entry_name`` or ``None``."""
    for entry in EXPECTED_ENTRIES:
        if entry.name == entry_name:
            return entry
    return None


def services_unblocked_by(entry_names: frozenset[str]) -> frozenset[str]:
    """Return the union of services unblocked by the given entry names."""
    services: set[str] = set()
    for name in entry_names:
        entry = lookup(name)
        if entry is not None:
            services.update(entry.unblocks)
    return frozenset(services)


@dataclass(frozen=True)
class CategoryView:
    """Per-category breakdown of present/missing entries."""

    category: str
    present: tuple[str, ...] = field(default_factory=tuple)
    missing: tuple[str, ...] = field(default_factory=tuple)


def categorize(present: frozenset[str], missing: frozenset[str]) -> tuple[CategoryView, ...]:
    """Group present + missing entry names by registry category."""
    categories: dict[str, list[list[str]]] = {}
    for entry in EXPECTED_ENTRIES:
        cat = categories.setdefault(entry.category, [[], []])
        if entry.name in present:
            cat[0].append(entry.name)
        elif entry.name in missing:
            cat[1].append(entry.name)
    return tuple(
        CategoryView(category=cat, present=tuple(sorted(p)), missing=tuple(sorted(m)))
        for cat, (p, m) in sorted(categories.items())
    )

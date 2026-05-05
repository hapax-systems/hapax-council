"""Polysemic 7-channel refusal artifact composer.

Closes cc-task ``polysemic-7-channel-artifact-compounder``. The module is a
pure publication-bus composer: it prepares a refusal-brief deposit body,
Zenodo-shaped metadata, RelatedIdentifier edges, and braid frontmatter for
the first deliberate artifact that saturates all seven Manifesto v0 decoder
channels.

No network, credential, or live publish action happens here. The output is
safe for tests and for a later production owner to pass through
``RefusalBriefPublisher`` when the operator authorizes an external deposit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from agents.publication_bus.related_identifier import (
    IdentifierType,
    RelatedIdentifier,
    RelationType,
)

__all__ = [
    "POLYSEMIC_ARTIFACT_BRAID_SCORE",
    "POLYSEMIC_ARTIFACT_CHANNEL_BONUS",
    "POLYSEMIC_ARTIFACT_SLUG",
    "POLYSEMIC_ARTIFACT_TITLE",
    "POLYSEMIC_CHANNELS",
    "DecoderChannel",
    "PolysemicSevenChannelArtifact",
    "braid_frontmatter",
    "build_payload_metadata",
    "compose_related_identifiers",
    "render_brief_body",
]

POLYSEMIC_ARTIFACT_SLUG: str = "polysemic-7-channel-artifact-compounder"
POLYSEMIC_ARTIFACT_TITLE: str = (
    "Refused: single-channel refusal artifacts as sufficient public evidence"
)
POLYSEMIC_ARTIFACT_CHANNEL_BONUS: float = 0.70
POLYSEMIC_ARTIFACT_BRAID_SCORE: float = 5.20


@dataclass(frozen=True)
class DecoderChannel:
    """One Manifesto v0 decoder channel and its artifact surface."""

    channel_id: int
    name: str
    artifact_surface: str
    evidence: str


POLYSEMIC_CHANNELS: tuple[DecoderChannel, ...] = (
    DecoderChannel(
        1,
        "visual",
        "visual-map.svg",
        "Seven-node refusal map: each decoder channel is a visible node.",
    ),
    DecoderChannel(
        2,
        "sonic",
        "sonic-score.txt",
        "A renderable three-pulse earcon score encodes refuse, compound, attest.",
    ),
    DecoderChannel(
        3,
        "linguistic",
        "source.md",
        "The refusal prose names the declined single-channel posture.",
    ),
    DecoderChannel(
        4,
        "typographic",
        "source.md",
        "The source uses an explicit seven-row typographic channel ledger.",
    ),
    DecoderChannel(
        5,
        "structural-form",
        "metadata.yaml",
        "The directory shape separates source, metadata, evidence, visual, and sonic files.",
    ),
    DecoderChannel(
        6,
        "marker-as-membership",
        "metadata.yaml",
        "The stable slug and channel ids act as repeatable membership markers.",
    ),
    DecoderChannel(
        7,
        "authorship",
        "attribution.yaml",
        "The attribution record keeps authorship indeterminacy visible.",
    ),
)

SUPPLEMENT_TO_DOIS: tuple[str, ...] = (
    "10.5281/zenodo.PLACEHOLDER-hapax-manifesto-v0",
    "10.5281/zenodo.PLACEHOLDER-refusal-brief-general-methodology",
)

REFERENCE_URLS: tuple[str, ...] = (
    "https://github.com/ryanklee/hapax-council/blob/main/docs/superpowers/specs/2026-05-01-braid-schema-v11-design.md",
    "https://github.com/ryanklee/hapax-council/blob/main/docs/published-artifacts/README.md",
)


def braid_frontmatter() -> dict[str, object]:
    """Return the formula-verifiable braid v1.1 vector for the artifact."""

    return {
        "braid_schema": 1.1,
        "braid_engagement": 6,
        "braid_monetary": 4,
        "braid_research": 8,
        "braid_tree_effect": 5,
        "braid_evidence_confidence": 6,
        "braid_risk_penalty": 0,
        "braid_unblock_breadth": 3,
        "braid_polysemic_channels": [channel.channel_id for channel in POLYSEMIC_CHANNELS],
        "braid_funnel_role": "compounder",
        "braid_compounding_curve": "mixed",
        "braid_axiomatic_strain": 0,
        "braid_score": POLYSEMIC_ARTIFACT_BRAID_SCORE,
    }


def compose_related_identifiers() -> list[RelatedIdentifier]:
    """Compose deposit graph edges for the staged refusal artifact."""

    edges: list[RelatedIdentifier] = []
    edges.extend(
        RelatedIdentifier(
            identifier=doi,
            identifier_type=IdentifierType.DOI,
            relation_type=RelationType.IS_SUPPLEMENT_TO,
            resource_type="Text",
        )
        for doi in SUPPLEMENT_TO_DOIS
    )
    edges.extend(
        RelatedIdentifier(
            identifier=url,
            identifier_type=IdentifierType.URL,
            relation_type=RelationType.REFERENCES,
            resource_type="Text",
        )
        for url in REFERENCE_URLS
    )
    return edges


def render_brief_body() -> str:
    """Render the refusal artifact body.

    The body is intentionally concise; the proof is the channel ledger and
    metadata shape, not a long essay.
    """

    channel_rows = "\n".join(
        f"| {channel.channel_id} | {channel.name} | {channel.artifact_surface} | "
        f"{channel.evidence} |"
        for channel in POLYSEMIC_CHANNELS
    )
    return f"""# {POLYSEMIC_ARTIFACT_TITLE}

## What is refused

This artifact refuses the claim that a refusal brief is complete when it is
only prose. For Manifesto v0 work, the refusal must also be legible as
image, sound, typography, structure, membership marker, and authorship trace.

## Why this is refused

Single-channel publication hides the system's actual argument. Hapax is
not only making a sentence-level claim; it is arranging evidence across a
stack of surfaces. Treating the refusal as text alone erases the channel
compound that braid schema v1.1 was built to score.

## Seven-channel ledger

| Channel | Name | Artifact surface | Evidence |
|---|---|---|---|
{channel_rows}

## Braid verification

The v1.1 vector declares channels 1 through 7. The formula adds
0.10 times the number of distinct decoder channels, so this artifact
earns a 0.70 channel bonus. With the declared vector, the computed
score is 5.20; removing the channel list lowers it to 4.50.

## Boundary

This composer does not mint a DOI, post to a public service, or make a
live external commitment. It stages the artifact and its evidence so a
publication owner can later pass it through the normal refusal-deposit
path when the operator authorizes that action.
"""


def build_payload_metadata() -> dict[str, object]:
    """Return Zenodo-shaped metadata plus Hapax-local channel evidence."""

    return {
        "title": POLYSEMIC_ARTIFACT_TITLE,
        "slug": POLYSEMIC_ARTIFACT_SLUG,
        "artifact_type": "refusal-brief-deposit",
        "publication_state": "repository_published",
        "external_publication_state": "not_minted",
        "keywords": [
            "polysemic",
            "refusal-as-data",
            "manifesto-v0",
            "braid-schema-v1.1",
            POLYSEMIC_ARTIFACT_SLUG,
        ],
        "related_identifiers": [edge.to_zenodo_dict() for edge in compose_related_identifiers()],
        "polysemic_channels": [
            {
                "id": channel.channel_id,
                "name": channel.name,
                "artifact_surface": channel.artifact_surface,
                "evidence": channel.evidence,
            }
            for channel in POLYSEMIC_CHANNELS
        ],
        "braid": braid_frontmatter(),
        "braid_channel_bonus": POLYSEMIC_ARTIFACT_CHANNEL_BONUS,
    }


class PolysemicSevenChannelArtifact:
    """Facade matching the publication-bus case-study composer pattern."""

    slug: ClassVar[str] = POLYSEMIC_ARTIFACT_SLUG
    title: ClassVar[str] = POLYSEMIC_ARTIFACT_TITLE

    def body(self) -> str:
        return render_brief_body()

    def metadata(self) -> dict[str, object]:
        return build_payload_metadata()

    def channels(self) -> tuple[DecoderChannel, ...]:
        return POLYSEMIC_CHANNELS

    def related_identifiers(self) -> list[RelatedIdentifier]:
        return compose_related_identifiers()

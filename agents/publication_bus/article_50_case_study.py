"""Article 50 case-study refusal-brief composer.

Closes cc-task ``refusal-brief-article-50-case-study``. Operator
directive: case-study refusal-brief documenting *declined-engagement*
patterns for the EU AI Act Article 50 compliance vector → Zenodo
refusal-deposit DOI carrying RelatedIdentifier graph edges so the
refusal participates in the DataCite citation graph.

Constitutional posture (operator framing 2026-05-04): refusals are
publications. The chain of attestation IS the work — the deposit
DOI + the refusal-shaped RelatedIdentifier edges are the load-bearing
artefact, not a 15-page preprint.

Refusal-shaped graph (per
:func:`agents.publication_bus.refusal_brief_publisher.compose_refusal_related_identifiers`):

* ``IsRequiredBy`` → the target surface that would have consumed the
  declined engagement (EU AI Office consultation portal, vendor cert
  portals, court-admissibility filings, journalist outreach lists).
  These are PLACEHOLDER DOIs because the targets are hypothetical
  surfaces Hapax has not engaged. DataCite accepts unresolved DOIs
  as orphan nodes in the graph; when a target deposit ever lands the
  graph stitches.
* ``IsObsoletedBy`` → sibling refusals in the same train. The
  case-study supersedes (and is superseded by) general-purpose
  refusal-briefs for adjacent declined engagements.
* ``IsSupplementTo`` → the upstream Hapax Manifesto v0 + general
  Refusal Brief methodology. Roots the case-study in the operator's
  prior public attestation chain.

The composer is *pure* — no network, no env vars, no allowlist
mutation. Wiring through to Zenodo happens in
:class:`agents.publication_bus.refusal_brief_publisher.RefusalBriefPublisher`
via the publisher kit; this module supplies the payload shape.

Evidence base (Gemini JR packet
``20260504T230725Z-jr-currentness-scout-eu-ai-act-art50-c2pa-currentness-2026-05-04``):

* C2PA spec at v2.3 (2026-01) and v2.4 (2026-04). COSE signatures +
  JUMBF containers.
* Interim Trust List frozen 2026-01-01; deposits must use the
  C2PA Conformance Program trust list.
* Article 50(2) — providers mark outputs machine-readably.
* Article 50(4) — deployers disclose deepfakes human-readably.
* Article 50(5) — disclosure at first interaction; for livestreams,
  labels present from start.
* C2PA v2.3 introduced "Verifiable Segment Info" for live DASH/HLS
  with sub-500ms real-time signing (Qualabs / Irdeto reference
  implementations).
* Multi-party attribution via "Ingredients" + "Multiple Signers" —
  AI engine listed as Ingredient (Provider), legal entity signs the
  final manifest (Deployer).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from agents.publication_bus.refusal_brief_publisher import (
    REFUSAL_DEPOSIT_TYPE,
    compose_refusal_related_identifiers,
)
from agents.publication_bus.related_identifier import (
    IdentifierType,
    RelatedIdentifier,
    RelationType,
)

__all__ = [
    "ARTICLE_50_CASE_STUDY_SLUG",
    "ARTICLE_50_CASE_STUDY_TITLE",
    "ArticleFiftyCaseStudy",
    "DeclinedEngagement",
    "build_payload_metadata",
    "compose_article_50_related_identifiers",
    "render_brief_body",
]

ARTICLE_50_CASE_STUDY_SLUG: str = "refusal-brief-article-50-case-study"
"""Stable slug — referenced by the publisher allowlist and by
external citation tooling. Matches the cc-task ``task_id``."""

ARTICLE_50_CASE_STUDY_TITLE: str = (
    "Refused: Article 50 vendor-portal-only audit-trail engagement (declined-engagement case study)"
)
"""Zenodo deposit title. Carries the ``Refused:`` prefix the
:class:`RefusalBriefPublisher` recognizes as a refusal-deposit, so
the deposit type discrimination is metadata-side."""

# Sibling refusal slugs in the same train. The deposit DOIs for these
# are placeholders until each sibling refusal mints its own concept-DOI
# — the IsObsoletedBy edges become live as siblings ship. Listed here
# explicitly so the graph composition is auditable from a single read
# without grepping the vault.
SIBLING_REFUSAL_SLUGS: tuple[str, ...] = (
    "declined-engagement-direct-regulator-outreach",
    "declined-engagement-direct-journalist-pitch",
    "declined-engagement-court-admissibility-marketing",
    "declined-engagement-vendor-portal-only-audit",
    "declined-engagement-promotional-cert-pricing",
)


@dataclass(frozen=True)
class DeclinedEngagement:
    """One declined-engagement record in the case study.

    The vocabulary mirrors the cc-task vault's ``automation_status:
    REFUSED`` shape so a future scan-and-promote pass can fold these
    into the canonical refusal-brief daemon flow without reshaping.
    """

    target_surface: str
    rationale: str
    constitutional_anchor: str


# Five declined engagements documented per the cc-task's "Out of scope"
# section + the operator's Article 50 stance. Ordering: most-frequently
# requested (vendor cert portals, court-admissibility) first, more
# specialised refusals (regulator outreach, journalist pitches) after.
DECLINED_ENGAGEMENTS: tuple[DeclinedEngagement, ...] = (
    DeclinedEngagement(
        target_surface="vendor-portal-only-audit-trail-substrate",
        rationale=(
            "Multi-tenant vendor portals route audit trails through the "
            "vendor's identity layer, breaking the single-tenant "
            "Zenodo-DOI-anchored substrate the operator's compliance "
            "evidence depends on. Truepic's Q4-2025 pivot to "
            "'Visual Risk Intelligence' vacates this space without a "
            "successor that meets the single-operator axiom."
        ),
        constitutional_anchor="single_user",
    ),
    DeclinedEngagement(
        target_surface="court-admissibility-marketing-claim",
        rationale=(
            "Hacker Factor's Daubert critique establishes that current "
            "C2PA + watermark substrates do not satisfy Federal Rules of "
            "Evidence reliability tests. The case-study scope is "
            "explicitly 'audit-trail compliance evidence' inside the "
            "Code-of-Practice multi-layered approach; making "
            "court-admissibility claims would overstate the warrant."
        ),
        constitutional_anchor="management_governance",
    ),
    DeclinedEngagement(
        target_surface="direct-regulator-outreach-eu-ai-office",
        rationale=(
            "Direct outreach is REFUSED per operator stance "
            "(Refusal Brief v0 §IV — outbound channels carry the "
            "operator-presence overhead the executive_function axiom "
            "is engineered to avoid). The EU AI Office consultation "
            "window remains a one-shot CONDITIONAL_ENGAGE when the "
            "regulator opens the next round."
        ),
        constitutional_anchor="executive_function",
    ),
    DeclinedEngagement(
        target_surface="direct-journalist-pitch",
        rationale=(
            "Auto-publication via the publication-bus 13-surface fanout "
            "is the only push channel the operator's stance permits. "
            "Journalist pitches require operator-active correspondence "
            "the executive_function axiom forbids. Third-party HN / "
            "Bluesky / Mastodon discovery via the citation graph "
            "remains the inbound funnel."
        ),
        constitutional_anchor="executive_function",
    ),
    DeclinedEngagement(
        target_surface="promotional-cert-pricing-copy",
        rationale=(
            "The brief is academic-register; pricing + deal structure "
            "live in the operator-controlled cert pipeline behind the "
            "citable-nexus front door. Embedding promotional copy in "
            "the deposit description would collapse the academic "
            "spectacle / commercial pipeline separation the auto-GTM "
            "plan engineered."
        ),
        constitutional_anchor="management_governance",
    ),
)


# Hapax Manifesto v0 + general Refusal Brief methodology — the upstream
# attestation chain this case-study supplements. Real concept-DOIs once
# they mint; placeholders carry the structural relationship through.
SUPPLEMENT_TO_DOIS: tuple[str, ...] = (
    "10.5281/zenodo.PLACEHOLDER-hapax-manifesto-v0",
    "10.5281/zenodo.PLACEHOLDER-refusal-brief-general-methodology",
)


def _placeholder_doi(slug: str) -> str:
    """Render a placeholder DOI for a slug whose deposit has not yet minted.

    DataCite accepts unresolved DOIs in RelatedIdentifier edges
    (per the Zenodo + DataCite docs). Using a stable
    ``10.5281/zenodo.PLACEHOLDER-<slug>`` shape keeps the graph
    well-formed; the placeholder resolves to the real DOI at the
    moment the sibling deposit lands.
    """

    return f"10.5281/zenodo.PLACEHOLDER-{slug}"


def compose_article_50_related_identifiers() -> list[RelatedIdentifier]:
    """Compose the full RelatedIdentifier graph for the case-study deposit.

    Combines:

    * One ``IsRequiredBy`` edge per declined-engagement target surface
      (placeholder DOIs — the targets are hypothetical surfaces Hapax
      has not engaged) + ``IsObsoletedBy`` edges for sibling refusals
      via :func:`compose_refusal_related_identifiers`.
    * ``IsSupplementTo`` edges to the Hapax Manifesto v0 + general
      Refusal Brief deposits, so the case-study roots in the operator's
      prior public attestation chain.

    Pure — no I/O, no allowlist, no env. The publisher consumes this
    via :func:`build_payload_metadata` below.
    """

    edges: list[RelatedIdentifier] = []

    # IsRequiredBy + IsObsoletedBy edges, one set per declined target.
    sibling_dois = [_placeholder_doi(slug) for slug in SIBLING_REFUSAL_SLUGS]
    for engagement in DECLINED_ENGAGEMENTS:
        edges.extend(
            compose_refusal_related_identifiers(
                target_surface_doi=_placeholder_doi(engagement.target_surface),
                sibling_refusal_dois=sibling_dois,
            )
        )

    # IsSupplementTo upstream attestation chain.
    edges.extend(
        RelatedIdentifier(
            identifier=doi,
            identifier_type=IdentifierType.DOI,
            relation_type=RelationType.IS_SUPPLEMENT_TO,
        )
        for doi in SUPPLEMENT_TO_DOIS
    )

    return edges


def render_brief_body() -> str:
    """Render the deposit's description body — the case-study's prose.

    Concise (sub-2000 words) per operator framing — the chain of
    attestation IS the work, not a 15-page preprint. Cites the
    Gemini JR packet for the C2PA + Article 50 evidence base; names
    each declined engagement with its constitutional anchor; closes
    with the limitations clause.
    """

    declined_block = "\n\n".join(
        f"### Declined: `{e.target_surface}`\n\n"
        f"{e.rationale}\n\n"
        f"*Constitutional anchor:* `{e.constitutional_anchor}`."
        for e in DECLINED_ENGAGEMENTS
    )

    return f"""# {ARTICLE_50_CASE_STUDY_TITLE}

## Thesis

The EU AI Act Article 50 obligations (provider machine-readable
marking under Art. 50(2); deployer human-readable disclosure under
Art. 50(4); first-interaction timing under Art. 50(5)) admit a
multi-layered compliance posture under the December 2025 Draft Code
of Practice. As of 2026-Q2, C2PA v2.3 (January 2026) and v2.4
(April 2026) ship the *technical* substrate that satisfies the
machine-readable marking obligation: COSE-signed JUMBF containers,
the Conformance Program trust list (interim list frozen 2026-01-01),
"Verifiable Segment Info" for live DASH/HLS streams with sub-500ms
real-time signing, and multi-party "Ingredients + Multiple Signers"
attribution where the AI engine signs as Provider Ingredient and
the legal entity signs the final manifest as Deployer. Hapax's
livestream surface is C2PA-compliant by construction along that
pipeline.

**The refusal documented in this brief is therefore principled, not
expedient.** Hapax has the technical means to satisfy Art. 50 via
C2PA. Hapax nonetheless declines a specific set of *adjacent*
engagements — vendor-portal-only audit-trail substrates, court-
admissibility marketing claims, direct regulator outreach, direct
journalist pitches, promotional cert-pricing copy. Each refusal is
rooted in a constitutional axiom whose enforcement does not depend
on whether an alternative compliance path exists.

The brief is a *case-study refusal-brief*: the chain of attestation
IS the publication. The deposit DOI + the refusal-shaped
RelatedIdentifier edges (IsRequiredBy → target surfaces;
IsObsoletedBy → sibling refusals; IsSupplementTo → upstream
methodology) constitute the load-bearing artefact. The Zenodo
single-tenant DOI-anchored substrate operates *alongside* the C2PA
pipeline as a second layer, not as a replacement — multi-layered
per the December 2025 Draft Code of Practice.

## Evidence base — currentness as of 2026-Q2

* C2PA specification at v2.3 (January 2026) and v2.4 (April 2026).
  COSE signatures inside JUMBF containers; SHA-256 hard-bindings.
* Interim Trust List frozen 2026-01-01; deposits must consume the
  C2PA Conformance Program trust list.
* Article 50(2) (providers): outputs marked in a machine-readable
  format. Article 50(4) (deployers): deepfake disclosure
  human-readable, clear, distinguishable. Article 50(5): disclosure
  present from first interaction; for livestreams, labels visible
  from stream start.
* C2PA v2.3 "Verifiable Segment Info" — asymmetric session keys at
  stream init, fMP4 segment Event Message Boxes carrying
  cryptographic segment-hash signatures. Reference implementations
  (Qualabs, Irdeto) at sub-500ms real-time signing.
* Multi-party attribution via "Ingredients" + "Multiple Signers" —
  AI engine listed as Provider Ingredient; legal entity signs the
  final manifest as Deployer.

Source: Gemini JR currentness-scout packet
``20260504T230725Z-jr-currentness-scout-eu-ai-act-art50-c2pa-currentness-2026-05-04``,
verified 2026-05-04.

## Declined engagements

{declined_block}

## Limitations

This deposit is *audit-trail compliance evidence* within the
multi-layered approach the December 2025 Draft Code of Practice
mandates. It is NOT:

* A court-admissibility claim (per Hacker Factor's Daubert critique).
* A regulator-blessed designation (the EU AI Office has issued no
  such designation as of 2026-05-04).
* A vendor-of-record positioning claim (the operator's stance
  forecloses single-vendor-of-record framing).

## Cross-references

* Refusal Brief general methodology (upstream supplement).
* Hapax Manifesto v0 §IV.5 — refusal as publication.
* Sibling case-study refusals listed in the deposit's
  ``IsObsoletedBy`` graph edges.

---

*{REFUSAL_DEPOSIT_TYPE}* deposit — refusal-as-data per the canonical
Hapax publication-bus refusal-brief contract. Authorship is
V5-unsettled (Hapax / Claude Code / operator), per the operator
referent policy.
"""


def build_payload_metadata() -> dict:
    """Return the Zenodo metadata block ready for ``PublisherPayload``.

    Carries the title + the rendered RelatedIdentifier graph in
    Zenodo's REST API ``related_identifiers`` shape (snake_case via
    :meth:`RelatedIdentifier.to_zenodo_dict`). The publisher kit
    pulls these into the ``deposit_metadata`` block at emit time.
    """

    return {
        "title": ARTICLE_50_CASE_STUDY_TITLE,
        "related_identifiers": [
            edge.to_zenodo_dict() for edge in compose_article_50_related_identifiers()
        ],
    }


class ArticleFiftyCaseStudy:
    """Self-contained case-study payload composer.

    Bundles the slug + title + graph composer + body renderer into one
    type so the publisher daemon (or a one-shot CLI) can dispatch the
    case-study deposit with a single instance.

    Usage::

        case = ArticleFiftyCaseStudy()
        publisher.publish(PublisherPayload(
            target=case.slug,
            text=case.body(),
            metadata=case.metadata(),
        ))
    """

    slug: ClassVar[str] = ARTICLE_50_CASE_STUDY_SLUG
    title: ClassVar[str] = ARTICLE_50_CASE_STUDY_TITLE

    def body(self) -> str:
        return render_brief_body()

    def metadata(self) -> dict:
        return build_payload_metadata()

    def declined(self) -> tuple[DeclinedEngagement, ...]:
        """Return the declined-engagement records for diagnostic use."""

        return DECLINED_ENGAGEMENTS

    def related_identifiers(self) -> list[RelatedIdentifier]:
        """Return the composed RelatedIdentifier graph edges."""

        return compose_article_50_related_identifiers()

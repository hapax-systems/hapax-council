"""Article 50 case-study refusal-brief composer tests.

Verifies the load-bearing invariants the operator's directive
specifies: refusal-shaped graph edges (IsRequiredBy, IsObsoletedBy,
IsSupplementTo), C2PA-vs-refused-engagement principled framing,
allowlist permits the case-study slug, payload metadata is in
Zenodo's REST shape.
"""

from __future__ import annotations

import pytest

from agents.publication_bus.article_50_case_study import (
    ARTICLE_50_CASE_STUDY_SLUG,
    ARTICLE_50_CASE_STUDY_TITLE,
    DECLINED_ENGAGEMENTS,
    SIBLING_REFUSAL_SLUGS,
    SUPPLEMENT_TO_DOIS,
    ArticleFiftyCaseStudy,
    DeclinedEngagement,
    build_payload_metadata,
    compose_article_50_related_identifiers,
    render_brief_body,
)
from agents.publication_bus.refusal_brief_publisher import (
    DEFAULT_REFUSAL_DEPOSIT_ALLOWLIST,
)
from agents.publication_bus.related_identifier import (
    IdentifierType,
    RelationType,
)

# ── Slug + title invariants ───────────────────────────────────────────


class TestSlugAndTitle:
    def test_slug_matches_cc_task_id(self) -> None:
        assert ARTICLE_50_CASE_STUDY_SLUG == "refusal-brief-article-50-case-study"

    def test_title_carries_refused_prefix(self) -> None:
        # The publisher recognizes ``Refused:`` as a refusal-deposit
        # discriminator; the title MUST start with it.
        assert ARTICLE_50_CASE_STUDY_TITLE.startswith("Refused:")


# ── Allowlist gate ────────────────────────────────────────────────────


class TestAllowlistGate:
    def test_default_refusal_allowlist_permits_case_study_slug(self) -> None:
        assert DEFAULT_REFUSAL_DEPOSIT_ALLOWLIST.permits(ARTICLE_50_CASE_STUDY_SLUG)


# ── Declined engagements ──────────────────────────────────────────────


class TestDeclinedEngagements:
    def test_records_at_least_five_declined_engagements(self) -> None:
        assert len(DECLINED_ENGAGEMENTS) >= 5

    def test_every_engagement_carries_constitutional_anchor(self) -> None:
        for engagement in DECLINED_ENGAGEMENTS:
            assert engagement.constitutional_anchor in {
                "single_user",
                "executive_function",
                "management_governance",
                "interpersonal_transparency",
                "corporate_boundary",
            }, f"unknown anchor for {engagement.target_surface}"

    def test_target_surfaces_are_unique(self) -> None:
        targets = [e.target_surface for e in DECLINED_ENGAGEMENTS]
        assert len(targets) == len(set(targets))

    def test_rationale_is_not_trivial(self) -> None:
        for engagement in DECLINED_ENGAGEMENTS:
            # Each rationale should be substantive enough to anchor the
            # refusal — operator's framing is "the chain of attestation
            # IS the work", so each link in the chain carries weight.
            assert len(engagement.rationale.split()) >= 25


# ── Graph composition ─────────────────────────────────────────────────


class TestRelatedIdentifierGraph:
    def test_graph_carries_is_required_by_edges_per_engagement(self) -> None:
        edges = compose_article_50_related_identifiers()
        is_required_by = [e for e in edges if e.relation_type == RelationType.IS_REQUIRED_BY]
        # One IsRequiredBy edge per declined engagement.
        assert len(is_required_by) == len(DECLINED_ENGAGEMENTS)

    def test_graph_carries_is_obsoleted_by_for_siblings(self) -> None:
        edges = compose_article_50_related_identifiers()
        is_obsoleted_by = [e for e in edges if e.relation_type == RelationType.IS_OBSOLETED_BY]
        # Each declined engagement composes IsObsoletedBy for every
        # sibling refusal — len(declined) × len(siblings).
        assert len(is_obsoleted_by) == len(DECLINED_ENGAGEMENTS) * len(SIBLING_REFUSAL_SLUGS)

    def test_graph_carries_is_supplement_to_upstream(self) -> None:
        edges = compose_article_50_related_identifiers()
        is_supplement_to = [e for e in edges if e.relation_type == RelationType.IS_SUPPLEMENT_TO]
        assert len(is_supplement_to) == len(SUPPLEMENT_TO_DOIS)

    def test_every_edge_uses_doi_identifier_type(self) -> None:
        edges = compose_article_50_related_identifiers()
        for edge in edges:
            assert edge.identifier_type is IdentifierType.DOI

    def test_target_dois_are_placeholder_shaped(self) -> None:
        """Target deposits are hypothetical — DOIs MUST carry the
        placeholder prefix so a downstream resolver can distinguish
        not-yet-minted from real DOIs."""
        edges = compose_article_50_related_identifiers()
        targets = [e.identifier for e in edges if e.relation_type == RelationType.IS_REQUIRED_BY]
        assert all(d.startswith("10.5281/zenodo.PLACEHOLDER-") for d in targets)

    def test_graph_is_deterministic_across_calls(self) -> None:
        first = compose_article_50_related_identifiers()
        second = compose_article_50_related_identifiers()
        assert first == second


# ── Brief body content ────────────────────────────────────────────────


class TestBriefBody:
    def test_body_carries_principled_refusal_contrast(self) -> None:
        """Operator currentness note: the brief MUST explicitly contrast
        refused engagement with EU compliance pipeline vs C2PA-compliant
        path so the refusal reads as principled, not expedient."""

        body = render_brief_body()
        assert "C2PA" in body
        assert "principled" in body.lower()
        assert "v2.3" in body or "v2.4" in body

    def test_body_cites_gemini_jr_currentness_packet(self) -> None:
        body = render_brief_body()
        assert "20260504T230725Z-jr-currentness-scout-eu-ai-act-art50-c2pa" in body

    def test_body_includes_all_declined_engagements(self) -> None:
        body = render_brief_body()
        for engagement in DECLINED_ENGAGEMENTS:
            assert engagement.target_surface in body

    def test_body_carries_limitations_clause(self) -> None:
        body = render_brief_body()
        # Per cc-task acceptance: explicitly disclaim court-admissibility
        # + scope as audit-trail compliance evidence.
        assert "Limitations" in body
        assert "court-admissibility" in body.lower()
        assert "audit-trail" in body.lower()

    def test_body_anchors_each_engagement_to_axiom(self) -> None:
        body = render_brief_body()
        for engagement in DECLINED_ENGAGEMENTS:
            assert engagement.constitutional_anchor in body

    def test_body_has_substantive_word_count(self) -> None:
        # Operator framing: chain-of-attestation, not 15-page preprint.
        # Floor of 300 words ensures it's substantive without inflating.
        body = render_brief_body()
        assert len(body.split()) >= 300


# ── Zenodo metadata payload ───────────────────────────────────────────


class TestPayloadMetadata:
    def test_metadata_carries_title(self) -> None:
        meta = build_payload_metadata()
        assert meta["title"] == ARTICLE_50_CASE_STUDY_TITLE

    def test_metadata_related_identifiers_in_zenodo_rest_shape(self) -> None:
        meta = build_payload_metadata()
        assert "related_identifiers" in meta
        for entry in meta["related_identifiers"]:
            # snake_case Zenodo REST shape — identifier / relation /
            # scheme.
            assert {"identifier", "relation", "scheme"}.issubset(entry.keys())

    def test_metadata_relation_strings_use_datacite_camelcase(self) -> None:
        meta = build_payload_metadata()
        relations = {entry["relation"] for entry in meta["related_identifiers"]}
        assert "IsRequiredBy" in relations
        assert "IsObsoletedBy" in relations
        assert "IsSupplementTo" in relations


# ── ArticleFiftyCaseStudy facade ─────────────────────────────────────


class TestArticleFiftyCaseStudyFacade:
    def test_class_attributes_match_module_constants(self) -> None:
        case = ArticleFiftyCaseStudy()
        assert case.slug == ARTICLE_50_CASE_STUDY_SLUG
        assert case.title == ARTICLE_50_CASE_STUDY_TITLE

    def test_body_method_returns_rendered_brief(self) -> None:
        case = ArticleFiftyCaseStudy()
        assert case.body() == render_brief_body()

    def test_metadata_method_returns_payload_metadata(self) -> None:
        case = ArticleFiftyCaseStudy()
        assert case.metadata() == build_payload_metadata()

    def test_declined_method_returns_engagement_records(self) -> None:
        case = ArticleFiftyCaseStudy()
        assert case.declined() == DECLINED_ENGAGEMENTS

    def test_related_identifiers_method_returns_graph(self) -> None:
        case = ArticleFiftyCaseStudy()
        assert case.related_identifiers() == compose_article_50_related_identifiers()


# ── Surface integration with the publisher ──────────────────────────


class TestPublisherWiring:
    def test_dataclass_fields_match_published_shape(self) -> None:
        engagement = DeclinedEngagement(
            target_surface="x",
            rationale="y",
            constitutional_anchor="single_user",
        )
        assert engagement.target_surface == "x"
        assert engagement.rationale == "y"


# ── No-leak invariants ───────────────────────────────────────────────


class TestNoLeak:
    """Operator-referent + axiom invariants on the brief body.

    The brief is published under V5 attribution (operator referent
    via :data:`shared.operator_referent`); the legal name MUST NOT
    appear in the deposit description. Similarly, no PII shaped
    tokens (email, phone, real address) should appear.
    """

    def test_body_does_not_contain_email_pattern(self) -> None:
        import re

        body = render_brief_body()
        # Loose email regex — catches the obvious shape; no need for
        # full RFC parsing.
        assert not re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", body)

    def test_body_does_not_contain_phone_pattern(self) -> None:
        import re

        body = render_brief_body()
        # Loose phone shape — three-digit-three-digit-four-digit.
        assert not re.search(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b", body)

    @pytest.mark.parametrize(
        "marker",
        [
            "TODO",
            "FIXME",
            "XXX",
        ],
    )
    def test_body_has_no_lingering_dev_markers(self, marker: str) -> None:
        body = render_brief_body()
        assert marker not in body

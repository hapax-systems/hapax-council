"""Pin the council README's current public-frontmatter contract."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
START_HERE = REPO_ROOT / "START_HERE.md"
OBSIDIAN_HOME = REPO_ROOT / "config" / "obsidian-publish" / "Home.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _squash_whitespace(text: str) -> str:
    return " ".join(text.lower().split())


class TestNoCtaCopy:
    FORBIDDEN_PHRASES = (
        "Pull requests welcome",
        "PRs welcome",
        "Get Started",
        "Get a Demo",
        "Sign Up",
        "Buy Now",
        "Star this repo",
        "leave a star",
        "Subscribe",
        "subscribe to our",
    )

    def test_no_forbidden_marketing_copy(self) -> None:
        body = _readme()
        for phrase in self.FORBIDDEN_PHRASES:
            assert phrase not in body


class TestPublicFrame:
    def test_first_screen_declares_governed_research_artifact(self) -> None:
        head = _readme()[:2400].lower()
        for token in (
            "single-operator",
            "governance",
            "evidence",
            "refusal",
            "public egress",
            "publication-bus",
        ):
            assert token in head

    def test_not_product_or_framework_or_support_surface(self) -> None:
        body = _readme().lower()
        assert "not an adoption package" in body
        assert "not a supported framework" in body
        assert "not the commercial product front door" in body
        assert "no public support queue" in body

    def test_reader_map_points_to_value_partitioned_surfaces(self) -> None:
        body = _readme()
        for repo in (
            "https://github.com/hapax-systems/agentgov",
            "https://github.com/hapax-systems/reins",
            "https://github.com/hapax-systems/hapax-constitution",
            "https://github.com/hapax-systems/hapax-research-ledger",
        ):
            assert repo in body

    def test_reader_map_translates_features_to_reader_value(self) -> None:
        body = _readme().lower()
        for value_statement in (
            "pilot a narrow, mit-licensed boundary",
            "inspect delivery state and proposed writes",
            "follow how claims, refusals, route authority, and public egress behave",
            "audit numeric observations with caveats preserved",
        ):
            assert value_statement in body


class TestAudienceValueCopy:
    def test_start_here_covers_distinct_reader_values(self) -> None:
        body = START_HERE.read_text(encoding="utf-8").lower()
        for token in (
            "ai-safety researchers",
            "technical directors",
            "harness evaluators",
            "narrow-tool adopters",
            "what hapax makes inspectable",
        ):
            assert token in body
        for value_statement in (
            "grounding attempts with source state",
            "authority boundaries",
            "part of the measured surface",
            "distinguish portable hooks",
        ):
            assert value_statement in body

    def test_obsidian_home_covers_public_reader_values(self) -> None:
        body = _squash_whitespace(OBSIDIAN_HOME.read_text(encoding="utf-8"))
        for value_statement in (
            "adopters can find bounded hooks",
            "technical leaders can see where authority and write paths stop",
            "researchers can inspect claim and refusal evidence",
            "harness readers can compare",
            "public egress is part of the governed task surface",
        ):
            assert value_statement in body

    def test_obsidian_home_scale_claims_are_recheckable(self) -> None:
        body = OBSIDIAN_HOME.read_text(encoding="utf-8")
        assert "190 source-visible agent directories" in body
        assert "147 equipment records" in body
        assert "200+ AI agents" not in body
        assert "150+ pieces of studio equipment" not in body
        for command in (
            "find agents -mindepth 1 -maxdepth 1 -type d | wc -l",
            "find config/equipment -maxdepth 1 -type f",
            "uv run python scripts/check-public-surface-claims.py --warnings-fail",
        ):
            assert command in body

    def test_obsidian_home_links_public_mcp_repo_after_live_readback(self) -> None:
        body = OBSIDIAN_HOME.read_text(encoding="utf-8")
        assert "https://github.com/hapax-systems/hapax-mcp" in body
        assert "not listed as public until live-state readback reports" not in body


class TestMetadataCoherence:
    def test_no_apache_badge(self) -> None:
        body = _readme()
        assert "License-Apache" not in body
        assert "Apache_2.0" not in body

    def test_license_pointer_to_authority_surfaces(self) -> None:
        body = _readme()
        assert "PolyForm Strict" in body
        for local_doc in ("LICENSE", "NOTICE.md", "CITATION.cff", ".zenodo.json"):
            assert local_doc in body

    def test_repo_urls_use_current_public_org(self) -> None:
        body = _readme()
        assert "https://github.com/hapax-systems/hapax-council" in body
        assert "github.com/ryanklee" not in body

    def test_private_legacy_table_removed(self) -> None:
        body = _readme()
        assert "private/not a public repo as of 2026-05-11" not in body


class TestPublicationBoundary:
    def test_public_surface_directories_are_named(self) -> None:
        body = _readme()
        for surface in (
            "agents/publication_bus/",
            "docs/publication-drafts/",
            "docs/published-artifacts/",
            "START_HERE.md",
            "SUPPORT.md",
            "CONTRIBUTING.md",
        ):
            assert surface in body

    def test_direct_public_egress_is_disclaimed(self) -> None:
        body = _readme().lower()
        assert "direct public egress is not a reader-facing affordance" in body
        assert "governed publication-bus surfaces" in body

    def test_constitution_pointer(self) -> None:
        assert "hapax-constitution" in _readme()


class TestLicenseReconciliationStatusDoc:
    DOC = REPO_ROOT / "docs" / "governance" / "license-reconciliation-status.md"

    def test_doc_exists(self) -> None:
        assert self.DOC.exists()

    def test_doc_lists_all_four_surfaces(self) -> None:
        body = self.DOC.read_text(encoding="utf-8")
        for surface in ("LICENSE", "NOTICE.md", "CITATION.cff", "codemeta.json", ".zenodo.json"):
            assert surface in body

    def test_doc_separates_local_and_live_license_state(self) -> None:
        body = self.DOC.read_text(encoding="utf-8")
        assert "LOCAL LICENSE POSTURE RECONCILED" in body
        assert "Zenodo's" in body
        assert "`other-closed`" in body
        assert "live GitHub/license-detection" in body
        assert "public-surface live-state report" in body

    def test_doc_declares_polyform_strict(self) -> None:
        assert "PolyForm Strict 1.0.0" in self.DOC.read_text(encoding="utf-8")

    def test_zenodo_license_note_matches_doc(self) -> None:
        zenodo = json.loads((REPO_ROOT / ".zenodo.json").read_text(encoding="utf-8"))
        assert zenodo["license"] == "other-closed"
        assert "PolyForm Strict 1.0.0" in zenodo["notes"]
        body = self.DOC.read_text(encoding="utf-8")
        assert (
            'assert zenodo["license"] == "other-closed" '
            'and "PolyForm Strict 1.0.0" in zenodo["notes"]'
        ) in body

    def test_archive_identifier_metadata_remains_intact(self) -> None:
        zenodo = json.loads((REPO_ROOT / ".zenodo.json").read_text(encoding="utf-8"))
        citation = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))

        assert zenodo["doi"] == "10.5281/zenodo.20113515"
        assert zenodo["conceptdoi"] == "10.5281/zenodo.20113514"
        assert zenodo["publication_date"] == "2026-05-10"
        assert citation["doi"] == "10.5281/zenodo.20113515"
        assert any(
            identifier.get("type") == "doi" and identifier.get("value") == "10.5281/zenodo.20113515"
            for identifier in citation["identifiers"]
        )


class TestGithubPublicSurfaceLiveStateDoc:
    DOC = (
        REPO_ROOT / "docs" / "research" / "2026-04-30-github-public-surface-live-state-reconcile.md"
    )

    def test_freshness_uses_frontmatter_and_generated_fields_not_filename_slug(self) -> None:
        text = self.DOC.read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        generated_line = next(line for line in text.splitlines() if line.startswith("- Generated:"))

        assert self.DOC.name.startswith("2026-04-30-")
        generated_at = generated_line.split("`", 2)[1]
        assert str(frontmatter["date"]) == generated_at.split("T", 1)[0]
        assert "Freshness checks must read those fields, not the filename slug." in text

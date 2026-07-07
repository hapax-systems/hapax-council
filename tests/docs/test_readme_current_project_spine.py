"""Pin the council README's current public-frontmatter contract."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


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

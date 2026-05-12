"""Pin the README's public-posture invariants.

Per cc-task ``github-readme-profile-current-project-refresh``. The
README is the public entry point for the project — silent drift
toward marketing copy, contributor invitations, or empirical
overclaims is a constitutional risk. These tests pin the contract
deterministically so future edits surface as failing tests rather
than as silent rot.

Coverage:

  - **No CTA / contributor copy.** The cc-task's "out of scope" list
    forbids public support prompts, contribution invitations,
    screenshots/demos, social badges, and marketing hero language.
  - **Project spine.** The README must center the current Hapax spine
    (single-operator, executive function, semantic recruitment,
    perceptual grounding, livestream-as-instrument, refusal-as-data,
    value-braid loop), not the older voice-grounding-only slice.
  - **No-contributor stance.** The README must explicitly state the
    not-a-product / not-seeking-contributors stance.
  - **Metadata coherence.** The README's license posture must defer to
    NOTICE / CITATION / codemeta, all converged on PolyForm Strict.
    The Apache-2.0 badge that the pre-rewrite README carried must NOT
    reappear.
  - **Refusal / governance pointers.** The README must point at the
    refusal-and-governance surfaces that exist (NOTICE, CONTRIBUTING,
    governance docs, Refusal Brief, Manifesto v0).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


# ── No CTA / marketing copy ──────────────────────────────────────────


class TestNoCtaCopy:
    """Per cc-task scope §"Out of scope": no contributor / marketing /
    social-engagement copy in the public README."""

    FORBIDDEN_PHRASES = (
        "contribute",
        "Contribute",
        "Pull request",
        "pull requests welcome",
        "PRs welcome",
        "Get Started",
        "Get a Demo",
        "Sign Up",
        "Sign up",
        "Buy Now",
        "Star this repo",
        "leave a star",
        "Subscribe",
        "subscribe to our",
    )

    def test_no_forbidden_marketing_copy(self) -> None:
        body = _readme()
        for phrase in self.FORBIDDEN_PHRASES:
            assert phrase not in body, (
                f"README contains forbidden CTA / marketing phrase: {phrase!r}; "
                "the README is a public entry point, not a contributor-recruitment surface "
                "(per cc-task github-readme-profile-current-project-refresh §Out of scope)"
            )


# ── Current project spine ────────────────────────────────────────────


class TestProjectSpineCenters:
    """The cc-task spine list must show up in the README's first
    screen (above the architecture section). Older lead — Clark &
    Brennan grounding-only — must NOT be the dominant frame anymore."""

    SPINE_TOKENS = (
        "single-operator",
        "executive function",
        "semantic recruitment",
        # No-false-grounding discipline / perceptual grounding language
        # is the project's commitment around public claims.
        "grounding",
        "livestream",
        "refusal",
    )

    def test_first_2k_chars_contain_spine_tokens(self) -> None:
        body = _readme()
        head = body[:2000]
        for tok in self.SPINE_TOKENS:
            assert tok.lower() in head.lower(), (
                f"README first screen missing project-spine token {tok!r}"
            )

    def test_voice_daemon_is_subordinate_not_dominant(self) -> None:
        # The voice daemon is one component, not the whole identity.
        # Its mention should be subordinate (after the spine
        # block) — verify by ordering: 'voice daemon' should not be
        # the dominant content of the first screen.
        body = _readme()
        head = body[:2000]
        spine_pos = head.lower().find("project spine")
        voice_pos = head.lower().find("voice daemon")
        # Spine block exists; voice daemon either does not appear in
        # the head OR appears after the spine block.
        assert spine_pos != -1, "Project spine section missing from first screen"
        if voice_pos != -1:
            assert voice_pos > spine_pos, (
                "voice daemon mention precedes project-spine block; "
                "the older voice-grounding-only frame should not dominate"
            )


# ── No-contributor + research-status stance ──────────────────────────


class TestNoContributorStance:
    def test_not_a_product_explicit(self) -> None:
        body = _readme()
        assert "not a product" in body.lower()

    def test_not_seeking_contributors_explicit(self) -> None:
        body = _readme()
        assert "not seeking contributors" in body.lower()

    def test_research_artifact_explicit(self) -> None:
        body = _readme()
        # Must declare the research-as-artifact frame somewhere
        # (not just contributor refusal).
        assert "artifact" in body.lower()


# ── Metadata coherence ───────────────────────────────────────────────


class TestMetadataCoherence:
    def test_no_apache_badge(self) -> None:
        # Per cc-task: "Remove stale Apache badge/claim if license
        # reconciliation chooses PolyForm Strict." Three of four
        # canonical surfaces have converged on PolyForm Strict, so the
        # Apache badge does not belong in the README.
        body = _readme()
        assert "License-Apache" not in body, "README still carries the legacy Apache 2.0 badge"
        assert "Apache_2.0" not in body, "README still carries the legacy Apache 2.0 badge"
        # The word "Apache" itself is acceptable in the LICENSE-
        # reconciliation pointer text, but the badge URL is not.

    def test_license_pointer_to_notice(self) -> None:
        body = _readme()
        assert "NOTICE.md" in body
        # The README should defer to NOTICE for the canonical license
        # statement rather than authoring its own.
        assert "CITATION.cff" in body

    def test_license_reconciliation_status_referenced(self) -> None:
        # Keep the status doc linked after reconciliation so readers
        # can audit how the public license posture was resolved.
        body = _readme()
        assert "license-reconciliation-status" in body

    def test_repo_urls_use_current_public_org(self) -> None:
        body = _readme()
        assert "https://github.com/hapax-systems/hapax-council" in body
        assert "git@github.com:hapax-systems/hapax-council.git" in body
        assert "https://github.com/ryanklee/hapax-council" not in body
        assert "git@github.com:ryanklee/hapax-council.git" not in body

    def test_private_repos_not_linked_as_public_entry_points(self) -> None:
        body = _readme()
        for private_repo in ("hapax-mcp", "hapax-watch", "hapax-phone"):
            assert f"https://github.com/ryanklee/{private_repo}" not in body
            assert f"| {private_repo} |" in body
        assert "private/not a public repo as of 2026-05-11" in body

    def test_public_refusal_links_exist_locally(self) -> None:
        body = _readme()
        for local_doc in ("CONTRIBUTING.md", "NOTICE.md", "CITATION.cff"):
            assert local_doc in body
            assert (REPO_ROOT / local_doc).exists()


# ── Refusal / governance pointers ────────────────────────────────────


class TestGovernancePointers:
    def test_refusal_brief_link(self) -> None:
        body = _readme()
        assert "refusal-brief" in body.lower()

    def test_manifesto_link(self) -> None:
        body = _readme()
        assert "manifesto" in body.lower()

    def test_constitution_pointer(self) -> None:
        body = _readme()
        assert "hapax-constitution" in body

    def test_axioms_pointer(self) -> None:
        body = _readme()
        assert "axioms" in body.lower()


# ── License reconciliation status doc invariants ─────────────────────


class TestLicenseReconciliationStatusDoc:
    """Pin the status doc's contract so the divergence record stays
    auditable rather than silently disappearing."""

    DOC = REPO_ROOT / "docs" / "governance" / "license-reconciliation-status.md"

    def test_doc_exists(self) -> None:
        assert self.DOC.exists()

    def test_doc_lists_all_four_surfaces(self) -> None:
        body = self.DOC.read_text(encoding="utf-8")
        for surface in ("LICENSE", "NOTICE.md", "CITATION.cff", "codemeta.json"):
            assert surface in body

    def test_doc_marks_resolved(self) -> None:
        body = self.DOC.read_text(encoding="utf-8")
        assert "RESOLVED" in body

    def test_doc_declares_polyform_strict(self) -> None:
        body = self.DOC.read_text(encoding="utf-8")
        assert "PolyForm Strict 1.0.0" in body

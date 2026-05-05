"""Per-grant framing wrapper tests.

Coverage:

1. ``GrantFraming`` enum carries exactly the three operator-curated
   framings.
2. ``FRAMING_PREFIXES`` defines all three; each prefix is non-trivial
   (≥ 30 words) and carries the framing's lens marker.
3. ``FRAMING_BY_RECIPE`` maps the immediate Q2 batch recipes
   (ltff / cooperative_ai_foundation / nlnet / emergent_ventures /
   manifund); stubs left unmapped.
4. ``framing_for_recipe`` returns ``None`` for unknown recipes.
5. ``apply_framing`` is pure + deterministic + composes prefix +
   universal-section verbatim.
6. ``FramedPackage`` constitutional disclosure passes through
   un-modified (every grant submission carries the same V5 disclosure).
"""

from __future__ import annotations

import pytest

from agents.playwright_grant_submission_runner.framing import (
    FRAMING_BY_RECIPE,
    FRAMING_PREFIXES,
    FramedPackage,
    GrantFraming,
    apply_framing,
    framing_for_recipe,
)
from agents.playwright_grant_submission_runner.package import UniversalGrantPackage


def _package(
    *,
    abstract: str = "Hapax thesis abstract.",
    problem_statement: str = "The problem this grant addresses.",
    approach: str = "How the grant funds will be applied.",
    constitutional_disclosure: str = (
        "V5 attribution: Hapax (system) / Claude Code (substrate) / "
        "operator. No engagement obligations beyond auto-publication."
    ),
) -> UniversalGrantPackage:
    return UniversalGrantPackage(
        project_name="hapax-q2-2026",
        applicant_name="Operator",
        applicant_entity="Wyoming SMLLC",
        contact_email="contact@example.com",
        abstract=abstract,
        problem_statement=problem_statement,
        approach=approach,
        constitutional_disclosure=constitutional_disclosure,
    )


# ── Enum + registry shape ─────────────────────────────────────────────


class TestEnumAndRegistry:
    def test_grant_framing_has_three_members(self) -> None:
        assert {f.value for f in GrantFraming} == {
            "ai_personhood",
            "infrastructure_studies",
            "critical_ai",
        }

    def test_framing_prefixes_has_entry_per_framing(self) -> None:
        for framing in GrantFraming:
            assert framing in FRAMING_PREFIXES

    def test_each_prefix_is_substantive(self) -> None:
        for framing, prefixes in FRAMING_PREFIXES.items():
            for section, text in (
                ("abstract_prefix", prefixes.abstract_prefix),
                ("problem_statement_prefix", prefixes.problem_statement_prefix),
                ("approach_prefix", prefixes.approach_prefix),
            ):
                wc = len(text.split())
                assert wc >= 30, f"{framing.value}.{section} too short ({wc} words)"

    def test_each_prefix_names_its_lens(self) -> None:
        """Each prefix's lead sentence MUST name the framing —
        reviewers should know which lens the application is in."""
        markers = {
            GrantFraming.AI_PERSONHOOD: "personhood",
            GrantFraming.INFRASTRUCTURE_STUDIES: "infrastructure",
            GrantFraming.CRITICAL_AI: "critical AI",
        }
        for framing, marker in markers.items():
            prefixes = FRAMING_PREFIXES[framing]
            assert marker.lower() in prefixes.abstract_prefix.lower()


# ── Recipe assignment ────────────────────────────────────────────────


class TestRecipeAssignment:
    def test_immediate_q2_batch_recipes_have_framing(self) -> None:
        for recipe in (
            "ltff",
            "cooperative_ai_foundation",
            "nlnet",
            "emergent_ventures",
            "manifund",
        ):
            assert recipe in FRAMING_BY_RECIPE

    def test_recipe_to_framing_assignments_match_cc_task(self) -> None:
        # Operator-curated assignments per cc-task spec.
        assert FRAMING_BY_RECIPE["ltff"] is GrantFraming.AI_PERSONHOOD
        assert FRAMING_BY_RECIPE["cooperative_ai_foundation"] is GrantFraming.AI_PERSONHOOD
        assert FRAMING_BY_RECIPE["nlnet"] is GrantFraming.INFRASTRUCTURE_STUDIES
        assert FRAMING_BY_RECIPE["emergent_ventures"] is GrantFraming.CRITICAL_AI
        assert FRAMING_BY_RECIPE["manifund"] is GrantFraming.CRITICAL_AI

    def test_stub_recipes_unmapped_by_default(self) -> None:
        # Stubs (anthropic_cco / openai_safety_airtable / schmidt_sciences)
        # are not in the immediate Q2 batch; their framing assignments
        # land with the conversion-from-stub PRs.
        for stub in ("anthropic_cco", "openai_safety_airtable", "schmidt_sciences"):
            assert stub not in FRAMING_BY_RECIPE

    def test_framing_for_recipe_returns_none_on_unknown(self) -> None:
        assert framing_for_recipe("not-a-real-recipe") is None

    def test_framing_for_recipe_returns_assigned(self) -> None:
        assert framing_for_recipe("nlnet") is GrantFraming.INFRASTRUCTURE_STUDIES


# ── apply_framing purity ─────────────────────────────────────────────


class TestApplyFraming:
    def test_apply_framing_returns_framed_package(self) -> None:
        pkg = _package()
        framed = apply_framing(pkg, GrantFraming.AI_PERSONHOOD)
        assert isinstance(framed, FramedPackage)
        assert framed.framing is GrantFraming.AI_PERSONHOOD
        assert framed.base is pkg

    def test_apply_framing_is_deterministic(self) -> None:
        pkg = _package()
        first = apply_framing(pkg, GrantFraming.CRITICAL_AI)
        second = apply_framing(pkg, GrantFraming.CRITICAL_AI)
        assert first == second

    def test_apply_framing_prepends_prefix_to_abstract(self) -> None:
        pkg = _package(abstract="Original abstract sentence.")
        framed = apply_framing(pkg, GrantFraming.INFRASTRUCTURE_STUDIES)
        assert framed.framed_abstract.endswith("Original abstract sentence.")
        assert framed.framed_abstract.startswith(
            FRAMING_PREFIXES[GrantFraming.INFRASTRUCTURE_STUDIES].abstract_prefix
        )

    def test_apply_framing_prepends_prefix_to_problem_statement(self) -> None:
        pkg = _package(problem_statement="Original problem statement.")
        framed = apply_framing(pkg, GrantFraming.AI_PERSONHOOD)
        assert framed.framed_problem_statement.endswith("Original problem statement.")

    def test_apply_framing_prepends_prefix_to_approach(self) -> None:
        pkg = _package(approach="Original approach text.")
        framed = apply_framing(pkg, GrantFraming.CRITICAL_AI)
        assert framed.framed_approach.endswith("Original approach text.")


# ── Constitutional disclosure pass-through ───────────────────────────


class TestDisclosurePassThrough:
    @pytest.mark.parametrize("framing", list(GrantFraming))
    def test_disclosure_unchanged_across_framings(self, framing: GrantFraming) -> None:
        """Constitutional disclosure MUST be byte-identical across all
        framings — the V5 attribution paragraph is the runner's
        invariant for every submission."""

        original = (
            "V5 attribution: Hapax / Claude Code / operator. No "
            "engagement obligations beyond auto-publication."
        )
        pkg = _package(constitutional_disclosure=original)
        framed = apply_framing(pkg, framing)
        assert framed.constitutional_disclosure == original

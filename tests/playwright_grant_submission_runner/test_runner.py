"""Tests for the Playwright grant-submission runner.

Coverage:

1. Universal package reader — frontmatter validation, section parsing,
   constitutional-disclosure presence enforcement.
2. Constitutional-disclosure verifier — substring matches, missing
   tokens, empty preview.
3. Recipe registry — both live recipes (NLnet, Manifund) plus all 6
   stubs are registered; ``BATCH_Q2_2026`` lists 8 distinct names.
4. Dry-run flow — NLnet + Manifund return ``RecipeStatus.DRY_RUN`` with
   the disclosure-present invariant satisfied.
5. Stub flow — every stub returns ``RecipeStatus.NOT_IMPLEMENTED`` so
   the operator knows which recipes need follow-up wiring.
6. CLI — ``--list`` enumerates recipes; ``--target`` + ``--dry-run``
   returns OK for live recipes; missing package file returns exit 2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.playwright_grant_submission_runner import (
    GrantSubmissionRunner,
    UniversalGrantPackage,
    constitutional_disclosure_present,
    load_universal_package,
)
from agents.playwright_grant_submission_runner.__main__ import main as cli_main
from agents.playwright_grant_submission_runner.recipe import (
    RecipeStatus,
)
from agents.playwright_grant_submission_runner.recipes import (
    BATCH_Q2_2026,
    default_recipes,
)

# ── Fixtures ────────────────────────────────────────────────────────


_VALID_PACKAGE = """\
---
project_name: Hapax
applicant_name: The Operator
applicant_entity: Hapax Wyoming SMLLC
contact_email: ops@example.invalid
funding_target_usd: 25000
---

## Abstract

Hapax is a research-instrument livestream studying long-horizon AI
governance under operator-self constraints.

## Problem statement

The grant-funded research program tests whether an autonomous research
instrument can sustain its own operations while attributing every
output through a constitutional disclosure regime.

## Approach

We will publish per-segment research artifacts to Zenodo with concept-DOI
minting, route every public utterance through a constitutional
attribution layer, and submit the program's outputs to peer-review
venues for external scrutiny.

## Constitutional disclosure

Hapax is a research instrument operating under the Wyoming DAO
Supplement (W.S. 17-31). All outputs are AI-generated under operator
supervision; prompts and unedited outputs are recorded for
verification and disclosed on every public archive.
"""


@pytest.fixture
def package() -> UniversalGrantPackage:
    return load_universal_package(text=_VALID_PACKAGE)


# ── 1. Package reader ───────────────────────────────────────────────


class TestUniversalGrantPackage:
    def test_parses_canonical_sections(self, package: UniversalGrantPackage):
        assert package.project_name == "Hapax"
        assert package.applicant_entity == "Hapax Wyoming SMLLC"
        assert "research-instrument" in package.abstract
        assert "Wyoming" in package.constitutional_disclosure

    def test_extra_metadata_carries_through(self, package: UniversalGrantPackage):
        assert package.extra_metadata["funding_target_usd"] == "25000"

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ValueError, match="frontmatter"):
            load_universal_package(text="## abstract\nbody only, no frontmatter\n")

    def test_missing_required_section_raises(self):
        bad = (
            "---\n"
            "project_name: x\n"
            "applicant_name: y\n"
            "applicant_entity: z\n"
            "contact_email: a@b.invalid\n"
            "---\n\n"
            "## abstract\nfoo\n\n"
            "## problem_statement\nbar\n"
            # missing approach + constitutional_disclosure
        )
        with pytest.raises(ValueError, match="required sections"):
            load_universal_package(text=bad)

    def test_missing_required_frontmatter_raises(self):
        bad = (
            "---\n"
            "project_name: x\n"
            "---\n\n"
            "## abstract\nfoo\n\n"
            "## problem_statement\nbar\n\n"
            "## approach\nbaz\n\n"
            "## constitutional_disclosure\nHapax disclosure\n"
        )
        with pytest.raises(ValueError, match="frontmatter missing"):
            load_universal_package(text=bad)

    def test_empty_disclosure_raises(self):
        bad = (
            "---\n"
            "project_name: x\n"
            "applicant_name: y\n"
            "applicant_entity: z\n"
            "contact_email: a@b.invalid\n"
            "---\n\n"
            "## abstract\nfoo\n\n"
            "## problem_statement\nbar\n\n"
            "## approach\nbaz\n\n"
            "## constitutional_disclosure\n\n"
            # disclosure present but empty (only blank line)
        )
        with pytest.raises(ValueError):
            load_universal_package(text=bad)


# ── 2. Constitutional-disclosure verifier ──────────────────────────


class TestConstitutionalDisclosurePresent:
    def test_full_preview_passes(self, package: UniversalGrantPackage):
        rendered = package.constitutional_disclosure
        assert constitutional_disclosure_present(rendered, package) is True

    def test_empty_preview_fails(self, package: UniversalGrantPackage):
        assert constitutional_disclosure_present("", package) is False

    def test_preview_without_required_token_fails(self, package: UniversalGrantPackage):
        # Disclosure substring matches but the required token "Hapax" is missing.
        rendered = (
            "Some platform-rewritten preview that elided the project name "
            "but kept the legal disclaimer text"
        )
        assert constitutional_disclosure_present(rendered, package) is False

    def test_preview_with_head_substring_passes(self, package: UniversalGrantPackage):
        # Portal might wrap whitespace; head substring is enough.
        head = package.constitutional_disclosure[:64]
        rendered = f"REWRITTEN PREVIEW Hapax intro {head} ... [truncated]"
        assert constitutional_disclosure_present(rendered, package) is True


# ── 3. Recipe registry ─────────────────────────────────────────────


class TestRecipeRegistry:
    def test_all_eight_recipes_registered(self):
        recipes = default_recipes()
        assert set(recipes.keys()) == {
            "nlnet",
            "manifund",
            "emergent_ventures",
            "ltff",
            "cooperative_ai_foundation",
            "openai_safety_airtable",
            "anthropic_cco",
            "schmidt_sciences",
        }

    def test_batch_q2_2026_is_eight_distinct_recipes(self):
        assert len(BATCH_Q2_2026) == 8
        assert len(set(BATCH_Q2_2026)) == 8

    def test_batch_recipes_all_in_default_registry(self):
        recipes = default_recipes()
        for name in BATCH_Q2_2026:
            assert name in recipes

    def test_two_live_six_stubs(self):
        recipes = default_recipes()
        live = [name for name, r in recipes.items() if not r.schema_only]
        stubs = [name for name, r in recipes.items() if r.schema_only]
        assert sorted(live) == ["manifund", "nlnet"]
        assert len(stubs) == 6


# ── 4. Dry-run flow ────────────────────────────────────────────────


class TestDryRunFlow:
    def test_nlnet_dry_run_returns_dry_run_status(
        self, package: UniversalGrantPackage, tmp_path: Path
    ):
        runner = GrantSubmissionRunner(
            default_recipes(),
            package=package,
            output_root=tmp_path / "outputs",
        )
        outcome = runner.run_target("nlnet", dry_run=True)
        assert outcome.status == RecipeStatus.DRY_RUN
        assert outcome.portal_url == "https://nlnet.nl/propose"
        assert outcome.recipe_name == "nlnet"

    def test_manifund_dry_run_returns_dry_run_status(
        self, package: UniversalGrantPackage, tmp_path: Path
    ):
        runner = GrantSubmissionRunner(
            default_recipes(),
            package=package,
            output_root=tmp_path / "outputs",
        )
        outcome = runner.run_target("manifund", dry_run=True)
        assert outcome.status == RecipeStatus.DRY_RUN

    def test_outcome_jsonl_is_written(self, package: UniversalGrantPackage, tmp_path: Path):
        output_root = tmp_path / "outputs"
        runner = GrantSubmissionRunner(
            default_recipes(),
            package=package,
            output_root=output_root,
        )
        runner.run_target("nlnet", dry_run=True)
        # An ``outcomes.jsonl`` file appears under a date-stamped dir.
        children = list(output_root.iterdir())
        assert len(children) == 1
        jsonl_path = children[0] / "outcomes.jsonl"
        assert jsonl_path.exists()
        line = jsonl_path.read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(line)
        assert record["recipe_name"] == "nlnet"
        assert record["status"] == "dry_run"


# ── 5. Stub flow ───────────────────────────────────────────────────


class TestStubFlow:
    @pytest.mark.parametrize(
        "recipe_name",
        [
            "emergent_ventures",
            "ltff",
            "cooperative_ai_foundation",
            "openai_safety_airtable",
            "anthropic_cco",
            "schmidt_sciences",
        ],
    )
    def test_stub_returns_not_implemented(
        self, recipe_name: str, package: UniversalGrantPackage, tmp_path: Path
    ):
        runner = GrantSubmissionRunner(
            default_recipes(),
            package=package,
            output_root=tmp_path / "outputs",
        )
        outcome = runner.run_target(recipe_name, dry_run=True)
        assert outcome.status == RecipeStatus.NOT_IMPLEMENTED


# ── 6. Disclosure-missing path ─────────────────────────────────────


class TestDisclosureMissing:
    def test_nlnet_disclosure_missing_returns_disclosure_missing(self, tmp_path: Path):
        # Build a package whose disclosure is technically present but
        # short enough that the head probe fails the required-token
        # check. We bypass ``load_universal_package`` to construct an
        # invalid-looking package with a disclosure that lacks the
        # ``Hapax`` token.
        bad_package = UniversalGrantPackage(
            project_name="OtherProject",
            applicant_name="X",
            applicant_entity="Y",
            contact_email="z@example.invalid",
            abstract="abstract",
            problem_statement="problem",
            approach="approach",
            constitutional_disclosure="Generic disclaimer without project name token",
        )
        runner = GrantSubmissionRunner(
            default_recipes(),
            package=bad_package,
            output_root=tmp_path / "outputs",
        )
        outcome = runner.run_target("nlnet", dry_run=True)
        assert outcome.status == RecipeStatus.DISCLOSURE_MISSING


# ── 7. CLI surface ─────────────────────────────────────────────────


class TestCLI:
    def test_list_flag_exits_zero(self, capsys, tmp_path: Path):
        rc = cli_main(["--list"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "nlnet" in captured.out
        assert "stub" in captured.out
        assert "live" in captured.out

    def test_missing_package_returns_two(self, capsys, tmp_path: Path):
        nonexistent = tmp_path / "does-not-exist.md"
        rc = cli_main(["--target", "nlnet", "--dry-run", "--package", str(nonexistent)])
        captured = capsys.readouterr()
        assert rc == 2
        assert "not found" in captured.err

    def test_target_dry_run_returns_zero_for_live_recipe(self, tmp_path: Path):
        package_path = tmp_path / "package.md"
        package_path.write_text(_VALID_PACKAGE, encoding="utf-8")
        rc = cli_main(["--target", "nlnet", "--dry-run", "--package", str(package_path)])
        assert rc == 0

    def test_mutual_exclusion_target_and_batch(self, capsys, tmp_path: Path):
        package_path = tmp_path / "package.md"
        package_path.write_text(_VALID_PACKAGE, encoding="utf-8")
        with pytest.raises(SystemExit):
            cli_main(
                [
                    "--target",
                    "nlnet",
                    "--batch",
                    "q2-2026",
                    "--package",
                    str(package_path),
                ]
            )

    def test_no_target_no_batch_errors(self, capsys, tmp_path: Path):
        package_path = tmp_path / "package.md"
        package_path.write_text(_VALID_PACKAGE, encoding="utf-8")
        with pytest.raises(SystemExit):
            cli_main(["--package", str(package_path)])

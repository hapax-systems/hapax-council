"""Tests for the PR review-team system.

Covers the lens registry + charters (``config/review-lenses/``) and the
constitution/synthesis/gate logic in ``scripts/review_team.py``.
Spec: ~/Documents/Personal/30-areas/hapax/pr-review-team-design-2026-06-11.md
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LENS_DIR = REPO_ROOT / "config" / "review-lenses"
REGISTRY_PATH = LENS_DIR / "registry.yaml"

CHECKLIST_ITEM_RE = re.compile(r"^- \[ \] (?P<slug>[a-z0-9-]+): \S", re.MULTILINE)


def _registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _all_registry_lenses(reg: dict) -> set[str]:
    lenses = set(reg["always_on_lenses"]) | set(reg["tests_only_lenses"])
    for row in reg["surface_lenses"]:
        lenses.update(row["lenses"])
    return lenses


class TestLensRegistry:
    def test_registry_parses_with_schema_1(self) -> None:
        reg = _registry()
        assert reg["registry_schema"] == 1

    def test_every_referenced_lens_has_a_charter_file(self) -> None:
        reg = _registry()
        missing = [
            lens
            for lens in sorted(_all_registry_lenses(reg))
            if not (LENS_DIR / f"{lens}.md").is_file()
        ]
        assert missing == []

    def test_sizing_matches_ratified_spec(self) -> None:
        sizing = _registry()["sizing"]
        assert sizing["t3_docs"]["team_size"] == 2
        assert sizing["t3_docs"]["quorum_accept"] == 2
        assert sizing["t2_standard"]["team_size"] == 3
        assert sizing["t2_standard"]["quorum_accept"] == 2
        assert sizing["t2_standard"]["min_families"] >= 2
        t1 = sizing["t1_critical"]
        assert t1["team_size_min"] == 4
        assert t1["team_size_max"] == 5
        assert t1["quorum_accept"] == 3
        assert t1["require_all_families"] is True
        assert t1["criticals_must_resolve"] is True

    def test_families_roster_covers_three_model_families(self) -> None:
        roster = _registry()["families"]
        families = {entry["family"] for entry in roster}
        assert {"claude", "codex", "gemini"} <= families
        for entry in roster:
            assert isinstance(entry["reviewer_command"], list) and entry["reviewer_command"]
            assert entry["timeout_seconds"] > 0

    def test_surface_rows_cover_spec_table(self) -> None:
        reg = _registry()
        surfaces = {row["surface"]: row for row in reg["surface_lenses"]}
        assert "voice-doctrine" in surfaces["daimonion"]["lenses"]
        assert "axiom-compliance" in surfaces["governance"]["lenses"]
        assert "audio-protected-invariants" in surfaces["audio"]["lenses"]
        assert "wire-contract" in surfaces["deploy"]["lenses"]
        assert "sdlc-legibility" in surfaces["sdlc"]["lenses"]
        assert "security" in surfaces["trust-boundary"]["lenses"]
        for row in reg["surface_lenses"]:
            assert row["globs"], f"surface {row['surface']} has no globs"

    def test_lane_families_map_lanes_to_families(self) -> None:
        lane_families = _registry()["lane_families"]
        assert lane_families["exact"]["zeta"] == "claude"
        assert lane_families["exact"]["iota"] == "gemini"
        assert lane_families["prefixes"]["cx-"] == "codex"
        assert lane_families["default"] == "claude"


def _load_review_team_module():
    import importlib.util
    import sys

    if "review_team" in sys.modules:
        return sys.modules["review_team"]
    path = REPO_ROOT / "scripts" / "review_team.py"
    spec = importlib.util.spec_from_file_location("review_team", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_team"] = module
    spec.loader.exec_module(module)
    return module


class TestLensSelection:
    def test_daimonion_diff_gets_daimonion_lenses_plus_always_on(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        lenses = rt.lenses_for_files(["agents/hapax_daimonion/voice.py"], reg)
        assert "correctness" in lenses
        assert "live-runtime-composition" in lenses
        assert "voice-doctrine" in lenses
        assert "tests-cover-the-diff" in lenses
        assert "exit-predicate-adequacy" in lenses
        assert "doc-claims-recheck" in lenses

    def test_tests_only_diff_gets_test_lenses(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        lenses = rt.lenses_for_files(["tests/test_x.py", "tests/sub/test_y.py"], reg)
        assert "test-validity" in lenses
        assert "anti-theater" in lenses

    def test_mixed_diff_is_not_tests_only(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        lenses = rt.lenses_for_files(["tests/test_x.py", "shared/foo.py"], reg)
        assert "test-validity" not in lenses

    def test_cc_script_diff_gets_sdlc_lenses(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        lenses = rt.lenses_for_files(["scripts/cc-pr-autoqueue.py"], reg)
        assert "sdlc-legibility" in lenses
        assert "sdlc-gate-compose" in lenses

    def test_no_duplicate_lenses(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        lenses = rt.lenses_for_files(
            ["scripts/cc-claim", "scripts/cc-close", "systemd/units/x.service"], reg
        )
        assert len(lenses) == len(set(lenses))


class TestTeamClassification:
    def test_docs_only_diff_is_t3(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        cls = rt.team_class_for({"risk_tier": "T2"}, ["docs/foo.md", "README.md"], reg)
        assert cls == "t3_docs"

    def test_risk_tier_t3_is_t3(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        assert rt.team_class_for({"risk_tier": "T3"}, ["shared/foo.py"], reg) == "t3_docs"

    def test_risk_tier_t1_is_t1(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        assert rt.team_class_for({"risk_tier": "T1"}, ["shared/foo.py"], reg) == "t1_critical"

    def test_governance_surface_forces_t1_even_at_t2(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        cls = rt.team_class_for({"risk_tier": "T2"}, ["systemd/units/x.service"], reg)
        assert cls == "t1_critical"

    def test_t1_surface_beats_docs_only(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        cls = rt.team_class_for({"risk_tier": "T2"}, ["axioms/registry.yaml", "docs/x.md"], reg)
        assert cls == "t1_critical"

    def test_default_is_t2(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        assert rt.team_class_for({"risk_tier": "T2"}, ["shared/foo.py"], reg) == "t2_standard"


class TestConstitution:
    def test_t2_team_is_three_seats_at_least_two_families_writer_minority(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team("t2_standard", "claude", reg, pr_number=101)
        assert len(team.seats) == 3
        families = [seat.family for seat in team.seats]
        assert len(set(families)) >= 2
        assert families.count("claude") <= 1  # writer family never the majority alone

    def test_t1_team_has_all_three_families(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team("t1_critical", "claude", reg, pr_number=7)
        assert 4 <= len(team.seats) <= 5
        assert {"claude", "codex", "gemini"} <= {seat.family for seat in team.seats}

    def test_t3_team_is_two_seats_two_families(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team("t3_docs", "claude", reg, pr_number=3)
        assert len(team.seats) == 2
        assert len({seat.family for seat in team.seats}) == 2

    def test_seat_ids_are_unique(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team("t1_critical", "codex", reg, pr_number=11)
        ids = [seat.id for seat in team.seats]
        assert len(ids) == len(set(ids))

    def test_constitution_is_deterministic(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        a = rt.constitute_team("t2_standard", "codex", reg, pr_number=42)
        b = rt.constitute_team("t2_standard", "codex", reg, pr_number=42)
        assert [(s.id, s.family) for s in a.seats] == [(s.id, s.family) for s in b.seats]

    def test_t1_with_missing_family_fails_closed(self) -> None:
        import pytest

        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        with pytest.raises(ValueError, match="family"):
            rt.constitute_team(
                "t1_critical", "claude", reg, pr_number=5, available_families=("claude", "codex")
            )

    def test_writer_family_from_lane(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        assert rt.writer_family_for_lane("zeta", reg) == "claude"
        assert rt.writer_family_for_lane("cx-gold", reg) == "codex"
        assert rt.writer_family_for_lane("iota", reg) == "gemini"
        assert rt.writer_family_for_lane(None, reg) == "claude"
        assert rt.writer_family_for_lane("mystery-lane", reg) == "claude"


class TestLensCharters:
    def test_charters_have_frontmatter_and_checklist_items(self) -> None:
        reg = _registry()
        for lens in sorted(_all_registry_lenses(reg)):
            path = LENS_DIR / f"{lens}.md"
            text = path.read_text(encoding="utf-8")
            assert text.startswith("---\n"), f"{lens}: missing frontmatter"
            fm = yaml.safe_load(text.split("---", 2)[1])
            assert fm["lens_id"] == lens, f"{lens}: lens_id mismatch"
            assert fm["version"] >= 1
            items = CHECKLIST_ITEM_RE.findall(text)
            assert len(items) >= 3, f"{lens}: only {len(items)} checklist items"
            assert len(items) == len(set(items)), f"{lens}: duplicate item slugs"
            assert "pass / finding / NA" in text, f"{lens}: missing verdict contract"

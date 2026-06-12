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
ALWAYS_ON_CHECKLIST = {
    "tests-cover-the-diff": {
        "diff-behavior-coverage": "pass",
        "red-before-green": "na",
        "new-paths-tested": "pass",
        "no-coverage-theater": "pass",
    },
    "exit-predicate-adequacy": {
        "predicate-testable": "pass",
        "predicate-evidenced": "pass",
        "diff-matches-predicate": "pass",
        "witness-durability": "pass",
    },
    "doc-claims-recheck": {
        "recheck-cmds-present": "pass",
        "claims-match-code": "pass",
        "stale-docs-updated": "pass",
        "next-actions-on-error": "pass",
    },
}
ALWAYS_ON_LENSES = tuple(ALWAYS_ON_CHECKLIST)


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
        gemini = next(entry for entry in roster if entry["family"] == "gemini")
        assert "--skip-trust" in gemini["reviewer_command"]

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

    def test_review_team_substrate_gets_sdlc_lenses(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        lenses = rt.lenses_for_files(
            ["scripts/review_team.py", "config/review-lenses/registry.yaml"], reg
        )
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

    def test_review_team_substrate_forces_t1_even_at_t2(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        assert (
            rt.team_class_for({"risk_tier": "T2"}, ["scripts/review_team.py"], reg) == "t1_critical"
        )
        assert (
            rt.team_class_for({"risk_tier": "T2"}, ["config/review-lenses/registry.yaml"], reg)
            == "t1_critical"
        )

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


def _review(
    reviewer_id: str,
    family: str,
    verdict: str = "accept",
    findings: list[dict] | None = None,
    checklist: dict | None = None,
) -> dict:
    return {
        "id": reviewer_id,
        "family": family,
        "verdict": verdict,
        "findings": findings or [],
        "checklist": (checklist if checklist is not None else ALWAYS_ON_CHECKLIST),
    }


def _critical(title: str = "named critical", resolved: bool = False) -> dict:
    return {
        "severity": "critical",
        "lens": "correctness",
        "file": "shared/foo.py",
        "line": 10,
        "title": title,
        "detail": "detail",
        "resolved": resolved,
    }


def _synth(rt, reviews: list[dict], *, team_class: str = "t2_standard") -> dict:
    reg = rt.load_lens_registry()
    return rt.synthesize_dossier(
        task_id="task-x",
        pr_number=99,
        head_sha="a" * 40,
        team_class=team_class,
        registry=reg,
        reviews=reviews,
        lenses=ALWAYS_ON_LENSES,
        constituted_at="2026-06-11T20:00:00+00:00",
    )


class TestSynthesizeDossier:
    def test_two_of_three_accepts_is_quorum_accept(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept-with-findings"),
                _review("claude-1", "claude", "block", [_critical(resolved=True)]),
            ],
        )
        assert dossier["review_team_verdict"] == "quorum-accept"
        assert dossier["accept_count"] == 2
        assert dossier["dossier_schema"] == 1

    def test_accept_without_complete_checklist_does_not_count(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept", checklist={}),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "block"),
            ],
        )
        assert dossier["accept_count"] == 1
        assert dossier["review_team_verdict"] == "no-quorum"
        assert any(e["kind"] == "checklist-incomplete" for e in dossier["escalations"])

    def test_unresolved_critical_blocks_despite_quorum(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "block", [_critical()]),
            ],
        )
        assert dossier["review_team_verdict"] == "blocked"
        assert any(e["kind"] == "unresolved-critical" for e in dossier["escalations"])

    def test_cross_family_split_escalates_to_top(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "block", [_critical()]),
            ],
        )
        assert any(e["kind"] == "cross-family-split" for e in dossier["escalations"])

    def test_one_accept_is_no_quorum(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "invalid-output"),
                _review("claude-1", "claude", "invalid-output"),
            ],
        )
        assert dossier["review_team_verdict"] == "no-quorum"

    def test_invalid_output_never_counts_as_accept(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "invalid-output"),
                _review("gemini-1", "gemini", "invalid-output"),
                _review("claude-1", "claude", "invalid-output"),
            ],
        )
        assert dossier["accept_count"] == 0
        assert dossier["review_team_verdict"] == "no-quorum"

    def test_t1_needs_an_accept_from_every_family(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("codex-2", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "block"),
            ],
            team_class="t1_critical",
        )
        assert dossier["review_team_verdict"] == "no-quorum"

    def test_t2_needs_two_accepting_families(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("claude-1", "claude", "accept"),
                _review("claude-2", "claude", "accept"),
                _review("claude-3", "claude", "accept"),
            ],
        )
        assert dossier["review_team_verdict"] == "no-quorum"

    def test_t1_quorum_with_all_families_accepting(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "accept"),
                _review("codex-2", "codex", "accept-with-findings"),
            ],
            team_class="t1_critical",
        )
        assert dossier["review_team_verdict"] == "quorum-accept"

    def test_block_without_named_critical_is_escalated_not_blocking(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "block"),  # no critical finding named
            ],
        )
        assert dossier["review_team_verdict"] == "quorum-accept"
        assert any(e["kind"] == "block-without-named-critical" for e in dossier["escalations"])


def _write_dossier(tmp_path: Path, task_id: str, dossier: dict) -> Path:
    note = tmp_path / f"{task_id}.md"
    note.write_text(f"---\ntype: cc-task\ntask_id: {task_id}\n---\n", encoding="utf-8")
    dossier_path = tmp_path / f"{task_id}.review-dossier.yaml"
    dossier_path.write_text(yaml.safe_dump(dossier, sort_keys=False), encoding="utf-8")
    return note


class TestVerdictBlockers:
    def _frontmatter(self, task_id: str = "task-x") -> dict:
        return {"task_id": task_id}

    def _good_dossier(self, rt) -> dict:
        return _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "accept"),
            ],
        )

    def test_missing_dossier_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = tmp_path / "task-x.md"
        note.write_text("---\ntype: cc-task\ntask_id: task-x\n---\n", encoding="utf-8")
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert blockers == ("missing_review_dossier",)

    def test_malformed_dossier_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = tmp_path / "task-x.md"
        note.write_text("---\ntype: cc-task\ntask_id: task-x\n---\n", encoding="utf-8")
        (tmp_path / "task-x.review-dossier.yaml").write_text("[not a mapping]", encoding="utf-8")
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert any(b.startswith("review_dossier_malformed:") for b in blockers)

    def test_stale_head_sha_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._good_dossier(rt))
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="b" * 40)
        assert any(b.startswith("review_dossier_stale_head:") for b in blockers)

    def test_unknown_current_head_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._good_dossier(rt))
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha=None)
        assert "review_dossier_current_head_unknown" in blockers

    def test_quorum_accept_dossier_passes(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._good_dossier(rt))
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert blockers == ()

    def test_no_quorum_dossier_blocks_with_recomputed_count(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "invalid-output"),
                _review("claude-1", "claude", "invalid-output"),
            ],
        )
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert "review_dossier_quorum_not_met:1/2" in blockers
        assert any(b.startswith("review_team_verdict_not_quorum_accept:") for b in blockers)

    def test_malformed_recorded_quorum_blocks_without_crashing(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = self._good_dossier(rt)
        dossier["quorum_required"] = "two"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert "review_dossier_malformed:quorum_required:two" in blockers

    def test_missing_mandatory_lens_floor_blocks_even_if_verdict_lies(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = self._good_dossier(rt)
        dossier["lenses"] = []
        dossier["review_team_verdict"] = "quorum-accept"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert any(b.startswith("review_dossier_missing_required_lenses:") for b in blockers)

    def test_task_risk_tier_floor_blocks_downgraded_dossier(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = self._good_dossier(rt)
        dossier["team_class"] = "t3_docs"
        dossier["quorum_required"] = 2
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            {"task_id": "task-x", "risk_tier": "T1"}, note, pr_head_sha="a" * 40
        )
        assert "review_dossier_team_class_below_task_floor:t3_docs!=t1_critical" in blockers

    def test_changed_file_scope_recomputed_in_gate(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = self._good_dossier(rt)
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            changed_files=("scripts/review_team.py",),
        )
        assert "review_dossier_team_class_scope_mismatch:t2_standard!=t1_critical" in blockers
        assert any(
            b.startswith("review_dossier_missing_required_lenses:")
            and "sdlc-gate-compose" in b
            and "sdlc-legibility" in b
            for b in blockers
        )

    def test_empty_changed_file_scope_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._good_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            changed_files=(),
        )
        assert "review_dossier_changed_files_unknown" in blockers

    def test_unregistered_accept_family_blocks_even_if_family_count_passes(
        self, tmp_path: Path
    ) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("mystery-1", "mystery", "accept"),
                _review("claude-1", "claude", "block"),
            ],
        )
        dossier["review_team_verdict"] = "quorum-accept"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert "review_dossier_unknown_accept_family:mystery" in blockers

    def test_t2_single_family_accepts_block_even_if_verdict_lies(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("claude-1", "claude", "accept"),
                _review("claude-2", "claude", "accept"),
                _review("claude-3", "claude", "accept"),
            ],
        )
        dossier["review_team_verdict"] = "quorum-accept"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            {"task_id": "task-x", "assigned_to": "zeta"}, note, pr_head_sha="a" * 40
        )
        assert any(b.startswith("review_dossier_family_diversity:") for b in blockers)
        assert any(b.startswith("review_dossier_writer_family_majority:") for b in blockers)

    def test_incomplete_accept_checklist_blocks_even_if_verdict_lies(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept", checklist={}),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "accept"),
            ],
        )
        dossier["review_team_verdict"] = "quorum-accept"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert any(b.startswith("review_dossier_checklist_missing:codex-1") for b in blockers)

    def test_unresolved_critical_blocks_even_if_verdict_field_lies(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "block", [_critical()]),
            ],
        )
        dossier["review_team_verdict"] = "quorum-accept"  # tampered/buggy field
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert "review_dossier_unresolved_critical:1" in blockers

    def test_undersized_team_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
            ],
        )
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert any(b.startswith("review_dossier_team_undersized:") for b in blockers)

    def test_killswitch_disables_gate(self, tmp_path: Path, monkeypatch) -> None:
        rt = _load_review_team_module()
        monkeypatch.setenv("HAPAX_REVIEW_TEAM_GATE_OFF", "1")
        note = tmp_path / "task-x.md"
        note.write_text("---\ntype: cc-task\ntask_id: task-x\n---\n", encoding="utf-8")
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert blockers == ()

    def test_missing_task_id_is_unkeyable_not_missing_dossier(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = tmp_path / "anonymous.md"
        note.write_text("---\ntype: cc-task\n---\n", encoding="utf-8")
        blockers = rt.review_team_verdict_blockers({}, note, pr_head_sha="a" * 40)
        assert blockers == ("review_dossier_unkeyable:missing_task_id",)


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

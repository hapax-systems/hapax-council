"""Tests for the PR review-team system.

Covers the lens registry + charters (``config/review-lenses/``) and the
constitution/synthesis/gate logic in ``scripts/review_team.py``.
Spec: ~/Documents/Personal/30-areas/hapax/pr-review-team-design-2026-06-11.md
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
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


@pytest.fixture(autouse=True)
def _isolate_live_route_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _load_review_team_module()
    real_review_route_blocked_families = rt.review_route_blocked_families

    def isolated_review_route_blocked_families(registry, **kwargs):
        if kwargs.get("platform_registry") is not None:
            return real_review_route_blocked_families(registry, **kwargs)
        return {}

    monkeypatch.setattr(rt, "review_route_blocked_families", isolated_review_route_blocked_families)


def _registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _platform_registry_payload() -> dict:
    return json.loads((REPO_ROOT / "config" / "platform-capability-registry.json").read_text())


def _mark_route_fresh(route: dict, *, checked_at: str = "2026-05-09T20:55:00Z") -> None:
    route["route_state"] = "active"
    route["blocked_reasons"] = []
    route["freshness"]["capability_checked_at"] = checked_at
    route["freshness"]["quota_checked_at"] = checked_at
    route["freshness"]["resource_checked_at"] = checked_at
    route["freshness"]["provider_docs_checked_at"] = checked_at
    route["freshness"]["capability_stale_after"] = "365d"
    route["freshness"]["quota_stale_after"] = "365d"
    route["freshness"]["resource_stale_after"] = "365d"
    route["freshness"]["provider_docs_stale_after"] = "365d"
    route["freshness"]["evidence"] = {
        "capability": {"evidence_refs": ["test:fresh-capability"], "blocked_reasons": []},
        "quota": {"evidence_refs": ["test:fresh-quota"], "blocked_reasons": []},
        "resource": {"evidence_refs": ["test:fresh-resource"], "blocked_reasons": []},
        "provider_docs": {"evidence_refs": ["test:fresh-provider-docs"], "blocked_reasons": []},
    }
    route["telemetry"]["quota_source"] = "manual"
    route["telemetry"]["resource_source"] = "local_probe"
    for score in route["capability_scores"].values():
        score["observed_at"] = checked_at
        score["stale_after"] = "365d"
        if not score.get("evidence_refs"):
            score["evidence_refs"] = ["test:fresh-score"]
    for tool in route["tool_state"]:
        tool["observed_at"] = checked_at
        tool["stale_after"] = "365d"


def _review_safe_route(route: dict) -> None:
    route["authority_ceiling"] = "read_only"
    route["mutability"] = {
        "vault_docs": False,
        "source": False,
        "runtime": False,
        "public": False,
        "provider_spend": False,
    }
    route["tool_access"] = {
        "filesystem": "read_only",
        "shell": "none",
        "browser": False,
        "mcp": [],
    }
    route["worker_tier"] = "read_only_sidecar"
    route["approval_posture"] = "plan_mode_read_only"


def _platform_registry_with_route(route_id: str, *, admitted: bool):
    rt = _load_review_team_module()
    payload = _platform_registry_payload()
    route = next(row for row in payload["routes"] if row["route_id"] == route_id)
    _review_safe_route(route)
    if admitted:
        _mark_route_fresh(route)
    return rt.PlatformCapabilityRegistry.model_validate(payload)


def _registry_with_extra_review_descriptor(
    *,
    family: str = "haiku-review",
    route_id: str = "claude.headless.haiku",
    command: list[str] | None = None,
) -> dict:
    reg = _registry()
    route = next(
        (row for row in _platform_registry_payload()["routes"] if row["route_id"] == route_id),
        None,
    )
    wrapper = route["sanctioned_wrapper"] if route is not None else "scripts/missing-reviewer"
    reg["route_backed_review_families"] = [
        {
            "family": family,
            "route_id": route_id,
            "reviewer_command": command or [wrapper, "--review-seat"],
            "timeout_seconds": 1200,
        }
    ]
    return reg


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

    def test_voice_doctrine_consent_egress_criterion_passes_eval_plane_without_coverage_hole(
        self,
    ) -> None:
        # Class-closure canary (2026-06-15): the voice-doctrine consent-egress item carries the correct
        # CRITERION for data/LLM egress — a shared-gateway eval-plane call matching the deliberative
        # council's established pattern (e.g. composability classification on the 'balanced' route) PASSES,
        # and a finding is raised only for a NEW external sink / ungated sensitive egress. The old phrasing
        # had no such criterion, so all 4 families mis-fired it as a CRITICAL on PR #4143's eval-plane call.
        #
        # Crucially this does NOT scope consent-egress out of voice-doctrine: a daimonion eval-plane change
        # must STILL receive an egress-reviewing lens (security/consent-provenance are NOT path-selected for
        # bare agents/hapax_daimonion/ paths — only voice-doctrine is), so removing it would leave a coverage
        # hole. This test exercises lenses_for_files to prove the coverage is retained.
        #
        # Predicate is re-ratified in the linked parent_spec (pr-review-team-design-2026-06-11.md, Amendment
        # 2026-06-15: the operator chose the class-fix; the inline-criterion design is the accepted one, the
        # scope-out attempt is rejected for the coverage hole). Lens charters are LLM-consumed prose with no
        # deterministic judging code path, so the only unit-testable surfaces are SELECTION (lenses_for_files,
        # the real reviewer-prompt path) and the rendered charter content; the criterion's effect on verdicts
        # is validated by the re-review dossier, as for every other lens in the registry.
        rt = _load_review_team_module()
        reg = _registry()
        eval_plane_diff = ["agents/hapax_daimonion/segment_composability_gate.py"]
        lenses = rt.lenses_for_files(eval_plane_diff, reg)
        assert "voice-doctrine" in lenses, (
            "a daimonion eval-plane change must still get an egress-reviewing lens (no coverage hole)"
        )
        # consent-egress survives the real checklist parser the reviewer prompt is built from
        assert "consent-egress" in rt.charter_checklist_items("voice-doctrine"), (
            "consent-egress must remain a parsed checklist item the reviewers receive"
        )

        charter = (LENS_DIR / "voice-doctrine.md").read_text(encoding="utf-8")
        consent_line = next(
            (ln for ln in charter.splitlines() if ln.startswith("- [ ] consent-egress:")), ""
        )
        assert consent_line, "voice-doctrine must keep a consent-egress checklist item"
        low = consent_line.lower()
        # the AUDIO/broadcast half is retained — this lens's core duty (codex-1: pin both behaviors, not
        # just the eval-plane criterion, so deleting the TTS/broadcast gate language fails this test).
        assert "broadcast consent gates" in low, consent_line
        assert "tts" in low, consent_line
        # the eval-plane PASS criterion is present...
        assert "eval-plane" in low and "passes" in low, consent_line
        assert "balanced" in low, consent_line
        # ...and a finding is still raised for genuinely-unsafe egress (not a blanket exemption)
        assert "finding" in low and ("new" in low and "sink" in low), consent_line
        # do NOT reference trust-boundary as a lens (it is a SURFACE; its lenses are security +
        # silent-failure-hunting) and do NOT claim other lenses cover daimonion egress (they are not selected
        # for these paths).
        referenced = set(re.findall(r"[a-z-]+(?= lens)", low))
        assert "trust-boundary" not in referenced, consent_line

    def test_gemini_prompt_names_rdf_prefix_directives_as_valid_syntax(self) -> None:
        reg = _registry()
        gemini = next(row for row in reg["families"] if row["family"] == "gemini")
        assert gemini["reviewer_command"] == ["scripts/hapax-agy-reviewer"]
        prompt = (REPO_ROOT / "scripts" / "hapax-agy-reviewer").read_text(encoding="utf-8")
        assert "RDF/Turtle/TriG @prefix directives are" in prompt
        assert "valid source syntax" in prompt
        assert "path-like corruption" in prompt

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

    def test_families_roster_covers_four_model_families(self) -> None:
        roster = _registry()["families"]
        families = {entry["family"] for entry in roster}
        assert {"claude", "codex", "gemini", "glm"} <= families
        for entry in roster:
            assert isinstance(entry["reviewer_command"], list) and entry["reviewer_command"]
            assert entry["timeout_seconds"] > 0
        gemini = next(entry for entry in roster if entry["family"] == "gemini")
        assert gemini["reviewer_command"] == ["scripts/hapax-agy-reviewer"]
        assert "route_id" not in gemini
        gemini_wrapper = (REPO_ROOT / "scripts" / "hapax-agy-reviewer").read_text(encoding="utf-8")
        assert "fenced yaml code block" in gemini_wrapper
        assert "ONLY the dossier YAML" not in gemini_wrapper
        glm = next(entry for entry in roster if entry["family"] == "glm")
        assert glm["reviewer_command"] == ["scripts/hapax-glmcp-reviewer"]
        assert "route_id" not in glm

    def test_claude_family_forces_bare_fence_output(self) -> None:
        """Claude (a reasoning model) must be given a bare-fence output directive,
        or it prepends prose and the strict dossier parser discards its verdict as
        invalid-output (a lost vote — PR #4119 rounds 6-8). It carries the same
        no-prose contract gemini gets, delivered via --append-system-prompt."""
        roster = _registry()["families"]
        claude = next(entry for entry in roster if entry["family"] == "claude")
        cmd = claude["reviewer_command"]
        assert "--append-system-prompt" in cmd, "claude needs a system-prompt directive"
        command = " ".join(str(part) for part in cmd)
        # the directive must demand a single bare yaml fence with no prose
        assert "one fenced yaml code block" in command
        assert "invalid-output" in command  # states the consequence

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
        assert "iota" not in lane_families["exact"]
        assert lane_families["exact"]["cx-glmcp"] == "glm"
        assert lane_families["exact"]["codex-glmcp"] == "glm"
        assert lane_families["exact"]["glmcp"] == "glm"
        assert lane_families["prefixes"]["cx-"] == "codex"
        assert lane_families["prefixes"]["codex-"] == "codex"
        assert lane_families["prefixes"]["glm-"] == "glm"
        assert "agy-" not in lane_families["prefixes"]
        assert "antigrav-" not in lane_families["prefixes"]
        assert "iota" in lane_families["retired"]
        assert "agy" in lane_families["retired"]
        assert "antigrav" in lane_families["retired"]
        assert "agy-" in lane_families["retired_prefixes"]
        assert "antigrav-" in lane_families["retired_prefixes"]
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

    def test_system_dynamics_map_surface_beats_docs_only(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        cls = rt.team_class_for(
            {"risk_tier": "T2"},
            [
                "docs/architecture/system-dynamics-map-viewer.html",
                "docs/architecture/vendor/cytoscape-3.34.0.min.js",
            ],
            reg,
        )
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

    def test_t1_team_has_all_registry_families(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team("t1_critical", "claude", reg, pr_number=7)
        assert 4 <= len(team.seats) <= 5
        roster = {entry["family"] for entry in reg["families"]}
        assert roster <= {seat.family for seat in team.seats}

    def test_t1_route_blocked_family_degrades_with_receipt_reason(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team(
            "t1_critical",
            "codex",
            reg,
            pr_number=7,
            route_blocked_families={"gemini": ("route_specific_quota_receipt_absent",)},
        )
        families = {seat.family for seat in team.seats}
        assert "gemini" not in families
        assert team.quorum_required == int(reg["sizing"]["t2_standard"]["quorum_accept"])
        assert "degraded_to:t2_standard" in team.notes
        assert "degraded_family_route_blocked:gemini" in team.notes
        assert (
            "route_blocked_family_reason:gemini:agy.review.direct:"
            "route_specific_quota_receipt_absent"
        ) in team.notes
        assert "post_route_receipt_rereview_required" in team.notes

    def test_admitted_extra_review_route_joins_roster_and_restores_quorum(self) -> None:
        rt = _load_review_team_module()
        reg = _registry_with_extra_review_descriptor()
        platform_registry = _platform_registry_with_route("claude.headless.haiku", admitted=True)
        expanded = rt.review_registry_with_route_families(reg, platform_registry=platform_registry)

        families = {entry["family"] for entry in rt.review_family_entries(expanded)}
        assert "haiku-review" in families
        blocked = rt.review_route_blocked_families(reg, platform_registry=platform_registry)
        assert "haiku-review" not in blocked

        team = rt.constitute_team(
            "t2_standard",
            "codex",
            expanded,
            pr_number=0,
            available_families=("claude", "haiku-review"),
            route_blocked_families=blocked,
        )
        assert {seat.family for seat in team.seats} == {"claude", "haiku-review"}
        dossier = rt.synthesize_dossier(
            task_id="task-x",
            pr_number=99,
            head_sha="a" * 40,
            team_class="t2_standard",
            registry=expanded,
            reviews=[
                _review("claude-1", "claude", "accept"),
                _review("haiku-review-1", "haiku-review", "accept"),
                _review("claude-2", "claude", "invalid-output"),
            ],
            lenses=ALWAYS_ON_LENSES,
            constituted_at="2026-06-11T20:00:00+00:00",
        )
        assert dossier["review_team_verdict"] == "quorum-accept"
        assert dossier["accept_count"] == 2

    def test_blocked_extra_review_route_degrades_with_route_specific_reason(self) -> None:
        rt = _load_review_team_module()
        reg = _registry_with_extra_review_descriptor()
        platform_registry = _platform_registry_with_route("claude.headless.haiku", admitted=False)
        expanded = rt.review_registry_with_route_families(reg, platform_registry=platform_registry)
        blocked = rt.review_route_blocked_families(reg, platform_registry=platform_registry)

        assert "haiku-review" in blocked
        assert any(
            "fresh_capability_evidence_absent" in reason for reason in blocked["haiku-review"]
        )
        team = rt.constitute_team(
            "t2_standard",
            "codex",
            expanded,
            pr_number=0,
            route_blocked_families=blocked,
        )
        assert "haiku-review" not in {seat.family for seat in team.seats}
        assert "degraded_family_route_blocked:haiku-review" in team.notes
        assert any(
            note.startswith("route_blocked_family_reason:haiku-review:claude.headless.haiku:")
            for note in team.notes
        )

    def test_extra_review_route_requires_sanctioned_reviewer_command(self) -> None:
        rt = _load_review_team_module()
        reg = _registry_with_extra_review_descriptor(command=["scripts/not-sanctioned-reviewer"])
        platform_registry = _platform_registry_with_route("claude.headless.haiku", admitted=True)
        expanded = rt.review_registry_with_route_families(reg, platform_registry=platform_registry)
        blocked = rt.review_route_blocked_families(reg, platform_registry=platform_registry)

        assert blocked["haiku-review"] == (
            "claude.headless.haiku:reviewer_command_not_sanctioned_wrapper:"
            "scripts/not-sanctioned-reviewer",
        )
        team = rt.constitute_team(
            "t2_standard",
            "codex",
            expanded,
            pr_number=0,
            route_blocked_families=blocked,
        )
        assert "haiku-review" not in {seat.family for seat in team.seats}

    def test_missing_extra_review_route_degrades_without_seating(self) -> None:
        rt = _load_review_team_module()
        reg = _registry_with_extra_review_descriptor(route_id="claude.headless.nope")
        platform_registry = _platform_registry_with_route("claude.headless.haiku", admitted=True)
        expanded = rt.review_registry_with_route_families(reg, platform_registry=platform_registry)
        blocked = rt.review_route_blocked_families(reg, platform_registry=platform_registry)

        assert blocked["haiku-review"] == (
            "claude.headless.nope:route_missing_from_platform_registry",
        )
        team = rt.constitute_team(
            "t2_standard",
            "codex",
            expanded,
            pr_number=0,
            route_blocked_families=blocked,
        )
        assert "haiku-review" not in {seat.family for seat in team.seats}

    def test_worker_and_boutique_routes_do_not_autobecome_review_families(self) -> None:
        rt = _load_review_team_module()
        payload = _platform_registry_payload()
        for route_id in ("vibe.headless.full", "local_tool.local.worker"):
            route = next(row for row in payload["routes"] if row["route_id"] == route_id)
            _mark_route_fresh(route)
        platform_registry = rt.PlatformCapabilityRegistry.model_validate(payload)

        expanded = rt.review_registry_with_route_families(
            _registry(), platform_registry=platform_registry
        )
        families = {entry["family"] for entry in rt.review_family_entries(expanded)}
        assert {"vibe", "local_tool", "ornith", "fugu"}.isdisjoint(families)

    def test_static_review_roster_behavior_remains_unchanged_without_extra_descriptor(self) -> None:
        rt = _load_review_team_module()
        reg = _registry()
        entries = rt.review_family_entries(reg)

        assert [entry["family"] for entry in entries] == [
            entry["family"] for entry in reg["families"]
        ]
        assert rt.review_family_route_ids(reg) == {
            "gemini": "agy.review.direct",
            "glm": "glmcp.review.direct",
        }

    def test_t2_team_can_seat_glm_as_independent_family(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team("t2_standard", "claude", reg, pr_number=101)
        assert "glm" in {seat.family for seat in team.seats}

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
        assert rt.writer_family_for_lane("codex-agy-cli", reg) == "codex"
        assert rt.writer_family_for_lane("cx-glmcp", reg) == "glm"
        assert rt.writer_family_for_lane("codex-glmcp", reg) == "glm"
        assert rt.writer_family_for_lane("glm-alpha", reg) == "glm"
        assert rt.writer_family_for_lane(None, reg) == "claude"
        assert rt.writer_family_for_lane("mystery-lane", reg) == "claude"

    def test_retired_authoring_lanes_fail_closed(self) -> None:
        import pytest

        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        for lane in ("iota", "antigrav", "antigrav-2", "antigravity", "agy", "agy-review"):
            with pytest.raises(ValueError, match="retired authoring lane"):
                rt.writer_family_for_lane(lane, reg)


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


def _synth(rt, reviews: list[dict], *, team_class: str = "t2_standard", **kwargs) -> dict:
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
        **kwargs,
    )


class TestSynthesizeDossier:
    def test_dossier_persists_scope_metadata(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "accept"),
            ],
            writer_family="claude",
            constitution_writer_family="codex",
            changed_files=("scripts/review_team.py", "config/review-lenses/registry.yaml"),
        )
        assert dossier["registry_id"] == "review-lenses"
        assert dossier["registry_declared_at"]
        assert dossier["writer_family"] == "claude"
        assert dossier["constitution_writer_family"] == "codex"
        assert dossier["changed_file_count"] == 2
        assert dossier["changed_files"] == [
            "scripts/review_team.py",
            "config/review-lenses/registry.yaml",
        ]

    def test_dossier_preserves_unknown_changed_files(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "accept"),
            ],
            changed_files=None,
            changed_file_count=None,
        )
        assert dossier["changed_file_count"] is None
        assert dossier["changed_files"] is None

    def test_reviewer_supplied_resolved_critical_blocks(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept-with-findings"),
                _review("claude-1", "claude", "block", [_critical(resolved=True)]),
            ],
        )
        assert dossier["review_team_verdict"] == "blocked"
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
                _review("glm-1", "glm", "accept"),
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

    def test_blocked_route_family_seated_blocks_admission(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._good_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            route_blocked_families={"gemini": ("route_specific_quota_receipt_absent",)},
        )
        assert "review_dossier_blocked_route_family_seated:gemini" in blockers

    def _route_blocked_degraded_dossier(self, rt) -> dict:
        notes = (
            "degraded_family_route_blocked:gemini",
            "route_blocked_family_reason:gemini:agy.review.direct:"
            "route_specific_quota_receipt_absent",
            "degraded_to:t2_standard",
            "post_route_receipt_rereview_required",
        )
        return _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("claude-1", "claude", "accept"),
                _review("glm-1", "glm", "accept"),
            ],
            team_class="t1_critical",
            constitution_notes=notes,
        )

    def test_route_blocked_degraded_dossier_passes_while_route_still_blocked(
        self, tmp_path: Path
    ) -> None:
        rt = _load_review_team_module()
        dossier = self._route_blocked_degraded_dossier(rt)
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            route_blocked_families={"gemini": ("route_specific_quota_receipt_absent",)},
        )
        assert dossier["review_team_verdict"] == rt.QUORUM_ACCEPT
        assert dossier["degraded_family_route_blocked"] == ["gemini"]
        assert dossier["post_route_receipt_rereview_required"] is True
        assert blockers == ()
        prefixed_blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            route_blocked_families={
                "gemini": ("agy.review.direct:route_specific_quota_receipt_absent",)
            },
        )
        assert prefixed_blockers == ()

    def test_recovered_route_block_invalidates_pending_degraded_admission(
        self, tmp_path: Path
    ) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._route_blocked_degraded_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            route_blocked_families={},
        )
        assert "review_dossier_route_block_degradation_unwitnessed:gemini" in blockers

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
            changed_file_count=1,
        )
        assert "review_dossier_team_class_scope_mismatch:t2_standard!=t1_critical" in blockers
        assert any(
            b.startswith("review_dossier_missing_required_lenses:")
            and "sdlc-gate-compose" in b
            and "sdlc-legibility" in b
            for b in blockers
        )

    def test_stronger_team_class_satisfies_weaker_scope(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "accept"),
                _review("codex-2", "codex", "accept"),
            ],
            team_class="t1_critical",
        )
        dossier["lenses"] = list(ALWAYS_ON_LENSES)
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            changed_files=("shared/foo.py",),
            changed_file_count=1,
        )
        assert not any(b.startswith("review_dossier_team_class_scope_mismatch:") for b in blockers)

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

    def test_truncated_changed_file_scope_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._good_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            changed_files=("shared/foo.py",),
            changed_file_count=2,
        )
        assert "review_dossier_changed_files_truncated:1/2" in blockers

    def test_missing_changed_file_count_blocks_when_files_are_supplied(
        self, tmp_path: Path
    ) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._good_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(),
            note,
            pr_head_sha="a" * 40,
            changed_files=("shared/foo.py",),
        )
        assert "review_dossier_changed_files_count_unknown" in blockers

    def test_dossier_task_id_mismatch_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = self._good_dossier(rt)
        dossier["task_id"] = "other-task"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert "review_dossier_task_id_mismatch:other-task!=task-x" in blockers

    def test_dossier_pr_mismatch_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._good_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._frontmatter(), note, pr_head_sha="a" * 40, pr_number=100
        )
        assert "review_dossier_pr_mismatch:99!=100" in blockers

    def test_unknown_reviewer_family_blocks_even_when_not_accepting(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("mystery-1", "mystery", "invalid-output"),
            ],
        )
        dossier["review_team_verdict"] = "quorum-accept"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert "review_dossier_unknown_reviewer_family:mystery" in blockers

    def test_unknown_reviewer_verdict_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = self._good_dossier(rt)
        dossier["reviewers"][2]["verdict"] = "banana"
        dossier["review_team_verdict"] = "quorum-accept"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert "review_dossier_unknown_reviewer_verdict:banana" in blockers

    def test_duplicate_reviewer_id_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = self._good_dossier(rt)
        dossier["reviewers"][1]["id"] = "codex-1"
        dossier["review_team_verdict"] = "quorum-accept"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert "review_dossier_duplicate_reviewer_id:codex-1" in blockers

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

    def test_reviewer_supplied_resolved_true_critical_still_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "block", [_critical(resolved=True)]),
            ],
        )
        dossier["review_team_verdict"] = "quorum-accept"
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

    def test_killswitch_false_does_not_disable_gate(self, tmp_path: Path, monkeypatch) -> None:
        rt = _load_review_team_module()
        monkeypatch.setenv("HAPAX_REVIEW_TEAM_GATE_OFF", "false")
        note = tmp_path / "task-x.md"
        note.write_text("---\ntype: cc-task\ntask_id: task-x\n---\n", encoding="utf-8")
        blockers = rt.review_team_verdict_blockers(self._frontmatter(), note, pr_head_sha="a" * 40)
        assert blockers == ("missing_review_dossier",)

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


class TestFamilyOutageDegradation:
    """Postmortem 2026-06-12 failure class #1: walls degrade the gate, never seal it."""

    WALL_2026_06_12 = "You've hit your weekly limit · resets 5pm America/Chicago"

    def test_the_20260612_wall_text_is_a_quota_wall(self) -> None:
        rt = _load_review_team_module()
        assert rt.is_quota_wall(self.WALL_2026_06_12, process_failed=True)
        assert rt.is_quota_wall(
            "You've hit your session limit · resets 10pm (America/Chicago)",
            process_failed=True,
        )
        assert rt.is_quota_wall(
            "You've hit your weekly limit · resets Jun 19, 5pm (America/Chicago)",
            process_failed=True,
        )
        assert rt.is_quota_wall(
            "You've hit your weekly limit · resets Jun 19, 5pm (America/Port-au-Prince)",
            process_failed=True,
        )
        assert rt.is_quota_wall(
            "You've hit your weekly limit · resets Jun 19, 5pm (America/Argentina/Buenos_Aires)",
            process_failed=True,
        )
        assert not rt.is_quota_wall(
            "You've hit your weekly limit · resets not a date and here is model prose",
            process_failed=True,
        )

    def test_wall_variants_classify_on_process_failure(self) -> None:
        rt = _load_review_team_module()
        assert rt.is_quota_wall("HTTP 429 Too Many Requests", process_failed=True)
        assert rt.is_quota_wall("RESOURCE_EXHAUSTED: Quota exceeded", process_failed=True)
        assert rt.is_quota_wall("rate limit reached for requests", process_failed=True)
        assert rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 429: "
            '{"error":{"message":"Quota exceeded"}}; retry later or check the '
            "Z.ai Coding Plan endpoint/status",
            process_failed=True,
        )
        assert rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 429: "
            '{"error":{"message":"insufficient balance"}}; retry later or check the '
            "Z.ai Coding Plan endpoint/status",
            process_failed=True,
        )
        assert rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 429; zai_error_code=1313; "
            "error_class=fair_use_restricted; action=hold_until_manual_clear",
            process_failed=True,
        )
        assert rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 429; zai_error_code=1121; "
            "error_class=account_hard_hold; action=contact_provider",
            process_failed=True,
        )
        assert rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 429; zai_error_code=1311; "
            "error_class=plan_model_unavailable; action=switch_model_or_upgrade_plan",
            process_failed=True,
        )
        assert rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 429; "
            "error_class=quota_exhausted; action=hold_until_reset; "
            "message=provider echoed action=not_a_control_token",
            process_failed=True,
        )
        assert not rt.is_quota_wall(
            "wrapper failed while reviewing text containing "
            "error_class=quota_exhausted action=hold_until_reset",
            process_failed=True,
        )
        assert not rt.is_quota_wall(
            "wrapper failed while reviewing text containing hapax-glmcp-reviewer: "
            "api error: HTTP 429; error_class=quota_exhausted; action=hold_until_reset",
            process_failed=True,
        )
        assert not rt.is_quota_wall(
            "wrapper failed while reviewing text containing HTTP 429 quota exceeded",
            process_failed=True,
        )
        assert not rt.is_quota_wall(
            "wrapper failed while reviewing text containing zai_error_code=1313 "
            "error_class=fair_use_restricted action=hold_until_manual_clear",
            process_failed=True,
        )
        assert not rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 418; "
            "error_class=api_error; action=inspect_provider_response; "
            "message=provider echoed error_class=quota_exhausted action=hold_until_reset",
            process_failed=True,
        )
        assert not rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 429; "
            "error_class=provider_high_traffic; action=backoff_or_switch_model; "
            "message=provider echoed quota exceeded hold_until_reset",
            process_failed=True,
        )
        assert not rt.is_quota_wall(
            "hapax-glmcp-reviewer: api error: HTTP 418; "
            "zai_error_code=x; error_class=quota_exhausted; action=hold_until_reset; "
            "error_class=api_error; action=inspect_provider_response",
            process_failed=True,
        )
        assert not rt.is_quota_wall("failed while checking line 429", process_failed=True)
        assert not rt.is_quota_wall(
            "HTTP 529: The service may be temporarily overloaded, please try again later",
            process_failed=True,
        )

    def test_provider_outage_variants_classify_on_process_failure(self) -> None:
        rt = _load_review_team_module()
        assert rt.is_provider_outage(
            "HTTP 529: The service may be temporarily overloaded, please try again later",
            process_failed=True,
        )
        assert rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 529: "
            '{"error":"The service may be temporarily overloaded, please try again later"}',
            process_failed=True,
        )
        assert rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 429: "
            '{"error":{"code":"1305","message":"The service may be temporarily overloaded, '
            'please try again later"}}; retry later or check the Z.ai Coding Plan endpoint/status',
            process_failed=True,
        )
        assert rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 429; zai_error_code=1312; "
            "error_class=provider_high_traffic; action=backoff_or_switch_model",
            process_failed=True,
        )
        assert rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 503; "
            "error_class=provider_error; action=retry_later",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "wrapper failed while reviewing text containing "
            "error_class=provider_error action=retry_later",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "wrapper failed while reviewing text containing hapax-glmcp-reviewer: "
            "api error: HTTP 503; error_class=provider_error; action=retry_later",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "wrapper failed while reviewing text containing HTTP 503 bad gateway",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "wrapper failed while reviewing text containing zai_error_code=1312 "
            "error_class=provider_high_traffic action=backoff_or_switch_model",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 418; "
            "error_class=api_error; action=inspect_provider_response; "
            "detail=provider echoed error_class=provider_error action=retry_later",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 503; "
            "error_class=quota_exhausted; action=hold_until_reset; "
            "detail=provider echoed temporarily overloaded retry later",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 418; "
            "error_class=api_error; action=inspect_provider_response; resets_at=x; "
            "error_class=provider_error; action=retry_later",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 429: "
            '{"error":{"message":"Quota exceeded"}}; retry later or check the '
            "Z.ai Coding Plan endpoint/status",
            process_failed=True,
        )
        assert rt.is_provider_outage(
            'hapax-glmcp-reviewer: api error: HTTP 529: {\n  "error": {\n'
            '    "message": "The service may be temporarily overloaded, please try again later"\n'
            "  }\n}",
            process_failed=True,
        )
        assert rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 502: Bad Gateway; "
            "retry later or check the Z.ai Coding Plan endpoint/status",
            process_failed=True,
        )
        assert rt.is_provider_outage(
            "other-reviewer: api error: HTTP 502: Bad Gateway; "
            "retry later or check the provider endpoint/status",
            process_failed=True,
        )
        for status in ("500", "501", "520", "530", "599"):
            assert rt.is_provider_outage(
                f"hapax-glmcp-reviewer: api error: HTTP {status}: provider failure; "
                "retry later or check the Z.ai Coding Plan endpoint/status",
                process_failed=True,
            )
        assert rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: network error: connection reset; "
            "retry later or check the Z.ai Coding Plan endpoint",
            process_failed=True,
        )
        assert rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: request timed out after 900s; "
            "retry later or reduce the review prompt size",
            process_failed=True,
        )
        assert not rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 529: "
            '{"error":"The service may be temporarily overloaded, please try again later"}',
            process_failed=False,
        )
        assert not rt.is_provider_outage(
            "Error authenticating: IneligibleTierError: This client is no longer "
            "supported for Gemini Code Assist for individuals.",
            process_failed=True,
            model_stdout="```yaml\nverdict: accept\n```",
        )
        assert not rt.is_provider_outage(
            "hapax-glmcp-reviewer: api error: HTTP 529: "
            '{"error":"The service may be temporarily overloaded, please try again later"}',
            process_failed=True,
            model_stdout="```yaml\nverdict: block\n```",
        )

    def test_reviewer_route_unavailable_classifies_on_process_failure(self) -> None:
        rt = _load_review_team_module()
        unsupported_client = (
            "Error authenticating: IneligibleTierError: This client is no longer "
            "supported for Gemini Code Assist for individuals. To continue using "
            "Gemini, please migrate to the Antigravity suite of products.\n"
            "reasonCode: 'UNSUPPORTED_CLIENT'"
        )
        assert rt.is_reviewer_route_unavailable(unsupported_client, process_failed=True)
        assert not rt.is_reviewer_route_unavailable(unsupported_client, process_failed=False)
        assert not rt.is_reviewer_route_unavailable(
            unsupported_client,
            process_failed=True,
            model_stdout="```yaml\nverdict: accept\n```",
        )
        embedded_marker = "wrapper prelude\n" + unsupported_client
        assert rt.is_reviewer_route_unavailable(embedded_marker, process_failed=True)
        oversized_marker = (
            "x" * (rt._REVIEWER_ROUTE_UNAVAILABLE_MAX_CHARS + 1) + "UNSUPPORTED_CLIENT"
        )
        assert not rt.is_reviewer_route_unavailable(oversized_marker, process_failed=True)
        advisory_only = "Please migrate to the Antigravity suite of products."
        assert not rt.is_reviewer_route_unavailable(advisory_only, process_failed=True)
        missing_agy = (
            "hapax-agy-reviewer: failed to launch /usr/bin/agy: [Errno 2] "
            "No such file or directory; install agy or pass --agy-bin /absolute/path/to/agy"
        )
        assert rt.is_reviewer_route_unavailable(missing_agy, process_failed=True)
        assert not rt.is_reviewer_route_unavailable(
            missing_agy,
            process_failed=True,
            model_stdout="```yaml\nverdict: accept\n```",
        )

    def test_agy_missing_binary_stderr_classifies_as_route_unavailable(
        self, tmp_path: Path
    ) -> None:
        rt = _load_review_team_module()
        wrapper = REPO_ROOT / "scripts" / "hapax-agy-reviewer"
        env = {**os.environ, "HAPAX_AGY_BIN": str(tmp_path / "agy")}

        result = subprocess.run(
            [str(wrapper)],
            input="review\n",
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )

        assert result.returncode == 2
        assert rt.is_reviewer_route_unavailable(
            result.stderr,
            process_failed=True,
            model_stdout=result.stdout,
        )

    def test_clean_exit_text_never_counts_as_wall_evidence(self) -> None:
        # round-6 channel trust: model-influenced stdout cannot forge a wall,
        # even by printing an exact provider-looking literal.
        rt = _load_review_team_module()
        assert not rt.is_quota_wall("HTTP 429 Too Many Requests", process_failed=False)
        assert not rt.is_quota_wall("RESOURCE_EXHAUSTED: Quota exceeded", process_failed=False)
        assert not rt.is_quota_wall(self.WALL_2026_06_12, process_failed=False)
        assert not rt.is_quota_wall("HTTP 429 error while fetching", process_failed=False)
        assert not rt.is_quota_wall("quota exceeded in the parser fixture", process_failed=False)
        assert not rt.is_quota_wall(
            'finding: the fixture quotes "You\'ve hit your weekly limit" in prose',
            process_failed=False,
        )
        assert not rt.is_quota_wall(
            "You've hit your weekly limit in a quoted fixture, but this is review prose",
            process_failed=False,
        )
        assert not rt.is_quota_wall(
            "You've hit your weekly limit\nverdict: block",
            process_failed=False,
        )

    def test_review_prose_is_not_a_wall(self) -> None:
        rt = _load_review_team_module()
        assert not rt.is_quota_wall("verdict: block\nfindings: the ring index wraps early")
        assert not rt.is_quota_wall("")

    # --- codex v0.139.0 chrome-wrapped wall (postmortem 2026-06-15) ---

    CODEX_V0139_STDERR = (
        "ERROR: You've hit your usage limit. Visit "
        "https://platform.openai.com/settings/organization/billing/overview to purchase "
        "more credits or visit https://platform.openai.com/usage to view your usage. If "
        "you have questions, please reach out to support@openai.com. You can try again "
        "at Jun 17 2026, 3:34:47 AM (UTC)."
    )

    def test_codex_v0139_chrome_wrapped_wall_detected(self) -> None:
        """The real codex v0.139.0 stderr — 704+ chars, buried in CLI chrome."""
        rt = _load_review_team_module()
        # Must detect as wall when process failed and stdout is empty
        assert rt.is_quota_wall(self.CODEX_V0139_STDERR, process_failed=True, model_stdout="")

    def test_codex_wall_with_nonempty_stdout_rejected(self) -> None:
        """Anti-forge: if the process emitted review content on stdout, the stderr
        wall text cannot be trusted (the model was active)."""
        rt = _load_review_team_module()
        assert not rt.is_quota_wall(
            self.CODEX_V0139_STDERR,
            process_failed=True,
            model_stdout="```review\nverdict: block\n```",
        )

    def test_codex_wall_with_whitespace_only_stdout_accepted(self) -> None:
        """Empty or whitespace-only stdout is still 'empty' — the process produced nothing."""
        rt = _load_review_team_module()
        assert rt.is_quota_wall(
            self.CODEX_V0139_STDERR, process_failed=True, model_stdout="   \n  "
        )

    def test_codex_wall_multiline_stderr_detected(self) -> None:
        """Codex may emit the wall phrase on one line plus additional lines of chrome."""
        rt = _load_review_team_module()
        multiline = (
            "codex v0.139.0 (stable)\n"
            "ERROR: You've hit your usage limit. Visit https://platform.openai.com to "
            "purchase more credits. You can try again at Jun 17 2026.\n"
            "For more information, run codex --help."
        )
        assert rt.is_quota_wall(multiline, process_failed=True, model_stdout="")

    def test_existing_bare_wall_still_works_with_model_stdout(self) -> None:
        """Backward compat: bare wall phrases still detected (model_stdout defaults to empty)."""
        rt = _load_review_team_module()
        assert rt.is_quota_wall(self.WALL_2026_06_12, process_failed=True)
        assert rt.is_quota_wall("HTTP 429 Too Many Requests", process_failed=True, model_stdout="")

    def test_t1_degrades_on_evidenced_outage(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team(
            "t1_critical", "codex", reg, pr_number=7, outage_families=frozenset({"claude"})
        )
        families = {seat.family for seat in team.seats}
        assert "claude" not in families
        assert len(families) >= 2
        assert "degraded_family_outage:claude" in team.notes
        assert "degraded_to:t2_standard" in team.notes
        assert "post_recovery_rereview_required" in team.notes
        # degraded quorum is t2's, and reachable with claude gone
        assert team.quorum_required == int(reg["sizing"]["t2_standard"]["quorum_accept"])

    def test_t1_still_seals_when_family_missing_without_outage_evidence(self) -> None:
        import pytest

        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        with pytest.raises(ValueError, match="family"):
            rt.constitute_team(
                "t1_critical",
                "claude",
                reg,
                pr_number=5,
                available_families=("claude", "codex"),
            )

    def test_degraded_synthesis_accepts_without_the_walled_family(self) -> None:
        rt = _load_review_team_module()
        notes = (
            "degraded_family_outage:claude",
            "degraded_to:t2_standard",
            "post_recovery_rereview_required",
        )
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("gemini-2", "gemini", "accept"),
            ],
            team_class="t1_critical",
            constitution_notes=notes,
        )
        assert dossier["review_team_verdict"] == rt.QUORUM_ACCEPT
        assert dossier["degraded_family_outage"] == ["claude"]
        assert dossier["post_recovery_rereview_required"] is True

    def test_undegraded_t1_still_requires_all_families_at_verdict(self) -> None:
        rt = _load_review_team_module()
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("gemini-2", "gemini", "accept"),
                _review("claude-1", "claude", "quota-wall", checklist={}),
            ],
            team_class="t1_critical",
        )
        assert dossier["review_team_verdict"] == "no-quorum"
        assert dossier["degraded_family_outage"] == []

    # --- the ADMISSION side (PR #4110 round-2 finding: the downstream gate
    # re-sealed what the constitution degraded) ---

    def _degraded_dossier(self, rt) -> dict:
        notes = (
            "degraded_family_outage:claude",
            "degraded_to:t2_standard",
            "post_recovery_rereview_required",
        )
        return _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("gemini-2", "gemini", "accept"),
            ],
            team_class="t1_critical",
            constitution_notes=notes,
        )

    def test_degraded_t1_dossier_passes_admission_validation(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._degraded_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=self._witness(tmp_path),
            admission_time="2026-06-11T20:30:00+00:00",
        )
        assert blockers == (), f"degraded dossier must admit, got: {blockers}"

    def test_inconsistent_degradation_flags_block_admission(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        dossier = self._degraded_dossier(rt)
        dossier["post_recovery_rereview_required"] = False  # forged/torn flags
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(), note, pr_head_sha="a" * 40
        )
        assert "review_dossier_degradation_flags_inconsistent" in blockers

    def test_degraded_dossier_with_walled_family_seated_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        notes = (
            "degraded_family_outage:claude",
            "degraded_to:t2_standard",
            "post_recovery_rereview_required",
        )
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("claude-1", "claude", "accept"),  # walled family seated?!
            ],
            team_class="t1_critical",
            constitution_notes=notes,
        )
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=self._witness(tmp_path),
            admission_time="2026-06-11T20:30:00+00:00",
        )
        assert any(b.startswith("review_dossier_degraded_family_was_seated:") for b in blockers)

    # --- round 3: t2/t3 during an outage keep their OWN rules (the first
    # consistency cut sealed every non-t1 review conducted under an outage) ---

    def test_t2_constitution_under_outage_marks_without_sizing_swap(self) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        team = rt.constitute_team(
            "t2_standard", "codex", reg, pr_number=9, outage_families=frozenset({"claude"})
        )
        assert "claude" not in {s.family for s in team.seats}
        assert "degraded_family_outage:claude" in team.notes
        assert "post_recovery_rereview_required" in team.notes
        assert "degraded_to:t2_standard" not in team.notes
        assert team.quorum_required == int(reg["sizing"]["t2_standard"]["quorum_accept"])

    def test_t2_outage_dossier_passes_admission_validation(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        notes = ("degraded_family_outage:claude", "post_recovery_rereview_required")
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("gemini-2", "gemini", "accept"),
            ],
            team_class="t2_standard",
            constitution_notes=notes,
        )
        assert dossier["review_team_verdict"] == rt.QUORUM_ACCEPT
        assert dossier["degraded_family_outage"] == ["claude"]
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=self._witness(tmp_path),
            admission_time="2026-06-11T20:30:00+00:00",
        )
        assert blockers == (), f"t2 outage dossier must admit by its own rules, got: {blockers}"

    def test_t1_marker_on_a_t2_dossier_is_inconsistent(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        notes = (
            "degraded_family_outage:claude",
            "degraded_to:t2_standard",  # forged: a t2 class never swaps sizing
            "post_recovery_rereview_required",
        )
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("gemini-2", "gemini", "accept"),
            ],
            team_class="t2_standard",
            constitution_notes=notes,
        )
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(), note, pr_head_sha="a" * 40
        )
        assert "review_dossier_degradation_flags_inconsistent" in blockers

    @staticmethod
    def _witness(
        tmp_path,
        families=("claude",),
        observed="2026-06-11T19:30:00+00:00",
        started=None,
    ):
        p = tmp_path / "family-outage.json"
        if started is None:
            state = {f: observed for f in families}  # legacy str format
        else:
            # window format: a sustained outage has a stable outage_started_at + a moving observed_at
            state = {f: {"observed_at": observed, "outage_started_at": started} for f in families}
        p.write_text(json.dumps(state), encoding="utf-8")
        return p

    @staticmethod
    def _tfb_frontmatter(task_id: str = "task-x") -> dict:
        return {"task_id": task_id}

    def test_unwitnessed_degradation_blocks_admission(self, tmp_path) -> None:
        """Round-4 finding: dossier-internal consistency can be forged — the
        dispatcher's outage state is the external witness, and without it a
        degraded dossier must not admit."""

        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._degraded_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=tmp_path / "absent-witness.json",
        )
        assert any(b.startswith("review_dossier_degradation_unwitnessed:") for b in blockers)

    def test_recovered_witness_invalidates_pending_degraded_admission(self, tmp_path) -> None:
        # the family recovered (entry cleared) -> the pending degraded dossier
        # stops admitting: post_recovery_rereview_required, enforced mechanically
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._degraded_dossier(rt))
        empty_witness = tmp_path / "family-outage.json"
        empty_witness.write_text("{}", encoding="utf-8")
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=empty_witness,
        )
        assert any(b.startswith("review_dossier_degradation_unwitnessed:") for b in blockers)

    def test_expired_witness_blocks_current_admission(self, tmp_path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._degraded_dossier(rt))
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=self._witness(tmp_path),
            admission_time="2026-06-11T22:01:00+00:00",
        )
        assert any(b.startswith("review_dossier_degradation_unwitnessed:") for b in blockers)

    def test_sustained_outage_re_stamp_after_constitution_still_admits(
        self, tmp_path: Path
    ) -> None:
        """Clobber regression (#4142): the outage's observed_at is a MOVING latest stamp
        pushed forward every run. A degraded dossier constituted mid-outage must NOT be
        un-witnessed when a later run re-stamps observed_at PAST its constituted_at. The
        window model anchors validity on the STABLE outage_started_at (set when the
        sustained outage began): the dossier is valid iff constituted + admitted both fall
        in [outage_started_at, observed_at + TTL]. Re-stamping observed_at forward only
        EXTENDS the window, so a valid dossier stays valid."""
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._degraded_dossier(rt))  # constituted 20:00
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            # outage started 19:55; a later run re-stamped observed_at to 20:05 (5 min AFTER
            # constitution). The stable outage_started_at (19:55) <= constituted (20:00) anchors it.
            outage_state_path=self._witness(
                tmp_path, observed="2026-06-11T20:05:00+00:00", started="2026-06-11T19:55:00+00:00"
            ),
            admission_time="2026-06-11T20:30:00+00:00",
        )
        assert blockers == (), f"sustained-outage dossier must admit, got: {blockers}"

    def test_back_dated_constituted_before_outage_started_blocks(self, tmp_path: Path) -> None:
        """Anti-forge (#4246 review finding): abs() admitted a dossier whose constituted_at
        was back-dated to BEFORE the sustained outage was first observed. The window model
        requires constituted >= outage_started_at, so a back-dated dossier is correctly
        UN-witnessed — the abs() symmetric relaxation is NOT used."""
        rt = _load_review_team_module()
        # dossier claims it was constituted at 19:30, but the outage didn't start until 20:00
        dossier = self._degraded_dossier(rt)
        dossier["constituted_at"] = "2026-06-11T19:30:00+00:00"
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=self._witness(
                tmp_path, observed="2026-06-11T20:05:00+00:00", started="2026-06-11T20:00:00+00:00"
            ),
            admission_time="2026-06-11T20:30:00+00:00",
        )
        assert any(b.startswith("review_dossier_degradation_unwitnessed:") for b in blockers), (
            f"back-dated dossier (before outage started) must block, got: {blockers}"
        )

    def test_non_mapping_witness_is_a_named_blocker(self, tmp_path) -> None:
        rt = _load_review_team_module()
        note = _write_dossier(tmp_path, "task-x", self._degraded_dossier(rt))
        witness = tmp_path / "family-outage.json"
        witness.write_text("[]", encoding="utf-8")
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=witness,
            admission_time="2026-06-11T20:30:00+00:00",
        )
        assert any(b.startswith("review_dossier_degradation_unwitnessed:") for b in blockers)

    def test_long_quotaish_review_text_is_not_a_wall(self) -> None:
        # round-4: forging an outage via reply content must be harder than
        # hitting one — long unparseable text mentioning quota words stays
        # invalid-output
        rt = _load_review_team_module()
        long_reply = (
            "This change refactors the rate limit reached handling and the "
            "quota exceeded paths in the ingestion layer. " * 20
        )
        assert len(long_reply) > 600
        assert not rt.is_quota_wall(long_reply)

    def test_unknown_degraded_family_blocks_admission(self, tmp_path) -> None:
        # round-5: a nonsense family in the markers must not buy a downgrade
        rt = _load_review_team_module()
        notes = (
            "degraded_family_outage:claudex",
            "degraded_to:t2_standard",
            "post_recovery_rereview_required",
        )
        dossier = _synth(
            rt,
            [
                _review("codex-1", "codex", "accept"),
                _review("gemini-1", "gemini", "accept"),
                _review("gemini-2", "gemini", "accept"),
            ],
            team_class="t1_critical",
            constitution_notes=notes,
        )
        note = _write_dossier(tmp_path, "task-x", dossier)
        blockers = rt.review_team_verdict_blockers(
            self._tfb_frontmatter(),
            note,
            pr_head_sha="a" * 40,
            outage_state_path=self._witness(tmp_path, families=("claudex",)),
        )
        assert any(b.startswith("review_dossier_degradation_unknown_family:") for b in blockers)


class TestGoGate:
    """The fail-closed literal-defect verifier (the go-gate). A critical claiming a syntax error /
    compile failure / corruption / a specific broken line is INVALIDATED (does not block quorum)
    when the actual file at head refutes it — verified deterministically out-of-model (ast.parse for
    Python; file/line existence otherwise). Non-literal criticals are never touched."""

    def _py(self, root: Path, rel: str, src: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")

    def _lit(self, title: str, file: str = "shared/foo.py", line: int = 10) -> dict:
        return {
            "severity": "critical",
            "lens": "sdlc-gate-compose",
            "file": file,
            "line": line,
            "title": title,
        }

    def test_clean_python_syntax_claim_is_phantom(self, tmp_path: Path) -> None:
        # in-range syntax claim on a file that parses clean -> phantom (exercises the ast path)
        rt = _load_review_team_module()
        self._py(tmp_path, "shared/foo.py", "\n".join(f"x{i} = {i}" for i in range(20)) + "\n")
        f = self._lit("fatal syntax error: corrupted decorators", line=5)
        assert rt.verify_literal_defect_critical(f, tmp_path) is False

    def test_real_syntax_error_is_verified(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "bad.py", "def f(:\n")
        f = self._lit("syntax error: invalid syntax", file="bad.py", line=1)
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_clean_turtle_parse_claim_in_detail_is_phantom(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(
            tmp_path,
            "docs/ok.ttl",
            "@prefix ex: <https://example.test/> .\nex:s ex:p ex:o .\n",
        )
        f = self._lit(
            "corrupted namespace directive",
            file="docs/ok.ttl",
            line=1,
        )
        f["detail"] = "The file is unparseable Turtle because @prefix was corrupted."
        assert rt.verify_literal_defect_critical(f, tmp_path) is False

    def test_clean_turtle_namespace_contract_claim_is_phantom(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(
            tmp_path,
            "docs/ok.ttl",
            "@prefix ex: <https://example.test/> .\nex:s ex:p ex:o .\n",
        )
        f = self._lit(
            "Corrupted RDF namespace directive",
            file="docs/ok.ttl",
            line=1,
        )
        f["detail"] = "The namespace directive was replaced by `@bad/path.py`."
        assert rt.verify_literal_defect_critical(f, tmp_path) is False

    def test_path_like_at_literal_accepts_leading_space_before_at_path(self) -> None:
        rt = _load_review_team_module()
        assert rt._is_path_like_at_literal(" @bad/path.py") is True
        assert rt._is_path_like_at_literal("@bad/path.py") is True
        assert rt._is_path_like_at_literal("@prefix") is False

    def test_malformed_turtle_namespace_claim_with_absent_literal_is_kept(
        self, tmp_path: Path
    ) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "docs/bad.ttl", "@prefix ex: <https://example.test/> .\nex:s ex:p\n")
        f = self._lit(
            "Corrupted RDF namespace directive",
            file="docs/bad.ttl",
            line=1,
        )
        f["detail"] = "The namespace directive was replaced by `@bad/path.py`."
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_parseable_rdf_namespace_contract_semantic_claim_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(
            tmp_path,
            "docs/semantic.ttl",
            "@prefix wrong: <https://example.test/wrong/> .\nwrong:s wrong:p wrong:o .\n",
        )
        f = self._lit(
            "Invalid RDF namespace contract",
            file="docs/semantic.ttl",
            line=1,
        )
        f["detail"] = "The namespace IRI violates the documented semantic contract."
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_real_turtle_parse_error_is_verified(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "docs/bad.ttl", "@prefix ex: <https://example.test/> .\nex:s ex:p\n")
        f = self._lit("Turtle will not parse", file="docs/bad.ttl", line=2)
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_real_turtle_parse_error_with_absent_bad_literal_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "docs/bad.ttl", "@prefix ex: <https://example.test/> .\nex:s ex:p\n")
        f = self._lit("Turtle will not parse", file="docs/bad.ttl", line=2)
        f["detail"] = "The file contains `@bad/path.py` and will fail to parse."
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_clean_trig_parse_claim_is_phantom(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(
            tmp_path,
            "docs/ok.trig",
            "@prefix ex: <https://example.test/> .\nex:g { ex:s ex:p ex:o . }\n",
        )
        f = self._lit("TriG cannot be parsed", file="docs/ok.trig", line=1)
        assert rt.verify_literal_defect_critical(f, tmp_path) is False

    def test_absent_quoted_namespace_literal_on_cited_line_is_phantom(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "tests/test_fixture.py", 'value = "ordinary fixture"\n')
        f = self._lit(
            "Corrupted namespace directive in test data",
            file="tests/test_fixture.py",
            line=1,
        )
        f["detail"] = "The line uses `@bad/path.py` instead of `@prefix`."
        assert rt.verify_literal_defect_critical(f, tmp_path) is False

    def test_absent_quoted_namespace_literal_split_across_title_detail_is_phantom(
        self, tmp_path: Path
    ) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "tests/test_fixture.py", 'value = "@prefix ex:"\n')
        f = self._lit(
            "Corrupted string literal",
            file="tests/test_fixture.py",
            line=1,
        )
        f["detail"] = "The line uses `@bad/path.py` instead of `@prefix`."
        assert rt.verify_literal_defect_critical(f, tmp_path) is False

    def test_present_quoted_namespace_literal_on_cited_line_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "tests/test_fixture.py", 'value = "@bad/path.py"\n')
        f = self._lit(
            "Corrupted namespace directive in test data",
            file="tests/test_fixture.py",
            line=1,
        )
        f["detail"] = "The line uses `@bad/path.py` instead of `@prefix`."
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_absent_expected_namespace_iri_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(
            tmp_path,
            "docs/semantic.ttl",
            "@prefix wrong: <https://example.test/wrong/> .\nwrong:s wrong:p wrong:o .\n",
        )
        f = self._lit(
            "Invalid RDF namespace contract",
            file="docs/semantic.ttl",
            line=1,
        )
        f["detail"] = "The expected namespace IRI `https://example.test/required/` is absent."
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_absent_expected_prefix_directive_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(
            tmp_path,
            "docs/semantic.ttl",
            "@prefix wrong: <https://example.test/wrong/> .\nwrong:s wrong:p wrong:o .\n",
        )
        f = self._lit(
            "Missing required RDF namespace prefix",
            file="docs/semantic.ttl",
            line=1,
        )
        f["detail"] = "The expected directive `@prefix sd:` is absent."
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_absent_expected_full_prefix_directive_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(
            tmp_path,
            "docs/semantic.ttl",
            "@prefix wrong: <https://example.test/wrong/> .\nwrong:s wrong:p wrong:o .\n",
        )
        f = self._lit(
            "Missing required RDF namespace prefix",
            file="docs/semantic.ttl",
            line=1,
        )
        f["detail"] = (
            "The expected directive "
            "`@prefix sd: <https://hapax.local/ns/system-dynamics-map#> .` is absent."
        )
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_non_literal_critical_passes_through(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        f = self._lit("no regression test covers the new reviewer path")
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_semantic_critical_with_negated_syntax_phrase_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "scripts/review_team.py", "x = 1\n")
        f = self._lit(
            "Semantic criticals can be invalidated by incidental syntax words",
            file="scripts/review_team.py",
            line=1,
        )
        f["detail"] = "A real semantic critical says this is not a syntax error."
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_semantic_critical_with_negated_syntax_title_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "scripts/review_team.py", "x = 1\n")
        f = self._lit(
            "Not a syntax error: trust-boundary bypass",
            file="scripts/review_team.py",
            line=1,
        )
        f["detail"] = "A real semantic critical should not be invalidated on a clean file."
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_syntax_claim_beyond_file_is_phantom(self, tmp_path: Path) -> None:
        # the documented gemini confabulation: a SYNTAX claim citing a line absent from the file
        rt = _load_review_team_module()
        self._py(tmp_path, "shared/t.py", "a = 1\nb = 2\n")
        f = self._lit("syntax error at line 690", file="shared/t.py", line=690)
        assert rt.verify_literal_defect_critical(f, tmp_path) is False

    def test_semantic_out_of_range_critical_is_kept(self, tmp_path: Path) -> None:
        # claude-1 v2 fix: a SEMANTIC corrupt/malformed critical with an off (out-of-range) line is a
        # real finding with a wrong line number — it must NOT be invalidated (only syntax claims are).
        rt = _load_review_team_module()
        self._py(tmp_path, "shared/t.py", "a = 1\nb = 2\n")
        f = self._lit("corruption of shared state", file="shared/t.py", line=690)
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_wrong_checkout_skips_verification(self, tmp_path: Path) -> None:
        # claude-1 v2 fix: if local HEAD is not the reviewed commit, do NOT verify (keep all)
        rt = _load_review_team_module()
        (tmp_path / ".git").mkdir()  # a repo dir with no HEAD -> rev-parse fails -> cannot match
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        phantom = self._lit("fatal syntax error at line 690", line=690)
        reviews = [_review("gemini-1", "gemini", "block", findings=[phantom])]
        blocking, phantoms = rt._blocking_criticals(reviews, tmp_path, head_sha="deadbeef" * 5)
        assert len(blocking) == 1 and phantoms == []

    def test_nonexistent_file_is_kept(self, tmp_path: Path) -> None:
        # conservative: a claim citing a file not in the tree cannot be DISPROVEN -> keep it
        rt = _load_review_team_module()
        f = self._lit("syntax error", file="does/not/exist.py", line=1)
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_missing_file_field_literal_claim_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        f = {"severity": "critical", "lens": "x", "file": "", "line": None, "title": "syntax error"}
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_semantic_corrupt_on_clean_python_is_kept(self, tmp_path: Path) -> None:
        # THE false-negative fix (claude-1's critical on #4136): a SEMANTIC corrupt/malformed
        # critical on a file that parses clean must NOT be invalidated — not a syntax/compile claim.
        rt = _load_review_team_module()
        self._py(tmp_path, "shared/foo.py", "\n".join(f"x{i} = {i}" for i in range(20)) + "\n")
        f = self._lit("corrupt state handling here is malformed and unsafe")
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_unreadable_file_is_kept(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        p = tmp_path / "shared" / "blob.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xff\xfe\x00not-utf8\xff")
        f = self._lit("syntax error", file="shared/blob.py", line=1)
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_killswitch_disables_gate(self, tmp_path: Path, monkeypatch) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        phantom = self._lit("fatal syntax error at line 690", line=690)
        reviews = [_review("gemini-1", "gemini", "block", findings=[phantom])]
        monkeypatch.setenv("HAPAX_REVIEW_GO_GATE_OFF", "1")
        blocking, phantoms = rt._blocking_criticals(reviews, tmp_path)
        assert len(blocking) == 1 and phantoms == []

    def test_discover_repo_root_finds_git_dir(self, tmp_path: Path, monkeypatch) -> None:
        rt = _load_review_team_module()
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        assert rt._discover_repo_root() == tmp_path

    def test_blocking_criticals_uses_cwd_discovery(self, tmp_path: Path, monkeypatch) -> None:
        # the admission-gate production path: repo_root=None discovers the repo from cwd
        # v4: head_sha is now required for verification to fire, so provide one + mock matcher
        rt = _load_review_team_module()
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr(rt, "_repo_head_matches", lambda *a, **k: True)
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        phantom = self._lit("fatal syntax error at line 690", line=690)
        reviews = [_review("gemini-1", "gemini", "block", findings=[phantom])]
        monkeypatch.chdir(tmp_path)
        blocking, phantoms = rt._blocking_criticals(reviews, None, head_sha="a" * 40)
        assert blocking == [] and len(phantoms) == 1

    def test_phantom_literal_critical_does_not_block(self, tmp_path: Path, monkeypatch) -> None:
        rt = _load_review_team_module()
        # bypass the head_sha checkout-binding (separately covered by test_wrong_checkout); this
        # test exercises the synthesize verdict path with verification active.
        monkeypatch.setattr(rt, "_repo_head_matches", lambda *a, **k: True)
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        phantom = self._lit("fatal syntax error: corrupted decorators at line 690", line=690)
        reviews = [
            _review("gemini-1", "gemini", "block", findings=[phantom]),
            _review("claude-1", "claude", "accept"),
            _review("codex-1", "codex", "accept"),
        ]
        d = _synth(rt, reviews, repo_root=tmp_path)
        assert d["review_team_verdict"] != "blocked"
        assert any(e["kind"] == "invalidated-phantom-critical" for e in d["escalations"])
        finding = d["reviewers"][0]["findings"][0]
        assert finding["resolved"] is True
        assert finding["resolution_source"] == "review-go-gate"

    def test_phantom_only_block_counts_for_quorum(self, tmp_path: Path, monkeypatch) -> None:
        rt = _load_review_team_module()
        monkeypatch.setattr(rt, "_repo_head_matches", lambda *a, **k: True)
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        phantom = self._lit("fatal syntax error: corrupted decorators at line 690", line=690)
        reviews = [
            _review("gemini-1", "gemini", "block", findings=[phantom]),
            _review("codex-1", "codex", "accept"),
            _review("claude-1", "claude", "invalid-output"),
        ]
        dossier = _synth(rt, reviews, repo_root=tmp_path)

        assert dossier["review_team_verdict"] == rt.QUORUM_ACCEPT
        assert dossier["accept_count"] == 2
        assert dossier["reviewers"][0]["verdict"] == "block"
        assert dossier["reviewers"][0]["findings"][0]["resolution_source"] == "review-go-gate"

    def test_admission_counts_phantom_only_block_for_quorum(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        monkeypatch.setattr(rt, "_repo_head_matches", lambda *a, **k: True)
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        (tmp_path / ".git").mkdir()
        phantom = self._lit("fatal syntax error: corrupted decorators at line 690", line=690)
        reviews = [
            _review("gemini-1", "gemini", "block", findings=[phantom]),
            _review("codex-1", "codex", "accept"),
            _review("claude-1", "claude", "invalid-output"),
        ]
        dossier = _synth(rt, reviews, repo_root=tmp_path)

        monkeypatch.chdir(tmp_path)
        blockers = rt._dossier_validity_blockers(
            dossier,
            pr_head_sha="a" * 40,
            registry=reg,
        )

        assert "review_dossier_quorum_not_met:1/2" not in blockers
        assert "review_dossier_family_diversity:accept_families=1/2" not in blockers
        assert not any(b.startswith("review_team_verdict_not_quorum_accept:") for b in blockers)

    def test_admission_blocks_recorded_go_gate_resolution_from_wrong_checkout(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        reviewed = tmp_path / "reviewed"
        wrong_checkout = tmp_path / "wrong-checkout"
        reviewed.mkdir()
        wrong_checkout.mkdir()
        monkeypatch.setattr(rt, "_repo_head_matches", lambda *a, **k: True)
        self._py(reviewed, "shared/foo.py", "x = 1\n")
        phantom = self._lit("fatal syntax error: corrupted decorators at line 690", line=690)
        reviews = [
            _review("gemini-1", "gemini", "block", findings=[phantom]),
            _review("codex-1", "codex", "accept"),
            _review("claude-1", "claude", "invalid-output"),
        ]
        dossier = _synth(rt, reviews, repo_root=reviewed)
        assert dossier["reviewers"][0]["findings"][0]["resolution_source"] == "review-go-gate"

        monkeypatch.setattr(rt, "_repo_head_matches", lambda *a, **k: False)
        monkeypatch.chdir(wrong_checkout)
        blockers = rt._dossier_validity_blockers(
            dossier,
            pr_head_sha="a" * 40,
            registry=reg,
        )

        assert "review_dossier_unresolved_critical:1" in blockers

    def test_admission_uses_frontmatter_worktree_for_go_gate_from_wrong_checkout(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        reviewed = tmp_path / "reviewed"
        wrong_checkout = tmp_path / "wrong-checkout"
        reviewed.mkdir()
        wrong_checkout.mkdir()
        (reviewed / ".git").mkdir()
        self._py(reviewed, "shared/foo.py", "x = 1\n")
        monkeypatch.setattr(
            rt, "_repo_head_matches", lambda root, *a, **k: Path(root).resolve() == reviewed
        )
        phantom = self._lit("fatal syntax error: corrupted decorators at line 690", line=690)
        reviews = [
            _review("gemini-1", "gemini", "block", findings=[phantom]),
            _review("codex-1", "codex", "accept"),
            _review("claude-1", "claude", "invalid-output"),
        ]
        dossier = _synth(rt, reviews, repo_root=reviewed)

        monkeypatch.chdir(wrong_checkout)
        blockers = rt._dossier_validity_blockers(
            dossier,
            pr_head_sha="a" * 40,
            registry=reg,
            frontmatter={"mutation_scope_refs": [str(reviewed / "shared" / "foo.py")]},
        )

        assert "review_dossier_unresolved_critical:1" not in blockers
        assert "review_dossier_quorum_not_met:1/2" not in blockers
        assert "review_dossier_family_diversity:accept_families=1/2" not in blockers

    def test_admission_rejects_recorded_go_gate_resolution_for_semantic_critical(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        wrong_checkout = tmp_path / "wrong-checkout"
        wrong_checkout.mkdir()
        semantic = _critical("logic error: trusted dossier can suppress semantic critical")
        semantic["resolved"] = True
        semantic["resolution_source"] = "review-go-gate"
        semantic["resolution_detail"] = "literal-defect critical refuted by the file at head"
        dossier = _synth(
            rt,
            [
                _review("gemini-1", "gemini", "block", findings=[semantic]),
                _review("codex-1", "codex", "accept"),
                _review("claude-1", "claude", "accept"),
            ],
            repo_root=tmp_path,
        )
        dossier["review_team_verdict"] = rt.QUORUM_ACCEPT

        monkeypatch.chdir(wrong_checkout)
        blockers = rt._dossier_validity_blockers(
            dossier,
            pr_head_sha="a" * 40,
            registry=reg,
        )

        assert "review_dossier_unresolved_critical:1" in blockers

    def test_real_literal_critical_still_blocks(self, tmp_path: Path) -> None:
        rt = _load_review_team_module()
        self._py(tmp_path, "bad.py", "def f(:\n")
        real = self._lit("syntax error: invalid syntax", file="bad.py", line=1)
        reviews = [
            _review("codex-1", "codex", "block", findings=[real]),
            _review("claude-1", "claude", "accept"),
            _review("gemini-1", "gemini", "accept"),
        ]
        d = _synth(rt, reviews, repo_root=tmp_path)
        assert d["review_team_verdict"] == "blocked"

    def test_non_literal_critical_still_blocks(self, tmp_path: Path) -> None:
        # the verifier must never suppress a non-literal-defect critical
        rt = _load_review_team_module()
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        nonlit = self._lit("logic error: off-by-one drops the last element")
        reviews = [
            _review("codex-1", "codex", "block", findings=[nonlit]),
            _review("claude-1", "claude", "accept"),
            _review("gemini-1", "gemini", "accept"),
        ]
        d = _synth(rt, reviews, repo_root=tmp_path)
        assert d["review_team_verdict"] == "blocked"

    def test_eof_syntax_error_kept(self, tmp_path: Path) -> None:
        """v4 fix: a REAL broken .py with a syntax claim citing a line past EOF must return True
        (keep). The out-of-range shortcut was removed — ast.parse catches the real error."""
        rt = _load_review_team_module()
        # 3-line file that genuinely fails to parse
        self._py(tmp_path, "broken.py", "def f():\n    pass\ndef g(:\n")
        f = self._lit("syntax error at line 10", file="broken.py", line=10)
        assert rt.verify_literal_defect_critical(f, tmp_path) is True

    def test_empty_head_sha_skips_verification(self, tmp_path: Path) -> None:
        """v4 fix: when head_sha is empty/None, _blocking_criticals must NOT verify — keep all
        criticals (the safe pre-go-gate behaviour). Prevents firing against an unverified checkout."""
        rt = _load_review_team_module()
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        phantom = self._lit("fatal syntax error at line 690", line=690)
        reviews = [_review("gemini-1", "gemini", "block", findings=[phantom])]
        # head_sha="" -> should skip verification, keep all as blocking
        blocking, phantoms = rt._blocking_criticals(reviews, tmp_path, head_sha="")
        assert len(blocking) == 1 and phantoms == []
        # head_sha=None -> same
        blocking2, phantoms2 = rt._blocking_criticals(reviews, tmp_path, head_sha=None)
        assert len(blocking2) == 1 and phantoms2 == []

    def test_admission_gate_drops_phantom_critical(self, tmp_path: Path, monkeypatch) -> None:
        """v4 integration: the admission gate (_dossier_validity_blockers) must NOT emit
        review_dossier_unresolved_critical for a syntax-claim phantom that ast.parse refutes.
        This exercises the go-gate on the admission path (lines 949-960), not just synthesize."""
        rt = _load_review_team_module()
        monkeypatch.setattr(rt, "_repo_head_matches", lambda *a, **k: True)
        self._py(tmp_path, "shared/foo.py", "x = 1\n")
        # a phantom syntax critical on a clean file — must be dropped by the go-gate
        phantom = self._lit("fatal syntax error: corrupted decorators at line 690", line=690)
        reviews = [
            _review("gemini-1", "gemini", "block", findings=[phantom]),
            _review("claude-1", "claude", "accept"),
        ]
        # Build a dossier that the admission gate will validate
        reg = rt.load_lens_registry()
        dossier = rt.synthesize_dossier(
            task_id="task-admission-test",
            pr_number=99,
            head_sha="a" * 40,
            team_class="t2_standard",
            registry=reg,
            reviews=reviews,
            lenses=ALWAYS_ON_LENSES,
            constituted_at="2026-06-11T20:00:00+00:00",
            repo_root=tmp_path,
        )
        # The synthesizer should have already dropped the phantom
        assert dossier["review_team_verdict"] != "blocked"
        # Now validate via the admission gate path (_dossier_validity_blockers)
        # which independently calls _blocking_criticals
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir(exist_ok=True)
        blockers = rt._dossier_validity_blockers(
            dossier,
            pr_head_sha="a" * 40,
            registry=reg,
        )
        # The phantom critical must NOT appear as an unresolved-critical blocker
        critical_blockers = [b for b in blockers if "unresolved_critical" in b]
        assert critical_blockers == [], f"phantom critical should not block admission: {blockers}"

    def test_synthesize_dossier_persists_head_sha(self, tmp_path: Path) -> None:
        """Refutes reviewer claim: 'synthesize_dossier never persists head_sha'.
        Line 739 of review_team.py unconditionally writes head_sha into the dossier."""
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        dossier = rt.synthesize_dossier(
            task_id="task-sha-test",
            pr_number=1,
            head_sha="abc123def456" * 4,  # 48 chars, arbitrary
            team_class="t2_standard",
            registry=reg,
            reviews=[_review("g-1", "gemini", "accept"), _review("c-1", "claude", "accept")],
            lenses=ALWAYS_ON_LENSES,
            constituted_at="2026-06-11T20:00:00+00:00",
            repo_root=tmp_path,
        )
        assert dossier["head_sha"] == "abc123def456" * 4, "synthesize_dossier MUST persist head_sha"

    def test_admission_gate_uses_dossier_head_sha_for_go_gate(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Refutes reviewer claim: 'admission-gate ignores pr_head_sha'.
        _dossier_validity_blockers passes dossier head_sha to _blocking_criticals (line 950-951)
        and blocks when head_sha is stale (line 805-806)."""
        rt = _load_review_team_module()
        reg = rt.load_lens_registry()
        dossier = rt.synthesize_dossier(
            task_id="task-sha-admission",
            pr_number=2,
            head_sha="a" * 40,
            team_class="t2_standard",
            registry=reg,
            reviews=[_review("g-1", "gemini", "accept"), _review("c-1", "claude", "accept")],
            lenses=ALWAYS_ON_LENSES,
            constituted_at="2026-06-11T20:00:00+00:00",
            repo_root=tmp_path,
        )
        # With matching pr_head_sha: no stale_head blocker
        blockers_match = rt._dossier_validity_blockers(dossier, pr_head_sha="a" * 40, registry=reg)
        stale = [b for b in blockers_match if "stale_head" in b]
        assert stale == [], f"matching head_sha should not trigger stale_head: {stale}"

        # With mismatched pr_head_sha: MUST emit stale_head blocker
        blockers_mismatch = rt._dossier_validity_blockers(
            dossier, pr_head_sha="b" * 40, registry=reg
        )
        stale = [b for b in blockers_mismatch if "stale_head" in b]
        assert len(stale) == 1, f"mismatched head_sha MUST trigger stale_head: {blockers_mismatch}"


def test_gemini_reviewer_prompt_has_diff_awareness():
    """Regression guard: the gemini reviewer hallucinated phantom IndentationError /
    SyntaxError / invalid-decorator criticals by misreading unified-diff +/- prefixes
    and context paths as source code, blocking valid PRs (#4135, #4161, #4163) that
    claude + codex accepted. Its reviewer_command prompt must declare that diff
    prefixes are syntax, not code, so it confirms a defect against real line content."""
    reg = _registry()
    gemini = next(f for f in reg["families"] if (f.get("family") or f.get("name")) == "gemini")
    assert gemini["reviewer_command"] == ["scripts/hapax-agy-reviewer"]
    prompt = (REPO_ROOT / "scripts" / "hapax-agy-reviewer").read_text(encoding="utf-8")
    assert "UNIFIED DIFF" in prompt, "gemini reviewer prompt lost its diff-awareness guard"
    assert "DIFF SYNTAX" in prompt


def test_gemini_reviewer_denies_repo_roaming_and_blocks_phantom_syntax():
    """Durable fix for the gemini plan-mode hallucination (deadlocked PR #4167): in
    plan-mode gemini ROAMED the repo (grep/read) and manufactured phantom syntax
    criticals (notify-failure@%n.service read as invalid template syntax) AND a false
    'volatile cache' critical on the canonical source-activation deploy path -- blocking a
    PR that claude + codex accepted. The reviewer_command must (a) enforce a
    deny-roaming equivalent by invoking agy in sandboxed print mode and telling the
    reviewer it has no repository access, and (b) tell gemini the diff already passed CI
    so it does not block on phantom syntax findings."""
    reg = _registry()
    gemini = next(f for f in reg["families"] if (f.get("family") or f.get("name")) == "gemini")
    cmd = [str(part) for part in gemini["reviewer_command"]]
    assert cmd == ["scripts/hapax-agy-reviewer"]
    wrapper = (REPO_ROOT / "scripts" / "hapax-agy-reviewer").read_text(encoding="utf-8")
    assert "--sandbox" in wrapper, "agy reviewer must use sandboxed print mode"
    assert "no repository access" in wrapper
    prompt = wrapper
    assert "fenced yaml code block" in prompt
    assert "no prose" in prompt
    assert "ALREADY PASSED" in prompt and "CI" in prompt, "gemini prompt must cite the CI gates"
    assert "source-activation" in prompt, "gemini prompt must whitelist the canonical deploy path"


def test_gemini_review_family_uses_agy_wrapper_not_legacy_cli():
    """Gemini-family review seats must not execute the retired gemini binary."""

    reg = _registry()
    gemini = next(f for f in reg["families"] if (f.get("family") or f.get("name")) == "gemini")
    assert gemini["reviewer_command"] == ["scripts/hapax-agy-reviewer"]
    wrapper = (REPO_ROOT / "scripts" / "hapax-agy-reviewer").read_text(encoding="utf-8")
    assert "--print" in wrapper
    assert "--model" in wrapper
    assert "agy" in wrapper


class TestClassifyFailureReceipt:
    """The additive classify_failure() helper — the review-plane measurement-spine API. It applies the
    same priority order as the dispatch verdict (quota > route > provider > else) and never
    auto-degrades (UNKNOWN default). These pin THIS helper's branch mapping + priority behaviorally;
    no production consumer invokes classify_failure yet, so behavioral parity against the dispatch
    else-if path lands with the worker-path consumer slice (a source-text .index() cross-check would
    be coverage theater — #4249 round-4 review)."""

    def test_quota_wall_maps_to_quota_exhaustion_lossless(self) -> None:
        rt = _load_review_team_module()
        from shared.failure_classification import FailureCode

        receipt = rt.classify_failure(
            "You've hit your weekly limit · resets 5pm America/Chicago",
            process_failed=True,
            platform="claude",
            route_id="claude.headless.opus",
        )
        assert receipt.code is FailureCode.QUOTA_EXHAUSTION
        assert receipt.raw_signal.startswith("You've hit")  # lossless
        assert receipt.platform == "claude" and receipt.route_id == "claude.headless.opus"

    def test_route_unavailable_maps_to_route_unavailable(self) -> None:
        rt = _load_review_team_module()
        from shared.failure_classification import FailureCode

        receipt = rt.classify_failure(
            "IneligibleTierError: client tier not allowed", process_failed=True
        )
        assert receipt.code is FailureCode.ROUTE_UNAVAILABLE

    def test_provider_outage_maps_to_provider_outage(self) -> None:
        rt = _load_review_team_module()
        from shared.failure_classification import FailureCode

        receipt = rt.classify_failure("HTTP 503; service unavailable", process_failed=True)
        assert receipt.code is FailureCode.PROVIDER_OUTAGE

    def test_no_classifier_fires_defaults_to_unknown_no_degrade(self) -> None:
        rt = _load_review_team_module()
        from shared.failure_classification import FailureCode

        # not a process failure -> the anti-forge short-circuits fire -> nothing classifies -> UNKNOWN
        receipt = rt.classify_failure(
            "model prose mentioning quota and overload", process_failed=False
        )
        assert receipt.code is FailureCode.UNKNOWN

    def test_route_takes_priority_over_provider_outage(self) -> None:
        rt = _load_review_team_module()
        from shared.failure_classification import FailureCode

        # a text that fires BOTH is_reviewer_route_unavailable AND is_provider_outage; classify_failure
        # checks route before provider (mirroring the dispatch else-if), so route must win.
        text = "HTTP 503 service unavailable; IneligibleTierError"
        assert rt.is_reviewer_route_unavailable(text, process_failed=True)
        assert rt.is_provider_outage(text, process_failed=True)
        assert rt.classify_failure(text, process_failed=True).code is FailureCode.ROUTE_UNAVAILABLE

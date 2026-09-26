"""Tests for system release auto-arm — dispatch resilience to lane-death.

Reform improve (CASE-CAPACITY-ROUTING-001): a lane that dies after creating its
PR but before flipping ``release_authorized: true`` strands a CLEAN, green,
mergeable PR at ``pr_open`` forever. The autoqueue (running as the system,
unclaimed — FM-20) must auto-arm such a task — but only when its release was
already authorized-in-principle by its ISAP and every applicable sensitivity
class has machine-verified mitigation evidence.

Release auto-arm blocker reason codes are part of the reconciler/ledger
contract: ``risk_flag:{name}`` means no PR check evidence was supplied,
``needs_mitigation:{name}:{check}`` is emitted once per missing mitigation
check, and ``unmitigable_risk_flag:{name}`` means no automated mitigation gate
exists for that sensitive class.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.release_gate import (
    LIVE_EGRESS_CONSENT_CONTAINMENT_SURFACES,
    LIVE_EGRESS_CONSENT_COUPLED_ADMISSIONS,
    LIVE_EGRESS_MITIGATION_CHECKS,
    _path_in_consent_containment_lane,
    assess_release_auto_arm_estate,
)
from shared.sdlc_lifecycle import (
    RELEASE_MITIGATION_CHECKS,
    REVIEW_TEAM_QUORUM_EVIDENCE,
    apply_release_auto_arm,
    assess_release_auto_arm,
    release_auto_arm_waivers,
)


def _eligible_frontmatter(**overrides: object) -> dict[str, object]:
    """A pr_open, implementation-authorized, non-sensitive source task."""
    base: dict[str, object] = {
        "type": "cc-task",
        "task_id": "reform-improve-dispatch-resilience-20260601",
        "title": "Reform improve — make dispatch resilient to lane-death",
        "status": "pr_open",
        "stage": "S6_IMPLEMENTATION",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "~/Documents/Personal/30-areas/hapax/master-design.md",
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "risk_tier": "T2",
        "implementation_authorized": True,
        "release_authorized": False,
        "public_current": False,
        "tags": ["cc-task", "sdlc", "reform", "dispatch"],
    }
    base.update(overrides)
    return base


# ── subject / needs_arming gating ─────────────────────────────────────


def test_eligible_pr_open_unauthorized_nonsensitive_task_is_auto_armable() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter())
    assert assessment.subject is True
    assert assessment.armed is False
    assert assessment.needs_arming is True
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_task_without_release_authorized_field_is_not_subject() -> None:
    fm = _eligible_frontmatter()
    del fm["release_authorized"]
    assessment = assess_release_auto_arm(fm)
    assert assessment.subject is False
    assert assessment.needs_arming is False
    assert assessment.eligible is False


def test_already_release_authorized_task_does_not_need_arming() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(release_authorized=True))
    assert assessment.subject is True
    assert assessment.armed is True
    assert assessment.needs_arming is False
    assert assessment.eligible is False


# ── governance / sensitivity veto (AC2: sensitive stays manual) ────────


def test_ineligible_when_explicit_governance_risk_flag_set() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    assessment = assess_release_auto_arm(fm)
    assert assessment.needs_arming is True
    assert assessment.eligible is False
    assert "risk_flag:governance_sensitive" in assessment.blockers


def test_ineligible_when_governance_keyword_in_title_without_explicit_flags() -> None:
    fm = _eligible_frontmatter(
        title="Tighten governance policy enforcement on authority cases",
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("governance" in blocker for blocker in assessment.blockers)


def test_ineligible_when_audio_or_live_egress_sensitive() -> None:
    fm = _eligible_frontmatter(
        title="Adjust broadcast audio loudnorm egress chain",
        tags=["cc-task", "audio", "egress"],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("audio_or_live_egress" in blocker for blocker in assessment.blockers)


def test_audio_or_live_egress_sensitive_with_full_evidence_auto_arms() -> None:
    # The class is evidence-gated through the estate extension
    # (cc-task-release-arm-held-sensitive-class-20260808): every mitigation
    # check passing, over a covered change surface, discharges the veto.
    fm = _eligible_frontmatter(risk_flags={"audio_or_live_egress_sensitive": True})
    assessment = assess_release_auto_arm_estate(
        fm,
        verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS),
        changed_files=["shared/capability_adapter_protocol.py"],
    )
    assert not any("audio_or_live_egress" in blocker for blocker in assessment.blockers)
    assert assessment.eligible is True


def test_canon_map_still_fails_the_class_closed_without_the_wrapper() -> None:
    # The canon-hashed map (sdlc_lifecycle.py, byte-pinned by the Gate 0A
    # fixture) is deliberately UNCHANGED: the plain canon assessment still
    # fails the class closed. The extension lives only in the estate wrapper.
    fm = _eligible_frontmatter(risk_flags={"audio_or_live_egress_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS))
    assert assessment.eligible is False
    assert "unmitigable_risk_flag:audio_or_live_egress_sensitive" in assessment.blockers
    assert "audio_or_live_egress_sensitive" not in RELEASE_MITIGATION_CHECKS


def test_audio_or_live_egress_sensitive_held_per_missing_mitigation_check() -> None:
    # Each missing check is its own needs_mitigation blocker.
    fm = _eligible_frontmatter(risk_flags={"audio_or_live_egress_sensitive": True})
    full = set(LIVE_EGRESS_MITIGATION_CHECKS)
    for missing in sorted(full):
        assessment = assess_release_auto_arm_estate(fm, verified_checks=full - {missing})
        assert assessment.eligible is False
        assert f"needs_mitigation:audio_or_live_egress_sensitive:{missing}" in assessment.blockers


def test_audio_path_scope_stays_human_released_with_full_evidence() -> None:
    # config/pipewire/ is a SENSITIVE_PATH_MARKERS hit: the audio lane keeps its
    # human release even when the class's mitigation evidence is complete. The
    # remaining hold is exactly the path gate — with full evidence supplied, no
    # flag-derived blocker survives (the independence pin for the new entry).
    fm = _eligible_frontmatter(
        risk_flags={"audio_or_live_egress_sensitive": True},
        mutation_scope_refs=["config/pipewire/routes.conf", "scripts/hapax-audio-routing-check"],
    )
    assessment = assess_release_auto_arm_estate(
        fm, verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS)
    )
    assert assessment.eligible is False
    assert any(
        "sensitive_path:config/pipewire/routes.conf" in blocker for blocker in assessment.blockers
    )
    assert not any("audio_or_live_egress" in blocker for blocker in assessment.blockers)


def test_audio_or_live_egress_mitigation_contract_is_exact() -> None:
    # Drift pin: this tuple IS what the release gate accepts as mitigation for a
    # live-egress class. Extending or narrowing it changes what the system will
    # release — a ratification act, never an edit. Update this test deliberately.
    assert LIVE_EGRESS_MITIGATION_CHECKS == (
        "egress-boundary-pin",
        "authority-case-check",
        "capability-surface-delta",
        "secrets-scan",
        REVIEW_TEAM_QUORUM_EVIDENCE,
    )


def _egress_frontmatter() -> dict[str, object]:
    return _eligible_frontmatter(risk_flags={"audio_or_live_egress_sensitive": True})


def test_egress_auto_arm_coverage_bound_admits_covered_paths() -> None:
    # The behavioral evidence covers exactly the pinned surface; a PR changing
    # only it (plus docs) auto-arms with the full mitigation set.
    assessment = assess_release_auto_arm_estate(
        _egress_frontmatter(),
        verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS),
        changed_files=[
            "shared/capability_adapter_protocol.py",
            "tests/test_capability_adapter_protocol.py",
            "docs/runbooks/capabilityio-session-gate.md",
        ],
    )
    assert not any("egress_evidence_uncovered" in b for b in assessment.blockers)
    assert assessment.eligible is True


def test_egress_auto_arm_coverage_bound_holds_uncovered_paths() -> None:
    # A live-egress-sensitive PR changing a non-doc path the pin suite does not
    # cover has NO machine behavioral evidence for its change — held, even with
    # every mitigation check green (evidence must cover the surface changed).
    assessment = assess_release_auto_arm_estate(
        _egress_frontmatter(),
        verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS),
        changed_files=["shared/capability_adapter_protocol.py", "scripts/hapax-operator-message"],
    )
    assert assessment.eligible is False
    assert any(
        blocker.startswith("egress_evidence_uncovered_paths:scripts/hapax-operator-message")
        for blocker in assessment.blockers
    )


def test_consent_containment_lane_surfaces_is_exact() -> None:
    # Drift pin: this tuple IS the consent-containment lane the release gate
    # admits past the coverage bound. Extending or narrowing it re-scopes what
    # a live-egress-sensitive PR may touch without new behavioral evidence —
    # a ratification act, never an edit. Update this test deliberately, and
    # extend the egress-boundary-pin job's consent pins first: evidence
    # follows coverage, coverage follows the pin suite. Production sources are
    # exact files (fail-closed for future files beside them); only
    # axioms/contracts (person-named deletions) and the test trees (not egress
    # surfaces; landing layer is the merge-queue full shard) are directories.
    assert LIVE_EGRESS_CONSENT_CONTAINMENT_SURFACES == (
        ".github/workflows/ci.yml",
        "agents/_governance.py",
        "agents/_governance/carrier.py",
        "agents/_governance/consent.py",
        "agents/_governance/consent_gate.py",
        "agents/_governance/consent_label.py",
        "agents/_governance/consent_reader.py",
        "agents/_governance/provenance.py",
        "agents/_governance/revocation.py",
        "agents/hapax_daimonion/conversation_pipeline.py",
        "agents/hapax_daimonion/conversational_policy.py",
        "agents/studio_compositor/consent.py",
        "agents/studio_compositor/consent_live_egress.py",
        "axioms/contracts",
        "logos/_governance.py",
        "logos/api/deps/stream_redaction.py",
        "logos/api/routes/consent.py",
        "logos/api/routes/data.py",
        "packages/agentgov/src/agentgov/carrier.py",
        "packages/agentgov/src/agentgov/consent.py",
        "packages/agentgov/src/agentgov/consent_label.py",
        "packages/agentgov/src/agentgov/provenance.py",
        "packages/agentgov/src/agentgov/revocation.py",
        "packages/agentgov/tests",
        "scripts/archive-purge.py",
        "scripts/hapax-guest-consent",
        "scripts/screwm-guest-source.py",
        "scripts/vulture_whitelist.py",
        "shared/face_enrollment_registry.py",
        "shared/governance/consent.py",
        "shared/governance/consent_gate.py",
        "shared/governance/consent_reader.py",
        "tests/conftest.py",
        "tests/hapax_daimonion",
        "tests/logos",
        "tests/scripts",
        "tests/shared",
        "tests/test_affordance_pipeline.py",
        "tests/test_archive_purge.py",
        "tests/test_consent_gate.py",
        "tests/test_consent_label.py",
        "tests/test_consent_pipeline_reader.py",
        "tests/test_revocation_wiring.py",
    )
    # The count is machine-checked so prose can never understate the lane's
    # governance blast radius (review F round 3): 43 entries, not fewer.
    assert len(LIVE_EGRESS_CONSENT_CONTAINMENT_SURFACES) == 43


def test_consent_containment_lane_admits_lane_shapes() -> None:
    # Every non-doc shape of the containment PR class — contract deletions,
    # test helpers, package sources, gate files, docs — passes the coverage
    # bound with the full mitigation set: the lane's pins (per PR) plus the
    # full suite at landing are its behavioral evidence.
    assessment = assess_release_auto_arm_estate(
        _egress_frontmatter(),
        verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS),
        changed_files=[
            "shared/release_gate.py",
            "axioms/contracts/contract-removed-one.yaml",
            "axioms/contracts/contract-removed-two.yaml",
            "packages/agentgov/src/agentgov/consent.py",
            "packages/agentgov/tests/test_consent_binding.py",
            "agents/_governance/consent_reader.py",
            "tests/shared/test_consent_round_ten.py",
            "agents/studio_compositor/consent_live_egress.py",
            ".github/workflows/ci.yml",
            "tests/test_consent_gate.py",
            "tests/test_consent_label.py",
            "docs/runbooks/pii-containment.md",
        ],
    )
    assert not any("egress_evidence_uncovered" in b for b in assessment.blockers)
    assert assessment.eligible is True


def test_consent_containment_lane_boundary_is_anchored() -> None:
    # The lane is exact-or-directory-prefix, never substring, and production
    # trees fail CLOSED for future files: a sibling of a lane entry, a
    # lookalike extension, and a brand-new production source beside admitted
    # ones are all outside the lane and held by the coverage bound.
    assessment = assess_release_auto_arm_estate(
        _egress_frontmatter(),
        verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS),
        changed_files=[
            "shared/governance/other.py",
            "agents/_governance.py.bak",
            "packages/agentgov/src/agentgov/new_egress.py",
            "agents/_governance/new_surface.py",
            "agents/studio_compositor/compositor.py",
            "agents/studio_compositor/lifecycle.py.bak",
            "agents/hapax_daimonion/_perception_state_writer.py.bak",
        ],
    )
    assert assessment.eligible is False
    blockers = list(assessment.blockers)
    for held in (
        "agents/_governance.py.bak",
        "agents/_governance/new_surface.py",
        "agents/hapax_daimonion/_perception_state_writer.py.bak",
        "agents/studio_compositor/compositor.py",
        "agents/studio_compositor/lifecycle.py.bak",
        "packages/agentgov/src/agentgov/new_egress.py",
        "shared/governance/other.py",
    ):
        assert any(held in blocker for blocker in blockers), (
            f"lane boundary leaked for {held}: {blockers}"
        )


def test_consent_containment_lane_membership_is_exact_and_degenerate_safe() -> None:
    # Direct unit pin for the lane matcher: exact-file and under-directory
    # admission, sibling/lookalike denials, and degenerate inputs — empty and
    # whitespace-only paths match nothing.
    assert _path_in_consent_containment_lane("shared/governance/consent.py")
    assert _path_in_consent_containment_lane("agents/_governance.py")
    assert _path_in_consent_containment_lane("tests/logos/test_anything.py")
    assert _path_in_consent_containment_lane(".github/workflows/ci.yml")
    assert _path_in_consent_containment_lane("tests/test_consent_gate.py")
    assert _path_in_consent_containment_lane("tests/test_consent_label.py")
    # The coupled admissions are NOT lane members: they are admitted only with
    # their consent suite in the same PR (LIVE_EGRESS_CONSENT_COUPLED_ADMISSIONS).
    assert not _path_in_consent_containment_lane("agents/studio_compositor/lifecycle.py")
    assert not _path_in_consent_containment_lane("agents/studio_compositor/models.py")
    assert not _path_in_consent_containment_lane("agents/studio_compositor/state.py")
    assert not _path_in_consent_containment_lane(
        "agents/hapax_daimonion/_perception_state_writer.py"
    )
    assert not _path_in_consent_containment_lane(
        "tests/studio_compositor/test_recording_consent_fail_closed.py"
    )
    assert not _path_in_consent_containment_lane("tests/studio_compositor/test_other.py")
    assert not _path_in_consent_containment_lane("agents/studio_compositor")
    assert not _path_in_consent_containment_lane("agents/studio_compositor/compositor.py")
    assert not _path_in_consent_containment_lane("agents/studio_compositor/lifecycle.py.bak")
    assert not _path_in_consent_containment_lane("agents/studio_compositor/state/x.py")
    assert not _path_in_consent_containment_lane(
        "agents/hapax_daimonion/_perception_state_writer.py.bak"
    )
    assert not _path_in_consent_containment_lane("tests/studio_compositor_other/x.py")
    assert not _path_in_consent_containment_lane(".github/workflows/ci.yml.bak")
    assert not _path_in_consent_containment_lane(".github/workflows/other.yml")
    assert not _path_in_consent_containment_lane("tests/test_consent_gate.py.bak")
    assert not _path_in_consent_containment_lane("shared/governance/other.py")
    assert not _path_in_consent_containment_lane("agents/_governance.py.bak")
    assert not _path_in_consent_containment_lane("tests/logos-other/x.py")
    assert not _path_in_consent_containment_lane("")
    assert not _path_in_consent_containment_lane("   ")
    assert not _path_in_consent_containment_lane("./shared/governance/consent.py")
    assert not _path_in_consent_containment_lane("packages/agentgov/src/agentgov/other.py")


_WRITER = "agents/hapax_daimonion/_perception_state_writer.py"
_WRITER_SUITE = "tests/hapax_daimonion/test_perception_state_writer_consent.py"
_COMPOSITOR_SUITE = "tests/studio_compositor/test_recording_consent_fail_closed.py"
_COMPOSITOR_SOURCES = (
    "agents/studio_compositor/lifecycle.py",
    "agents/studio_compositor/models.py",
    "agents/studio_compositor/state.py",
)


def _egress_uncovered(
    changed_files: list[str], deleted_files: tuple[str, ...] | None = ()
) -> set[str]:
    assessment = assess_release_auto_arm_estate(
        _egress_frontmatter(),
        verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS),
        changed_files=changed_files,
        deleted_files=deleted_files,
    )
    prefix = "egress_evidence_uncovered_paths:"
    return {
        path
        for blocker in assessment.blockers
        if blocker.startswith(prefix)
        for path in blocker[len(prefix) :].split(",")
    }


def test_consent_coupled_admissions_are_exact() -> None:
    # Drift pin: each production source is admitted past the coverage bound
    # ONLY together with its consent suite in the same PR — never alone, as a
    # lane member would be. Changing a pairing is a ratification act.
    assert LIVE_EGRESS_CONSENT_COUPLED_ADMISSIONS == (
        (
            "agents/hapax_daimonion/_perception_state_writer.py",
            "tests/hapax_daimonion/test_perception_state_writer_consent.py",
        ),
        (
            "agents/studio_compositor/lifecycle.py",
            "tests/studio_compositor/test_recording_consent_fail_closed.py",
        ),
        (
            "agents/studio_compositor/models.py",
            "tests/studio_compositor/test_recording_consent_fail_closed.py",
        ),
        (
            "agents/studio_compositor/state.py",
            "tests/studio_compositor/test_recording_consent_fail_closed.py",
        ),
    )


def test_consent_coupled_admission_admits_consent_fail_closed_live_perception_shape() -> None:
    # The exact changed-file set of the compositor recording-consent and
    # perception-writer fail-closed fix: four production sources, each with
    # its consent suite in the same PR. Nothing is left outside the bound.
    # The writer suite is covered by the pre-existing tests/hapax_daimonion
    # directory entry, which this change does not touch; pin that premise.
    assert "tests/hapax_daimonion" in LIVE_EGRESS_CONSENT_CONTAINMENT_SURFACES
    assert not _egress_uncovered([_WRITER, *_COMPOSITOR_SOURCES, _WRITER_SUITE, _COMPOSITOR_SUITE])


def test_consent_coupled_writer_alone_fails_closed() -> None:
    # Unsafe case: a PR touching the perception writer without its consent
    # suite stays held, exactly as before the admission existed.
    assert _egress_uncovered([_WRITER]) == {_WRITER}


def test_consent_coupled_compositor_alone_fails_closed() -> None:
    for source in _COMPOSITOR_SOURCES:
        assert _egress_uncovered([source]) == {source}
    assert _egress_uncovered(list(_COMPOSITOR_SOURCES)) == set(_COMPOSITOR_SOURCES)


def test_consent_coupled_production_with_the_wrong_suite_fails_closed() -> None:
    # A consent suite admits only its own production sources.
    assert _egress_uncovered([_WRITER, _COMPOSITOR_SUITE]) == {_WRITER}
    assert _egress_uncovered([*_COMPOSITOR_SOURCES, _WRITER_SUITE]) == set(_COMPOSITOR_SOURCES)
    assert _egress_uncovered([_COMPOSITOR_SOURCES[0], "tests/studio_compositor/test_other.py"]) == {
        _COMPOSITOR_SOURCES[0],
        "tests/studio_compositor/test_other.py",
    }


def test_consent_coupled_admission_admits_only_the_named_suites() -> None:
    # Narrowed option D: the named consent suites are admitted as exact files;
    # the rest of tests/studio_compositor (ignored/deselected files included)
    # and every sibling of a coupled source stay held.
    assert not _egress_uncovered([_COMPOSITOR_SUITE])
    assert _egress_uncovered(
        [
            "tests/studio_compositor/test_face_obscure_pipeline.py",
            f"{_COMPOSITOR_SUITE}.bak",
            "agents/studio_compositor/compositor.py",
            f"{_WRITER}.bak",
        ]
    ) == {
        "tests/studio_compositor/test_face_obscure_pipeline.py",
        f"{_COMPOSITOR_SUITE}.bak",
        "agents/studio_compositor/compositor.py",
        f"{_WRITER}.bak",
    }


def test_consent_coupled_source_with_deleted_suite_fails_closed() -> None:
    # Unsafe case: the suite is in the changed files because the PR DELETES it.
    # A deleted suite is not carried: the source stays held, and so does the
    # deletion itself (removing a named consent suite is never admitted).
    assert _egress_uncovered([_WRITER, _WRITER_SUITE], deleted_files=(_WRITER_SUITE,)) == {_WRITER}
    assert _egress_uncovered(
        [*_COMPOSITOR_SOURCES, _COMPOSITOR_SUITE], deleted_files=(_COMPOSITOR_SUITE,)
    ) == {*_COMPOSITOR_SOURCES, _COMPOSITOR_SUITE}


def test_consent_coupled_unknown_change_status_fails_closed() -> None:
    # A caller that cannot say which files were deleted (deleted_files=None)
    # gets no coupled admission at all; lane members are unaffected.
    assert _egress_uncovered(
        [_WRITER, *_COMPOSITOR_SOURCES, _WRITER_SUITE, _COMPOSITOR_SUITE], deleted_files=None
    ) == {_WRITER, *_COMPOSITOR_SOURCES, _COMPOSITOR_SUITE}
    assert not _egress_uncovered(["tests/test_consent_gate.py"], deleted_files=None)


def test_consent_coupled_admission_ignores_unrelated_deletions() -> None:
    # Deleting an unrelated file does not revoke a carried suite.
    assert (
        _egress_uncovered(
            [_WRITER, _WRITER_SUITE, "tests/shared/test_old.py"],
            deleted_files=("tests/shared/test_old.py",),
        )
        == set()
    )


def test_consent_coupled_production_sources_exist() -> None:
    # The coupled production sources exist at this head. Their suites arrive
    # with the fix PR itself; an absent suite can never satisfy the coupling,
    # so absence fails closed rather than hollow.
    repo_root = Path(__file__).resolve().parents[1]
    missing = [
        source
        for source, _suite in LIVE_EGRESS_CONSENT_COUPLED_ADMISSIONS
        if not (repo_root / source).is_file()
    ]
    assert not missing, (
        f"coupled production sources absent from the tree: {missing}. Next action: "
        f"re-point the coupling at the moved source, or remove the pairing by ratification."
    )


#: Directory entries the lane doctrine admits: axioms/contracts (person-named
#: deletions) and the test trees. Every other entry is a production source and
#: must be an exact file, so a future file beside it stays outside the lane.
_LANE_DIRECTORY_ENTRIES_ADMITTED = frozenset(
    {
        "axioms/contracts",
        "packages/agentgov/tests",
        "tests/hapax_daimonion",
        "tests/logos",
        "tests/scripts",
        "tests/shared",
    }
)


def test_consent_containment_lane_production_entries_are_exact_files() -> None:
    # Unsafe case: a production directory admitted where only exact files are
    # ratified (e.g. agents/studio_compositor for its three consent-bearing
    # modules) would silently admit compositor.py and every future sibling.
    # Only the ratified directory entries may be directories on the tree.
    # Every ratified directory is itself a lane entry, checked apart from the
    # tree so a missing entry and a missing directory fail with distinct
    # messages.
    lane = set(LIVE_EGRESS_CONSENT_CONTAINMENT_SURFACES)
    assert not _LANE_DIRECTORY_ENTRIES_ADMITTED - lane, (
        f"ratified directory entries missing from the lane: "
        f"{sorted(_LANE_DIRECTORY_ENTRIES_ADMITTED - lane)}. Next action: restore "
        f"the entry in LIVE_EGRESS_CONSENT_CONTAINMENT_SURFACES, or, if the lane "
        f"narrowing is ratified, remove it from _LANE_DIRECTORY_ENTRIES_ADMITTED."
    )
    repo_root = Path(__file__).resolve().parents[1]
    directories = {entry for entry in lane if (repo_root / entry).is_dir()}
    assert not directories - _LANE_DIRECTORY_ENTRIES_ADMITTED, (
        f"production entries admitted as directories: "
        f"{sorted(directories - _LANE_DIRECTORY_ENTRIES_ADMITTED)}. Next action: "
        f"replace each with the exact consent-bearing files beneath it; add a "
        f"test tree to _LANE_DIRECTORY_ENTRIES_ADMITTED only by ratification."
    )
    assert not _LANE_DIRECTORY_ENTRIES_ADMITTED - directories, (
        f"ratified directory entries not directories on the tree: "
        f"{sorted(_LANE_DIRECTORY_ENTRIES_ADMITTED - directories)}. Next action: "
        f"run from a full checkout (sparse checkouts omit trees); if the tree was "
        f"removed, drop it from the lane and _LANE_DIRECTORY_ENTRIES_ADMITTED together."
    )


def test_consent_containment_lane_entries_exist_with_evidence_substrate() -> None:
    # The landing-time layer of the lane's evidence (test-full-shard executes
    # the whole tests/ tree at merge, anchored by
    # test_composition_suite_itself_runs_in_the_required_full_shard) presumes
    # every admitted entry exists on disk with its suites present — a lane
    # entry whose path vanished, or whose directory emptied, would silently
    # degrade the three-layer evidence shape to two layers. The allowlist is
    # machine-coupled to its substrate: every entry exists, none hollow.
    repo_root = Path(__file__).resolve().parents[1]
    missing: list[str] = []
    hollow: list[str] = []
    for entry in LIVE_EGRESS_CONSENT_CONTAINMENT_SURFACES:
        path = repo_root / entry
        if not path.exists():
            missing.append(entry)
        elif path.is_dir() and not any(path.iterdir()):
            hollow.append(entry)
    assert not missing, f"lane entries absent from the tree: {missing}"
    assert not hollow, f"lane directories carry no evidence substrate: {hollow}"


def test_egress_coverage_bound_unevaluable_without_changed_files() -> None:
    # A caller that supplies no PR file list cannot evaluate the coverage bound —
    # the wrapper holds closed (unbounded behavioral evidence is no evidence).
    assessment = assess_release_auto_arm_estate(
        _egress_frontmatter(),
        verified_checks=set(LIVE_EGRESS_MITIGATION_CHECKS),
    )
    assert assessment.eligible is False
    assert "egress_evidence_coverage_unevaluable:no_changed_files" in assessment.blockers


def test_account_live_quota_evidence_does_not_false_block_release_auto_arm() -> None:
    fm = _eligible_frontmatter(
        title="Claude subscription quota receipts require account-live evidence",
        risk_flags={
            "governance_sensitive": True,
            "privacy_or_secret_sensitive": True,
        },
        tags=["cc-task", "quota", "receipt", "subscription"],
    )
    verified_checks = set(RELEASE_MITIGATION_CHECKS["governance_sensitive"]) | set(
        RELEASE_MITIGATION_CHECKS["privacy_or_secret_sensitive"]
    )

    assessment = assess_release_auto_arm(fm, verified_checks=verified_checks)

    assert assessment.eligible is True
    assert not any("audio_or_live_egress_sensitive" in blocker for blocker in assessment.blockers)


def test_ineligible_when_public_claim_sensitive() -> None:
    fm = _eligible_frontmatter(
        title="Publish public claim to external surface",
        tags=["cc-task", "publication", "public"],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("public_claim" in blocker for blocker in assessment.blockers)


def test_pass_backed_runtime_secret_subscription_task_is_auto_armable() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.needs_arming is True
    assert assessment.eligible is True
    assert assessment.blockers == ()
    assert release_auto_arm_waivers(fm) == ("pass_backed_runtime_secret_waiver",)


def test_pass_backed_runtime_secret_requires_no_secret_value_storage() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_rejects_traversing_pass_entry() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/../other/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_rejects_non_glmcp_pass_entry() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="other/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_does_not_waive_explicit_privacy_flag() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
        risk_flags={"privacy_or_secret_sensitive": True},
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_does_not_waive_governance() -> None:
    fm = _eligible_frontmatter(
        title="Governance GLMCP pass-backed secret lane",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:governance_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_does_not_waive_provider_billing() -> None:
    fm = _eligible_frontmatter(
        title="Provider billing GLMCP pass-backed secret lane",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:provider_billing_sensitive" in assessment.blockers
    assert "risk_flag:privacy_or_secret_sensitive" not in assessment.blockers


def test_ineligible_when_mutation_surface_is_public() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(mutation_surface="public"))
    assert assessment.eligible is False
    assert any("mutation_surface" in blocker for blocker in assessment.blockers)


def test_ineligible_when_mutation_surface_is_provider_spend() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(mutation_surface="provider_spend"))
    assert assessment.eligible is False
    assert any("mutation_surface" in blocker for blocker in assessment.blockers)


def test_ineligible_when_governance_protected_path_in_scope() -> None:
    fm = _eligible_frontmatter(
        mutation_scope_refs=["axioms/registry.yaml", "shared/foo.py"],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("sensitive_path" in blocker for blocker in assessment.blockers)


def test_sensitive_path_does_not_false_match_substring_in_segment() -> None:
    # 'codeowners' is a marker, but 'scripts/sync-codeowners.py' only CONTAINS
    # it as a substring of a filename — it does not modify CODEOWNERS. The raw
    # substring match false-vetoed such tasks from system auto-arm.
    fm = _eligible_frontmatter(mutation_scope_refs=["scripts/sync-codeowners.py"])
    assessment = assess_release_auto_arm(fm)
    assert not any("sensitive_path" in blocker for blocker in assessment.blockers)
    assert assessment.eligible is True


def test_sensitive_path_does_not_false_match_dir_marker_substring() -> None:
    # Marker 'axioms/' must match the governed axioms/ directory, not a
    # segment that merely ends in '...axioms'.
    fm = _eligible_frontmatter(mutation_scope_refs=["research/meta-axioms/notes.md"])
    assessment = assess_release_auto_arm(fm)
    assert not any("sensitive_path" in blocker for blocker in assessment.blockers)
    assert assessment.eligible is True


def test_sensitive_path_matches_codeowners_as_path_segment() -> None:
    fm = _eligible_frontmatter(mutation_scope_refs=[".github/CODEOWNERS"])
    assessment = assess_release_auto_arm(fm)
    assert any("sensitive_path" in blocker for blocker in assessment.blockers)


def test_sensitive_path_matches_claude_md_file_segment() -> None:
    fm = _eligible_frontmatter(mutation_scope_refs=["hapax-council/CLAUDE.md"])
    assessment = assess_release_auto_arm(fm)
    assert any("sensitive_path" in blocker for blocker in assessment.blockers)


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "nested/AGENTS.md",
        "CLAUDE.md",
        "nested/CLAUDE.md",
        "config/agent-instructions/AGENTS.md",
        "config/agent-instructions/native/claude.md",
        "config/agent-instructions/native/grok.md",
        "config/agent-instructions/native/kimi.md",
        "config/agent-instructions/native/vibe.md",
        "config/agent-instructions/native/future-client.md",
        "config/agent-instructions/bindings.json",
        "docs/runbooks/council-domain-context.md",
        "scripts/install-agent-instructions.py",
    ],
)
@pytest.mark.parametrize("prefix", ["", "hapax-council/", "/abs/repo/"])
def test_sensitive_path_matches_instruction_sources(path: str, prefix: str) -> None:
    path = prefix + path
    assessment = assess_release_auto_arm(_eligible_frontmatter(mutation_scope_refs=[path]))
    assert assessment.eligible is False
    assert f"sensitive_path:{path}" in assessment.blockers


@pytest.mark.parametrize(
    "path",
    [
        "docs/AGENTS.md.example",
        "docs/CLAUDE.md.example",
        "docs/runbooks/ordinary.md",
        "config/ordinary.yaml",
        "config/agent-instructions/README.md",
        "config/agent-instructions/native-extra/grok.md",
        "config/agent-instructions/bindings.json.example",
        "config/agent-instructions-extra/bindings.json",
        "other-config/agent-instructions/native/grok.md",
        "docs/runbooks/council-domain-context.md.example",
        "docs/runbooks/other-council-domain-context.md",
        "other-docs/runbooks/council-domain-context.md",
        "scripts/install-agent-instructions.py.example",
        "scripts/other-install-agent-instructions.py",
        "other-scripts/install-agent-instructions.py",
    ],
)
@pytest.mark.parametrize("prefix", ["", "hapax-council/", "/abs/repo/"])
def test_instruction_lookalikes_and_ordinary_docs_are_not_sensitive(path: str, prefix: str) -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(mutation_scope_refs=[prefix + path]))
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_ineligible_when_public_current_already_true() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(public_current=True))
    assert assessment.eligible is False
    assert any("public_current" in blocker for blocker in assessment.blockers)


def test_ineligible_when_risk_tier_is_t3() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(risk_tier="T3"))
    assert assessment.eligible is False
    assert any("risk_tier" in blocker for blocker in assessment.blockers)


# ── ISAP authorization-in-principle precondition ──────────────────────


def test_ineligible_when_not_implementation_authorized() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(implementation_authorized=False))
    assert assessment.eligible is False
    assert any("implementation_authorized" in blocker for blocker in assessment.blockers)


def test_ineligible_when_implementation_authorized_field_absent() -> None:
    fm = _eligible_frontmatter()
    del fm["implementation_authorized"]
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("implementation_authorized" in blocker for blocker in assessment.blockers)


# ── AVSDLC axes evidence gate (axes must permit) ──────────────────────


def test_ineligible_when_avsdlc_axis_evidence_missing() -> None:
    fm = _eligible_frontmatter(avsdlc_axes=["visual"])
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any(blocker.startswith("avsdlc:") for blocker in assessment.blockers)


def test_eligible_when_avsdlc_axes_declared_none() -> None:
    fm = _eligible_frontmatter(avsdlc_axes=[])
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True


# ── note-text arming transform ────────────────────────────────────────

_NOTE = """---
type: cc-task
task_id: reform-improve-dispatch-resilience-20260601
status: pr_open
stage: S6_IMPLEMENTATION
implementation_authorized: true
release_authorized: false
updated_at: 2026-06-01T00:00:00Z
authority_case: CASE-CAPACITY-ROUTING-001
---

# task

## Session log
- prior line
"""


def test_apply_release_auto_arm_sets_release_authorized_true() -> None:
    out = apply_release_auto_arm(_NOTE, now_iso="2026-06-01T03:00:00Z")
    assert "release_authorized: true" in out
    assert "release_authorized: false" not in out


def test_apply_release_auto_arm_advances_stage_to_s7() -> None:
    out = apply_release_auto_arm(_NOTE, now_iso="2026-06-01T03:00:00Z")
    assert "stage: S7_RELEASE" in out
    assert "stage: S6_IMPLEMENTATION" not in out


def test_apply_release_auto_arm_keeps_existing_s7_stage() -> None:
    note = _NOTE.replace("stage: S6_IMPLEMENTATION", "stage: S7_RELEASE")
    out = apply_release_auto_arm(note, now_iso="2026-06-01T03:00:00Z")
    assert out.count("stage: S7_RELEASE") == 1


def test_apply_release_auto_arm_updates_timestamp_and_logs() -> None:
    out = apply_release_auto_arm(_NOTE, now_iso="2026-06-01T03:00:00Z")
    assert "updated_at: 2026-06-01T03:00:00Z" in out
    assert "- prior line" in out  # body preserved
    assert "release auto-arm" in out.lower()  # audit line appended to body


# ── evidence-gated auto-arm (no manual arming; operator directive 2026-06-22) ──


def test_sensitivity_is_hard_veto_without_verified_checks_backward_compat() -> None:
    # Pure-frontmatter assessment (no verified_checks) preserves the historical
    # hard veto so legacy callers are unaffected.
    fm = _eligible_frontmatter(risk_flags={"privacy_or_secret_sensitive": True})
    assessment = assess_release_auto_arm(fm)
    assert not assessment.eligible
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_privacy_secret_auto_arms_when_mitigation_evidence_present() -> None:
    # With the dedicated secret scanner passing, a privacy/secret-sensitive change
    # auto-arms on its evidence — the #4256 proof case. No human arm.
    fm = _eligible_frontmatter(risk_flags={"privacy_or_secret_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks={"secrets-scan", "test", "review"})
    assert assessment.eligible
    assert assessment.blockers == ()


def test_privacy_secret_held_when_mitigation_evidence_missing() -> None:
    # Evidence absent → held with a "needs_mitigation" reason; resolved by PRODUCING
    # the mitigation (running secrets-scan), never by a manual override.
    fm = _eligible_frontmatter(risk_flags={"privacy_or_secret_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks={"test", "review"})
    assert not assessment.eligible
    assert "needs_mitigation:privacy_or_secret_sensitive:secrets-scan" in assessment.blockers


def test_governance_sensitive_auto_arms_when_mitigation_evidence_present() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    verified_checks = set(RELEASE_MITIGATION_CHECKS["governance_sensitive"])

    assessment = assess_release_auto_arm(fm, verified_checks=verified_checks)

    assert assessment.eligible
    assert assessment.blockers == ()


def test_governance_sensitive_held_when_mitigation_evidence_missing() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks={"authority-case-check"})

    assert not assessment.eligible
    assert assessment.blockers == ("needs_mitigation:governance_sensitive:review-team-quorum",)


def test_governance_sensitive_still_fails_closed_without_verified_checks() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    assessment = assess_release_auto_arm(fm)

    assert not assessment.eligible
    assert assessment.blockers == ("risk_flag:governance_sensitive",)


def test_public_claim_sensitive_held_when_mitigation_evidence_missing() -> None:
    fm = _eligible_frontmatter(risk_flags={"public_claim_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks={"secrets-scan", "test", "review"})
    assert not assessment.eligible
    assert assessment.blockers == (
        "needs_mitigation:public_claim_sensitive:authority-case-check",
        "needs_mitigation:public_claim_sensitive:review-team-quorum",
    )


def test_public_claim_sensitive_auto_arms_when_mitigation_evidence_present() -> None:
    fm = _eligible_frontmatter(risk_flags={"public_claim_sensitive": True})
    verified_checks = set(RELEASE_MITIGATION_CHECKS["public_claim_sensitive"])

    assessment = assess_release_auto_arm(fm, verified_checks=verified_checks)

    assert assessment.eligible
    assert assessment.blockers == ()


def test_public_claim_mitigation_does_not_grant_public_surface_release() -> None:
    fm = _eligible_frontmatter(
        risk_flags={"public_claim_sensitive": True},
        mutation_surface="public",
    )
    verified_checks = set(RELEASE_MITIGATION_CHECKS["public_claim_sensitive"])

    assessment = assess_release_auto_arm(fm, verified_checks=verified_checks)

    assert not assessment.eligible
    assert "mutation_surface:public" in assessment.blockers


def test_nonsensitive_task_stays_eligible_with_verified_checks() -> None:
    # Supplying verified_checks must not regress the non-sensitive happy path.
    assessment = assess_release_auto_arm(
        _eligible_frontmatter(), verified_checks={"secrets-scan", "test"}
    )
    assert assessment.eligible


# ── M129: a declared false takes precedence over the keyword deriver ───
#
# The title and tags are an upstream free variable. The keyword deriver may add
# a sensitive class the route omits, but never override the route's authored
# ``false``. Omitted, non-boolean and unvalidated declarations keep today's
# derivation: failure narrows.

# "live" is a verb here, as in cc-claim-governed-rebinding-20260914's title.
_LIVE_VERB_TITLE = "The exclusivity primitive belongs where the lease lock and transaction live"
_EGRESS = "audio_or_live_egress_sensitive"
_NON_EGRESS_CHANGED_FILES = ["scripts/cc-claim", "shared/sdlc_claim.py", "tests/test_x.py"]


def _live_verb_frontmatter(**overrides: object) -> dict[str, object]:
    return _eligible_frontmatter(title=_LIVE_VERB_TITLE, **overrides)


@pytest.mark.parametrize(
    "placement",
    [
        pytest.param(lambda flags: {"risk_flags": flags}, id="top-level"),
        pytest.param(lambda flags: {"route_metadata": {"risk_flags": flags}}, id="nested"),
    ],
)
def test_declared_false_vetoes_the_keyword_derived_egress_class(placement) -> None:
    fm = _live_verb_frontmatter(**placement({_EGRESS: False}))

    assessment = assess_release_auto_arm_estate(
        fm, verified_checks=set(), changed_files=_NON_EGRESS_CHANGED_FILES
    )

    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_undeclared_flag_keeps_the_keyword_derivation() -> None:
    assessment = assess_release_auto_arm(_live_verb_frontmatter())

    assert assessment.eligible is False
    assert f"risk_flag:{_EGRESS}" in assessment.blockers


def test_a_declared_false_on_one_flag_does_not_veto_another_omitted_flag() -> None:
    # The parsed RiskFlags model defaults an omitted flag to False; only the raw
    # declaration may veto, so a sibling's false must leave the egress class held.
    fm = _live_verb_frontmatter(risk_flags={"governance_sensitive": False})

    assessment = assess_release_auto_arm(fm)

    assert f"risk_flag:{_EGRESS}" in assessment.blockers


@pytest.mark.parametrize("title", [_LIVE_VERB_TITLE, "Reform improve dispatch resilience"])
def test_declared_true_is_kept(title: str) -> None:
    fm = _eligible_frontmatter(title=title, risk_flags={_EGRESS: True})

    assessment = assess_release_auto_arm(fm)

    assert assessment.eligible is False
    assert f"risk_flag:{_EGRESS}" in assessment.blockers


@pytest.mark.parametrize("declared", ["false", "False", "no", 0, None], ids=repr)
def test_non_boolean_declaration_keeps_the_keyword_derivation(declared: object) -> None:
    fm = _live_verb_frontmatter(risk_flags={_EGRESS: declared})

    assessment = assess_release_auto_arm(fm)

    assert f"risk_flag:{_EGRESS}" in assessment.blockers


def test_unvalidated_route_metadata_keeps_the_keyword_derivation() -> None:
    from shared.route_metadata_schema import RouteMetadataStatus, assess_route_metadata

    fm = _live_verb_frontmatter(
        risk_flags={_EGRESS: False}, mutation_surface="not-a-mutation-surface"
    )
    assert assess_route_metadata(fm).status is RouteMetadataStatus.MALFORMED

    assessment = assess_release_auto_arm(fm)

    assert f"risk_flag:{_EGRESS}" in assessment.blockers


@pytest.mark.parametrize(
    ("top_level", "nested", "held"),
    [
        pytest.param(True, False, True, id="top-level-true-beats-nested-false"),
        pytest.param(False, True, False, id="top-level-false-beats-nested-true"),
    ],
)
def test_top_level_risk_flags_win_a_conflict_with_nested(
    top_level: bool, nested: bool, held: bool
) -> None:
    # The veto reads exactly the payload the model validates, where a top-level
    # ``risk_flags`` replaces ``route_metadata.risk_flags`` wholesale.
    fm = _live_verb_frontmatter(
        risk_flags={_EGRESS: top_level},
        route_metadata={"risk_flags": {_EGRESS: nested}},
    )

    assessment = assess_release_auto_arm(fm)

    assert (f"risk_flag:{_EGRESS}" in assessment.blockers) is held

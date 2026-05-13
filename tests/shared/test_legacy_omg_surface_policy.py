"""Pins for legacy omg.lol surface lifecycle policy."""

from __future__ import annotations

from pathlib import Path

from shared.legacy_omg_surface_policy import LEGACY_OMG_SURFACE_POLICIES, policy_by_surface_id

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_clean_source_required_paths_exist() -> None:
    for policy in LEGACY_OMG_SURFACE_POLICIES:
        if policy.clean_source_required:
            assert (REPO_ROOT / policy.path).exists(), policy.surface_id


def test_sidebar_sync_is_refused_and_absent_from_clean_source() -> None:
    policy = policy_by_surface_id()["weblog-sidebar-sync"]

    assert policy.classification == "refused"
    assert policy.clean_source_required is False
    assert policy.broad_visibility_eligible is False
    assert not (REPO_ROOT / policy.path).exists()


def test_guarded_legacy_surfaces_are_not_broad_visibility_eligible() -> None:
    policies = policy_by_surface_id()
    guarded_ids = {
        "operator-awareness-statuslog",
        "now-page-sync",
        "pastebin-artifact-publisher",
        "weblog-deploy-verifier",
        "cross-weblog-rss-fanout",
    }

    for surface_id in guarded_ids:
        assert policies[surface_id].broad_visibility_eligible is False


def test_broad_visibility_paths_are_only_rvpe_or_orchestrator_backed() -> None:
    eligible = [
        policy for policy in LEGACY_OMG_SURFACE_POLICIES if policy.broad_visibility_eligible
    ]

    assert eligible
    assert {
        "orchestrator_backed",
        "rvpe_backed",
    } == {policy.classification for policy in eligible}

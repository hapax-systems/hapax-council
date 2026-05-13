"""Legacy omg.lol surface lifecycle policy.

This manifest separates canonical visibility-engine publication paths from
guarded legacy utilities. It is source truth for HN-readiness work that needs
to prove all omg.lol public egress is either routed through the publication bus
or explicitly refused before broader visibility activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LegacyOmgClassification = Literal[
    "orchestrator_backed",
    "rvpe_backed",
    "v5_publisher_backed_guarded_legacy",
    "guarded_legacy",
    "refused",
]


@dataclass(frozen=True)
class LegacyOmgSurfacePolicy:
    surface_id: str
    path: str
    classification: LegacyOmgClassification
    clean_source_required: bool
    broad_visibility_eligible: bool
    rationale: str


LEGACY_OMG_SURFACE_POLICIES: tuple[LegacyOmgSurfacePolicy, ...] = (
    LegacyOmgSurfacePolicy(
        surface_id="operator-awareness-statuslog",
        path="agents/operator_awareness/omg_lol_fanout.py",
        classification="v5_publisher_backed_guarded_legacy",
        clean_source_required=True,
        broad_visibility_eligible=False,
        rationale=(
            "Hourly operator-awareness telemetry routed through "
            "OmgLolStatuslogPublisher; not the canonical RVPE statuslog path."
        ),
    ),
    LegacyOmgSurfacePolicy(
        surface_id="rvpe-statuslog-adapter",
        path="shared/omg_statuslog_public_event_adapter.py",
        classification="rvpe_backed",
        clean_source_required=True,
        broad_visibility_eligible=True,
        rationale="Canonical RVPE gate for omg_statuslog candidates and rejections.",
    ),
    LegacyOmgSurfacePolicy(
        surface_id="statuslog-poster",
        path="agents/omg_statuslog_poster/poster.py",
        classification="rvpe_backed",
        clean_source_required=True,
        broad_visibility_eligible=True,
        rationale=(
            "Consumes RVPE rows through the statuslog adapter and posts only "
            "allowed candidates with event_id idempotency."
        ),
    ),
    LegacyOmgSurfacePolicy(
        surface_id="now-page-sync",
        path="agents/omg_now_sync/sync.py",
        classification="v5_publisher_backed_guarded_legacy",
        clean_source_required=True,
        broad_visibility_eligible=False,
        rationale="Guarded /now state page utility routed through OmgLolNowPublisher.",
    ),
    LegacyOmgSurfacePolicy(
        surface_id="pastebin-artifact-publisher",
        path="agents/omg_pastebin_publisher/publisher.py",
        classification="v5_publisher_backed_guarded_legacy",
        clean_source_required=True,
        broad_visibility_eligible=False,
        rationale=(
            "Guarded digest/artifact publisher routed through "
            "OmgLolPastebinPublisher; not rolling visibility fanout."
        ),
    ),
    LegacyOmgSurfacePolicy(
        surface_id="weblog-orchestrator-adapter",
        path="agents/omg_weblog_publisher/publisher.py",
        classification="orchestrator_backed",
        clean_source_required=True,
        broad_visibility_eligible=True,
        rationale="Legacy weblog adapter is still routed by the publication orchestrator.",
    ),
    LegacyOmgSurfacePolicy(
        surface_id="weblog-rvpe-producer",
        path="agents/weblog_publish_public_event_producer.py",
        classification="rvpe_backed",
        clean_source_required=True,
        broad_visibility_eligible=True,
        rationale="Canonical non-broadcast weblog RVPE producer.",
    ),
    LegacyOmgSurfacePolicy(
        surface_id="weblog-deploy-verifier",
        path="scripts/verify-weblog-producer-deploy.py",
        classification="v5_publisher_backed_guarded_legacy",
        clean_source_required=True,
        broad_visibility_eligible=False,
        rationale=(
            "Manual deploy verifier with tightly allowlisted live egress and cleanup by default."
        ),
    ),
    LegacyOmgSurfacePolicy(
        surface_id="weblog-sidebar-sync",
        path="scripts/sync_omg_weblog_sidebar.py",
        classification="refused",
        clean_source_required=False,
        broad_visibility_eligible=False,
        rationale=(
            "Absent from clean source; reintroduction must be refused unless "
            "rewired through V5 publisher/public-surface gates."
        ),
    ),
    LegacyOmgSurfacePolicy(
        surface_id="cross-weblog-rss-fanout",
        path="agents/publication_bus/omg_rss_fanout.py",
        classification="guarded_legacy",
        clean_source_required=True,
        broad_visibility_eligible=False,
        rationale="Cross-weblog RSS helper; not a canonical HN visibility producer.",
    ),
)


def policy_by_surface_id() -> dict[str, LegacyOmgSurfacePolicy]:
    return {policy.surface_id: policy for policy in LEGACY_OMG_SURFACE_POLICIES}


__all__ = [
    "LEGACY_OMG_SURFACE_POLICIES",
    "LegacyOmgClassification",
    "LegacyOmgSurfacePolicy",
    "policy_by_surface_id",
]

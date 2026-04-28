"""Regression pins for the livestream substrate registry seed."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-28-livestream-substrate-registry-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "livestream-content-substrate.schema.json"


def _spec_body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _spec_body()

    for heading in (
        "## `ContentSubstrate` Schema Seed",
        "## Lifecycle Statuses",
        "## Public And Private Claim Policy",
        "## Director Vocabulary And Programme Hooks",
        "## Initial Registry Map",
        "## Duplicate Absorption Notes",
        "## First Adapter Tranche And Exact Child Tasks",
        "## Downstream Packet Unblockers",
    ):
        assert heading in body


def test_schema_has_required_content_substrate_fields_and_statuses() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "substrate_id",
        "substrate_type",
        "producer",
        "consumer",
        "freshness_ttl_s",
        "rights_class",
        "provenance_token",
        "privacy_class",
        "public_private_modes",
        "render_target",
        "director_vocabulary",
        "director_affordances",
        "programme_bias_hooks",
        "objective_links",
        "public_claim_permissions",
        "health_signal",
        "fallback",
        "kill_switch_behavior",
        "integration_status",
    ):
        assert field in required
        assert field in properties

    statuses = set(properties["integration_status"]["enum"])
    assert statuses == {
        "unavailable",
        "dormant",
        "dry-run",
        "private",
        "public-live",
        "archive-only",
        "degraded",
        "retired-only-if-obsolete",
    }


def test_example_row_is_parseable_and_fail_closed_by_default() -> None:
    body = _spec_body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ContentSubstrate JSON block missing"

    row = json.loads(match.group("payload"))

    assert row["schema_version"] == 1
    assert row["substrate_id"] == "caption_in_band"
    assert row["integration_status"] == "dormant"
    assert row["public_claim_permissions"]["claim_live"] is False
    assert row["public_claim_permissions"]["requires_egress_public_claim"] is True
    assert row["public_claim_permissions"]["requires_audio_safe"] is True
    assert row["fallback"]["mode"] == "dry_run_badge"


def test_initial_registry_map_consumes_required_scour_rows() -> None:
    body = _spec_body()

    for substrate_id in (
        "caption_in_band",
        "programme_cuepoints",
        "chat_legend",
        "chat_ambient_aggregate",
        "chat_keyword_consumer",
        "overlay_zones",
        "research_marker_overlay",
        "hls_archive",
        "youtube_metadata",
        "youtube_player",
        "youtube_channel_sections",
        "arena_blocks",
        "omg_statuslog",
        "omg_weblog",
        "publication_rss",
        "publication_hash_sidecars",
        "mastodon_fanout",
        "research_cards",
        "terminal_tiles",
        "geal_overlay",
        "lore_wards",
        "durf_visual_layer",
        "homage_ward_system",
        "ward_contrast",
        "cbip_signal_density",
        "local_visual_pool",
        "broadcast_provenance_manifest",
        "shorts_candidates",
        "refusal_briefs",
        "refusal_annex_footer",
        "lyrics_context",
        "re_splay_m8",
        "re_splay_polyend",
        "re_splay_steam_deck",
        "mobile_9x16_substream",
        "mobile_companion_page",
        "music_request_sidechat",
        "music_provenance",
        "lrr_audio_archive",
        "cdn_assets",
        "autonomous_narrative_emission",
        "operator_quality_rating",
        "future_sources",
    ):
        assert f"`{substrate_id}`" in body


def test_duplicate_absorption_and_adapter_tranche_are_explicit() -> None:
    body = _spec_body()

    for anchor in (
        "m8-re-splay-operator-install-and-smoke",
        "content-source-local-visual-pool",
        "mobile-livestream-substream-implementation",
        "ytb-009-production-wire",
        "content-source-provenance-egress-gate",
        "broadcast-audio-safety-ssot",
        "cross-surface-event-contract",
    ):
        assert anchor in body

    for child_task in (
        "caption-substrate-adapter",
        "cuepoint-substrate-adapter",
        "chat-ambient-keyword-substrate-adapter",
        "overlay-research-marker-substrate-adapter",
        "local-visual-pool-substrate-adapter",
        "cbip-substrate-adapter",
        "re-splay-m8-substrate-adapter",
        "music-request-provenance-substrate-adapter",
        "youtube-player-substrate-smoke",
        "refusal-publication-substrate-adapter",
    ):
        assert child_task in body

    assert "Do not create one umbrella implementation task" in body

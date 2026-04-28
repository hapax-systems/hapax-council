"""Regression pins for the spectacle control plane contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-04-28-spectacle-control-plane-design.md"
SCHEMA = REPO_ROOT / "schemas" / "spectacle-control-plane.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## `SpectacleLaneState` Schema Seed",
        "## Lifecycle States",
        "## Director Verbs",
        "## Silence And Hold",
        "## Transition And Conflict Policy",
        "## Initial Lane Map",
        "## Public Claim Policy",
        "## Child Implementation Tasks",
        "## Downstream Packet Unblockers",
    ):
        assert heading in body


def test_schema_has_required_lane_state_fields_verbs_and_risk_tiers() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "lane_id",
        "content_substrate_refs",
        "state",
        "mounted",
        "renderable",
        "renderability_evidence",
        "claim_bearing",
        "rights_risk",
        "consent_risk",
        "monetization_risk",
        "director_verbs",
        "programme_hooks",
        "fallback",
        "public_claim_allowed",
    ):
        assert field in required
        assert field in properties

    assert set(properties["state"]["enum"]) == {
        "unmounted",
        "candidate",
        "dry-run",
        "private",
        "mounted",
        "degraded",
        "public-live",
        "blocked",
    }

    assert set(properties["director_verbs"]["items"]["enum"]) == {
        "foreground",
        "background",
        "hold",
        "suppress",
        "transition",
        "crossfade",
        "intensify",
        "stabilize",
        "route_attention",
        "mark_boundary",
    }

    assert set(schema["$defs"]["risk_tier"]["enum"]) == {
        "none",
        "low",
        "medium",
        "high",
        "blocking",
        "unknown",
    }


def test_example_lane_is_parseable_and_fail_closed_by_default() -> None:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example SpectacleLaneState JSON block missing"

    lane = json.loads(match.group("payload"))

    assert lane["schema_version"] == 1
    assert lane["lane_id"] == "chat_ambient"
    assert lane["state"] == "dry-run"
    assert lane["mounted"] is False
    assert lane["renderable"] is False
    assert lane["claim_bearing"] == "dry_run"
    assert lane["consent_risk"] == "medium"
    assert lane["public_claim_allowed"] is False
    assert lane["fallback"]["mode"] == "dry_run_badge"
    assert lane["director_verbs"] == ["hold", "suppress", "mark_boundary"]


def test_initial_lane_map_consumes_required_sources() -> None:
    body = _body()

    for lane_id in (
        "research_ledger",
        "music_listening",
        "studio_work",
        "homage_ward_system",
        "gem_mural",
        "chat_ambient",
        "chat_keyword_ward",
        "youtube_slots",
        "publication_fanout",
        "reverie_substrate",
        "health_egress_status",
        "re_splay",
        "captions",
        "metadata",
        "cbip",
        "overlay_zones",
        "research_markers",
        "private_sidechat",
        "stream_deck",
        "kdeconnect",
        "music_request",
        "mobile_portrait_stream",
        "autonomous_speech",
        "geal_overlay",
        "lore_wards",
        "durf_visual_layer",
        "refusal_as_data",
    ):
        assert f"`{lane_id}`" in body


def test_no_op_hold_silence_and_child_task_split_are_explicit() -> None:
    body = _body()

    for phrase in (
        "Silence and stillness are directorial moves",
        "Invalid examples",
        "No mounted-lane claim until hardware smoke",
        "Do not create one implementation umbrella",
        "unavailable no-op",
    ):
        assert phrase in body

    for child_task in (
        "homage-spectacle-lane-adapter",
        "reverie-spectacle-lane-adapter",
        "re-splay-spectacle-lane-adapter",
        "captions-spectacle-lane-adapter",
        "metadata-status-spectacle-lane-adapter",
        "overlay-research-marker-spectacle-adapter",
        "chat-ambient-keyword-spectacle-adapter",
        "cbip-spectacle-lane-adapter",
        "private-controls-spectacle-adapter",
        "mobile-portrait-spectacle-lane-adapter",
        "autonomous-narration-spectacle-lane-adapter",
    ):
        assert child_task in body

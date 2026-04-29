"""Regression pins for the director substrate control-plane contract."""

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
    / "2026-04-29-director-substrate-control-plane-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "director-substrate-control-plane.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Current Integration Points",
        "## `DirectorControlMove` Schema Seed",
        "## Vocabulary Generation",
        "## Move Verbs And Audit Outputs",
        "## Evidence Freshness And Fallback",
        "## Programme And Cuepoint Policy",
        "## Private Control Policy",
        "## Child Implementation Split",
    ):
        assert heading in body


def test_schema_has_required_move_fields_targets_verbs_and_fallbacks() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "decision_id",
        "emitted_at",
        "director_tier",
        "condition_id",
        "programme_id",
        "verb",
        "target",
        "vocabulary",
        "evidence",
        "freshness",
        "execution_state",
        "fallback",
        "public_claim_allowed",
        "audit_event",
    ):
        assert field in required
        assert field in properties

    target_types = set(properties["target"]["properties"]["target_type"]["enum"])
    assert target_types == {
        "substrate",
        "spectacle_lane",
        "ward",
        "camera",
        "re_splay_device",
        "private_control",
        "cuepoint",
        "claim_binding",
        "programme",
        "egress_status",
    }

    assert set(schema["$defs"]["director_verb"]["enum"]) == {
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

    assert set(schema["$defs"]["evidence_status"]["enum"]) == {
        "fresh",
        "stale",
        "missing",
        "unknown",
        "not_applicable",
    }

    assert set(properties["fallback"]["properties"]["mode"]["enum"]) == {
        "no_op",
        "dry_run",
        "fallback",
        "operator_reason",
        "hold_last_safe",
        "suppress",
        "private_only",
        "degraded_status",
        "kill_switch",
    }


def test_example_move_is_parseable_and_explicit_no_op() -> None:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example DirectorControlMove JSON block missing"

    move = json.loads(match.group("payload"))

    assert move["schema_version"] == 1
    assert move["verb"] == "hold"
    assert move["target"]["target_type"] == "re_splay_device"
    assert move["target"]["target_id"] == "re_splay_m8"
    assert move["freshness"]["state"] == "missing"
    assert move["execution_state"] == "no_op"
    assert move["fallback"]["mode"] == "no_op"
    assert move["fallback"]["operator_facing"] is True
    assert move["public_claim_allowed"] is False
    assert move["audit_event"]["event_type"] == "director.move.hold"
    assert move["evidence"][0]["status"] == "missing"


def test_vocabulary_sources_cover_substrates_lanes_controls_and_claims() -> None:
    body = _body()

    for phrase in (
        "Load `ContentSubstrate` rows",
        "Load `SpectacleLaneState` rows",
        "Add active wards and ward claim bindings",
        "Add active cameras from compositor status/layout evidence",
        "Add Re-Splay device rows",
        "Add private controls from sidechat, Stream Deck, and KDEConnect",
        "Add cuepoint/programme-boundary terms",
        "Add claim bindings from calibrated `Claim` envelopes",
    ):
        assert phrase in body

    for ref_prefix in (
        "substrate:caption_in_band",
        "lane:captions",
        "ward:chat_ambient",
        "camera:c920-desk",
        "control:stream_deck.key.7",
        "cuepoint:programme_boundary",
        "claim:vinyl_spinning",
    ):
        assert ref_prefix in body


def test_all_director_verbs_have_audit_event_outputs() -> None:
    body = _body()
    schema = _schema()
    audit_events = set(schema["properties"]["audit_event"]["properties"]["event_type"]["enum"])

    for verb in schema["$defs"]["director_verb"]["enum"]:
        assert f"`{verb}`" in body
        assert f"`director.move.{verb}`" in body
        assert f"director.move.{verb}" in audit_events


def test_unavailable_behavior_and_child_split_do_not_duplicate_audit_18() -> None:
    body = _body()

    for phrase in (
        "no-op, dry-run, fallback, or operator-facing reason",
        "Unavailable targets must select one of these modes",
        "cannot be omitted from the audit stream",
        "SS2 and SS3 remain blocked",
    ):
        assert phrase in body

    assert "audit-18-director-loop-programme-integration becomes an implementation anchor" in body

    for child_task in (
        "director-vocabulary-builder",
        "director-control-move-audit-log",
        "director-programme-envelope-adapter",
        "programme-boundary-event-surface",
        "cuepoint-director-public-event-adapter",
        "private-controls-director-adapter",
        "camera-ward-claim-source-adapter",
        "re-splay-director-noop-adapter",
        "director-runtime-wireup",
    ):
        assert child_task in body

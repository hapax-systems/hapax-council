"""Regression pins for the cross-surface event contract seed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from shared.cross_surface_event_contract import cross_surface_contract_payload

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-29-cross-surface-event-contract-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "cross-surface-event-contract.schema.json"


def _spec_body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _spec_body()

    for heading in (
        "## Machine-Readable Contract",
        "## Surface Actions",
        "## Event-Driven Fanout",
        "## Failure And Health",
        "## First-Class Apertures",
        "## Public Claim Policy",
        "## Aperture Notes",
        "## Child Task Boundary",
    ):
        assert heading in body


def test_schema_declares_actions_failure_event_and_health_contract() -> None:
    schema = _schema()
    action_enum = set(schema["$defs"]["fanout_action"]["enum"])

    assert action_enum == {
        "publish",
        "link",
        "embed",
        "redact",
        "hold",
        "archive",
        "replay",
    }
    assert schema["properties"]["failure_event_type"]["const"] == "fanout.decision"
    assert set(schema["properties"]["health_contract"]["required"]) == {
        "ok",
        "degraded",
        "blocked",
    }


def test_schema_and_helper_cover_first_class_apertures() -> None:
    schema = _schema()
    payload = cross_surface_contract_payload()
    jsonschema.validate(payload, schema)

    schema_apertures = set(schema["$defs"]["aperture"]["enum"])
    payload_apertures = {item["aperture_id"] for item in payload["apertures"]}

    assert schema_apertures == payload_apertures
    assert schema_apertures == {
        "youtube",
        "youtube_channel_trailer",
        "omg_statuslog",
        "omg_weblog",
        "arena",
        "mastodon",
        "bluesky",
        "discord",
        "shorts",
        "archive",
        "replay",
    }


def test_failure_decision_event_schema_is_explicit() -> None:
    schema = _schema()
    decision_schema = schema["$defs"]["fanout_decision_event"]
    required = set(decision_schema["required"])

    for field in (
        "decision_id",
        "source_event_id",
        "source_event_type",
        "target_aperture",
        "requested_action",
        "resolved_action",
        "decision",
        "reasons",
        "health_status",
        "health_ref",
        "failure_event_type",
        "failure_event_id",
        "child_task",
        "dry_run",
    ):
        assert field in required


def test_spec_preserves_adapter_boundary_and_child_splits() -> None:
    body = _spec_body()

    for phrase in (
        "Non-scope",
        "No child task is implemented here.",
        "Mastodon and Bluesky are currently active legacy tailers.",
        "Discord is linked but inactive.",
        "Shorts is first-class but unavailable",
        "public replay links and replay residency still need explicit adapter work",
    ):
        assert phrase in body

    for child_task in (
        "mastodon-public-event-adapter",
        "bluesky-public-event-adapter",
        "discord-public-event-activation-or-retire",
        "arena-public-event-unit-and-block-shape",
        "omg-statuslog-public-event-adapter",
        "omg-weblog-rss-public-event-adapter",
        "shorts-public-event-adapter",
        "archive-replay-public-event-link-adapter",
        "publication-artifact-public-event-adapter",
        "youtube-research-translation-ledger",
    ):
        assert child_task in body

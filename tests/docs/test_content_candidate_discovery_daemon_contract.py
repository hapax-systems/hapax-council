"""Regression pins for the content candidate discovery daemon contract."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-29-content-candidate-discovery-daemon-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "content-candidate-discovery-daemon.schema.json"
CONFIG = REPO_ROOT / "config" / "content-candidate-discovery-daemon.json"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-content-candidate-discovery.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-content-candidate-discovery.timer"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _config() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_spec_covers_runtime_policy_output_and_gate_sections() -> None:
    body = _body()

    for heading in (
        "## Runtime Contract",
        "## Policy And Deployment Config",
        "## Source Observation Contract",
        "## Candidate Output Contract",
        "## Gate Behavior",
        "## Downstream Boundaries",
        "## Verification",
    ):
        assert heading in body

    assert "The daemon must never schedule shows directly" in body
    assert "Trend/currentness may route attention but may not become a truth warrant" in body


def test_schema_and_config_pin_enabled_safe_producer_defaults() -> None:
    schema = _schema()
    config = _config()

    assert schema["properties"]["enabled"]["const"] is True
    assert config["enabled"] is True
    assert config["global_policy"]["single_operator_only"] is True
    assert config["global_policy"]["schedules_programmes_directly"] is False
    assert config["global_policy"]["creates_supporter_request_queue"] is False
    assert config["global_policy"]["trend_as_truth_allowed"] is False
    assert config["global_policy"]["missing_freshness_blocks_public_claim"] is True
    assert config["downstream_contract"]["never_schedules_programmes"] is True
    assert "content-programme-scheduler-policy" in config["downstream_contract"]["blocks"]


def test_source_class_modes_are_complete_and_conservative() -> None:
    config = _config()
    required = set(_schema()["properties"]["source_class_modes"]["required"])
    modes = config["source_class_modes"]

    assert set(modes) == required
    assert set(modes["ambient_aggregate_audience"]) == {"private", "dry_run"}
    assert set(modes["internal_anomalies"]) == {"private", "dry_run"}
    assert "public_monetizable" not in modes["trend_sources"]
    assert "public_monetizable" in modes["owned_media"]


def test_systemd_timer_is_shipped_and_preset_enabled() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    preset = PRESET.read_text(encoding="utf-8")

    assert "python -m agents.content_candidate_discovery --once" in service
    assert "OnUnitActiveSec=5min" in timer
    assert "enable hapax-content-candidate-discovery.timer" in preset

"""Schema contract tests for Phase 6 audio routing policy."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "audio-routing-policy.schema.json"
POLICY = REPO_ROOT / "config" / "audio-routing.yaml"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _policy() -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(POLICY.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _route(payload: dict[str, Any], source_id: str) -> dict[str, Any]:
    return next(route for route in payload["routes"] if route["source_id"] == source_id)


def test_audio_routing_schema_validates_policy_yaml() -> None:
    _validator().validate(_policy())


def test_generated_output_contract_is_dry_run_only() -> None:
    schema = _json(SCHEMA)
    output = schema["properties"]["generated_output"]["properties"]
    policy_output = _policy()["generated_output"]

    assert output["output_dir"]["const"] == "config/pipewire/generated"
    assert output["manifest_path"]["const"] == (
        "config/pipewire/generated/audio-routing-policy.manifest.json"
    )
    # Audit F#8 (2026-05-02): generated_conf_writes_allowed is now a free
    # boolean (no `const`) — the generator gained LADSPA chain templates
    # so writes are supported. The other two flags stay locked to keep
    # PipeWire host-reload operator-driven.
    assert "const" not in output["generated_conf_writes_allowed"]
    assert isinstance(policy_output["generated_conf_writes_allowed"], bool)
    assert policy_output["live_reload_allowed"] is False
    assert policy_output["dry_run_only"] is True


def test_fail_closed_policy_constants_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    policy = _policy()
    fail_closed = schema["properties"]["fail_closed_policy"]["properties"]

    for key, value in policy["fail_closed_policy"].items():
        assert value is False
        assert fail_closed[key]["const"] is False


@pytest.mark.parametrize(
    "source_id",
    ["assistant-private", "notification-private", "multimedia-default", "youtube-bed"],
)
def test_schema_rejects_implicit_broadcast_eligibility_for_blocked_routes(source_id: str) -> None:
    bad = deepcopy(_policy())
    route = _route(bad, source_id)
    route["broadcast_eligible"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_broadcast_route_without_evidence_or_rights() -> None:
    bad = deepcopy(_policy())
    route = _route(bad, "broadcast-tts")
    route["evidence_refs"] = []
    route["rights_required"] = False

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_policy_maps_current_policy_bearing_artifacts() -> None:
    payload = _policy()
    mapped = {artifact["path"] for artifact in payload["artifacts"]}

    for path in (
        "config/pipewire/hapax-stream-split.conf",
        "config/pipewire/hapax-private-monitor-bridge.conf",
        "config/pipewire/hapax-notification-private.conf",
        "config/wireplumber/50-hapax-voice-duck.conf",
        "config/pipewire/hapax-l12-evilpet-capture.conf",
        "config/pipewire/voice-fx-chain.conf",
        "config/pipewire/hapax-music-loudnorm.conf",
        "config/pipewire/yt-loudnorm.conf",
        "config/pipewire/hapax-s4-loopback.conf",
        "config/pipewire/hapax-m8-loudnorm.conf",
    ):
        assert path in mapped


def test_policy_and_schema_avoid_local_absolute_paths() -> None:
    assert "/home/hapax/" not in SCHEMA.read_text(encoding="utf-8")
    assert "/home/hapax/" not in POLICY.read_text(encoding="utf-8")

"""Regression pins for the broadcast audio safety SSOT contract."""

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
    / "2026-04-28-broadcast-audio-safety-ssot-design.md"
)


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Owner Map",
        "## SSOT Boundaries",
        "## Fail-Closed Safety Contract",
        "## `audio_safe_for_broadcast` Shape",
        "## Child Task Recommendations",
    ):
        assert heading in body


def test_spec_maps_active_audio_owners_without_duplication() -> None:
    body = _body()

    for task_id in (
        "audio-topology-descriptor-l12-drift",
        "audio-private-monitor-off-l12-bridge",
        "audio-l12-forward-invariant-ci-guard",
        "youtube-player-real-content-ducker-smoke",
    ):
        assert task_id in body

    assert "No new child should duplicate" in body
    assert "audio-l12-forward-invariant-ci-guard` should be unblocked" in body


def test_fail_closed_contract_names_forbidden_private_routes() -> None:
    body = _body()

    for route in (
        "hapax-private",
        "hapax-notification-private",
        "hapax-livestream-tap",
        "hapax-voice-fx-capture",
        "hapax-pc-loudnorm",
        "input.loopback.sink.role.multimedia",
    ):
        assert route in body

    assert "Missing private monitor hardware produces silence" in body
    assert "role.broadcast` is the only Hapax voice role allowed" in body


def test_audio_safe_for_broadcast_json_shape_is_parseable_and_fail_closed() -> None:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "audio_safe_for_broadcast JSON payload block missing"

    payload = json.loads(match.group("payload"))
    state = payload["audio_safe_for_broadcast"]

    assert state["safe"] is False
    assert state["status"] == "unsafe"
    assert state["blocking_reasons"][0]["code"] == "private_route_leak_guard_failed"
    assert state["evidence"]["loudness"]["target_lufs_i"] == -14.0
    assert state["evidence"]["loudness"]["target_true_peak_dbtp"] == -1.0
    assert state["evidence"]["private_routes"]["private_downstream_bridge"] == (
        "absent_fail_closed"
    )
    assert state["owners"]["loudness_constants"] == "shared/audio_loudness.py"

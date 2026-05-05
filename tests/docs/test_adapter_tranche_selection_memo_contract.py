"""Contract tests for the adapter tranche selection memo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "research" / "2026-04-30-adapter-tranche-selection-memo.md"
SCHEMA = REPO_ROOT / "schemas" / "adapter-tranche-selection-memo.schema.json"
MEMO = REPO_ROOT / "config" / "adapter-tranche-selection-memo.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _memo() -> dict[str, Any]:
    return _json(MEMO)


def _candidates_by_id() -> dict[str, dict[str, Any]]:
    return {candidate["adapter_id"]: candidate for candidate in _memo()["candidates"]}


def test_schema_validates_selection_memo_payload() -> None:
    payload = _memo()

    _validator().validate(payload)

    assert payload["schema_version"] == 1
    assert payload["memo_id"] == "adapter_tranche_selection_memo"
    assert payload["schema_ref"] == "schemas/adapter-tranche-selection-memo.schema.json"


def test_candidate_matrix_covers_required_acceptance_rows() -> None:
    payload = _memo()
    schema = _json(SCHEMA)
    labels = {candidate["label"] for candidate in payload["candidates"]}

    assert set(schema["x-required_candidate_labels"]) <= labels
    assert len(payload["candidates"]) >= 15
    assert set(payload["candidate_statuses"]) == {
        "select_tranche_1",
        "block",
        "defer_behind_named_gate",
        "absorb_into_active_task",
        "unavailable",
    }


def test_first_wave_is_capped_at_five_and_matches_selected_rows() -> None:
    payload = _memo()
    schema = _json(SCHEMA)
    candidates = _candidates_by_id()
    selected_ids = set(payload["selected_adapter_ids"])
    selected_rows = {
        candidate["adapter_id"]
        for candidate in payload["candidates"]
        if candidate["status"] == "select_tranche_1"
    }

    assert len(selected_ids) <= payload["first_wave_cap"] == 5
    assert selected_ids == set(schema["x-required_selected_adapter_ids"])
    assert selected_rows == selected_ids

    for adapter_id in selected_ids:
        row = candidates[adapter_id]
        for field in (
            "event_input",
            "producer_freshness",
            "render_target",
            "rights_consent_posture",
            "public_claim_policy",
            "health_signal",
            "dry_run_explanation",
            "tests",
            "verification_artifact",
        ):
            assert row[field], adapter_id


def test_selection_preserves_fail_closed_public_live_policy() -> None:
    policy = _memo()["public_live_policy"]
    candidates = _memo()["candidates"]

    assert policy["selection_grants_public_live"] is False
    assert policy["selection_grants_viewer_visibility"] is False
    assert policy["selection_grants_publication"] is False
    assert policy["selection_grants_monetization"] is False
    assert policy["requires_egress_public_claim"] is True
    assert policy["requires_rights_consent_privacy"] is True
    assert policy["requires_provenance"] is True
    assert policy["requires_health_signal"] is True
    assert policy["unknown_or_stale_fails_closed"] is True

    for candidate in candidates:
        public_policy = candidate["public_claim_policy"].lower()
        assert any(
            phrase in public_policy
            for phrase in ("no public", "defer", "until", "require", "requires")
        ), candidate["adapter_id"]


def test_youtube_player_is_deferred_in_favor_of_music_provenance() -> None:
    payload = _memo()
    candidates = _candidates_by_id()
    choice = payload["youtube_player_vs_music_choice"]

    assert choice["chosen"] == "music-request-provenance-substrate-adapter"
    assert choice["not_chosen"] == "youtube-player-substrate-smoke"
    assert "live audio routing" in choice["rationale"]
    assert candidates[choice["chosen"]]["status"] == "select_tranche_1"
    assert candidates[choice["not_chosen"]]["status"] == "defer_behind_named_gate"
    assert "daimonion-private-voice-containment" in candidates[choice["not_chosen"]]["gates"]


def test_blocked_and_deferred_candidates_keep_named_gates() -> None:
    for candidate in _memo()["candidates"]:
        if candidate["status"] in {"block", "defer_behind_named_gate"}:
            assert candidate["gates"], candidate["adapter_id"]
            assert candidate["selection_rationale"], candidate["adapter_id"]
            assert candidate["dry_run_explanation"], candidate["adapter_id"]

    candidates = _candidates_by_id()
    assert candidates["re-splay-m8-substrate-adapter"]["status"] == "block"
    assert (
        "m8-re-splay-operator-install-and-smoke"
        in candidates["re-splay-m8-substrate-adapter"]["gates"]
    )
    assert candidates["lrr-audio-archive-substrate-adapter"]["status"] == "block"
    assert "operator-consent" in candidates["lrr-audio-archive-substrate-adapter"]["gates"]


def test_umbrella_is_superseded_not_dispatched_as_implementation() -> None:
    umbrella = _memo()["umbrella_action"]

    assert umbrella["umbrella_task_id"] == "substrate-adapter-buildout-tranche-1"
    assert umbrella["action"] == "supersede_with_dispatch_table"
    assert umbrella["dispatch_umbrella_as_implementation"] is False
    assert "child packets" in umbrella["reason"]


def test_markdown_memo_references_contract_and_selection_boundary() -> None:
    body = DOC.read_text(encoding="utf-8")

    assert "config/adapter-tranche-selection-memo.json" in body
    assert "schemas/adapter-tranche-selection-memo.schema.json" in body
    assert "First-wave adapter implementation is capped at five tasks" in body
    assert "Selection does not make any adapter public-live" in body
    assert "substrate-adapter-buildout-tranche-1" in body
    for adapter_id in _memo()["selected_adapter_ids"]:
        assert adapter_id in body


def test_markdown_handoff_closes_umbrella_into_child_packets() -> None:
    body = DOC.read_text(encoding="utf-8")

    assert "2026-05-05 Buildout Handoff Status" in body
    assert "The umbrella remains architecture only" in body
    assert "must not" in body
    assert "adapter implementation changes" in body
    assert "public-live state, viewer visibility, publication, audio" in body

    selected_ids = _memo()["selected_adapter_ids"]
    for adapter_id in selected_ids:
        assert f"| `{adapter_id}` |" in body

    assert "| `caption-substrate-adapter` | closed via PR #2288 |" in body
    assert "| `cuepoint-substrate-adapter` | closed via PR #2290 |" in body
    assert "| `chat-ambient-keyword-substrate-adapter` | offered child packet |" in body
    assert "| `overlay-research-marker-substrate-adapter` | offered child packet |" in body
    assert "| `music-request-provenance-substrate-adapter` | offered child packet |" in body

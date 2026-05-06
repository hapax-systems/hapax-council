"""Deterministic segment script/action/layout fixture evals.

Fixtures are built in code so each regression names the contract surface
it is exercising. The only JSON here is the tiny golden receipt corpus.
No model calls, compositor calls, or broadcast authority changes occur.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from shared.segment_quality_layout_eval import (
    LayoutReceipt,
    evaluate_segment_quality_layout_fixture,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "segment_quality_layout"


def _golden_receipts() -> list[dict[str, Any]]:
    parsed = json.loads((FIXTURE_DIR / "golden-receipts.json").read_text(encoding="utf-8"))
    return [LayoutReceipt.model_validate(receipt).model_dump(mode="json") for receipt in parsed]


def _receipts_by_id() -> dict[str, dict[str, Any]]:
    return {receipt["id"]: receipt for receipt in _golden_receipts()}


def _excellent_segment_fixture() -> dict[str, Any]:
    receipts = _receipts_by_id()
    return {
        "fixture_id": "excellent-ranking-manifest-layout",
        "format": "tier_list",
        "expected_pass": True,
        "layout_responsibility_version": 1,
        "hosting_context": {
            "mode": "responsible_hosting",
            "hapax_controls_layout": True,
            "responsible_for_content_quality": True,
            "static_layout_success_allowed": False,
        },
        "topic_anchors": ["ranking", "manifest", "Command-R", "layout"],
        "evidence_refs": [
            {
                "id": "manifest",
                "source": "builder:prepared-manifest",
                "summary": "Command-R prepared artifact manifest with source hashes.",
            },
            {
                "id": "layout_state",
                "source": "builder:rendered-layout-state",
                "summary": "Rendered LayoutState confirms ranking chart and manifest panel.",
            },
            {
                "id": "operator_constraint",
                "source": "builder:operator-constraint",
                "summary": "Prepared artifacts declare needs but do not command layout.",
            },
        ],
        "script": {
            "premise": (
                "Rank the Command-R manifest gates that decide whether a segment can claim "
                "broadcast actionability."
            ),
            "tension": (
                "A confident ranking claim is unsafe unless the manifest and layout "
                "readback are visible when the host names the chart change."
            ),
            "beats": [
                {
                    "beat_id": "hook",
                    "role": "hook",
                    "text": (
                        "The ranking starts with a simple test: if the audience cannot see "
                        "the Command-R manifest and the layout proof, the chart has not earned "
                        "its S-tier placement."
                    ),
                    "evidence_refs": ["operator_constraint"],
                    "callback_refs": [],
                    "action_intent_refs": [],
                },
                {
                    "beat_id": "context",
                    "role": "context",
                    "text": (
                        "The manifest is the context, not decoration. It shows the prepared "
                        "artifact stayed prior-only while the layout runtime remains the only "
                        "authority that can make something visible."
                    ),
                    "evidence_refs": ["manifest", "operator_constraint"],
                    "callback_refs": ["hook.visible-proof"],
                    "action_intent_refs": [],
                },
                {
                    "beat_id": "evidence",
                    "role": "evidence",
                    "text": (
                        "The evidence is the pair: Command-R manifest on one side, rendered "
                        "LayoutState on the other. If either disappears, the ranking claim "
                        "becomes polish without proof."
                    ),
                    "evidence_refs": ["manifest", "layout_state"],
                    "callback_refs": ["hook.visible-proof"],
                    "action_intent_refs": [],
                },
                {
                    "beat_id": "turn",
                    "role": "turn",
                    "text": (
                        "The turn is that a default layout can launder failure. A static host "
                        "shot looks calm, but it hides whether the manifest panel and ranking "
                        "chart ever rendered."
                    ),
                    "evidence_refs": ["layout_state", "operator_constraint"],
                    "callback_refs": [],
                    "action_intent_refs": [],
                },
                {
                    "beat_id": "action",
                    "role": "action",
                    "text": (
                        "Show the ranking chart and manifest panel before saying the chart "
                        "changed. The host claim, the expected effect, and the rendered "
                        "layout receipt land together."
                    ),
                    "evidence_refs": ["manifest", "layout_state"],
                    "callback_refs": ["turn.default-laundering"],
                    "action_intent_refs": ["show_ranking_manifest"],
                },
                {
                    "beat_id": "close",
                    "role": "close",
                    "text": (
                        "The callback is the opening test again: responsible ranking is not "
                        "a voice claim; it is a visible chart, manifest, and receipt."
                    ),
                    "evidence_refs": ["manifest", "layout_state"],
                    "callback_refs": ["hook.visible-proof", "action.visible-chart"],
                    "action_intent_refs": [],
                },
            ],
        },
        "action_intents": [
            {
                "id": "show_ranking_manifest",
                "spoken_claim": "show the ranking chart and manifest before claiming the chart changed",
                "operator_visible_effect": "ranking chart visible; manifest panel visible",
                "evidence_refs": ["manifest", "layout_state"],
                "required_layout_needs": ["ranking_chart", "manifest_panel"],
            }
        ],
        "layout_needs": [
            {
                "id": "ranking_chart",
                "kind": "ranking_focus",
                "reason": "The spoken action says the ranking chart changed.",
                "evidence_refs": ["layout_state"],
                "action_intent_refs": ["show_ranking_manifest"],
            },
            {
                "id": "manifest_panel",
                "kind": "segment_focus",
                "reason": "The claim depends on prepared artifact provenance.",
                "evidence_refs": ["manifest"],
                "action_intent_refs": ["show_ranking_manifest"],
            },
        ],
        "beat_layout_intents": [
            {
                "beat_id": "action",
                "layout_needs": ["ranking_chart", "manifest_panel"],
                "expected_effects": ["ranking chart visible", "manifest panel visible"],
                "default_static_success_allowed": False,
            }
        ],
        "layout_decision_contract": {
            "bounded_vocabulary": [
                "segment_focus",
                "ranking_focus",
                "comparison_split",
                "chat_prompt",
                "camera_target",
                "consent_safe",
                "speech_only_fallback",
                "non_responsible_static",
            ]
        },
        "layout_decision": {
            "mode": "dynamic_responsible",
            "need_ids": ["ranking_chart", "manifest_panel"],
            "reason": "Show ranking and provenance because the action claim depends on both.",
            "receipt_refs": ["receipt.store_switch", "receipt.layout_state_rendered"],
            "authority": "canonical_broadcast_runtime",
            "ttl_s": 30,
            "min_dwell_s": 5,
        },
        "layout_receipts": [
            receipts["receipt.store_switch"],
            receipts["receipt.layout_state_rendered"],
        ],
        "prepared_artifact": {
            "model_id": "command-r-08-2024-exl3-5.0bpw",
            "prior_only": True,
            "authority": "prep_metadata_only",
            "provenance_refs": ["manifest", "operator_constraint"],
            "direct_layout_commands": [],
            "public_broadcast_bypass": False,
        },
    }


def _non_responsible_static_fixture() -> dict[str, Any]:
    fixture = _excellent_segment_fixture()
    fixture["fixture_id"] = "non-responsible-static-explicit-reason"
    fixture["hosting_context"] = {
        "mode": "non_responsible",
        "hapax_controls_layout": False,
        "responsible_for_content_quality": False,
        "static_layout_success_allowed": True,
        "explicit_static_reason": "legacy non-hosting monitor surface; no Hapax content claim",
    }
    fixture["layout_needs"] = [
        {
            "id": "legacy_static",
            "kind": "non_responsible_static",
            "reason": "Legacy monitor mode is explicitly outside responsible hosting.",
            "evidence_refs": ["operator_constraint"],
            "action_intent_refs": ["show_ranking_manifest"],
        }
    ]
    fixture["action_intents"][0]["required_layout_needs"] = ["legacy_static"]
    fixture["beat_layout_intents"][0]["layout_needs"] = ["legacy_static"]
    fixture["beat_layout_intents"][0]["default_static_success_allowed"] = True
    fixture["layout_decision"] = {
        "mode": "default_static",
        "need_ids": ["legacy_static"],
        "reason": "Explicit non-responsible legacy monitor posture.",
        "receipt_refs": [],
        "authority": "canonical_broadcast_runtime",
        "ttl_s": None,
        "min_dwell_s": None,
    }
    fixture["layout_receipts"] = []
    return fixture


def _boot_safety_fallback_fixture() -> dict[str, Any]:
    receipts = _receipts_by_id()
    fixture = _excellent_segment_fixture()
    fixture["fixture_id"] = "boot-safety-fallback-not-success"
    fixture["hosting_context"] = {
        "mode": "boot_safety_fallback",
        "hapax_controls_layout": True,
        "responsible_for_content_quality": False,
        "static_layout_success_allowed": False,
        "explicit_static_reason": "boot safety: rendered layout unavailable",
    }
    fixture["layout_needs"] = [
        {
            "id": "speech_only",
            "kind": "speech_only_fallback",
            "reason": "Boot safety keeps narration audible while visible layout is unavailable.",
            "evidence_refs": ["operator_constraint"],
            "action_intent_refs": ["show_ranking_manifest"],
        }
    ]
    fixture["action_intents"][0]["required_layout_needs"] = ["speech_only"]
    fixture["beat_layout_intents"][0] = {
        "beat_id": "action",
        "layout_needs": ["speech_only"],
        "expected_effects": ["speech only fallback active"],
        "default_static_success_allowed": False,
    }
    fixture["layout_decision"] = {
        "mode": "explicit_fallback",
        "need_ids": ["speech_only"],
        "reason": "Boot safety fallback because rendered layout readback is unavailable.",
        "receipt_refs": ["receipt.boot_safety_fallback"],
        "authority": "canonical_broadcast_runtime",
        "ttl_s": 10,
        "min_dwell_s": 3,
    }
    fixture["layout_receipts"] = [receipts["receipt.boot_safety_fallback"]]
    return fixture


def _failure_codes(fixture: dict[str, Any]) -> tuple[str, ...]:
    report = evaluate_segment_quality_layout_fixture(fixture)
    return tuple(failure.code for failure in report.failures)


def test_action_intents_build_layout_needs_for_excellent_segment() -> None:
    fixture = _excellent_segment_fixture()
    report = evaluate_segment_quality_layout_fixture(fixture)

    assert report.passed
    assert fixture["beat_layout_intents"][0]["layout_needs"] == [
        "ranking_chart",
        "manifest_panel",
    ]


def test_responsible_hosting_accepts_receipted_dynamic_layout() -> None:
    report = evaluate_segment_quality_layout_fixture(_excellent_segment_fixture())

    assert report.passed
    assert tuple(failure.code for failure in report.failures) == ()


def test_responsible_hosting_rejects_default_static_layout_as_success() -> None:
    fixture = _excellent_segment_fixture()
    fixture["layout_decision"]["mode"] = "default_static"
    fixture["layout_decision"]["receipt_refs"] = []
    fixture["layout_receipts"] = []

    assert "layout.default_static_responsible" in _failure_codes(fixture)


def test_non_responsible_context_allows_static_default_with_explicit_reason() -> None:
    report = evaluate_segment_quality_layout_fixture(_non_responsible_static_fixture())

    assert report.passed


def test_non_responsible_static_default_requires_explicit_reason() -> None:
    fixture = _non_responsible_static_fixture()
    fixture["hosting_context"]["explicit_static_reason"] = ""

    assert "layout.non_responsible_static_without_reason" in _failure_codes(fixture)


def test_explicit_fallback_is_not_reported_as_success() -> None:
    report = evaluate_segment_quality_layout_fixture(_boot_safety_fallback_fixture())

    assert not report.passed
    assert tuple(failure.code for failure in report.failures) == (
        "layout.explicit_fallback_not_success",
    )


def test_boot_safety_fallback_requires_ttl_receipt_and_reason() -> None:
    fixture = _boot_safety_fallback_fixture()
    fixture["layout_decision"]["ttl_s"] = None
    fixture["layout_decision"]["reason"] = ""
    fixture["layout_decision"]["receipt_refs"] = []
    fixture["layout_receipts"] = []

    codes = _failure_codes(fixture)
    assert "layout.explicit_fallback_not_success" in codes
    assert "layout.fallback_missing_ttl" in codes
    assert "layout.fallback_missing_reason" in codes
    assert "layout.fallback_missing_receipt" in codes


def test_generic_script_fails_triad_even_when_layout_readback_is_good() -> None:
    fixture = _excellent_segment_fixture()
    fixture["fixture_id"] = "bad-generic-script-good-layout"
    fixture["topic_anchors"] = []
    fixture["script"] = {
        "premise": "Talk about some ideas.",
        "tension": "Some things are interesting.",
        "beats": [
            {
                "beat_id": "hook",
                "role": "hook",
                "text": "Today we will discuss something important.",
                "evidence_refs": [],
                "callback_refs": [],
                "action_intent_refs": [],
            },
            {
                "beat_id": "context",
                "role": "context",
                "text": "There is context and people may disagree.",
                "evidence_refs": [],
                "callback_refs": [],
                "action_intent_refs": [],
            },
            {
                "beat_id": "close",
                "role": "close",
                "text": "That is the lesson.",
                "evidence_refs": [],
                "callback_refs": [],
                "action_intent_refs": [],
            },
        ],
    }

    codes = _failure_codes(fixture)
    assert "script.generic_prose" in codes
    assert "script.missing_arc_roles" in codes
    assert "action.intent_not_scripted" in codes


def test_unsupported_action_claim_fails_even_with_layout_need() -> None:
    fixture = _excellent_segment_fixture()
    fixture["action_intents"][0]["evidence_refs"] = []

    assert "action.unsupported_claim" in _failure_codes(fixture)


def test_action_layout_mismatch_fails_when_decision_omits_required_need() -> None:
    fixture = _excellent_segment_fixture()
    fixture["layout_decision"]["need_ids"] = ["manifest_panel"]
    fixture["layout_decision"]["receipt_refs"] = ["receipt.layout_state_rendered"]

    assert "layout.action_need_not_decided" in _failure_codes(fixture)


def test_layout_store_gauge_success_does_not_satisfy_without_rendered_state() -> None:
    receipts = _receipts_by_id()
    fixture = _excellent_segment_fixture()
    fixture["fixture_id"] = "store-gauge-without-rendered-state"
    fixture["layout_decision"]["receipt_refs"] = ["receipt.store_switch", "receipt.gauge_active"]
    fixture["layout_receipts"] = [
        receipts["receipt.store_switch"],
        receipts["receipt.gauge_active"],
    ]

    codes = _failure_codes(fixture)
    assert "layout.rendered_state_missing" in codes
    assert "layout.visible_effect_missing" in codes


def test_ttl_shorter_than_dwell_fails_thrash_guard() -> None:
    fixture = _excellent_segment_fixture()
    fixture["layout_decision"]["ttl_s"] = 2
    fixture["layout_decision"]["min_dwell_s"] = 5

    assert "layout.ttl_dwell_thrash" in _failure_codes(fixture)


def test_prepared_artifact_cannot_command_layout_or_bypass_broadcast() -> None:
    fixture = _excellent_segment_fixture()
    fixture["prepared_artifact"] = deepcopy(fixture["prepared_artifact"])
    fixture["prepared_artifact"]["authority"] = "layout_command"
    fixture["prepared_artifact"]["direct_layout_commands"] = ["switch_to:garage-door"]
    fixture["prepared_artifact"]["public_broadcast_bypass"] = True

    codes = _failure_codes(fixture)
    assert "artifact.authority_bypass" in codes
    assert "artifact.direct_layout_command" in codes
    assert "artifact.public_broadcast_bypass" in codes

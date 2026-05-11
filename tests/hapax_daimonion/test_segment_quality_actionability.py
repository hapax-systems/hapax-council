from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agents.hapax_daimonion import daily_segment_prep as prep
from shared.segment_quality_actionability import (
    ACTIONABILITY_RUBRIC_VERSION,
    EXPLICIT_LAYOUT_FALLBACK_CONTEXT,
    LAYOUT_RESPONSIBILITY_VERSION,
    NON_RESPONSIBLE_STATIC_CONTEXT,
    QUALITY_RUBRIC_VERSION,
    RESPONSIBLE_HOSTING_CONTEXT,
    build_beat_action_intents,
    forbidden_layout_authority_fields,
    score_segment_quality,
    validate_layout_responsibility,
    validate_segment_actionability,
)

EXCELLENT_SCRIPT = [
    (
        "Number 3: Zuboff is useful here because surveillance capitalism is not just "
        "a villain label; it is a theory of extraction, prediction, and enclosure. "
        "The tension is that livestream tools promise intimacy while quietly asking "
        "the host to turn every hesitation into a metric. That matters because the "
        "audience is not only watching a segment, it is watching a measurement system "
        "try to become culture."
    ),
    (
        "Now compare that with the rendered LayoutState receipt, because the runtime "
        "example makes the tradeoff visible instead of abstract. Place rendered "
        "LayoutState in S-tier for legibility: not because storage telemetry is useless, "
        "but because the visible assignment stays accountable to material practice. "
        "Remember the opening problem: a system that cannot show its work becomes a "
        "confidence mask."
    ),
    (
        "So the ending is not nostalgia, it is a production rule. If Hapax says a chart "
        "changed, the chart has to change; if Hapax asks chat to judge the ranking, chat "
        "has to be the surface. Chat can challenge the ranking because the next "
        "move is deciding which claims deserve a visible instrument and which should "
        "remain spoken argument."
    ),
]

GENERIC_SCRIPT = [
    "This topic is interesting and important. There are many things to consider.",
    "Another point is also important. We should think about it carefully.",
    "In conclusion, this was a good discussion. Thanks for watching.",
]


def _artifact(script: list[str], beats: list[str]) -> dict:
    prompt_sha256 = prep._sha256_text("prompt")
    seed_sha256 = prep._sha256_text("seed")
    source_hashes = prep._source_hashes_from_fields(
        programme_id="prog-quality",
        role="tier_list",
        topic="Actionability test",
        segment_beats=beats,
        seed_sha256=seed_sha256,
        prompt_sha256=prompt_sha256,
    )
    actionability = validate_segment_actionability(script, beats)
    layout = validate_layout_responsibility(actionability["beat_action_intents"])
    source_consequence_map = prep.build_source_consequence_map(
        script,
        actionability["beat_action_intents"],
    )
    payload = {
        "schema_version": prep.PREP_ARTIFACT_SCHEMA_VERSION,
        "authority": prep.PREP_ARTIFACT_AUTHORITY,
        "programme_id": "prog-quality",
        "role": "tier_list",
        "topic": "Actionability test",
        "segment_beats": beats,
        "prepared_script": script,
        "segment_quality_rubric_version": QUALITY_RUBRIC_VERSION,
        "actionability_rubric_version": ACTIONABILITY_RUBRIC_VERSION,
        "layout_responsibility_version": LAYOUT_RESPONSIBILITY_VERSION,
        "hosting_context": layout["hosting_context"],
        "segment_quality_report": score_segment_quality(script, beats),
        "consultation_manifest": prep.build_consultation_manifest("tier_list"),
        "source_consequence_map": source_consequence_map,
        "live_event_viability": prep.build_live_event_viability(
            script,
            actionability=actionability,
            layout=layout,
            role="tier_list",
        ),
        "readback_obligations": prep.build_readback_obligations(layout["beat_layout_intents"]),
        "beat_action_intents": build_beat_action_intents(script, beats),
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
            "personage_violations": actionability["personage_violations"],
            "detector_theater_lines": actionability["detector_theater_lines"],
        },
        "beat_layout_intents": layout["beat_layout_intents"],
        "layout_decision_contract": layout["layout_decision_contract"],
        "runtime_layout_validation": layout["runtime_layout_validation"],
        "layout_decision_receipts": layout["layout_decision_receipts"],
        "prepped_at": "2026-05-05T00:00:00+00:00",
        "prep_session_id": "segment-prep-quality-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "prompt_sha256": prompt_sha256,
        "seed_sha256": seed_sha256,
        "source_hashes": source_hashes,
        "source_provenance_sha256": prep._sha256_json(source_hashes),
        "llm_calls": [
            {
                "call_index": 1,
                "phase": "compose",
                "programme_id": "prog-quality",
                "model_id": prep.RESIDENT_PREP_MODEL,
                "prompt_sha256": prompt_sha256,
                "prompt_chars": 123,
                "called_at": "2026-05-05T00:00:00+00:00",
            }
        ],
        "beat_count": len(beats),
        "avg_chars_per_beat": round(sum(len(item) for item in script) / len(script)),
        "refinement_applied": True,
    }
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    return payload


def _write_artifact(base: Path, payload: dict) -> None:
    today = prep._today_dir(base)
    path = today / "prog-quality.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (today / "manifest.json").write_text(
        json.dumps({"programmes": [path.name]}),
        encoding="utf-8",
    )


def test_quality_rubric_scores_exemplar_above_generic_script() -> None:
    excellent = score_segment_quality(EXCELLENT_SCRIPT, ["hook", "body", "close"])
    generic = score_segment_quality(GENERIC_SCRIPT, ["hook", "body", "close"])

    assert excellent["overall"] > generic["overall"] + 1.0
    assert excellent["scores"]["actionability"] > generic["scores"]["actionability"]
    assert generic["label"] == "generic"


def test_full_segment_prompt_rejects_spoken_only_responsible_beats() -> None:
    programme = SimpleNamespace(
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="source-backed ranking segment",
            segment_beats=[
                "hook: introduce the ranking pressure",
                "item_1: rank the first object",
                "close: recap the final chart",
            ],
        ),
    )

    prompt = prep._build_full_segment_prompt(programme, "source seed")

    assert "no beat may be spoken-only" in prompt
    assert "Every beat, including hook, criteria, recap, breathe, and close beats" in prompt
    assert "According to [source]" in prompt
    assert "Place [item] in [S/A/B/C/D]-tier" in prompt


def test_actionability_declares_expected_visible_or_doable_effects() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }
    assert {"countdown", "tier_chart", "chat_poll", "comparison"}.issubset(kinds)
    assert alignment["removed_unsupported_action_lines"] == []


def test_actionability_rejects_direct_layout_command_prose() -> None:
    alignment = validate_segment_actionability(
        ["Place FORTRAN in A-tier, then cue the tier panel and switch to the ranking layout."],
        ["rank FORTRAN"],
    )

    assert alignment["ok"] is False
    assert alignment["removed_unsupported_action_lines"] == [
        {
            "beat_index": 0,
            "line": "Place FORTRAN in A-tier, then cue the tier panel and switch to the ranking layout.",
        }
    ]


def test_actionability_rejects_common_layout_command_variants() -> None:
    script = [
        "Switch layout to the tier panel.",
        "Switch the layout to the tier panel.",
        "Cue up the tier chart.",
        "Place FORTRAN in A-tier, then switch the layout to the tier panel.",
    ]

    alignment = validate_segment_actionability(
        script,
        ["command 1", "command 2", "command 3", "command 4"],
    )

    assert alignment["ok"] is False
    assert [item["line"] for item in alignment["removed_unsupported_action_lines"]] == script
    assert "prepared_script" not in alignment
    assert alignment["diagnostic_sanitized_script"]


def test_tier_chart_requires_sentence_initial_place_trigger() -> None:
    invalid_script = [
        "I would place FORTRAN in A-tier because the evidence is visible.",
        "Please place COBOL in B-tier because the tradeoff still matters.",
    ]
    invalid_alignment = validate_segment_actionability(
        invalid_script,
        ["rank FORTRAN", "rank COBOL"],
    )

    invalid_kinds = {
        intent["kind"]
        for beat in invalid_alignment["beat_action_intents"]
        for intent in beat["intents"]
    }
    assert "tier_chart" not in invalid_kinds
    assert "comparison" in invalid_kinds

    valid_alignment = validate_segment_actionability(
        ["Place FORTRAN in A-tier because the evidence is visible."],
        ["rank FORTRAN"],
    )
    valid_kinds = {
        intent["kind"]
        for beat in valid_alignment["beat_action_intents"]
        for intent in beat["intents"]
    }
    assert "tier_chart" in valid_kinds

    gated = prep._with_tier_list_placement_gate(
        {"ok": True, "violations": [], "runtime_layout_validation": {"ok": True}},
        role="tier_list",
        segment_beats=["rank FORTRAN", "rank COBOL"],
        beat_action_intents=invalid_alignment["beat_action_intents"],
    )

    assert gated["ok"] is False
    assert "missing_tier_placement_phrase" in {
        violation["reason"] for violation in gated["violations"]
    }


def test_tier_list_gate_requires_final_non_skip_candidate_placement() -> None:
    alignment = validate_segment_actionability(
        [
            "This opening names the rubric and the stakes for the tier list.",
            "Place FORTRAN in A-tier because the legacy is visible in the ranking.",
            "Java belongs in B-tier because the enterprise tradeoff is real.",
        ],
        [
            "criteria intro",
            "second candidate: FORTRAN",
            "third candidate: Java",
        ],
    )

    gated = prep._with_tier_list_placement_gate(
        {"ok": True, "violations": [], "runtime_layout_validation": {"ok": True}},
        role="tier_list",
        segment_beats=["criteria intro", "second candidate: FORTRAN", "third candidate: Java"],
        beat_action_intents=alignment["beat_action_intents"],
    )

    assert gated["ok"] is False
    assert [
        violation["beat_index"]
        for violation in gated["violations"]
        if violation["reason"] == "missing_tier_placement_phrase"
    ] == [2]


def test_tier_list_gate_skips_numbered_criteria_and_recap_beats() -> None:
    alignment = validate_segment_actionability(
        [
            "This opening names the tier-list premise and the stakes.",
            "The criteria are impact, durability, and whether the example still teaches.",
            "Place FORTRAN in A-tier because the legacy is visible in the ranking.",
            "The recap ties the placements back to the audience reaction.",
            "The scoring rubric keeps durability above novelty before the chart moves.",
        ],
        [
            "hook with a tier rubric",
            "item_1: discuss criteria for ranking",
            "item_2: rank FORTRAN",
            "item_7: summarize tier placements and chat reactions",
            "criteria: score durability higher than novelty before moving to chat",
        ],
    )

    gated = prep._with_tier_list_placement_gate(
        {"ok": True, "violations": [], "runtime_layout_validation": {"ok": True}},
        role="tier_list",
        segment_beats=[
            "hook with a tier rubric",
            "item_1: discuss criteria for ranking",
            "item_2: rank FORTRAN",
            "item_7: summarize tier placements and chat reactions",
            "criteria: score durability higher than novelty before moving to chat",
        ],
        beat_action_intents=alignment["beat_action_intents"],
    )

    assert gated["ok"] is True
    assert gated["violations"] == []


def test_tier_list_gate_still_rejects_skip_direction_with_placement_action() -> None:
    alignment = validate_segment_actionability(
        [
            "This closing beat says the wildcard belongs in C-tier because the payoff is narrow.",
        ],
        ["closing: place the wildcard candidate"],
    )

    gated = prep._with_tier_list_placement_gate(
        {"ok": True, "violations": [], "runtime_layout_validation": {"ok": True}},
        role="tier_list",
        segment_beats=["closing: place the wildcard candidate"],
        beat_action_intents=alignment["beat_action_intents"],
    )

    assert gated["ok"] is False
    assert [
        violation["beat_index"]
        for violation in gated["violations"]
        if violation["reason"] == "missing_tier_placement_phrase"
    ] == [0]


def test_actionability_rejects_camera_director_command_prose() -> None:
    script = [
        "Place FORTRAN in A-tier because the ranking is legible. "
        "Switch to the overhead camera now.",
        "Cut to the director view while I explain the tradeoff.",
        "Show the desk camera feed for proof.",
        "Take overhead while I explain the tradeoff.",
        "Bring overhead up while chat votes.",
        "Take desk cam while I explain the tradeoff.",
    ]

    alignment = validate_segment_actionability(
        script,
        [
            "rank FORTRAN",
            "reject director cue",
            "reject desk camera cue",
            "reject overhead shorthand",
            "reject bring-up shorthand",
            "reject desk-cam shorthand",
        ],
    )

    assert alignment["ok"] is False
    assert [item["line"] for item in alignment["removed_unsupported_action_lines"]] == [
        "Switch to the overhead camera now.",
        "Cut to the director view while I explain the tradeoff.",
        "Show the desk camera feed for proof.",
        "Take overhead while I explain the tradeoff.",
        "Bring overhead up while chat votes.",
        "Take desk cam while I explain the tradeoff.",
    ]
    assert alignment["diagnostic_sanitized_script"][0] == (
        "Place FORTRAN in A-tier because the ranking is legible."
    )
    assert "prepared_script" not in alignment


def test_actionability_allows_neutral_camera_descriptions_without_commands() -> None:
    script = [
        "The overhead camera feed has a color cast; that is source context, not "
        "a director instruction. Place FORTRAN in A-tier because the ranking is legible.",
        "A director view of the argument is not the same thing as directing the "
        "runtime layout. Chat can mark whether that distinction is clear.",
        "Take the long view on this tradeoff before the ranking. "
        "Move the argument into view, then push the comparison angle harder.",
    ]

    alignment = validate_segment_actionability(
        script,
        [
            "rank FORTRAN with source context",
            "ask chat about the distinction",
            "allow ordinary idioms",
        ],
    )

    assert alignment["ok"] is True
    assert alignment["removed_unsupported_action_lines"] == []
    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }
    assert {"tier_chart", "chat_poll"}.issubset(kinds)


def test_layout_responsibility_derives_needs_from_action_intents() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    layout = validate_layout_responsibility(alignment["beat_action_intents"])

    kinds = {need for beat in layout["beat_layout_intents"] for need in beat["needs"]}
    assert {"countdown_visual", "tier_visual", "chat_prompt"}.issubset(kinds)
    assert layout["hosting_context"] == RESPONSIBLE_HOSTING_CONTEXT
    assert layout["layout_decision_contract"]["may_command_layout"] is False
    assert all(
        beat["evidence_refs"] and beat["source_affordances"]
        for beat in layout["beat_layout_intents"]
    )
    tier_beat = next(
        beat for beat in layout["beat_layout_intents"] if "tier_visual" in beat["needs"]
    )
    tier_binding = next(
        binding
        for binding in tier_beat["object_bindings"]
        if binding["source_action_kind"] == "tier_chart"
    )
    assert "tier_chart.place:rendered LayoutState:S" in tier_beat["expected_effects"]
    assert tier_binding["expected_effect"] == "tier_chart.place:rendered LayoutState:S"
    assert tier_binding["item_ref"] == "tier_item:rendered LayoutState:S"
    assert tier_binding["action_ref"] == "action:tier_chart:rendered LayoutState:S"
    assert forbidden_layout_authority_fields(layout["beat_layout_intents"]) == []


def test_tier_action_contract_is_object_bound_without_layout_authority() -> None:
    alignment = validate_segment_actionability(
        ["Place FORTRAN in S-tier because the ranking is legible."],
        ["rank FORTRAN with visible tier placement"],
    )

    layout = validate_layout_responsibility(alignment["beat_action_intents"])
    beat = layout["beat_layout_intents"][0]
    binding = beat["object_bindings"][0]

    assert "tier_visual" in beat["needs"]
    assert "tier_chart.place:FORTRAN:S" in beat["expected_effects"]
    assert "tier_chart" in beat["source_affordances"]
    assert binding == {
        "need_kind": "tier_visual",
        "source_action_kind": "tier_chart",
        "expected_effect": "tier_chart.place:FORTRAN:S",
        "action_ref": "action:tier_chart:FORTRAN:S",
        "object_ref": "object:FORTRAN",
        "item_ref": "tier_item:FORTRAN:S",
    }
    assert forbidden_layout_authority_fields(layout["beat_layout_intents"]) == []


def test_responsible_layout_rejects_spoken_only_beats() -> None:
    alignment = validate_segment_actionability(
        [
            "This is a spoken argument about programme quality. "
            "It names the problem, states the consequence, and makes no visible or doable claim."
        ],
        ["argue the point"],
    )

    layout = validate_layout_responsibility(alignment["beat_action_intents"])

    assert layout["ok"] is False
    assert layout["beat_layout_intents"][0]["needs"] == ["unsupported_layout_need"]
    assert "spoken_argument_only" in layout["beat_layout_intents"][0]["source_affordances"]
    assert "unsupported_layout_need" in {item["reason"] for item in layout["violations"]}


def test_source_backed_claims_propose_visible_source_context_not_layout_authority() -> None:
    script = [
        (
            "According to Shoshana Zuboff, surveillance capitalism turns prediction "
            "markets into institutional gravity. Zuboff argues that the extraction "
            "matters because behavioural surplus becomes a production surface."
        )
    ]
    alignment = validate_segment_actionability(script, ["source: make the claim accountable"])

    intents = alignment["beat_action_intents"][0]["intents"]
    assert {intent["kind"] for intent in intents} == {"source_citation"}
    assert intents[0]["target"] == "Shoshana Zuboff"
    assert intents[0]["expected_effect"] == "source.visible:Shoshana Zuboff"

    layout = validate_layout_responsibility(alignment["beat_action_intents"])
    beat = layout["beat_layout_intents"][0]

    assert beat["needs"] == ["source_visible"]
    assert beat["source_affordances"] == ["source_context"]
    assert "source.visible:Shoshana Zuboff" in beat["expected_effects"]
    assert any(
        binding.get("source_ref") == "source:Shoshana Zuboff" for binding in beat["object_bindings"]
    )
    assert beat["default_static_success_allowed"] is False
    assert layout["layout_decision_contract"]["may_command_layout"] is False
    assert layout["runtime_layout_validation"]["status"] == "pending_runtime_readback"
    assert layout["runtime_layout_validation"]["layout_success"] is False
    assert layout["layout_decision_receipts"] == []
    assert forbidden_layout_authority_fields(layout["beat_layout_intents"]) == []


def test_transition_phrases_do_not_become_source_visible_bypass() -> None:
    script = [
        "From here, the segment gets sharper while staying in spoken argument.",
        "Today shows why the issue matters without citing an external source.",
        "Drawing on the beat direction, we pivot to the next spoken point.",
    ]

    alignment = validate_segment_actionability(script, ["transition", "transition", "transition"])

    for declaration in alignment["beat_action_intents"]:
        assert [intent["kind"] for intent in declaration["intents"]] == ["spoken_argument"]

    layout = validate_layout_responsibility(alignment["beat_action_intents"])

    assert layout["ok"] is False
    assert [beat["needs"] for beat in layout["beat_layout_intents"]] == [
        ["unsupported_layout_need"],
        ["unsupported_layout_need"],
        ["unsupported_layout_need"],
    ]
    assert {item["reason"] for item in layout["violations"]} == {
        "unsupported_layout_need",
        "missing_layout_evidence_refs",
    }


def test_specific_source_structures_still_propose_visible_source_context() -> None:
    script = [
        "According to the 2024 FTC report, the interface hides the real cost.",
        "Zuboff argues that extraction becomes a production surface.",
    ]

    alignment = validate_segment_actionability(script, ["source", "source"])

    assert [intent["kind"] for intent in alignment["beat_action_intents"][0]["intents"]] == [
        "source_citation"
    ]
    assert [intent["kind"] for intent in alignment["beat_action_intents"][1]["intents"]] == [
        "source_citation"
    ]
    layout = validate_layout_responsibility(alignment["beat_action_intents"])
    assert [beat["needs"] for beat in layout["beat_layout_intents"]] == [
        ["source_visible"],
        ["source_visible"],
    ]


def test_responsible_hosting_rejects_unreceipted_static_default_layout() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    layout = validate_layout_responsibility(
        alignment["beat_action_intents"],
        observed_layout_state={
            "layout_id": "default",
            "is_static_default": True,
            "claims_success": True,
        },
    )

    assert layout["ok"] is False
    assert {
        "static_default_layout_not_responsible_success",
        "layout_success_without_decision_readback",
    }.issubset({violation["reason"] for violation in layout["violations"]})
    assert layout["runtime_layout_validation"]["layout_success"] is False


def test_layout_store_gauge_success_is_not_rendered_responsibility_success() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    layout = validate_layout_responsibility(
        alignment["beat_action_intents"],
        observed_layout_state={
            "layout_id": "comparison_split",
            "layout_store_success": True,
            "gauge_success": True,
            "claims_success": True,
            "receipt_id": "layout-store-only",
        },
    )

    assert layout["ok"] is False
    assert "advisory_layout_store_not_rendered_success" in {
        violation["reason"] for violation in layout["violations"]
    }
    assert layout["layout_decision_contract"]["rendered_authority"] == (
        "StudioCompositor.layout_state via fx_chain/Layout.assignments"
    )


def test_responsible_static_fallback_requires_ttl_and_receipt() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    missing_receipt = validate_layout_responsibility(
        alignment["beat_action_intents"],
        observed_layout_state={
            "layout_id": "default_fallback",
            "is_static_default": True,
            "fallback_explicit": True,
            "ttl_ms": 4000,
        },
    )
    receipted = validate_layout_responsibility(
        alignment["beat_action_intents"],
        observed_layout_state={
            "layout_id": "default_fallback",
            "is_static_default": True,
            "fallback_explicit": True,
            "receipt_id": "fallback-1",
            "ttl_ms": 4000,
            "rendered_readback": True,
        },
    )

    assert "static_fallback_missing_ttl_or_receipt" in {
        violation["reason"] for violation in missing_receipt["violations"]
    }
    assert receipted["ok"] is True
    assert receipted["runtime_layout_validation"]["fallback_active"] is True
    assert receipted["runtime_layout_validation"]["layout_success"] is False


def test_responsible_static_layout_aliases_never_count_as_success() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    for layout_id in (
        "layout:default-live",
        "default-live",
        "config/compositor-layouts/default.json",
    ):
        layout = validate_layout_responsibility(
            alignment["beat_action_intents"],
            observed_layout_state={
                "layout_id": layout_id,
                "rendered_readback": True,
                "receipt_id": "rendered-static-readback",
            },
        )

        assert layout["runtime_layout_validation"]["layout_success"] is False
        assert "static_default_layout_not_responsible_success" in {
            violation["reason"] for violation in layout["violations"]
        }


def test_non_responsible_static_context_allows_default_layout() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    layout = validate_layout_responsibility(
        alignment["beat_action_intents"],
        responsibility_mode=NON_RESPONSIBLE_STATIC_CONTEXT,
        observed_layout_state={
            "layout_id": "default",
            "is_static_default": True,
            "claims_success": True,
        },
    )

    assert layout["ok"] is True
    assert layout["layout_decision_contract"]["default_static_success_allowed"] is True


def test_explicit_fallback_context_allows_garage_door_layout() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    missing_receipt = validate_layout_responsibility(
        alignment["beat_action_intents"],
        responsibility_mode=EXPLICIT_LAYOUT_FALLBACK_CONTEXT,
        observed_layout_state={
            "layout_id": "garage-door",
            "is_static_default": True,
            "claims_success": True,
            "fallback_explicit": True,
        },
    )
    layout = validate_layout_responsibility(
        alignment["beat_action_intents"],
        responsibility_mode=EXPLICIT_LAYOUT_FALLBACK_CONTEXT,
        observed_layout_state={
            "layout_id": "garage-door",
            "is_static_default": True,
            "claims_success": True,
            "fallback_explicit": True,
            "receipt_id": "fallback-explicit-1",
            "ttl_ms": 4000,
            "rendered_readback": True,
        },
    )

    assert "static_fallback_missing_ttl_or_receipt" in {
        violation["reason"] for violation in missing_receipt["violations"]
    }
    assert layout["ok"] is True
    assert layout["layout_decision_contract"]["default_static_success_allowed"] is True


def test_layout_authority_shaped_fields_are_detected() -> None:
    assert forbidden_layout_authority_fields(
        {
            "beat_layout_intents": [
                {
                    "beat_index": 0,
                    "needs": [{"layout_name": "default", "surface_id": "main"}],
                }
            ],
            "segment_cues": ["front.cam"],
        }
    ) == [
        {
            "path": "$.beat_layout_intents[0].needs[0].layout_name",
            "field": "layout_name",
        },
        {
            "path": "$.beat_layout_intents[0].needs[0].surface_id",
            "field": "surface_id",
        },
        {"path": "$.segment_cues", "field": "segment_cues"},
    ]


def test_layout_authority_detection_rejects_aliases_and_static_values() -> None:
    forbidden = forbidden_layout_authority_fields(
        {
            "beat_layout_intents": [
                {
                    "beat_index": 0,
                    "needs": [
                        {
                            "LayoutName": "segment-tier",
                            "requested-layout": "segment-list",
                            "layoutId": "segment-tier",
                        },
                        {
                            "kind": "tier_visual",
                            "evidence_ref": "layout:default-live",
                        },
                    ],
                }
            ]
        }
    )

    assert {"path": "$.beat_layout_intents[0].needs[0].LayoutName", "field": "LayoutName"} in (
        forbidden
    )
    assert {
        "path": "$.beat_layout_intents[0].needs[0].requested-layout",
        "field": "requested-layout",
    } in forbidden
    assert {"path": "$.beat_layout_intents[0].needs[0].layoutId", "field": "layoutId"} in (
        forbidden
    )
    assert {
        "path": "$.beat_layout_intents[0].needs[1].evidence_ref",
        "value": "layout:default-live",
    } in forbidden


def test_actionability_rewrites_unsupported_visual_claims() -> None:
    script = [
        "Watch the clip on screen and you can see the problem. "
        "The safer claim is that the source record does not justify the leap."
    ]

    alignment = validate_segment_actionability(script, ["test unsupported clip claim"])

    assert alignment["ok"] is False
    assert alignment["removed_unsupported_action_lines"][0]["beat_index"] == 0
    assert "prepared_script" not in alignment
    assert "Watch the clip" not in alignment["diagnostic_sanitized_script"][0]
    assert "safer claim" in alignment["diagnostic_sanitized_script"][0]


def test_quality_rubric_requires_source_consequence_and_live_bit_range() -> None:
    excellent = score_segment_quality(EXCELLENT_SCRIPT, ["hook", "body", "close"])
    decorative = score_segment_quality(
        [
            "Zuboff, Schon, and Haraway are interesting names for this topic. "
            "This segment has context and a general explanation.",
            "The ideas are important and there are many factors to consider in the discussion.",
            "In conclusion, sources matter and the audience should keep thinking about them.",
        ],
        ["hook", "body", "close"],
    )

    assert excellent["scores"]["source_consequence"] >= 4
    assert excellent["scores"]["live_bit_viability"] >= 4
    assert excellent["scores"]["non_anthropomorphic_force"] >= 4
    assert decorative["scores"]["source_consequence"] < excellent["scores"]["source_consequence"]
    assert decorative["label"] == "generic"


def test_actionability_rejects_human_personage_and_detector_theater() -> None:
    alignment = validate_segment_actionability(
        [
            "I feel excited because the detector proved the chart changed. "
            "Place Detector Proof in S-tier because Zuboff argues measurement needs proof."
        ],
        ["reject personage and detector theater"],
    )

    assert alignment["ok"] is False
    assert alignment["personage_violations"]
    assert alignment["detector_theater_lines"]


def test_loader_rejects_artifact_requiring_unsupported_runtime_action_rewrite(
    tmp_path: Path,
) -> None:
    script = [
        "Show the clip on screen before ranking the evidence. "
        "Place the provenance ledger in A-tier because the source hashes line up."
    ]
    payload = _artifact(script, ["rank the evidence"])
    _write_artifact(tmp_path, payload)

    loaded = prep.load_prepped_programmes(tmp_path, require_selected=False)

    assert loaded == []


class TestHostPostureDetection:
    """Validates detection of podcast-host language patterns."""

    def test_collective_we_detected(self) -> None:
        from shared.segment_quality_actionability import segment_personage_violations

        script = ["We'll be examining the factors today."]
        violations = segment_personage_violations(script)
        rule_ids = {v["rule_id"] for v in violations}
        assert "collective_human_host_posture" in rule_ids

    def test_welcome_to_detected(self) -> None:
        from shared.segment_quality_actionability import segment_personage_violations

        script = ["Welcome to our segment on control loops."]
        violations = segment_personage_violations(script)
        rule_ids = {v["rule_id"] for v in violations}
        assert "stock_human_host_phrase" in rule_ids

    def test_moving_on_detected(self) -> None:
        from shared.segment_quality_actionability import segment_personage_violations

        script = ["Moving on to the next topic."]
        violations = segment_personage_violations(script)
        rule_ids = {v["rule_id"] for v in violations}
        assert "stock_human_host_phrase" in rule_ids

    def test_feel_free_detected(self) -> None:
        from shared.segment_quality_actionability import segment_personage_violations

        script = ["Feel free to share your thoughts in the chat."]
        violations = segment_personage_violations(script)
        rule_ids = {v["rule_id"] for v in violations}
        assert "stock_human_host_phrase" in rule_ids

    def test_hapax_voice_passes(self) -> None:
        from shared.segment_quality_actionability import segment_personage_violations

        script = [
            "The evidence shifts here. Zuboff argues that surveillance capitalism "
            "operates through behavioral surplus extraction. This source changes "
            "the ranking because the citation directly challenges the S-tier placement."
        ]
        violations = segment_personage_violations(script)
        host_violations = [
            v
            for v in violations
            if v.get("rule_id") in ("collective_human_host_posture", "stock_human_host_phrase")
        ]
        assert host_violations == []

    def test_canary_script_fails_validation(self) -> None:
        from shared.segment_quality_actionability import validate_segment_actionability

        canary_script = [
            "Hello everyone, and welcome to our segment. We'll be examining factors.",
            "Our first item is the validator rewrite prohibition.",
            "Next, we have programme-scoped abort supervision.",
            "Moving on to selected-release feedback. We can improve priors.",
            "As we conclude, let's review our chart. Feel free to share your thoughts.",
        ]
        result = validate_segment_actionability(
            canary_script, ["hook", "item_1", "item_2", "item_3", "close"]
        )
        assert result["ok"] is False
        assert len(result["personage_violations"]) >= 5


class TestHostPostureScrub:
    """Validates the post-compose scrub pass."""

    def test_scrub_removes_welcome(self) -> None:
        from agents.hapax_daimonion.daily_segment_prep import _scrub_host_posture

        result = _scrub_host_posture(["Welcome to our segment on control loops."])
        assert "welcome to" not in result[0].lower()

    def test_scrub_replaces_collective_we(self) -> None:
        from agents.hapax_daimonion.daily_segment_prep import _scrub_host_posture

        result = _scrub_host_posture(["We'll be examining the factors today."])
        assert "we'll" not in result[0].lower()

    def test_scrub_replaces_lets(self) -> None:
        from agents.hapax_daimonion.daily_segment_prep import _scrub_host_posture

        result = _scrub_host_posture(["Let's dive into the evidence."])
        assert "let's" not in result[0].lower()

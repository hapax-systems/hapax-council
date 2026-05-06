from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion import daily_segment_prep as prep
from shared.segment_quality_actionability import (
    ACTIONABILITY_RUBRIC_VERSION,
    EXPLICIT_LAYOUT_FALLBACK_CONTEXT,
    LAYOUT_RESPONSIBILITY_VERSION,
    NON_RESPONSIBLE_STATIC_CONTEXT,
    PERSONAGE_RUBRIC_VERSION,
    QUALITY_RUBRIC_VERSION,
    RESPONSIBLE_HOSTING_CONTEXT,
    build_beat_action_intents,
    forbidden_layout_authority_fields,
    score_segment_quality,
    validate_layout_responsibility,
    validate_nonhuman_personage,
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
        "Now compare that with the resolved workshop notebook, because the artifact "
        "makes the tradeoff physical instead of abstract. Place the workshop notebook "
        "in S-tier for legibility: not because craft is pure, but because the method "
        "stays accountable to material practice. Source check: the resolved source "
        "note argues that a system that cannot show its work becomes a personality mask."
    ),
    (
        "So the ending is not nostalgia, it is a production rule. If Hapax says a chart "
        "changed, the chart has to change; if Hapax asks chat to judge the ranking, chat "
        "has to be the surface. Chat pressure: which claim deserves a visible "
        "instrument before it becomes part of the bit? The next "
        "move is deciding which claims deserve a visible instrument and which need "
        "more grounding before they become part of the bit."
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
    personage = validate_nonhuman_personage(script)
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
        "personage_rubric_version": PERSONAGE_RUBRIC_VERSION,
        "hosting_context": layout["hosting_context"],
        "segment_quality_report": score_segment_quality(script, beats),
        "personage_alignment": personage,
        "beat_action_intents": build_beat_action_intents(script, beats),
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
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
        "prep_content_state_sha256": prep._content_state_sha256(None),
        "prep_content_state": None,
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


def test_actionability_declares_expected_visible_or_doable_effects() -> None:
    alignment = validate_segment_actionability(EXCELLENT_SCRIPT, ["hook", "body", "close"])

    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }
    assert {"countdown", "tier_chart", "chat_poll", "comparison", "source_check"}.issubset(kinds)
    assert alignment["removed_unsupported_action_lines"] == []


def test_source_evidence_and_definition_checks_create_responsible_layout_needs() -> None:
    script = [
        "Source check: the resolved vault note argues that the term changes the stakes. "
        "That source matters because it prevents a decorative citation from replacing "
        "the argument.",
        "Evidence check: the archived artifact shows the sequence moved in three steps. "
        "The example matters because the audience can track what changed.",
        "Definition check: residency means the same model stays loaded across sequential "
        "prep calls. That detail matters because continuity is part of the method.",
    ]

    alignment = validate_segment_actionability(script, ["source", "evidence", "definition"])
    layout = validate_layout_responsibility(alignment["beat_action_intents"])

    assert alignment["ok"] is True
    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }
    assert {"source_check", "evidence_check", "definition_check"}.issubset(kinds)
    layout_needs = {need for beat in layout["beat_layout_intents"] for need in beat["needs"]}
    assert {"source_visible", "evidence_visible", "readability_held"}.issubset(layout_needs)
    assert "unsupported_layout_need" not in layout_needs
    assert layout["ok"] is True


def test_strict_source_check_rejects_malformed_claim_marker() -> None:
    script = ["Source check: this is just my claim. Chat pressure: should this count?"]

    alignment = validate_segment_actionability(script, ["malformed source marker"])

    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }
    assert "source_check" not in kinds
    assert "chat_poll" in kinds


def test_source_check_accepts_named_packet_confirmation() -> None:
    alignment = validate_segment_actionability(
        [
            "Source check: packet:segment-prep-failure-modes-v19 confirms that "
            "human-host cosplay is rejected by the validation rules."
        ],
        ["packet confirmation"],
    )

    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }

    assert "source_check" in kinds


def test_public_readback_visible_test_and_worked_example_are_actionable() -> None:
    script = [
        "Public readback: the source card must show the receipt before the claim counts.",
        "Visible test: the ranking compares source access against visible readback.",
        "Worked example: the artifact moves from claim to receipt in three steps.",
    ]

    alignment = validate_segment_actionability(script, ["readback", "test", "example"])
    layout = validate_layout_responsibility(alignment["beat_action_intents"])

    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }
    assert {"public_readback", "visible_test", "worked_example"}.issubset(kinds)
    layout_needs = {need for beat in layout["beat_layout_intents"] for need in beat["needs"]}
    assert {"source_visible", "action_visible", "readability_held"}.issubset(layout_needs)
    assert layout["ok"] is True


def test_actionability_rejects_placeholder_visible_hooks() -> None:
    alignment = validate_segment_actionability(
        [
            "Public readback: something.",
            "Visible test: show it.",
            "Worked example: do the thing.",
            "Source check: the source shows the thing.",
        ],
        ["placeholder readback", "placeholder test", "placeholder example", "generic source"],
    )

    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }

    assert {"public_readback", "visible_test", "worked_example", "source_check"}.isdisjoint(kinds)


def test_mood_shift_trigger_uses_word_boundaries() -> None:
    alignment = validate_segment_actionability(
        [
            "The affair does not create a visual mood just because one substring "
            "looks like a short evaluative word."
        ],
        ["guard against substring mood false positives"],
    )

    kinds = {
        intent["kind"] for beat in alignment["beat_action_intents"] for intent in beat["intents"]
    }

    assert "mood_shift" not in kinds
    assert kinds == {"spoken_argument"}


def test_weak_comparison_only_does_not_satisfy_responsible_layout() -> None:
    alignment = validate_segment_actionability(
        [
            "The comparison matters, and the ranking has a tradeoff, but this beat "
            "never names a source, readback, tier placement, visible test, or public decision."
        ],
        ["bare comparison"],
    )

    layout = validate_layout_responsibility(alignment["beat_action_intents"])

    assert layout["ok"] is False
    assert "weak_action_only_not_responsible_layout" in {
        item["reason"] for item in layout["violations"]
    }


def test_tier_actionability_accepts_common_spoken_placement_variants() -> None:
    script = [
        "Place Quantum Computing in S-tier because the source packet "
        "shows a discontinuity in problem-solving capacity.",
        "AI Language Models earn an A-tier ranking because deployment changed "
        "search, writing, and software support.",
        "Blockchain Technology, the third contender, lands in the B-tier because "
        "the adoption evidence is mixed.",
        "5G Technology, our fourth entry, has uneven adoption and is thus placed in the C-tier.",
        "AR/VR, which currently resides in the D-tier, still needs stronger public "
        "evidence before it can move higher.",
    ]

    alignment = validate_segment_actionability(script, [f"beat {i}" for i in range(5)])

    placements = [
        intent
        for beat in alignment["beat_action_intents"]
        for intent in beat["intents"]
        if intent["kind"] == "tier_chart"
    ]
    assert len(placements) == 5
    assert {intent["target"] for intent in placements} == {
        "Quantum Computing",
        "AI Language Models",
        "Blockchain Technology",
        "5G Technology",
        "AR/VR",
    }


def test_nonhuman_personage_rejects_human_host_openers_and_inner_life() -> None:
    script = [
        "Welcome to this tier list. Let's dive into our world of inventions. I feel excited.",
        "Hapax hopes this thinker lands because my pick feels beautiful.",
        "Hapax is curious about the archive, and I am concerned about the result.",
        "There we have it. Join the chat, stay curious, and keep exploring.",
        "Sources show the claim works from my research.",
        "Hapax is a beacon of objectivity and free from bias in the viewer experience.",
    ]

    validation = validate_nonhuman_personage(script)

    reasons = {item["reason"] for item in validation["violations"]}
    assert validation["ok"] is False
    assert {"human_host_opener", "first_person_inner_life", "human_journey_frame"}.issubset(reasons)
    assert "ungrounded_taste_or_intuition" in reasons
    assert "generic_provenance_claim" in reasons
    assert "first_person_plural_host_frame" in reasons
    assert "false_objectivity_claim" in reasons
    assert "generic_viewer_agency_claim" in reasons
    assert "hapax_emotional_state_claim" in reasons


def test_nonhuman_personage_rejects_institutional_virtue_cosplay() -> None:
    validation = validate_nonhuman_personage(
        [
            "Hapax should strive to maintain integrity while presenting the ranking.",
            "Hapax's trustworthiness matters more than the runtime readback.",
        ]
    )

    reasons = {item["reason"] for item in validation["violations"]}
    assert {"aspirational_personage_claim", "institutional_virtue_personification"}.issubset(
        reasons
    )


def test_nonhuman_personage_accepts_operational_stance() -> None:
    script = [
        "Hapax marks this source as high-salience because the receipt links a claim, "
        "a visible readback, and an operator correction. Public readback: the source "
        "card must show the receipt before the claim counts.",
    ]

    validation = validate_nonhuman_personage(script)

    assert validation["ok"] is True
    assert validation["violations"] == []


def test_nonhuman_personage_rejects_generic_engagement_and_persona_language() -> None:
    validation = validate_nonhuman_personage(
        [
            "True actionability involves engaging the audience and creating a lasting impact.",
            "Hapax needs a non-human persona with a distinct and authentic voice aperture.",
            "Your input is invaluable in shaping future segments and actively involving viewers.",
            "The bit should foster a genuine connection and resonate with the public.",
            "The public are not passive listeners but active contributors driving the narrative.",
            "The segment invites the audience to actively engage and contribute to a shared experience.",
            "This creates a meaningful and immersive experience that remains grounded and authentic.",
            "Transparency and honesty make the analysis valuable and engaging for the public.",
            "The next-nine gate should stay closed until the review passes.",
            "Hapax's segments should strive for visibility and engagement.",
            "This connects genuinely with the audience and fosters trust.",
            "Presenting information with transparency is vital to the livestream's success.",
        ]
    )

    reasons = {item["reason"] for item in validation["violations"]}
    assert "generic_viewer_agency_claim" in reasons
    assert "anthropocentric_rhetoric_cliche" in reasons
    assert "fixed_batch_target_language" in reasons
    assert "false_objectivity_claim" in reasons


def test_nonhuman_personage_accepts_marked_analogy_without_human_identity() -> None:
    script = [
        "By analogy, call this beat tension: the source packet says the chart is "
        "loadable, while the runtime readback still owes proof. Public readback: "
        "the receipt card must show that contradiction before the ranking advances.",
    ]

    validation = validate_nonhuman_personage(script)

    assert validation["ok"] is True
    assert validation["violations"] == []


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


def test_actionability_rejects_unreceipted_visible_success_claims() -> None:
    alignment = validate_segment_actionability(
        ["The chart updates and the audience can see the source ranking now."],
        ["claim visible success"],
    )

    assert alignment["ok"] is False
    assert alignment["removed_unsupported_action_lines"] == [
        {
            "beat_index": 0,
            "line": "The chart updates and the audience can see the source ranking now.",
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
    assert alignment["prepared_script"][0] == (
        "Place FORTRAN in A-tier because the ranking is legible."
    )


def test_actionability_allows_neutral_camera_descriptions_without_commands() -> None:
    script = [
        "The overhead camera feed has a color cast; that is source context, not "
        "a director instruction. Place FORTRAN in A-tier because the ranking is legible.",
        "A director view of the argument is not the same thing as directing the "
        "runtime layout. Chat pressure: should the ranking gate require rendered readback?",
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
    assert {item["reason"] for item in layout["violations"]} == {"unsupported_layout_need"}


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

    layout = validate_layout_responsibility(
        alignment["beat_action_intents"],
        responsibility_mode=EXPLICIT_LAYOUT_FALLBACK_CONTEXT,
        observed_layout_state={
            "layout_id": "garage-door",
            "is_static_default": True,
            "claims_success": True,
            "fallback_explicit": True,
        },
    )

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
    assert "Watch the clip" not in alignment["prepared_script"][0]
    assert "safer claim" in alignment["prepared_script"][0]


def test_loader_rejects_artifact_requiring_unsupported_runtime_action_rewrite(
    tmp_path: Path,
) -> None:
    script = [
        "Show the clip on screen before ranking the evidence. "
        "Place the provenance ledger in A-tier because the source hashes line up."
    ]
    payload = _artifact(script, ["rank the evidence"])
    _write_artifact(tmp_path, payload)

    loaded = prep.load_prepped_programmes(tmp_path)

    assert loaded == []
